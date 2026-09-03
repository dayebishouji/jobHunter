"""LLM-driven extraction. Four domain calls (concurrency up to 4) + 1 aggregate."""

from __future__ import annotations

import asyncio
import json
import logging

from jobhunter.llm import (
    CONSOLIDATE_SYSTEM,
    CONSOLIDATE_USER_TEMPLATE,
    EXTRACT_BASE,
    EXTRACT_BUSINESS_SUFFIX,
    EXTRACT_JUDICIAL_SUFFIX,
    EXTRACT_NEWS_SUFFIX,
    EXTRACT_REVIEWS_SUFFIX,
    LLMClient,
    extract_tool_spec,
    safe_dumps,
)
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem

logger = logging.getLogger(__name__)

DOMAIN_SUFFIX = {
    "business": EXTRACT_BUSINESS_SUFFIX,
    "reviews": EXTRACT_REVIEWS_SUFFIX,
    "news": EXTRACT_NEWS_SUFFIX,
    "judicial": EXTRACT_JUDICIAL_SUFFIX,
}

MODEL_BY_DOMAIN: dict[str, type] = {
    "business": BusinessFacts,
    "reviews": ReviewFacts,
    "news": NewsFacts,
    "judicial": JudicialFacts,
}

CHARS_CAP = 25_000  # rough upper bound before passing to LLM


def _materialize(items: list[RawItem]) -> str:
    parts: list[str] = []
    for i, it in enumerate(items, start=1):
        parts.append(
            f"[{i}] {it.title or '(无标题)'} | {it.source} | {it.url}\n{(it.snippet or '').strip()}"
        )
    s = "\n\n".join(parts)
    return s[:CHARS_CAP]


async def _extract_one_domain(
    llm: LLMClient, domain: str, items: list[RawItem]
) -> object | None:
    if not items:
        return None
    spec = extract_tool_spec(domain)
    system = EXTRACT_BASE + DOMAIN_SUFFIX[domain]
    user = f"目标原材料：\n\n{_materialize(items)}"
    raw = await llm.structured_call(
        system=system,
        user=user,
        tool_name=spec["name"],
        tool_description=spec["description"],
        tool_schema=spec["input_schema"],
    )
    if not raw:
        return None
    return MODEL_BY_DOMAIN[domain].model_validate(raw)


async def extract_all_domains(
    llm: LLMClient, by_domain: dict[str, list[RawItem]]
) -> dict[str, object]:
    """Return {'business': BusinessFacts | None, 'reviews': ..., 'news': ..., 'judicial': ...}."""
    coros = [
        _extract_one_domain(llm, d, by_domain.get(d, []))
        for d in ("business", "reviews", "news", "judicial")
    ]
    results = await asyncio.gather(*coros)
    return {d: r for d, r in zip(("business", "reviews", "news", "judicial"), results)}


async def consolidate(
    llm: LLMClient,
    query: CompanyQuery,
    facets: dict[str, object | None],
) -> AggregatedFindings | None:
    """Second-pass consolidation across all four domain extractions."""
    spec = extract_tool_spec("aggregate")
    business = facets.get("business")
    reviews = facets.get("reviews")
    news = facets.get("news")
    judicial = facets.get("judicial")

    user = CONSOLIDATE_USER_TEMPLATE.format(
        company=query.company,
        position=query.position or "(未提供)",
        city=query.city or "(未提供)",
        business=safe_dumps(business.model_dump(mode="json") if business else {}),
        reviews=safe_dumps(reviews.model_dump(mode="json") if reviews else {}),
        news=safe_dumps(news.model_dump(mode="json") if news else {}),
        judicial=safe_dumps(judicial.model_dump(mode="json") if judicial else {}),
    )
    raw = await llm.structured_call(
        system=CONSOLIDATE_SYSTEM,
        user=user,
        tool_name=spec["name"],
        tool_description=spec["description"],
        tool_schema=spec["input_schema"],
    )
    if not raw:
        # Best-effort: stub from raw inputs
        return AggregatedFindings(
            company_query_summary=query.display(),
            business=business if isinstance(business, BusinessFacts) else None,
            reviews=reviews if isinstance(reviews, ReviewFacts) else None,
            news=news if isinstance(news, NewsFacts) else None,
            judicial=judicial if isinstance(judicial, JudicialFacts) else None,
            data_gaps=_auto_gaps(facets),
        )
    agg = AggregatedFindings.model_validate(raw)
    # Guarantee per-domain facts are set even if LLM omitted them
    agg.business = agg.business or (business if isinstance(business, BusinessFacts) else None)
    agg.reviews = agg.reviews or (reviews if isinstance(reviews, ReviewFacts) else None)
    agg.news = agg.news or (news if isinstance(news, NewsFacts) else None)
    agg.judicial = agg.judicial or (judicial if isinstance(judicial, JudicialFacts) else None)
    if not agg.data_gaps:
        agg.data_gaps = _auto_gaps(facets)
    return agg


def _auto_gaps(facets: dict[str, object | None]) -> list[str]:
    gaps: list[str] = []
    if facets.get("business") is None:
        gaps.append("工商基本面数据缺失（本机 gsxt.gov.cn 不可达），建议人工到该网站核实")
    if facets.get("judicial") is None:
        gaps.append("司法风险数据未能获取（裁判文书网 v0.1 抓取受限），建议人工到 wenshu.court.gov.cn 与 zxgk.court.gov.cn 自查")
    return gaps


def parse_interview_lines(text: str) -> list[str]:
    """Split a free-text answer into non-empty stripped lines."""
    return [ln.strip().lstrip("0123456789.、) ").strip() for ln in text.splitlines() if ln.strip()]

"""End-to-end pipeline: collect → normalize → extract → score → render."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx

from jobhunter.collectors.registry import build_all
from jobhunter.config import Settings, load_settings
from jobhunter.llm import (
    INTERVIEW_SYSTEM,
    INTERVIEW_USER_TEMPLATE,
    LLMClient,
    extract_tool_spec,
    list_company_aliases,
    list_workplace_slang,
)
from jobhunter.llm.client import safe_dumps
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.models.report import ReportData
from jobhunter.processing.crosscheck import all_notes, detect_salary_conflicts
from jobhunter.processing.extract import consolidate, extract_all_domains
from jobhunter.processing.normalize import normalize
from jobhunter.report.builder import build_report
from jobhunter.report.scoring import compute_axes
from jobhunter.search.cache import FileCache
from jobhunter.search.tavily_client import TavilyClient
from jobhunter.utils.http import make_client
from jobhunter.utils.slug import make_slug

logger = logging.getLogger(__name__)


@dataclass
class ReportArtifacts:
    data: ReportData
    path: Path
    collector_results: list[CollectorResult]
    cost_usd: float
    tokens_in: int
    tokens_out: int


async def run(
    query: CompanyQuery,
    *,
    settings: Settings | None = None,
    output_dir: Path | None = None,
    open_browser: bool = False,
) -> ReportArtifacts:
    """Execute the full pipeline and write HTML to disk.

    `output_dir` overrides `settings.output_dir`.
    """
    settings = settings or load_settings()
    ok, missing = settings.is_ready()
    if not ok:
        raise RuntimeError(f"Missing required API keys: {missing}")

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    out_dir = output_dir or settings.output_dir

    cache = FileCache()
    tavily = TavilyClient(settings, cache)
    llm = LLMClient(settings)

    # Generate aliases (abbreviations / English / sub-brands) before searching so
    # the reviews-domain query template can expand beyond exact-match quotes.
    # Best-effort: on failure, the run proceeds with only the full name.
    if not query.aliases:
        try:
            query = query.model_copy(
                update={"aliases": await list_company_aliases(llm, query.company)}
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("alias generation failed: %s", e)

    # Generate colloquial / slang search terms (内卷 / ICU / 摆烂 / PUA …) to
    # widen reviews-domain recall beyond literal "加班 / 薪资" queries. Same
    # best-effort posture — failure just means the run searches with literal
    # terms only.
    if not query.slang_queries:
        try:
            query = query.model_copy(
                update={"slang_queries": await list_workplace_slang(
                    llm, query.company, query.position
                )}
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("slang query generation failed: %s", e)

    async with make_client() as http:
        collectors = build_all(settings, tavily=tavily, http=http)
        results = await asyncio.gather(*(c.safe_collect(query) for c in collectors))

    by_domain = normalize(results)

    facets = await extract_all_domains(llm, by_domain)

    findings = await consolidate(llm, query, facets)
    if findings is None:
        findings = AggregatedFindings(
            company_query_summary=query.display(),
            business=facets.get("business") if isinstance(facets.get("business"), BusinessFacts) else None,
            reviews=facets.get("reviews") if isinstance(facets.get("reviews"), ReviewFacts) else None,
            news=facets.get("news") if isinstance(facets.get("news"), NewsFacts) else None,
            judicial=facets.get("judicial") if isinstance(facets.get("judicial"), JudicialFacts) else None,
            company_profile=facets.get("company_info") if isinstance(facets.get("company_info"), CompanyProfile) else None,
        )

    reviews = findings.reviews
    notes = detect_salary_conflicts(reviews) if reviews else []
    additional = all_notes(reviews) if reviews else []
    for n in additional:
        if n not in notes:
            notes.append(n)

    axes = compute_axes(findings, by_domain, notes)
    overall_confidence = _compute_confidence(by_domain, findings)

    interview_questions = await _gen_interview_questions(
        llm, query, axes, findings
    )

    data = ReportData(
        query=query,
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        axes=axes,
        business_facts=findings.business,
        review_facts=findings.reviews,
        news_facts=findings.news,
        judicial_facts=findings.judicial,
        company_profile=findings.company_profile,
        interview_questions=interview_questions,
        data_gaps=findings.data_gaps,
        overall_confidence=overall_confidence,
    )

    html = build_report(data)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    slug = make_slug(query, ts)
    out_path = out_dir / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")

    if open_browser:
        try:
            from jobhunter.utils.browser import open_in_browser
            open_in_browser(out_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("could not open browser: %s", e)

    return ReportArtifacts(
        data=data,
        path=out_path,
        collector_results=list(results),
        cost_usd=llm.cost_usd,
        tokens_in=llm.tokens_in,
        tokens_out=llm.tokens_out,
    )


def _compute_confidence(
    by_domain: dict[str, list],
    findings: AggregatedFindings | None,
) -> Literal["high", "medium", "low"]:
    have_business = bool(by_domain.get("business")) or (findings is not None and findings.business is not None)
    reviews = findings.reviews if findings else None
    have_reviews = bool(by_domain.get("reviews")) or (
        reviews is not None and (reviews.salary_signals or reviews.vibe_signals or reviews.overtime_signals)
    )
    news = findings.news if findings else None
    have_news = bool(by_domain.get("news")) or (news is not None and bool(news.items))
    have_judicial = bool(by_domain.get("judicial")) or (
        findings is not None and findings.judicial is not None
    )
    have_company_profile = bool(by_domain.get("company_info")) or (
        findings is not None
        and findings.company_profile is not None
        and (
            findings.company_profile.description
            or findings.company_profile.main_business
            or findings.company_profile.products
        )
    )
    n = sum([have_business, have_reviews, have_news, have_judicial, have_company_profile])
    if n >= 4:
        return "high"
    if n >= 3:
        return "medium"
    return "low"


async def _gen_interview_questions(
    llm: LLMClient,
    query: CompanyQuery,
    axes,
    findings: AggregatedFindings | None,
) -> list[str]:
    """Plain-text LLM call → split by line."""
    from jobhunter.processing.extract import parse_interview_lines

    axes_text = "\n".join(
        f"- {ax.label_zh} ({ax.stars}/5): {ax.rationale}" for ax in axes
    )
    snippets: dict[str, str] = {}
    if findings:
        if findings.business:
            snippets["business"] = f"工商: legal_rep={findings.business.legal_rep}, status={findings.business.status}"
        if findings.reviews:
            snippets["reviews"] = f"评价: {len(findings.reviews.salary_signals)} 薪酬条, {len(findings.reviews.vibe_signals)} 氛围条"
        if findings.news:
            snippets["news"] = f"新闻: {len(findings.news.items)} 条, 情感={findings.news.sentiment}"
        if findings.judicial:
            snippets["judicial"] = f"司法: 累计 {findings.judicial.case_count_total}, 被执行 {findings.judicial.enforcement_records}"
        if findings.company_profile:
            cp = findings.company_profile
            snippets["company_profile"] = (
                f"公司画像: 主营={'/'.join(cp.main_business[:2]) if cp.main_business else '?'}, "
                f"规模={cp.company_size or '?'}, 融资={cp.funding_stage or '?'}"
            )

    user = INTERVIEW_USER_TEMPLATE.format(
        company=query.company,
        position=query.position or "(未提供)",
        city=query.city or "(未提供)",
        axes=axes_text,
        business=snippets.get("business", "工商: 数据缺失"),
        reviews=snippets.get("reviews", "评价: 数据缺失"),
        news=snippets.get("news", "新闻: 数据缺失"),
        judicial=snippets.get("judicial", "司法: 数据缺失"),
        company_profile=snippets.get("company_profile", "公司画像: 数据缺失"),
    )
    text = await llm.chat(system=INTERVIEW_SYSTEM, user=user)
    return parse_interview_lines(text)

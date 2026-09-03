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
    list_company_entities,
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

    # ---------- Round 2: recursive sub-query via LLM-extracted internal entities ----------
    # After the first round of reviews hits land, ask the LLM to surface internal
    # entities (products / sub-brands / departments / founders) that 打工人 reference
    # instead of the company name. Use these as aliases for a second reviews pass
    # — close the loop between "raw text" and "search seed" without any new
    # external dependency. Hard caps (max 5 entities, max 1 recursive round) keep
    # cost bounded; URL + title dedup happens naturally in `normalize()` below.
    if llm.budget_ok():
        try:
            reviews_items: list = []
            for r in results:
                if not r.error and r.domain == "reviews":
                    reviews_items.extend(r.items)
            if reviews_items:
                entities = await list_company_entities(
                    llm, query.company, reviews_items, max_items=5
                )
                known = {query.company, *(query.aliases or [])}
                fresh = [e for e in entities if e not in known]
                if fresh:
                    logger.info(
                        "round 2: extracted %d entities, running sub-queries: %s",
                        len(fresh), fresh,
                    )
                    sub_query = query.model_copy(update={"aliases": fresh})
                    async with make_client() as http:
                        sub_collectors = build_all(settings, tavily=tavily, http=http)
                        sub_results = await asyncio.gather(
                            *(c.safe_collect(sub_query) for c in sub_collectors)
                        )
                    results = list(results) + list(sub_results)
                else:
                    logger.info("round 2: no fresh entities after dedup; skipping sub-query")
            else:
                logger.info("round 2: no reviews items in round 1; skipping sub-query")
        except Exception as e:  # noqa: BLE001 - best-effort, never block the run
            logger.warning("recursive sub-query failed: %s", e)

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
    chapter_confidence = _compute_confidence(by_domain, findings)
    overall_confidence = chapter_confidence.get("overall", "low")

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
        chapter_confidence=chapter_confidence,
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
) -> dict[str, Literal["high", "medium", "low"]]:
    """Per-chapter confidence bucket.

    Each domain gets its own high/medium/low based on whether raw items landed
    AND whether extract pulled structured signal out of them. A chapter is
    'high' only when both are true. 'medium' when one is true. 'low' otherwise.

    The function also returns an overall key (sum-based legacy behavior) for
    the hero ring badge.
    """
    reviews = findings.reviews if findings else None
    news = findings.news if findings else None

    def _bucket(have_raw: bool, have_struct: bool) -> Literal["high", "medium", "low"]:
        if have_raw and have_struct:
            return "high"
        if have_raw or have_struct:
            return "medium"
        return "low"

    have_company_struct = (
        findings is not None
        and findings.company_profile is not None
        and (
            findings.company_profile.description
            or findings.company_profile.main_business
            or findings.company_profile.products
        )
    )
    have_business_struct = (
        findings is not None
        and findings.business is not None
        and (
            findings.business.legal_rep
            or findings.business.status
            or findings.business.registered_capital
        )
    )
    have_reviews_struct = (
        reviews is not None
        and (reviews.salary_signals or reviews.vibe_signals or reviews.overtime_signals)
    )
    have_news_struct = news is not None and bool(news.items)
    have_judicial_struct = (
        findings is not None
        and findings.judicial is not None
        and (findings.judicial.case_count_total is not None or findings.judicial.sample_cases)
    )

    per = {
        "company": _bucket(bool(by_domain.get("company_info")), have_company_struct),
        "business": _bucket(bool(by_domain.get("business")), have_business_struct),
        "judicial": _bucket(bool(by_domain.get("judicial")), have_judicial_struct),
        "reviews": _bucket(bool(by_domain.get("reviews")), have_reviews_struct),
        "news": _bucket(bool(by_domain.get("news")), have_news_struct),
    }

    # Overall = sum-of-buckets score (high=2, medium=1, low=0). Legacy behavior
    # was "≥4 of 5 domains have something → high"; preserve the same user-visible
    # semantics by mapping the same richness to high/medium/low.
    score = (per["company"] == "high") * 2 + (per["company"] == "medium") \
          + (per["business"] == "high") * 2 + (per["business"] == "medium") \
          + (per["judicial"] == "high") * 2 + (per["judicial"] == "medium") \
          + (per["reviews"] == "high") * 2 + (per["reviews"] == "medium") \
          + (per["news"] == "high")    * 2 + (per["news"] == "medium")
    if score >= 8:
        overall: Literal["high", "medium", "low"] = "high"
    elif score >= 5:
        overall = "medium"
    else:
        overall = "low"
    per["overall"] = overall
    return per


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

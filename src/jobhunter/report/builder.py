"""HTML report builder — Jinja2 render of ReportData."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import jinja2

from jobhunter.models.report import ReportData, SourceEntry
from jobhunter.report.charts import (
    case_timeline_svg,
    case_year_buckets,
    funding_stage_position,
    news_items_for_timeline,
    news_timeline_svg,
    overtime_distribution,
    radar_svg,
    salary_distribution,
    score_ring_svg,
    shareholder_pie_svg,
    vibe_donut_svg,
    vibe_sentiment_counts,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _domain_of(url) -> str:
    try:
        return urlparse(str(url)).hostname or "link"
    except Exception:  # noqa: BLE001
        return "link"


def _favicon_url(domain: str, size: int = 32) -> str:
    return f"https://www.google.com/s2/favicons?sz={size}&domain={domain}"


def _collect_sources(data: ReportData) -> list[SourceEntry]:
    """De-dup sources by URL, sorted by domain then title."""
    seen: dict[str, SourceEntry] = {}
    f = data.findings
    if f is not None:
        for url in (
            (f.business.source_urls if f.business else [])
            + (f.reviews.source_urls if f.reviews else [])
            + (f.news.source_urls if f.news else [])
            + (f.judicial.source_urls if f.judicial else [])
        ):
            key = str(url)
            if key not in seen:
                seen[key] = SourceEntry(domain=_domain_of(url), title="", url=url)
    # Add title hints from review/news/judicial items where available
    if f is not None and f.reviews is not None:
        signals = (f.reviews.salary_signals or []) + (f.reviews.overtime_signals or []) + (f.reviews.vibe_signals or [])
        for s in signals:
            if s.url and str(s.url) not in seen:
                seen[str(s.url)] = SourceEntry(domain=_domain_of(s.url), title=getattr(s, "evidence", "")[:60], url=s.url)
    if f is not None and f.news is not None:
        for it in (f.news.items or []):
            if it.url and str(it.url) not in seen:
                seen[str(it.url)] = SourceEntry(domain=_domain_of(it.url), title=it.title, url=it.url)
    if f is not None and f.judicial is not None:
        for c in (f.judicial.sample_cases or []):
            if c.url and str(c.url) not in seen:
                seen[str(c.url)] = SourceEntry(domain=_domain_of(c.url), title=c.title, url=c.url)
    return sorted(seen.values(), key=lambda s: (s.domain, s.title or ""))


def _axes_avg(axes) -> float:
    if not axes:
        return 0.0
    return round(sum(a.stars for a in axes) / len(axes), 2)


def _domain_root(url: str | None) -> str:
    """Return the registrable root of a URL host (e.g. 'maimai.cn', 'v2ex.com').
    Used to bucket URLs by domain for cross-source corroboration."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(url)).hostname or "").lower()
        if not host:
            return ""
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


def compute_signal_supports(review_facts) -> dict[str, dict]:
    """For each signal in review_facts, compute (support_count, support_tier).

    support_count = len(supporting_urls) + 1 (the main `url` counts as one).
    support_tier:
        - 'unverified'           : no urls at all
        - 'single-source'        : exactly one url (could be the LLM-confabulated)
        - 'corroborated'         : ≥2 urls from ≥2 distinct domain roots
        - 'multi-domain'         : ≥3 urls from ≥3 distinct domain roots

    Returns a dict keyed by the signal's main url string for the template to
    look up. Signals with no url are excluded.
    """
    out: dict[str, dict] = {}
    if not review_facts:
        return out

    def _annotate(url, supporting_urls):
        if not url:
            return None
        all_urls = [str(url)] + [str(u) for u in (supporting_urls or [])]
        domains = {_domain_root(u) for u in all_urls if u}
        domains.discard("")
        n = len(all_urls)
        n_dom = len(domains)
        if n == 0:
            tier = "unverified"
        elif n == 1 or n_dom == 1:
            tier = "single-source"
        elif n_dom >= 3:
            tier = "multi-domain"
        else:
            tier = "corroborated"
        return {"support_count": n, "support_tier": tier, "domains": sorted(domains)}

    for s in (review_facts.salary_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.overtime_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.vibe_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.turnover_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    return out


_TIER_LABEL = {
    "unverified":    ("待核实", "tier-unverified"),
    "single-source": ("单一来源", "tier-single"),
    "corroborated":  ("多源印证", "tier-corroborated"),
    "multi-domain":  ("跨域印证", "tier-multi"),
}

_CONFIDENCE_LABEL = {
    "high":   ("数据充足",   "conf-high"),
    "medium": ("部分缺失",   "conf-medium"),
    "low":    ("需人工核查", "conf-low"),
}


def compute_diversity_kpi(review_facts, sources) -> dict:
    """Source-diversity KPI for the hero meta line.

    Aggregates:
      - total_signals (sum of salary/overtime/turnover/vibe signals)
      - corroborated_count (tier in {corroborated, multi-domain})
      - distinct_domains (unique domain roots across all review signals)
      - tier_distribution (count per tier)

    Used by the 「数据多样性」 pill in the report header.
    """
    out = {
        "total_signals": 0,
        "corroborated_count": 0,
        "distinct_domains": set(),
        "tier_distribution": {"unverified": 0, "single-source": 0, "corroborated": 0, "multi-domain": 0},
        "tier_label_zh": "—",
    }
    if review_facts:
        out["total_signals"] = (
            len(review_facts.salary_signals or [])
            + len(review_facts.overtime_signals or [])
            + len(review_facts.turnover_signals or [])
            + len(review_facts.vibe_signals or [])
        )
    supports = compute_signal_supports(review_facts) if review_facts else {}
    for info in supports.values():
        tier = info.get("support_tier", "unverified")
        out["tier_distribution"][tier] = out["tier_distribution"].get(tier, 0) + 1
        out["distinct_domains"].update(info.get("domains", []))
    out["corroborated_count"] = (
        out["tier_distribution"].get("corroborated", 0)
        + out["tier_distribution"].get("multi-domain", 0)
    )
    # Copy out — Jinja can't render set
    out["distinct_domains"] = sorted(out["distinct_domains"])
    n_dom = len(out["distinct_domains"])
    n_total = out["total_signals"]
    if n_total == 0:
        out["tier_label_zh"] = "无信号"
    elif n_dom >= 4 and out["corroborated_count"] >= 3:
        out["tier_label_zh"] = "高"
    elif n_dom >= 2 and out["corroborated_count"] >= 1:
        out["tier_label_zh"] = "中"
    else:
        out["tier_label_zh"] = "低"
    return out


def build_report(data: ReportData) -> str:
    css = (_STATIC_DIR / "report.css").read_text(encoding="utf-8")
    sources = _collect_sources(data)
    axes = data.axes or []
    avg_score = _axes_avg(axes)
    radar = radar_svg(axes)
    hero_ring = score_ring_svg(avg_score) if avg_score else ""
    overtime_dist = overtime_distribution(data.review_facts.overtime_signals) if data.review_facts else []
    salary_dist = salary_distribution(data.review_facts.salary_signals) if data.review_facts else []

    # New editorial primitives
    vibe_counts = vibe_sentiment_counts(data.review_facts.vibe_signals) if data.review_facts else []
    vibe_donut = vibe_donut_svg(vibe_counts)
    shareholders = (data.business_facts.top_shareholders if data.business_facts else []) or []
    shareholder_donut = shareholder_pie_svg(shareholders)
    sample_cases = (data.judicial_facts.sample_cases if data.judicial_facts else []) or []
    case_buckets = case_year_buckets(sample_cases)
    case_timeline = case_timeline_svg(case_buckets)
    funding_pos = funding_stage_position(
        data.company_profile.funding_stage if data.company_profile else None
    )
    news_timeline_items = (
        news_items_for_timeline(data.news_facts.items) if data.news_facts else []
    )
    news_timeline_svg_str = (
        news_timeline_svg(
            news_timeline_items,
            sentiment=data.news_facts.sentiment if data.news_facts else "neutral",
        )
        if news_timeline_items else ""
    )

    # Cross-source corroboration for review signals — drives the
    # 「待核实 / 单一来源 / 多源印证 / 跨域印证」tier badge in chapter IV/V/VI.
    signal_supports = compute_signal_supports(data.review_facts)
    diversity_kpi = compute_diversity_kpi(data.review_facts, sources)

    tmpl = _ENV.get_template("report.html.j2")
    return tmpl.render(
        data=data,
        css=css,
        sources=sources,
        now=datetime.now(),
        avg_score=avg_score,
        radar_svg=radar,
        hero_ring_svg=hero_ring,
        overtime_dist=overtime_dist,
        salary_dist=salary_dist,
        vibe_counts=vibe_counts,
        vibe_donut_svg=vibe_donut,
        shareholder_donut_svg=shareholder_donut,
        case_buckets=case_buckets,
        case_timeline_svg=case_timeline,
        funding_stage_pos=funding_pos,
        news_timeline_items=news_timeline_items,
        news_timeline_svg=news_timeline_svg_str,
        signal_supports=signal_supports,
        tier_label=_TIER_LABEL,
        diversity_kpi=diversity_kpi,
        confidence_label=_CONFIDENCE_LABEL,
        favicon_url=_favicon_url,
    )
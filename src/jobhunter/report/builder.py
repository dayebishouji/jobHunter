"""HTML report builder — Jinja2 render of ReportData."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import jinja2

from jobhunter.models.report import ReportData, SourceEntry
from jobhunter.report.charts import (
    overtime_distribution,
    radar_svg,
    salary_distribution,
    score_ring_svg,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Section icons (Unicode-only, no external font required)
SECTION_ICONS = {
    "工商基本面": "🏢",
    "司法风险": "⚖",
    "薪酬与福利": "💰",
    "加班与工作强度": "⏱",
    "团队氛围与文化": "🧭",
    "岗位真实情况 vs 招聘 JD": "📋",
    "近期舆情": "📰",
    "面试反问清单": "💬",
    "综合推断（LLM 推断，每条带佐证）": "🧠",
    "数据来源附录": "🔗",
    "数据缺口": "⚠",
}


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
        for s in list(f.reviews.salary_signals) + list(f.reviews.overtime_signals) + list(f.reviews.vibe_signals):
            if s.url and str(s.url) not in seen:
                seen[str(s.url)] = SourceEntry(domain=_domain_of(s.url), title=getattr(s, "evidence", "")[:60], url=s.url)
    if f is not None and f.news is not None:
        for it in f.news.items:
            if it.url and str(it.url) not in seen:
                seen[str(it.url)] = SourceEntry(domain=_domain_of(it.url), title=it.title, url=it.url)
    if f is not None and f.judicial is not None:
        for c in f.judicial.sample_cases:
            if c.url and str(c.url) not in seen:
                seen[str(c.url)] = SourceEntry(domain=_domain_of(c.url), title=c.title, url=c.url)
    return sorted(seen.values(), key=lambda s: (s.domain, s.title or ""))


def _axes_avg(axes) -> float:
    if not axes:
        return 0.0
    return round(sum(a.stars for a in axes) / len(axes), 2)


def build_report(data: ReportData) -> str:
    css = (_STATIC_DIR / "report.css").read_text(encoding="utf-8")
    sources = _collect_sources(data)
    axes = data.axes or []
    avg_score = _axes_avg(axes)
    radar = radar_svg(axes)
    hero_ring = score_ring_svg(avg_score) if avg_score else ""
    overtime_dist = overtime_distribution(data.review_facts.overtime_signals) if data.review_facts else []
    salary_dist = salary_distribution(data.review_facts.salary_signals) if data.review_facts else []
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
        favicon_url=_favicon_url,
        section_icon=lambda title: SECTION_ICONS.get(title, "•"),
    )
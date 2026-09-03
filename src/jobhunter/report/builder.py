"""HTML report builder — Jinja2 render of ReportData."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import jinja2

from jobhunter.models.report import ReportData, SourceEntry

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _collect_sources(data: ReportData) -> list[SourceEntry]:
    """De-dup sources by URL, sorted by domain then title."""
    seen: dict[str, SourceEntry] = {}
    for f in (data.findings,) if data.findings else ():
        for url in (f.business.source_urls if f.business else []) + \
                     (f.reviews.source_urls if f.reviews else []) + \
                     (f.news.source_urls if f.news else []) + \
                     (f.judicial.source_urls if f.judicial else []):
            key = str(url)
            if key not in seen:
                seen[key] = SourceEntry(domain="aggregated", title="", url=url)
    for url_set in (
        [u for f in (data.findings.business,) if f for u in f.source_urls],
        [u for f in (data.findings.reviews,) if f for u in f.source_urls],
        [u for f in (data.findings.news,) if f for u in f.source_urls],
        [u for f in (data.findings.judicial,) if f for u in f.source_urls],
    ):
        for u in url_set:
            seen.setdefault(str(u), SourceEntry(domain="link", title="", url=u))
    return sorted(seen.values(), key=lambda s: (s.domain, s.title or ""))


def build_report(data: ReportData) -> str:
    css = (_STATIC_DIR / "report.css").read_text(encoding="utf-8")
    sources = _collect_sources(data)
    tmpl = _ENV.get_template("report.html.j2")
    return tmpl.render(
        data=data,
        css=css,
        sources=sources,
        now=datetime.now(),
    )

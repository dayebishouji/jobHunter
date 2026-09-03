"""Report HTML rendering — generate and assert content."""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.models.query import CompanyQuery
from jobhunter.models.facts import (
    AggregatedFindings, ReviewFacts, OvertimeSignal, VibeSignal,
)
from jobhunter.models.report import ReportData
from jobhunter.report.builder import build_report
from jobhunter.report.scoring import compute_axes


def _minimal_data() -> ReportData:
    q = CompanyQuery(company="TestCorp", position="后端工程师", city="杭州")
    reviews = ReviewFacts(
        overtime_signals=[OvertimeSignal(pattern="996", intensity="high")],
        vibe_signals=[VibeSignal(sentiment="mixed", evidence="流程乱")],
    )
    findings = AggregatedFindings(reviews=reviews)
    return ReportData(
        query=q,
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        review_facts=reviews,
        axes=compute_axes(findings, {}, []),
    )


def test_render_basic_html_structure():
    data = _minimal_data()
    html = build_report(data)
    assert html.startswith("<!DOCTYPE")
    assert "</html>" in html
    assert "TestCorp" in html
    assert "<style>" in html
    assert ":root" in html  # CSS embedded
    assert "加班强度" in html  # axis label appears in radar + axis list
    assert "<details>" in html
    assert "薪酬与福利" in html  # at least one of the always-rendered sections
    assert "数据来源附录" in html
    # New: chart pieces
    assert "radar-svg" in html
    assert "score-ring-svg" in html
    assert "hbar-fill" in html  # overtime bar chart rendered (we have 1 overtime signal)


def test_render_with_data_gaps():
    data = _minimal_data()
    data.data_gaps = ["工商数据缺失"]
    html = build_report(data)
    assert "工商数据缺失" in html
    assert "数据缺口" in html


def test_render_includes_judicial_manual_link_when_missing():
    data = _minimal_data()
    # judicial_facts is None by default
    html = build_report(data)
    assert "wenshu.court.gov.cn" in html or "zxgk.court.gov.cn" in html

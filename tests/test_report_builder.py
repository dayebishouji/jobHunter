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
    assert "加班强度" in html  # axis label appears in ribbon + radar
    assert 'class="chapter"' in html  # chapter layout (no <details>)
    assert "薪酬与福利" in html  # at least one chapter title
    assert "来源附录" in html  # sources chapter title (renamed from 数据来源附录)
    # New: chart pieces
    assert "radar-svg" in html
    assert "score-ring-svg" in html
    assert "dist-row-fill" in html  # overtime distribution row rendered (we have 1 signal)


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


def test_render_company_profile_empty_uses_manual_links():
    """When CompanyProfile is None, template still surfaces manual-check links."""
    data = _minimal_data()
    html = build_report(data)
    assert "百度百科" in html
    assert "IT 桔子" in html


def test_render_axis_ribbon_renders_all_five_axes():
    data = _minimal_data()
    html = build_report(data)
    assert "axis-ribbon-cell" in html
    # 5 axis cells should be present
    assert html.count("axis-ribbon-cell") >= 5

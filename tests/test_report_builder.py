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
    assert "加班强度" in html  # axis label appears in KPI grid
    assert 'class="chapter"' in html  # chapter layout
    assert "薪酬" in html  # chapter IV title (v0.2.0 split into IV 薪酬 / V 团队健康度 / VI 团队氛围)
    assert "Σ 来源附录" in html  # sources chapter title
    # v0.2.0 — broker-research hybrid elements
    assert "投资要点" in html
    assert "主编按" in html
    assert "5 轴雷达" in html
    assert "风险提示" in html  # risk-disclosure footer
    # Charts
    assert "radar-svg" in html


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
    # v0.2.0 — manual-check link uses generic message in chapter-takeaway
    assert "公司画像" in html  # chapter heading still rendered
    assert "本次未能取得" in html  # soft-fail note visible


def test_render_axis_kpi_grid_renders_three_cells():
    """v0.2.0 — KPI grid (3 cells: 综合分 / 司法 / 加班) replaces the old 5-cell axis ribbon."""
    data = _minimal_data()
    html = build_report(data)
    assert "kpi-cell" in html
    assert html.count("kpi-cell") >= 3


class TestComputeSignalSupports:
    """Cross-source corroboration tier logic for review signals."""

    def test_no_signals_returns_empty_dict(self):
        from jobhunter.report.builder import compute_signal_supports
        from jobhunter.models.facts import ReviewFacts
        assert compute_signal_supports(ReviewFacts()) == {}

    def test_signal_with_only_main_url_is_single_source(self):
        from jobhunter.report.builder import compute_signal_supports
        from jobhunter.models.facts import ReviewFacts, OvertimeSignal
        rf = ReviewFacts(overtime_signals=[
            OvertimeSignal(
                pattern="996", intensity="high",
                url="https://maimai.cn/x",
            )
        ])
        supports = compute_signal_supports(rf)
        assert supports["https://maimai.cn/x"]["support_tier"] == "single-source"
        assert supports["https://maimai.cn/x"]["support_count"] == 1

    def test_signal_with_two_same_domain_urls_is_single_source(self):
        from jobhunter.report.builder import compute_signal_supports
        from jobhunter.models.facts import ReviewFacts, OvertimeSignal
        rf = ReviewFacts(overtime_signals=[
            OvertimeSignal(
                pattern="996", intensity="high",
                url="https://maimai.cn/a",
                supporting_urls=["https://maimai.cn/b"],
            )
        ])
        supports = compute_signal_supports(rf)
        # 2 urls, 1 domain → single-source
        assert supports["https://maimai.cn/a"]["support_tier"] == "single-source"

    def test_signal_with_two_distinct_domains_is_corroborated(self):
        from jobhunter.report.builder import compute_signal_supports
        from jobhunter.models.facts import ReviewFacts, OvertimeSignal
        rf = ReviewFacts(overtime_signals=[
            OvertimeSignal(
                pattern="996", intensity="high",
                url="https://maimai.cn/a",
                supporting_urls=["https://v2ex.com/b"],
            )
        ])
        supports = compute_signal_supports(rf)
        assert supports["https://maimai.cn/a"]["support_tier"] == "corroborated"
        assert supports["https://maimai.cn/a"]["support_count"] == 2

    def test_signal_with_three_distinct_domains_is_multi_domain(self):
        from jobhunter.report.builder import compute_signal_supports
        from jobhunter.models.facts import ReviewFacts, OvertimeSignal
        rf = ReviewFacts(overtime_signals=[
            OvertimeSignal(
                pattern="996", intensity="high",
                url="https://maimai.cn/a",
                supporting_urls=[
                    "https://v2ex.com/b",
                    "https://www.zhihu.com/c",
                ],
            )
        ])
        supports = compute_signal_supports(rf)
        assert supports["https://maimai.cn/a"]["support_tier"] == "multi-domain"
        assert supports["https://maimai.cn/a"]["support_count"] == 3


def test_render_includes_tier_badges_for_signals():
    """v0.2.0 — Tier badge appears next to each signal card in chapters V/VI."""
    from jobhunter.models.facts import OvertimeSignal
    data = _minimal_data()
    # Re-create with multi-domain corroboration
    reviews = ReviewFacts(
        overtime_signals=[OvertimeSignal(
            pattern="996", intensity="high",
            url="https://maimai.cn/a",
            supporting_urls=[
                "https://v2ex.com/b",
                "https://www.zhihu.com/c",
            ],
        )],
        vibe_signals=[VibeSignal(sentiment="mixed", evidence="流程乱")],
    )
    data.review_facts = reviews
    data.findings.reviews = reviews
    html = build_report(data)
    assert "signal-tier" in html
    assert "tier-multi-domain" in html  # 3 distinct domains → multi-domain (v0.2.0 class)
    assert "跨域印证" in html

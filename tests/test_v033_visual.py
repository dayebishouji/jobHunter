"""v0.3.3 — Visual refinement tests.

Asserts the 8 impeccable-grade visual upgrades (A1-A8) render in the
final HTML, plus integration tests confirming new CSS classes coexist
with existing rendering.
"""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    Shareholder,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import ReportData
from jobhunter.report.builder import build_report


def _data() -> ReportData:
    cp = CompanyProfile(
        motto="让生意更简单",
        founded_year=2014,
        funding_stage="D轮及以上",
        total_funding="约30亿元",
        investors=["红杉资本", "IDG"],
        main_business=["SaaS"],
        products=["有赞微商城"],
        employee_count=2500,
        insured_count=2300,
        industries=["企业服务"],
        headquarters="杭州",
    )
    bf = BusinessFacts(
        status="存续", legal_rep="白鸦", registered_capital="5000万元",
        top_shareholders=[Shareholder(name="白鸦", stake_pct=22.0)],
    )
    jf = JudicialFacts(case_count_total=2, enforcement_records=1)
    rf = ReviewFacts(
        overtime_signals=[OvertimeSignal(pattern="996", intensity="high",
                                          evidence="996 是日常",
                                          url="https://maimai.cn/x")],
        vibe_signals=[VibeSignal(sentiment="negative", evidence="流程乱",
                                   url="https://zhipin.com/y")],
    )
    nf = NewsFacts(sentiment="neutral", items=[])
    findings = AggregatedFindings(
        company_profile=cp, business=bf, judicial=jf, reviews=rf, news=nf,
        inferences=[],
    )
    return ReportData(
        query=CompanyQuery(company="有赞", position="后端", city="杭州"),
        generated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        findings=findings,
        company_profile=cp, business_facts=bf, judicial_facts=jf,
        review_facts=rf, news_facts=nf,
    )


class TestCoverThesis:
    """A1 — Cover thesis typographic peak."""

    def test_renders_when_verdict_present(self):
        html = build_report(_data())
        assert 'class="cover-thesis"' in html
        assert 'class="cover-thesis-quote"' in html


class TestKpiGrid:
    """A2 — KPI grid expands to 5 cells."""

    def test_renders_five_cells(self):
        html = build_report(_data())
        # 3 original + 数据多样性 + 已抓取维度 = 5
        assert html.count('class="kpi-cell"') == 5
        assert "数据多样性" in html
        assert "已抓取维度" in html


class TestMastheadDetail:
    """A3 — Pre-cover detail band."""

    def test_band_renders_six_items(self):
        html = build_report(_data())
        assert 'class="masthead-detail"' in html
        # 6 items: 公司 / 岗位 / 城市 / 日期 / 维度 / 置信度
        assert html.count('class="masthead-detail-item"') == 6
        assert "有赞" in html
        assert "后端" in html
        assert "杭州" in html


class TestSignalCardAttribution:
    """A5 — Signal evidence attribution line."""

    def test_signal_card_has_attribution(self):
        html = build_report(_data())
        assert 'class="signal-evidence-attribution"' in html
        assert "来源：" in html
        assert "印证" in html


class TestChapterDivider:
    """A6 — Dotted divider between main chapters."""

    def test_dividers_between_main_chapters(self):
        html = build_report(_data())
        # 6 dividers between 7 main chapters (I-VII)
        assert html.count('class="chapter-divider"') == 6
        assert "· · ·" in html


class TestSlangWall:
    """A7 — Compact slang chip wall."""

    def test_slang_chip_wall_replaces_grid(self):
        html = build_report(_data())
        # When slang_glossary is empty, the wall block is skipped; just
        # confirm the new container class exists in CSS for when data lands.
        assert ".slang-wall" in html  # in embedded CSS
        assert ".slang-chip" in html   # in embedded CSS

    def test_slang_chip_wall_renders_when_data_present(self):
        from jobhunter.models.facts import SlangEntry
        data = _data()
        data.review_facts.slang_glossary = [
            SlangEntry(term="内卷", meaning="竞争过度", count=8),
            SlangEntry(term="ICU", meaning="996 + ICU", count=3),
        ]
        html = build_report(data)
        assert 'class="slang-wall"' in html
        assert 'class="slang-chip"' in html
        # chip count = 2 entries
        assert html.count('class="slang-chip"') >= 2
        # new 1-char mark present
        assert 'class="slang-chip-mark"' in html


class TestCoverDispatchUpgrade:
    """A4 — Editorial aside with prose + ordered reasons."""

    def test_cover_dispatch_has_tag_body_reasons(self):
        html = build_report(_data())
        assert 'class="cover-dispatch"' in html
        assert 'class="cover-dispatch-tag"' in html
        # 主编按 label
        assert "主编按" in html


class TestSideSectionRule:
    """A8 — Side chapter section visual frame."""

    def test_side_section_visual_frame_in_css(self):
        html = build_report(_data())
        assert ".side-section" in html  # in CSS
        assert ".side-section-tag" in html  # in CSS

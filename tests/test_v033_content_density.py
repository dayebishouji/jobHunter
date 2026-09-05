"""v0.3.3 — Content density tests.

Surfaces ~17 under-leveraged fields into the rendered HTML report and asserts
each new slot renders correctly. Also guards the bf.stakeholders →
bf.top_shareholders template bug fix.
"""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    InferredClaim,
    JDGapSignal,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
    Shareholder,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import ReportData
from jobhunter.report.builder import build_report


def _data_with_all_fields() -> ReportData:
    """Build a maximally-populated ReportData so all v0.3.3 slots render."""
    cp = CompanyProfile(
        motto="让生意更简单",
        description="中国 SaaS 服务商",
        business_scope="为商家提供 SaaS 服务",
        main_business=["电商 SaaS", "门店管理", "营销工具", "跨境支付"],
        official_website="https://www.youzan.com",
        products=["有赞微商城", "有赞零售", "有赞美业"],
        industries=["企业服务", "电商 SaaS"],
        company_size="1000-5000人",
        employee_count=2500,
        insured_count=2300,
        founded_year=2014,
        founded_at=None,
        headquarters="杭州",
        funding_stage="D轮及以上",
        total_funding="约30亿元",
        investors=["红杉资本", "IDG资本", "高瓴创投"],
        prospects="受益于私域流量趋势，长期看好",
    )
    bf = BusinessFacts(
        legal_rep="白鸦",
        registered_capital="5000万元",
        paid_in_capital="5000万元",
        established_at=None,
        status="存续",
        address="浙江省杭州市西湖区文一西路 998 号",
        external_investments_count=4,
        anomaly_listed=False,
        top_shareholders=[
            Shareholder(name="白鸦", stake_pct=22.0),
            Shareholder(name="红杉资本", stake_pct=15.0),
            Shareholder(name="员工持股平台", stake_pct=10.0),
        ],
    )
    jf = JudicialFacts(
        case_count_total=5,
        case_count_recent_year=2,
        enforcement_records=1,
        sample_cases=[],
    )
    rf = ReviewFacts(
        jd_gap_signals=[
            JDGapSignal(jd_promise="弹性工作", reality="实际 996"),
            JDGapSignal(jd_promise="15 薪", reality="实际 12 薪"),
        ],
    )
    nf = NewsFacts(sentiment="neutral", items=[])
    findings = AggregatedFindings(
        company_profile=cp,
        business=bf,
        judicial=jf,
        reviews=rf,
        news=nf,
        company_query_summary="一家以 SaaS 为核心、面向电商与零售场景的国内服务商。",
        inferences=[
            InferredClaim(claim="加班强度偏重", grounding_evidence=["https://maimai.cn/x"]),
            InferredClaim(claim="晋升路径清晰", grounding_evidence=["https://zhipin.com/y"]),
        ],
        data_gaps=["员工满意度调研缺失"],
    )
    return ReportData(
        query=CompanyQuery(company="有赞", position="后端", city="杭州"),
        generated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        findings=findings,
        company_profile=cp,
        business_facts=bf,
        judicial_facts=jf,
        review_facts=rf,
        news_facts=nf,
        data_gaps=findings.data_gaps,
    )


# ---------- Chapter I (公司画像) ----------

class TestCompanyProfileFields:
    """B1.x — 8 fields surface in Chapter I + cover."""

    def test_official_website_chip_renders(self):
        html = build_report(_data_with_all_fields())
        assert "field-link" in html
        assert "youzan.com" in html

    def test_main_business_chips_in_cover(self):
        html = build_report(_data_with_all_fields())
        assert "cover-business-strip" in html
        assert "电商 SaaS" in html

    def test_products_grid_renders_in_chapter_i(self):
        html = build_report(_data_with_all_fields())
        assert "products-grid" in html
        assert "有赞微商城" in html

    def test_founded_year_age_display(self):
        html = build_report(_data_with_all_fields())
        # 2026 - 2014 = 12
        assert "12 年" in html

    def test_total_funding_renders(self):
        html = build_report(_data_with_all_fields())
        assert "累计融资" in html
        assert "约30亿元" in html

    def test_prospects_block_renders(self):
        html = build_report(_data_with_all_fields())
        assert "prospects-block" in html
        assert "私域流量趋势" in html

    def test_description_fallback_when_motto_missing(self):
        cp = CompanyProfile(description="中国 SaaS 服务商", motto=None)
        data = _data_with_all_fields()
        data.company_profile = cp
        data.findings.company_profile = cp
        html = build_report(data)
        assert "中国 SaaS 服务商" in html

    def test_company_timeline_viz_renders(self):
        html = build_report(_data_with_all_fields())
        assert "company-timeline-svg" in html
        assert "company-timeline" in html


# ---------- Chapter II (工商基本面) ----------

class TestBusinessFactsFields:
    """B3.x — 4 fields + template bug fix."""

    def test_paid_in_capital_renders(self):
        html = build_report(_data_with_all_fields())
        assert "实缴资本" in html
        assert "5000万元" in html

    def test_address_renders(self):
        html = build_report(_data_with_all_fields())
        assert "注册地址" in html
        assert "文一西路" in html

    def test_external_investments_count_renders(self):
        html = build_report(_data_with_all_fields())
        assert "对外投资" in html
        assert "4 项" in html

    def test_anomaly_flag_renders_when_true(self):
        data = _data_with_all_fields()
        data.business_facts.anomaly_listed = True
        data.findings.business.anomaly_listed = True
        html = build_report(data)
        assert "anomaly-flag" in html
        assert "经营异常名录" in html

    def test_anomaly_flag_omitted_when_false(self):
        html = build_report(_data_with_all_fields())
        # When anomaly_listed=False, the macro must NOT emit a rendered <div>;
        # the CSS class name itself appears in the embedded stylesheet.
        assert '<div class="anomaly-flag">' not in html

    def test_top_shareholders_bug_fix_regression(self):
        """v0.3.3 — template line 543 fix: bf.top_shareholders (not bf.stakeholders).

        The shareholder donut renders because bf.top_shareholders is truthy;
        before the fix, the conditional `bf.stakeholders` would be False on
        every data shape so the donut never appeared (it was being passed via
        shareholder_donut_svg but gated on a non-existent field).
        """
        html = build_report(_data_with_all_fields())
        # Donut svg renders (CSS class is .donut-svg) when top_shareholders non-empty
        assert "股东结构" in html
        assert "donut-svg" in html


# ---------- Chapter III (司法风险) ----------

class TestJudicialFactsFields:
    """B5.x — 2 fields."""

    def test_case_count_recent_year_renders(self):
        html = build_report(_data_with_all_fields())
        assert "近 12 个月" in html
        assert "case-recent-row" in html

    def test_enforcement_records_in_takeaway(self):
        html = build_report(_data_with_all_fields())
        assert "被执行 1 条" in html


# ---------- Chapter IV (薪酬) ----------

class TestJdgapSignals:
    """B4.1 — jd_gap_signals raw pairs render in Chapter IV tail."""

    def test_jd_gap_signals_render(self):
        html = build_report(_data_with_all_fields())
        assert "jd-gap-list" in html
        assert "弹性工作" in html
        assert "996" in html


# ---------- Cover-dispatch ----------

class TestCoverDispatchFields:
    """B7 — company_query_summary renders as first paragraph in cover-dispatch."""

    def test_company_query_summary_renders(self):
        html = build_report(_data_with_all_fields())
        assert "cover-dispatch-summary" in html
        assert "SaaS 为核心" in html


# ---------- ch-tail 综合推断 ----------

class TestInferencesSection:
    """B6 — findings.inferences render as infer-card blocks."""

    def test_inferences_render_when_present(self):
        html = build_report(_data_with_all_fields())
        assert "infer-card" in html
        assert "加班强度偏重" in html
        assert "依据：" in html

    def test_inferences_infer_tag_chip_present(self):
        html = build_report(_data_with_all_fields())
        assert "infer-tag" in html
        assert "推断" in html

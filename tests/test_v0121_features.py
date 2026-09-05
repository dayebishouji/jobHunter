"""v0.1.21 — Company profile fields (employee_count / insured_count) + ReviewFacts.typical_off_time.

Adds 3 structured fields to the report:
  - CompanyProfile.employee_count  (int | None)
  - CompanyProfile.insured_count   (int | None)
  - ReviewFacts.typical_off_time   (str | None) + evidence + url

Plus an EXTRACT_COMPANY_PROFILE_SUFFIX prompt (replacing the previously
empty `""` for company_info domain).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.scoring import AxisScore, RiskAxis
from jobhunter.models.report import ReportData
from jobhunter.processing.extract import DOMAIN_SUFFIX
from jobhunter.report.builder import build_report
from jobhunter.llm.prompts import EXTRACT_COMPANY_PROFILE_SUFFIX, EXTRACT_REVIEWS_SUFFIX


# ============================================================================
# Schema presence
# ============================================================================

class TestSchemaFields:
    def test_company_profile_has_employee_count(self):
        assert "employee_count" in CompanyProfile.model_fields

    def test_company_profile_has_insured_count(self):
        assert "insured_count" in CompanyProfile.model_fields

    def test_review_facts_has_typical_off_time(self):
        assert "typical_off_time" in ReviewFacts.model_fields
        assert "typical_off_time_evidence" in ReviewFacts.model_fields
        assert "typical_off_time_url" in ReviewFacts.model_fields

    def test_existing_company_size_field_still_present(self):
        assert "company_size" in CompanyProfile.model_fields


# ============================================================================
# Coercion validators (employee_count / insured_count)
# ============================================================================

class TestCountCoercion:
    """employee_count and insured_count share the same _coerce_count validator."""

    @pytest.mark.parametrize("raw,expected", [
        (1200, 1200),
        ("1200", 1200),
        ("1,200", 1200),
        ("约 1200 人", 1200),
        ("1200余人", 1200),
        ("1200+", 1200),
        (" 1200 ", 1200),
        ("约 1,200 人左右", 1200),
    ])
    def test_coercion_happy_paths(self, raw, expected):
        cp = CompanyProfile(employee_count=raw)
        assert cp.employee_count == expected

    @pytest.mark.parametrize("raw", ["未知", "未披露", "N/A", "—", "-", "", None, "无"])
    def test_coercion_returns_none_for_garbage(self, raw):
        cp = CompanyProfile(insured_count=raw)
        assert cp.insured_count is None

    def test_count_zero_is_preserved(self):
        cp = CompanyProfile(insured_count=0)
        assert cp.insured_count == 0

    def test_count_shared_validator_on_both_fields(self):
        cp = CompanyProfile(employee_count="约 500 人", insured_count="约 200 人")
        assert cp.employee_count == 500
        assert cp.insured_count == 200


# ============================================================================
# Extraction prompt
# ============================================================================

class TestExtractPrompts:
    def test_company_info_suffix_is_no_longer_empty(self):
        """v0.1.21 — fills the previously-empty company_info prompt slot."""
        assert DOMAIN_SUFFIX["company_info"], "company_info suffix must not be empty"
        assert DOMAIN_SUFFIX["company_info"] == EXTRACT_COMPANY_PROFILE_SUFFIX

    def test_company_profile_suffix_mentions_three_new_fields(self):
        for keyword in ("employee_count", "insured_count", "company_size"):
            assert keyword in EXTRACT_COMPANY_PROFILE_SUFFIX, f"{keyword} missing"

    def test_reviews_suffix_mentions_typical_off_time(self):
        assert "typical_off_time" in EXTRACT_REVIEWS_SUFFIX


# ============================================================================
# Report rendering
# ============================================================================

def _minimal_report(*, cp=None, rf=None):
    cp = cp or CompanyProfile()
    rf = rf or ReviewFacts()
    findings = AggregatedFindings(
        company_query_summary="X 后端 杭州",
        reviews=rf,
        business=BusinessFacts(status="存续", legal_rep="张三"),
        news=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial=JudicialFacts(),
        company_profile=cp,
    )
    return ReportData(
        query=CompanyQuery(company="X", position="后端", city="杭州"),
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        axes=[
            AxisScore(axis=RiskAxis.OVERTIME, stars=3, rationale="r"),
            AxisScore(axis=RiskAxis.SALARY_TRUST, stars=4, rationale="r"),
        ],
        review_facts=rf,
        business_facts=BusinessFacts(status="存续", legal_rep="张三"),
        news_facts=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial_facts=JudicialFacts(),
        company_profile=cp,
        overall_confidence="medium",
        chapter_confidence={"overall": "medium", "reviews": "high", "business": "medium",
                            "news": "low", "judicial": "low", "company": "medium"},
        data_gaps=[],
    )


class TestReportRendering:
    def test_company_profile_renders_employee_and_insured_count(self):
        """v0.2.0 — employee_count + insured_count rendered in 公司画像 data-table row."""
        cp = CompanyProfile(
            company_size="100-500人",
            employee_count=1200,
            insured_count=420,
        )
        html = build_report(_minimal_report(cp=cp))
        assert "员工 / 参保" in html  # data-table row key
        assert "1200" in html
        assert "参保" in html
        assert "420" in html

    def test_company_profile_renders_without_optional_counts(self):
        cp = CompanyProfile(company_size="100-500人")
        html = build_report(_minimal_report(cp=cp))
        # When counts absent, row key still renders but with "未披露"
        assert "员工 / 参保" in html
        assert "未披露" in html

    def test_typical_off_time_renders_in_team_health_chapter(self):
        """v0.2.0 — typical_off_time surfaces in chapter V 团队健康度 takeaway."""
        rf = ReviewFacts(
            typical_off_time="约 10:00 PM",
            typical_off_time_evidence="「十点走是常态」",
            typical_off_time_url="https://example.com/post/1",
        )
        html = build_report(_minimal_report(rf=rf))
        assert "21:30" not in html  # not the old format
        # Chapter V takeaway echoes typical_off_time + evidence
        assert "10:00 PM" in html
        assert "十点走是常态" in html

    def test_team_health_chapter_renders_without_typical_off_time(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")],
        )
        html = build_report(_minimal_report(rf=rf))
        # Without typical_off_time the takeaway falls back to "加班信号 N 条"
        assert "加班信号" in html or "本次未能取得" in html

    def test_typical_off_time_alone_renders(self):
        """typical_off_time surfaces even when no overtime_signals landed."""
        rf = ReviewFacts(typical_off_time="弹性 9-6")
        html = build_report(_minimal_report(rf=rf))
        assert "弹性 9-6" in html

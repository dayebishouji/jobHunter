"""Model validation / round-trip tests."""

from __future__ import annotations

from datetime import date

import pytest

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    InferredClaim,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    ReviewFacts,
    SalarySignal,
    Shareholder,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.models.report import ReportData, SourceEntry
from jobhunter.models.scoring import AxisScore, RiskAxis, axis_color


class TestCompanyQuery:
    def test_minimal(self):
        q = CompanyQuery(company="AC")
        assert q.company == "AC"
        assert q.position == ""
        assert q.city == ""

    def test_display(self):
        q = CompanyQuery(company="阿里云", position="后端", city="杭州")
        assert q.display() == "阿里云 · 后端 · 杭州"

    def test_empty_company_rejected(self):
        with pytest.raises(Exception):
            CompanyQuery(company="")


class TestFacts:
    def test_business_round_trip(self):
        b = BusinessFacts(
            legal_rep="张三",
            established_at=date(2010, 5, 1),
            registered_capital="1000万",
            status="存续",
            top_shareholders=[Shareholder(name="A", stake_pct=60.0)],
            anomaly_listed=False,
        )
        again = BusinessFacts.model_validate_json(b.model_dump_json())
        assert again.legal_rep == "张三"
        assert again.established_at == date(2010, 5, 1)
        assert again.top_shareholders[0].stake_pct == 60.0

    def test_review_signals(self):
        r = ReviewFacts(
            salary_signals=[SalarySignal(position="P6", base_monthly_k=30.0)],
        )
        assert r.salary_signals[0].base_monthly_k == 30.0

    def test_aggregated_findings_round_trip(self):
        a = AggregatedFindings(
            company_query_summary="测试",
            business=BusinessFacts(status="存续"),
            reviews=ReviewFacts(),
            inferences=[InferredClaim(claim="加班多")],
            data_gaps=["司法数据不足"],
        )
        again = AggregatedFindings.model_validate_json(a.model_dump_json())
        assert again.business.status == "存续"
        assert again.inferences[0].claim == "加班多"


class TestRawCollector:
    def test_collector_result_minimal(self):
        cr = CollectorResult(
            collector="tavily_reviews",
            domain="reviews",
            company_query=CompanyQuery(company="X"),
        )
        assert cr.items == []
        assert cr.error is None
        assert cr.confidence == "none"


class TestScoring:
    def test_axis_color_thresholds(self):
        assert axis_color(5) == "good"
        assert axis_color(4) == "good"
        assert axis_color(3) == "warn"
        assert axis_color(2) == "bad"

    def test_axis_score_in_range(self):
        a = AxisScore(axis=RiskAxis.OVERTIME, stars=3, rationale="中等")
        assert 1 <= a.stars <= 5

    def test_axis_score_rejects_out_of_range(self):
        with pytest.raises(Exception):
            AxisScore(axis=RiskAxis.OVERTIME, stars=6)


class TestReport:
    def test_report_data_defaults(self):
        rd = ReportData(
            query=CompanyQuery(company="X"),
            generated_at=__import__("datetime").datetime.now(),
        )
        assert rd.axes == []
        assert rd.interview_questions == []
        assert rd.overall_confidence == "low"


class TestSalarySignalCoercion:
    """LLM sometimes returns '15.4' as a string for total-months; coerce it."""

    def test_int_passes_through(self):
        s = SalarySignal(salary_total_months=14)
        assert s.salary_total_months == 14

    def test_string_int_passes(self):
        s = SalarySignal.model_validate({"salary_total_months": "14"})
        assert s.salary_total_months == 14

    def test_string_float_rounded(self):
        s = SalarySignal.model_validate({"salary_total_months": "15.4"})
        assert s.salary_total_months == 15

    def test_unparseable_string_becomes_none(self):
        s = SalarySignal.model_validate({"salary_total_months": "???"})
        assert s.salary_total_months is None


class TestNullListCoercion:
    """LLM returns null for list fields whose schema is list[...] — coerce to []."""

    def test_review_facts_null_lists_become_empty(self):
        r = ReviewFacts.model_validate({
            "salary_signals": None,
            "overtime_signals": None,
            "vibe_signals": [],
            "jd_gap_signals": None,
            "source_urls": None,
        })
        assert r.salary_signals == []
        assert r.overtime_signals == []
        assert r.jd_gap_signals == []
        assert r.source_urls == []

    def test_news_facts_null_source_urls(self):
        n = NewsFacts.model_validate({
            "items": [],
            "sentiment": "neutral",
            "source_urls": None,
        })
        assert n.source_urls == []

    def test_review_facts_item_envelope_unwrapped(self):
        """ccswitch wraps single-element arrays as {"item": [...]}."""
        r = ReviewFacts.model_validate({
            "salary_signals": {"item": [{"position": "后端", "base_monthly_k": 30.0}]},
            "source_urls": {"item": ["https://x.com/1"]},
        })
        assert len(r.salary_signals) == 1
        assert r.salary_signals[0].position == "后端"
        assert len(r.source_urls) == 1

    def test_business_facts_item_envelope_unwrapped(self):
        b = BusinessFacts.model_validate({
            "top_shareholders": {"item": [{"name": "张三", "stake_pct": 100.0, "contribution": "5000万"}]},
            "source_urls": {"item": ["https://x.com/1"]},
        })
        assert len(b.top_shareholders) == 1
        assert len(b.source_urls) == 1

    def test_aggregated_findings_null_inferences(self):
        a = AggregatedFindings.model_validate({
            "inferences": None,
            "data_gaps": None,
        })
        assert a.inferences == []
        assert a.data_gaps == []

    def test_non_list_non_null_coerced_to_empty(self):
        """LLM occasionally returns non-iterable scalars (int/str/bool) for list fields.
        Coerce to [] instead of letting pydantic raise ValidationError or downstream
        crash with 'NoneType is not iterable'."""
        for bad in (5, "garbage", True, 3.14):
            r = ReviewFacts.model_validate({
                "salary_signals": bad,
                "overtime_signals": bad,
                "vibe_signals": bad,
                "jd_gap_signals": bad,
                "source_urls": bad,
            })
            assert r.salary_signals == []
            assert r.overtime_signals == []
            assert r.vibe_signals == []
            assert r.jd_gap_signals == []
            assert r.source_urls == []

    def test_dict_with_non_list_value_coerced_to_empty(self):
        """OpenAPI 3.1 quirk: dict envelope where no inner is a list → [] (not the dict)."""
        r = ReviewFacts.model_validate({
            "salary_signals": {"foo": "bar"},
        })
        assert r.salary_signals == []

    def test_aggregated_findings_non_dict_submodel_coerced_to_none(self):
        """LLM (esp. via ccswitch) sometimes returns scalars for sub-model fields
        like 'business'/'reviews'/'judicial'. Pydantic would raise; sanitize first."""
        from jobhunter.processing.extract import _sanitize_aggregated

        raw = {
            "company_query_summary": "x",
            "business": "N/A",       # bad: string instead of dict
            "reviews": [],            # bad: list instead of dict
            "news": None,            # ok: None is allowed
            "judicial": 0,            # bad: int instead of dict
            "inferences": None,
            "data_gaps": None,
        }
        cleaned = _sanitize_aggregated(raw)
        assert cleaned["business"] is None
        assert cleaned["reviews"] is None
        assert cleaned["news"] is None
        assert cleaned["judicial"] is None
        a = AggregatedFindings.model_validate(cleaned)
        assert a.business is None
        assert a.reviews is None
        assert a.news is None
        assert a.judicial is None


class TestInferredClaimGrounding:
    """ccswitch / relay models sometimes wrap single-element arrays as
    `{"item": ["url1"]}` (OpenAPI 3.1 single-item-array style). Unwrap them.
    """

    def test_dict_with_item_key_unwrapped(self):
        from jobhunter.models.facts import InferredClaim
        c = InferredClaim.model_validate({
            "claim": "test",
            "grounding_evidence": {"item": ["https://x.com/1", "https://y.com/2"]},
        })
        assert len(c.grounding_evidence) == 2
        assert str(c.grounding_evidence[0]) == "https://x.com/1"

    def test_dict_without_list_value_becomes_empty(self):
        from jobhunter.models.facts import InferredClaim
        c = InferredClaim.model_validate({
            "claim": "test",
            "grounding_evidence": {"foo": "bar"},
        })
        assert c.grounding_evidence == []

    def test_none_becomes_empty(self):
        from jobhunter.models.facts import InferredClaim
        c = InferredClaim.model_validate({"claim": "test", "grounding_evidence": None})
        assert c.grounding_evidence == []

    def test_normal_list_passes_through(self):
        from jobhunter.models.facts import InferredClaim
        c = InferredClaim.model_validate({
            "claim": "test",
            "grounding_evidence": ["https://x.com/1"],
        })
        assert len(c.grounding_evidence) == 1


class TestBusinessStatusCoercion:
    """LLM returns equivalent phrasings — snap to enum values, fallback to '其他'."""

    def test_exact_match(self):
        b = BusinessFacts.model_validate({"status": "存续"})
        assert b.status == "存续"

    def test_synonym_snapped_to_active(self):
        b = BusinessFacts.model_validate({"status": "在业"})
        assert b.status == "存续"

    def test_unknown_falls_back_to_other(self):
        b = BusinessFacts.model_validate({"status": "未知状态XYZ"})
        assert b.status == "其他"


class TestEnumCoercion:
    """LLM returns synonyms; snap to enum or fall back."""

    def test_overtime_pattern_synonym(self):
        from jobhunter.models.facts import OvertimeSignal
        s = OvertimeSignal.model_validate({"pattern": "大小周末加班"})
        assert s.pattern == "大小周"

    def test_overtime_pattern_unknown(self):
        from jobhunter.models.facts import OvertimeSignal
        s = OvertimeSignal.model_validate({"pattern": "乱七八糟"})
        assert s.pattern == "未知"

    def test_intensity_chinese(self):
        from jobhunter.models.facts import OvertimeSignal
        s = OvertimeSignal.model_validate({"intensity": "重"})
        assert s.intensity == "high"

    def test_intensity_english_low(self):
        from jobhunter.models.facts import OvertimeSignal
        s = OvertimeSignal.model_validate({"intensity": "low"})
        assert s.intensity == "low"

    def test_turnover_rate_chinese(self):
        from jobhunter.models.facts import TurnoverSignal
        s = TurnoverSignal.model_validate({"rate": "高"})
        assert s.rate == "high"

    def test_vibe_sentiment_chinese(self):
        from jobhunter.models.facts import VibeSignal
        s = VibeSignal.model_validate({"sentiment": "负面"})
        assert s.sentiment == "negative"

    def test_case_role_synonym(self):
        from jobhunter.models.facts import CaseItem
        c = CaseItem.model_validate({"title": "X", "role": "被告方"})
        assert c.role == "被告"

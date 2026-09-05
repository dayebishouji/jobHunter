"""Model validation / round-trip tests."""

from __future__ import annotations

from datetime import date

import pytest

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    InferredClaim,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    ReviewFacts,
    SalarySignal,
    Shareholder,
    SlangEntry,
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
        assert q.aliases == []  # default empty

    def test_display(self):
        q = CompanyQuery(company="阿里云", position="后端", city="杭州")
        assert q.display() == "阿里云 · 后端 · 杭州"

    def test_empty_company_rejected(self):
        with pytest.raises(Exception):
            CompanyQuery(company="")

    def test_aliases_default_and_round_trip(self):
        q = CompanyQuery(company="阿里云", aliases=["aliyun", "阿里"])
        assert q.aliases == ["aliyun", "阿里"]
        again = CompanyQuery.model_validate_json(q.model_dump_json())
        assert again.aliases == ["aliyun", "阿里"]


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

    def test_business_coerces_partial_established_at(self):
        """LLM may return '未知' / '约 2010' / '?' for established_at. Coerce to None."""
        from jobhunter.models.facts import BusinessFacts
        b = BusinessFacts.model_validate({"established_at": "未知"})
        assert b.established_at is None
        b2 = BusinessFacts.model_validate({"established_at": "2014-05-01"})
        assert b2.established_at.year == 2014
        b3 = BusinessFacts.model_validate({"established_at": "约 2010 年"})
        assert b3.established_at is None

    def test_business_coerces_anomaly_listed_strings(self):
        """LLM may return 是 / 否 / 未列入 instead of bool."""
        from jobhunter.models.facts import BusinessFacts
        assert BusinessFacts.model_validate({"anomaly_listed": "是"}).anomaly_listed is True
        assert BusinessFacts.model_validate({"anomaly_listed": "否"}).anomaly_listed is False
        assert BusinessFacts.model_validate({"anomaly_listed": "未列入"}).anomaly_listed is False
        assert BusinessFacts.model_validate({"anomaly_listed": "未知"}).anomaly_listed is None

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

    # --- base_monthly_k / bonus_months defensive coercion ---

    def test_base_monthly_k_numeric_string_parses(self):
        s = SalarySignal.model_validate({"base_monthly_k": "28"})
        assert s.base_monthly_k == 28.0

    def test_base_monthly_k_range_string_takes_first_number(self):
        s = SalarySignal.model_validate({"base_monthly_k": "20k-40k"})
        assert s.base_monthly_k == 20.0

    def test_base_monthly_k_chinese_unknown_becomes_none(self):
        s = SalarySignal.model_validate({"base_monthly_k": "面议"})
        assert s.base_monthly_k is None

    def test_bonus_months_string_parses(self):
        s = SalarySignal.model_validate({"bonus_months": "3.5"})
        assert s.bonus_months == 3.5


class TestShareholderCoercion:
    """LLM may return '35%' / '约 40' for stake_pct."""

    def test_stake_pct_with_percent_sign(self):
        s = Shareholder.model_validate({"name": "X", "stake_pct": "35%"})
        assert s.stake_pct == 35.0

    def test_stake_pct_unparseable_becomes_none(self):
        s = Shareholder.model_validate({"name": "X", "stake_pct": "不详"})
        assert s.stake_pct is None


class TestJudicialCoercion:
    """LLM may return '约 8 起' / '10+' for count fields."""

    def test_case_count_total_chinese_string(self):
        j = JudicialFacts.model_validate({"case_count_total": "约 8 起"})
        assert j.case_count_total == 8

    def test_case_count_recent_year_plus_sign(self):
        j = JudicialFacts.model_validate({"case_count_recent_year": "10+"})
        assert j.case_count_recent_year == 10

    def test_enforcement_records_unknown_becomes_none(self):
        j = JudicialFacts.model_validate({"enforcement_records": "未知"})
        assert j.enforcement_records is None


class TestBusinessExternalInvestmentsCoercion:
    def test_string_count_parses(self):
        b = BusinessFacts.model_validate({"external_investments_count": "12 家"})
        assert b.external_investments_count == 12

    def test_unparseable_becomes_none(self):
        b = BusinessFacts.model_validate({"external_investments_count": "无数据"})
        assert b.external_investments_count is None


class TestSalarySignalSupportingUrls:
    """Each signal carries supporting_urls for cross-source corroboration."""

    def test_supporting_urls_default_empty(self):
        s = SalarySignal()
        assert s.supporting_urls == []

    def test_supporting_urls_round_trip(self):
        s = SalarySignal(
            evidence="x",
            url="https://maimai.cn/a",
            supporting_urls=[
                "https://v2ex.com/b",
                "https://www.zhihu.com/c",
            ],
        )
        assert len(s.supporting_urls) == 2
        s2 = SalarySignal.model_validate_json(s.model_dump_json())
        assert len(s2.supporting_urls) == 2

    def test_salary_range_fields(self):
        s = SalarySignal.model_validate({
            "salary_range_min_k": "20",
            "salary_range_max_k": "40",
            "evidence": "20k-40k",
        })
        assert s.salary_range_min_k == 20.0
        assert s.salary_range_max_k == 40.0


class TestSlangEntry:
    """SlangEntry surfaces internet / workplace slang used in UGC reviews,
    with a plain-Chinese gloss so report readers can parse it."""

    def test_minimal(self):
        s = SlangEntry(term="ICU")
        assert s.term == "ICU"
        assert s.meaning == ""
        assert s.count == 1

    def test_full(self):
        s = SlangEntry(
            term="内卷",
            meaning="竞争白热化、投入产出比低",
            count=5,
            url="https://www.zhihu.com/q/juan",
        )
        assert s.count == 5
        assert str(s.url) == "https://www.zhihu.com/q/juan"

    def test_count_string_coerces(self):
        s = SlangEntry.model_validate({"term": "ICU", "count": "约 5 次"})
        assert s.count == 5

    def test_count_unparseable_defaults_to_1(self):
        s = SlangEntry.model_validate({"term": "ICU", "count": "???"})
        assert s.count == 1

    def test_count_zero_clamped_to_1(self):
        s = SlangEntry.model_validate({"term": "ICU", "count": 0})
        assert s.count == 1

    def test_round_trip(self):
        s = SlangEntry(term="摆烂", meaning="主动降低投入", count=3)
        s2 = SlangEntry.model_validate_json(s.model_dump_json())
        assert s2.term == "摆烂"
        assert s2.meaning == "主动降低投入"
        assert s2.count == 3

    def test_numeric_term_coerced_to_string(self):
        """LLM occasionally emits slang like `996` as an int. Coerce to str
        so the whole ReviewFacts doesn't fail validation."""
        s = SlangEntry.model_validate({"term": 996, "count": 10})
        assert s.term == "996"
        assert s.count == 10

    def test_float_term_coerced_to_string(self):
        s = SlangEntry.model_validate({"term": 6.66})
        assert s.term == "6.66"


class TestReviewFactsSlangGlossary:
    """ReviewFacts.slang_glossary coerces null → [], and validates entries."""

    def test_null_glossary_becomes_empty(self):
        r = ReviewFacts.model_validate({"slang_glossary": None})
        assert r.slang_glossary == []

    def test_slang_glossary_with_entries(self):
        r = ReviewFacts.model_validate({
            "slang_glossary": [
                {"term": "ICU", "meaning": "996 反制运动", "count": 3},
                {"term": "内卷", "meaning": "过度竞争"},
            ]
        })
        assert len(r.slang_glossary) == 2
        assert r.slang_glossary[0].term == "ICU"
        assert r.slang_glossary[1].count == 1  # default


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

    def test_case_year_string_extracted(self):
        """LLM returns '2023年' / '约 2024' / '2023-01' — extract the 4-digit year."""
        from jobhunter.models.facts import CaseItem
        for raw, expected in [
            ("2023年", 2023),
            ("约 2024", 2024),
            ("2023-01", 2023),
            ("2023", 2023),
            ("2025.5", 2025),
        ]:
            c = CaseItem.model_validate({"title": "X", "year": raw})
            assert c.year == expected, f"raw={raw!r} got {c.year}"

    def test_case_year_unparseable_becomes_none(self):
        from jobhunter.models.facts import CaseItem
        c = CaseItem.model_validate({"title": "X", "year": "未知"})
        assert c.year is None


class TestCompanyProfile:
    """CompanyProfile distinct from BusinessFacts: qualitative / market positioning."""

    def test_minimal(self):
        cp = CompanyProfile()
        assert cp.description is None
        assert cp.main_business == []
        assert cp.products == []
        assert cp.industries == []
        assert cp.investors == []
        assert cp.source_urls == []
        assert cp.founded_year is None

    def test_round_trip(self):
        cp = CompanyProfile(
            description="国内最大云厂商",
            main_business=["云计算", "AI 平台"],
            products=["ECS", "RDS"],
            company_size="10000人以上",
            funding_stage="未融资",
            headquarters="杭州",
            prospects="持续布局海外市场",
        )
        again = CompanyProfile.model_validate_json(cp.model_dump_json())
        assert again.description == "国内最大云厂商"
        assert again.main_business == ["云计算", "AI 平台"]
        assert again.products == ["ECS", "RDS"]
        assert again.headquarters == "杭州"

    def test_founded_year_string_with_chinese_extracted(self):
        """Same regex as CaseItem.year — handle '2014年' / '约 2014' / '2014-09'."""
        for raw, expected in [
            ("2014年", 2014),
            ("约 2015", 2015),
            ("2010-09", 2010),
            ("2014", 2014),
        ]:
            cp = CompanyProfile.model_validate({"founded_year": raw})
            assert cp.founded_year == expected, f"raw={raw!r} got {cp.founded_year}"

    def test_founded_year_unparseable_becomes_none(self):
        cp = CompanyProfile.model_validate({"founded_year": "未知"})
        assert cp.founded_year is None

    def test_official_website_bare_hostname_normalized(self):
        """LLM often returns bare 'example.com' — normalize to https://example.com/."""
        cp = CompanyProfile.model_validate({"official_website": "aliyun.com"})
        assert str(cp.official_website) == "https://aliyun.com/"

    def test_official_website_with_path_collapsed_to_root(self):
        cp = CompanyProfile.model_validate({"official_website": "https://aliyun.com/about"})
        assert str(cp.official_website) == "https://aliyun.com/"

    def test_official_website_empty_becomes_none(self):
        for bad in ("", "   "):
            cp = CompanyProfile.model_validate({"official_website": bad})
            assert cp.official_website is None

    def test_null_lists_become_empty(self):
        cp = CompanyProfile.model_validate({
            "main_business": None,
            "products": None,
            "industries": None,
            "investors": None,
            "source_urls": None,
        })
        assert cp.main_business == []
        assert cp.products == []
        assert cp.industries == []
        assert cp.investors == []
        assert cp.source_urls == []

    def test_aggregated_findings_with_company_profile(self):
        a = AggregatedFindings(
            company_query_summary="x",
            company_profile=CompanyProfile(description="测试", founded_year=2010),
        )
        again = AggregatedFindings.model_validate_json(a.model_dump_json())
        assert again.company_profile is not None
        assert again.company_profile.description == "测试"
        assert again.company_profile.founded_year == 2010

    def test_aggregated_findings_company_profile_default_none(self):
        a = AggregatedFindings.model_validate({})
        assert a.company_profile is None


# ---------- v0.3.2 hotfix — typical_off_time_url empty-string guard ----------

class TestReviewFactsOffTimeUrlCoerce:
    """v0.3.2 hotfix — LLM sometimes returns `""` (empty string) for
    typical_off_time_url when no source URL is available. Pydantic v2 treats
    empty string as invalid URL even though the type is `HttpUrl | None`.
    The `_coerce_off_time_url` field validator turns blank / whitespace into
    None so the run doesn't crash on the validation step."""

    def test_empty_string_becomes_none(self):
        r = ReviewFacts.model_validate({
            "typical_off_time": "约 10 PM",
            "typical_off_time_url": "",
        })
        assert r.typical_off_time_url is None

    def test_whitespace_becomes_none(self):
        r = ReviewFacts.model_validate({
            "typical_off_time": "约 10 PM",
            "typical_off_time_url": "   ",
        })
        assert r.typical_off_time_url is None

    def test_none_passes_through(self):
        r = ReviewFacts.model_validate({
            "typical_off_time": "约 10 PM",
            "typical_off_time_url": None,
        })
        assert r.typical_off_time_url is None

    def test_valid_url_passes_through(self):
        r = ReviewFacts.model_validate({
            "typical_off_time": "约 10 PM",
            "typical_off_time_url": "https://www.zhihu.com/question/123",
        })
        assert str(r.typical_off_time_url) == "https://www.zhihu.com/question/123"

    def test_empty_url_does_not_crash_full_review_facts(self):
        """The original bug: full ReviewFacts with empty url crashed the LLM
        extract step. This is the regression the hotfix pins."""
        r = ReviewFacts.model_validate({
            "typical_off_time": "约 10:00 PM",
            "typical_off_time_evidence": "团队普遍约 10 点离开",
            "typical_off_time_url": "",  # the failure case
            "salary_signals": [],
            "overtime_signals": [],
            "turnover_signals": [],
            "vibe_signals": [],
        })
        assert r.typical_off_time == "约 10:00 PM"
        assert r.typical_off_time_url is None
        assert r.typical_off_time_evidence == "团队普遍约 10 点离开"

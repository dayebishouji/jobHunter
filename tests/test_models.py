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

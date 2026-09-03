"""Heuristic scoring tests (pure logic, no LLM)."""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    NewsFacts,
    ReviewFacts,
    OvertimeSignal,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import ReportData
from jobhunter.report.scoring import compute_axes


def test_overtime_score_high_when_mostly_996():
    reviews = ReviewFacts(
        overtime_signals=[
            OvertimeSignal(pattern="996", intensity="high"),
            OvertimeSignal(pattern="996", intensity="high"),
            OvertimeSignal(pattern="弹性", intensity="low"),
        ]
    )
    findings = AggregatedFindings(reviews=reviews)
    axes = compute_axes(findings, {}, [])
    overtime = next(a for a in axes if a.axis.value == "overtime")
    assert overtime.stars <= 3  # 2 or 3 depending on threshold
    assert "996" in overtime.rationale or "加班" in overtime.rationale


def test_salary_trust_drops_on_conflict():
    from jobhunter.processing.crosscheck import detect_salary_conflicts
    reviews = ReviewFacts(
        salary_signals=[
            SalarySignal(base_monthly_k=15.0),
            SalarySignal(base_monthly_k=40.0),
        ]
    )
    findings = AggregatedFindings(reviews=reviews)
    conflicts = detect_salary_conflicts(reviews)
    assert conflicts, "precondition: should detect conflict"
    axes = compute_axes(findings, {}, conflicts)
    salary = next(a for a in axes if a.axis.value == "salary_trust")
    assert salary.stars <= 4


def test_business_score_default_when_missing():
    findings = AggregatedFindings()  # no business
    axes = compute_axes(findings, {}, [])
    business = next(a for a in axes if a.axis.value == "business")
    assert business.stars == 3


def test_business_drops_on_anomaly():
    findings = AggregatedFindings(
        business=BusinessFacts(status="存续", anomaly_listed=True)
    )
    axes = compute_axes(findings, {}, [])
    business = next(a for a in axes if a.axis.value == "business")
    assert business.stars <= 3


def test_culture_from_reviews_sentiment():
    reviews = ReviewFacts(
        vibe_signals=[VibeSignal(sentiment="negative")] * 3
        + [VibeSignal(sentiment="positive")]
    )
    findings = AggregatedFindings(reviews=reviews)
    axes = compute_axes(findings, {}, [])
    culture = next(a for a in axes if a.axis.value == "culture")
    assert culture.stars <= 3

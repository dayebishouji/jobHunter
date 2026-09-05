"""Tests for v0.1.16 features: signal timestamps, JD alignment, top-level verdict."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from jobhunter.models.facts import (
    BusinessFacts,
    JudicialFacts,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import ReportData
from jobhunter.models.scoring import AxisScore, RiskAxis
from jobhunter.report.builder import (
    build_report,
    compute_overall_verdict,
    compute_trial_checklist,
)
from jobhunter.report.jd_alignment import compute_jd_alignment


def _q(jd_text: str | None = None) -> CompanyQuery:
    return CompanyQuery(
        company="TestCo", position="后端", city="杭州", jd_text=jd_text
    )


def _axes(scores: dict[RiskAxis, int]) -> list[AxisScore]:
    return [
        AxisScore(axis=k, stars=v, rationale=f"test-{k.value}")
        for k, v in scores.items()
    ]


# =============== F1: signal published_at ===============

class TestSignalPublishedAt:
    """v0.1.16 — every review signal carries a `published_at` we can render."""

    def test_salary_signal_accepts_published_at(self):
        s = SalarySignal(evidence="月薪 30k", published_at=date(2024, 5, 1))
        assert s.published_at == date(2024, 5, 1)

    def test_overtime_signal_accepts_published_at(self):
        o = OvertimeSignal(pattern="996", intensity="high", published_at=date(2023, 1, 1))
        assert o.published_at == date(2023, 1, 1)

    def test_vibe_signal_accepts_published_at(self):
        v = VibeSignal(sentiment="negative", published_at=date(2025, 3, 15))
        assert v.published_at == date(2025, 3, 15)

    def test_signal_date_coerces_iso_string(self):
        s = SalarySignal(evidence="x", published_at="2024-05-01")  # type: ignore[arg-type]
        assert s.published_at == date(2024, 5, 1)

    def test_signal_date_coerces_chinese_string(self):
        s = SalarySignal(evidence="x", published_at="2024年5月")  # type: ignore[arg-type]
        assert s.published_at == date(2024, 5, 1)

    def test_signal_date_drops_unparseable(self):
        s = SalarySignal(evidence="x", published_at="未知")  # type: ignore[arg-type]
        assert s.published_at is None

    def test_signal_date_optional(self):
        s = SalarySignal(evidence="x")
        assert s.published_at is None

    def test_signal_age_badge_renders_in_report(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(evidence="30k", published_at=date(2024, 1, 1))]
        )
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        html = build_report(data)
        # Should render 「X 月前」 or 「X 年前」 or 「X 天前」 somewhere in the salary row
        assert "signal-age" in html


# =============== F2: JD alignment ===============

class TestJDAlignment:
    """v0.1.16 — claim-by-claim alignment of JD text against gathered facts."""

    def test_empty_jd_returns_no_claims(self):
        data = ReportData(query=_q(None), generated_at=datetime.now(timezone.utc))
        assert compute_jd_alignment(data) == []

    def test_overtime_claim_contradicted_by_996_signals(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")] * 3
        )
        data = ReportData(
            query=_q("弹性工作，不加班"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        flex = next((c for c in claims if c.claim.startswith("弹性工作")), None)
        assert flex is not None
        assert flex.status == "contradicted"
        assert "996" in flex.reasoning or "大小周" in flex.reasoning

    def test_overtime_claim_confirmed_by_flex_signals(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="弹性", intensity="low")] * 2
        )
        data = ReportData(
            query=_q("弹性工作"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        flex = next((c for c in claims if c.claim.startswith("弹性工作")), None)
        assert flex is not None
        assert flex.status == "confirmed"

    def test_15_salary_claim_contradicted_by_12_months(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(salary_total_months=12, evidence="12 薪")]
        )
        data = ReportData(
            query=_q("15 薪"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        sal = next((c for c in claims if "薪" in c.claim), None)
        assert sal is not None
        assert sal.status == "contradicted"

    def test_15_salary_claim_confirmed_by_high_total(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(salary_total_months=15, evidence="15 薪")] * 2
        )
        data = ReportData(
            query=_q("15 薪"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        sal = next((c for c in claims if "薪" in c.claim), None)
        assert sal is not None
        assert sal.status == "confirmed"

    def test_no_matching_claims_returns_empty(self):
        data = ReportData(
            query=_q("Python 开发工程师"), generated_at=datetime.now(timezone.utc)
        )
        # Generic JD with no claim keywords
        claims = compute_jd_alignment(data)
        assert claims == []

    def test_jd_alignment_renders_in_report(self):
        """v0.2.0 — JD alignment renders inside ch-jd side chapter (class jd-grid, not section class)."""
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")] * 2
        )
        data = ReportData(
            query=_q("弹性工作"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        html = build_report(data)
        assert 'id="ch-jd"' in html
        assert "jd-cell-contradicted" in html

    def test_no_jd_no_section(self):
        data = ReportData(query=_q(None), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        # Side chapter is conditional; assert the actual element (not the CSS comment text)
        assert 'id="ch-jd"' not in html


# =============== F3: top-level verdict ===============

class TestOverallVerdict:
    """v0.1.16 — single top-level recommend / caution / avoid / neutral verdict."""

    def _data(self, axes=None, jf=None, bf=None, rf=None, cp=None):
        return ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            axes=_axes(axes or {}),
            judicial_facts=jf,
            business_facts=bf,
            review_facts=rf,
            company_profile=cp,
        )

    def test_clean_company_gets_recommend(self):
        rf = ReviewFacts(vibe_signals=[VibeSignal(sentiment="positive")] * 2)
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            jf=JudicialFacts(case_count_total=0),
            rf=rf,
        ))
        assert v.level == "recommend"
        assert v.score == 5.0

    def test_axis_low_triggers_avoid(self):
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 2,
                RiskAxis.SALARY_TRUST: 2,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
        ))
        assert v.level == "avoid"
        # Should mention at least one of the weak axes
        joined = " ".join(v.reasons)
        assert "加班强度" in joined or "薪酬诚信" in joined

    def test_high_judicial_triggers_avoid(self):
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            jf=JudicialFacts(case_count_total=15),
        ))
        assert v.level == "avoid"
        assert any("司法" in r for r in v.reasons)

    def test_axis_3_triggers_caution(self):
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 3,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
        ))
        assert v.level == "caution"

    def test_heavy_overtime_triggers_caution(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")] * 2
        )
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            rf=rf,
        ))
        assert v.level == "caution"

    def test_no_axes_is_neutral(self):
        v = compute_overall_verdict(self._data())
        assert v.level == "neutral"

    def test_anomaly_listed_triggers_caution(self):
        bf = BusinessFacts.model_validate({"anomaly_listed": True})
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            bf=bf,
        ))
        assert v.level == "caution"

    def test_anomaly_with_listed_still_caution(self):
        """Anomaly + already-listed should NOT auto-avoid — capital markets disclosures are normal."""
        from jobhunter.models.facts import CompanyProfile
        bf = BusinessFacts.model_validate({"anomaly_listed": True})
        cp = CompanyProfile.model_validate({"funding_stage": "已上市"})
        v = compute_overall_verdict(self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            bf=bf,
            cp=cp,
        ))
        # Falls to caution (anomaly alone), not avoid
        assert v.level == "caution"

    def test_verdict_renders_in_cover(self):
        """v0.2.0 — verdict lives in cover section (.cover-verdict) and masthead rating (增持)."""
        data = self._data(
            axes={
                RiskAxis.OVERTIME: 5,
                RiskAxis.SALARY_TRUST: 5,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
            jf=JudicialFacts(case_count_total=0),
        )
        html = build_report(data)
        assert "cover-verdict" in html
        assert "增持" in html  # masthead rating 增持 when recommend
        # avoid reason headline would not appear here, sanity
        assert "减持" not in html

    def test_verdict_avoid_renders_red_label(self):
        """v0.2.0 — avoid verdict uses cover-verdict-avoid (red border) + 减持 masthead rating."""
        data = self._data(
            axes={
                RiskAxis.OVERTIME: 1,
                RiskAxis.SALARY_TRUST: 2,
                RiskAxis.JUDICIAL: 5,
                RiskAxis.BUSINESS: 5,
                RiskAxis.CULTURE: 5,
            },
        )
        html = build_report(data)
        assert "cover-verdict-avoid" in html
        assert "masthead-rating-avoid" in html
        assert "减持" in html
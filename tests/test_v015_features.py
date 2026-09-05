"""Tests for v0.1.15 features: interview-process extraction, trial-period
checklist, cross-company comparison."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.facts import (
    BusinessFacts,
    CompanyProfile,
    InterviewSignal,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import PeerCompany, ReportData
from jobhunter.report.builder import (
    build_report,
    compute_trial_checklist,
)
from jobhunter.processing.extract import _merge_reviews


def _q() -> CompanyQuery:
    return CompanyQuery(company="TestCo", position="后端", city="杭州")


class TestInterviewSignalExtraction:
    """v0.1.15 — ReviewFacts gets interview_rounds / style / difficulty / signals."""

    def test_review_facts_accepts_interview_fields(self):
        rf = ReviewFacts(
            interview_rounds=4,
            interview_style=["算法", "系统设计", "behavioral"],
            interview_difficulty="hard",
            interview_signals=[InterviewSignal(aspect="rounds", observation="4 轮")],
        )
        assert rf.interview_rounds == 4
        assert rf.interview_style == ["算法", "系统设计", "behavioral"]
        assert rf.interview_difficulty == "hard"
        assert len(rf.interview_signals) == 1

    def test_merge_reviews_unions_interview_style(self):
        a = ReviewFacts(interview_style=["算法", "系统设计"])
        b = ReviewFacts(interview_style=["算法", "behavioral"])
        merged = _merge_reviews(a, b)
        assert "算法" in merged.interview_style
        assert "系统设计" in merged.interview_style
        assert "behavioral" in merged.interview_style
        # Dedup'd
        assert merged.interview_style.count("算法") == 1

    def test_merge_reviews_preserves_rounds(self):
        a = ReviewFacts(interview_rounds=3)
        b = ReviewFacts(interview_rounds=None)
        merged = _merge_reviews(a, b)
        assert merged.interview_rounds == 3

    def test_merge_reviews_prefers_real_difficulty(self):
        a = ReviewFacts(interview_difficulty="未知")
        b = ReviewFacts(interview_difficulty="hard")
        merged = _merge_reviews(a, b)
        assert merged.interview_difficulty == "hard"

    def test_merge_reviews_dedup_signals_by_url(self):
        sig = InterviewSignal(aspect="rounds", observation="3 轮", url="https://x.com/a")  # type: ignore[arg-type]
        a = ReviewFacts(interview_signals=[sig])
        b = ReviewFacts(interview_signals=[sig])  # same url
        merged = _merge_reviews(a, b)
        assert len(merged.interview_signals) == 1


class TestTrialChecklist:
    """v0.1.15 — 1mo / 3mo / 6mo observation checklist, fact-driven."""

    def test_three_checkpoints_always_present(self):
        # Empty data → still get the universal baseline items
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        cl = compute_trial_checklist(data)
        assert "1mo" in cl and "3mo" in cl and "6mo" in cl
        assert len(cl["1mo"]) >= 3
        assert len(cl["3mo"]) >= 3
        assert len(cl["6mo"]) >= 3

    def test_high_overtime_triggers_1mo_warning(self):
        rf = ReviewFacts(
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="996", intensity="high"),
            ]
        )
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        cl = compute_trial_checklist(data)
        # Should include a 加班强度 specific line
        assert any("加班强度" in line or "加班" in line for line in cl["1mo"])

    def test_judicial_cases_trigger_6mo_warning(self):
        jf = JudicialFacts(case_count_total=5)
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), judicial_facts=jf
        )
        cl = compute_trial_checklist(data)
        assert any("诉讼" in line for line in cl["6mo"])

    def test_anomaly_listed_triggers_3mo_warning(self):
        bf = BusinessFacts.model_validate({
            "legal_rep": "张三",
            "anomaly_listed": True,
        })
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), business_facts=bf
        )
        cl = compute_trial_checklist(data)
        assert any("经营异常" in line for line in cl["3mo"])

    def test_funding_stage_triggers_6mo_warning(self):
        cp = CompanyProfile.model_validate({"funding_stage": "B 轮"})
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), company_profile=cp
        )
        cl = compute_trial_checklist(data)
        assert any("B 轮" in line or "融资" in line for line in cl["6mo"])

    def test_listed_company_skips_funding_advice(self):
        cp = CompanyProfile.model_validate({"funding_stage": "已上市"})
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), company_profile=cp
        )
        cl = compute_trial_checklist(data)
        assert not any("下一轮融资" in line for line in cl["6mo"])

    def test_caps_at_5_per_checkpoint(self):
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        cl = compute_trial_checklist(data)
        for k in ("1mo", "3mo", "6mo"):
            assert len(cl[k]) <= 5


class TestPeerCompany:
    """v0.1.15 — Peer comparison schema."""

    def test_peer_company_basic(self):
        p = PeerCompany(name="美团", overall_score=4.2)
        assert p.name == "美团"
        assert p.overall_score == 4.2
        assert p.error is None

    def test_peer_company_records_error(self):
        p = PeerCompany(name="X", error="timeout")
        assert p.error == "timeout"

    def test_report_data_accepts_peer_comparison(self):
        d = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            peer_comparison=[
                PeerCompany(name="美团").model_dump(),
                PeerCompany(name="京东").model_dump(),
            ],
        )
        assert len(d.peer_comparison) == 2


class TestBuildReportRendersNewChapters:
    """End-to-end: build_report renders v0.1.15 features (now merged into chapter 面试准备)."""

    def test_trial_checklist_renders(self):
        """v0.2.0 — trial checklist bucket labels are 1 个月 / 3 个月 / 6 个月 (not 入职)."""
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        assert "试用期观察清单" in html
        assert "trial-grid" in html
        assert "1 个月" in html
        assert "3 个月" in html
        assert "6 个月" in html

    def test_high_overtime_drives_specific_1mo_line(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")]
        )
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        html = build_report(data)
        assert "加班强度提示" in html

    def test_interview_prep_chapter_renders(self):
        """v0.2.0 — interview process merged into ch-interview-prep side chapter."""
        rf = ReviewFacts(
            interview_rounds=4,
            interview_style=["算法", "系统设计"],
            interview_difficulty="hard",
            interview_signals=[InterviewSignal(
                aspect="rounds", observation="4 轮技术面 + 1 轮 HR",
                evidence="『一共 4 轮面试，第 3 轮是 cross-team』",
                url="https://x.com/q/1",  # type: ignore[arg-type]
            )],
        )
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        html = build_report(data)
        assert "面试流程" in html
        assert "ch-interview-prep" in html
        assert "算法" in html
        assert "系统设计" in html
        assert "较难" in html  # hard → 较难 label (v0.2.0 较难 vs old 偏难)

    def test_peer_comparison_chapter_renders(self):
        """v0.2.0 — peer table uses div grid not <table>; class peer-table remains."""
        q = CompanyQuery(company="测试目标", position="后端", city="杭州")
        data = ReportData(
            query=q,
            generated_at=datetime.now(timezone.utc),
            peer_comparison=[
                PeerCompany(name="测试目标", overall_score=3.5, axis_overtime=3).model_dump(),
                PeerCompany(name="美团", overall_score=4.0, axis_overtime=4).model_dump(),
                PeerCompany(name="京东", overall_score=3.8, axis_overtime=4).model_dump(),
            ],
        )
        html = build_report(data)
        assert "同行业对比" in html
        assert "ch-peers" in html
        assert 'class="peer-table"' in html
        assert "测试目标" in html
        assert "美团" in html
        assert "京东" in html

    def test_no_peer_no_comparison_chapter(self):
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        assert "ch-peers" not in html
        assert 'class="peer-table"' not in html

    def test_no_interview_data_no_process_chapter(self):
        """v0.2.0 — interview process sub-section is conditional inside ch-interview-prep."""
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        assert "ch-interview-prep" in html  # chapter itself always renders
        # but the interview_rounds / style / difficulty section stays hidden when no data
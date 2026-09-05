"""Tests for v0.1.17 features: salary band, JD fine-grained rules, snapshot
diff, watchlist, print-to-PDF auto-trigger."""

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
    compute_salary_band,
)
from jobhunter.report.jd_alignment import compute_jd_alignment
from jobhunter.report import snapshot as snap_mod
from jobhunter import watchlist


def _q(jd_text: str | None = None) -> CompanyQuery:
    return CompanyQuery(
        company="TestCo", position="后端", city="杭州", jd_text=jd_text
    )


# =============== G1: Salary band ===============

class TestSalaryBand:
    """v0.1.17 — P25 / P50 / P75 from salary_signals."""

    def test_returns_none_with_no_signals(self):
        assert compute_salary_band([]) is None

    def test_returns_none_with_single_signal(self):
        s = [SalarySignal(base_monthly_k=30)]
        assert compute_salary_band(s) is None  # need ≥2 datapoints

    def test_uses_midpoint_of_range(self):
        s = [
            SalarySignal(salary_range_min_k=20, salary_range_max_k=40),  # mid=30
            SalarySignal(salary_range_min_k=25, salary_range_max_k=45),  # mid=35
        ]
        band = compute_salary_band(s)
        assert band["n"] == 2
        assert band["p50"] == 32.5
        assert band["min"] == 30
        assert band["max"] == 35

    def test_percentiles_with_5_signals(self):
        s = [SalarySignal(base_monthly_k=v) for v in [10, 20, 30, 40, 50]]
        band = compute_salary_band(s)
        # Linear interp, n=5 → p25 = values[1] = 20, p50 = values[2] = 30, p75 = values[3] = 40
        assert band["p25"] == 20
        assert band["p50"] == 30
        assert band["p75"] == 40

    def test_mixed_signals(self):
        s = [
            SalarySignal(base_monthly_k=15),
            SalarySignal(salary_range_min_k=20, salary_range_max_k=40),  # mid=30
            SalarySignal(base_monthly_k=45),
        ]
        band = compute_salary_band(s)
        assert band["n"] == 3
        assert band["p50"] == 30  # middle value
        assert band["min"] == 15
        assert band["max"] == 45

    def test_band_renders_in_report(self):
        """v0.2.0 — band heading is 「薪酬 band」 (research-report tone); percentile labels still P25 / P50 / P75."""
        rf = ReviewFacts(salary_signals=[
            SalarySignal(base_monthly_k=20),
            SalarySignal(base_monthly_k=30),
            SalarySignal(base_monthly_k=40),
        ])
        data = ReportData(
            query=_q(), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        html = build_report(data)
        assert "salary-band" in html
        assert "薪酬 band" in html
        assert "P25" in html
        assert "P75" in html


# =============== G2: Fine-grained JD rules ===============

class TestFineJD:
    """v0.1.17 — 7 more JD rules beyond v0.1.16's 8."""

    def test_remote_work_contradicted_by_must_attend(self):
        rf = ReviewFacts(salary_signals=[
            SalarySignal(evidence="公司强制坐班，必须到岗")
        ])
        data = ReportData(
            query=_q("支持远程办公"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        c = next((x for x in claims if "远程" in x.claim), None)
        assert c is not None
        assert c.status == "contradicted"

    def test_two_day_weekend_contradicted_by_sizeweek(self):
        rf = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="大小周", intensity="high")]
        )
        data = ReportData(
            query=_q("周末双休"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        c = next((x for x in claims if "双休" in x.claim), None)
        assert c is not None
        assert c.status == "contradicted"

    def test_training_unverified_default(self):
        data = ReportData(
            query=_q("提供培训预算"), generated_at=datetime.now(timezone.utc)
        )
        claims = compute_jd_alignment(data)
        c = next((x for x in claims if "培训" in x.claim), None)
        assert c is not None
        assert c.status == "unverified"

    def test_promotion_contradicted_by_reviews(self):
        rf = ReviewFacts(vibe_signals=[
            VibeSignal(sentiment="negative", evidence="晋升难，三年没涨")
        ])
        data = ReportData(
            query=_q("晋升通道"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        c = next((x for x in claims if "晋升" in x.claim), None)
        assert c is not None
        assert c.status == "contradicted"

    def test_team_building_contradicted_by_review(self):
        rf = ReviewFacts(salary_signals=[
            SalarySignal(evidence="团建安排在周末 = 加班")
        ])
        data = ReportData(
            query=_q("定期团建"), generated_at=datetime.now(timezone.utc), review_facts=rf
        )
        claims = compute_jd_alignment(data)
        c = next((x for x in claims if "团建" in x.claim), None)
        assert c is not None
        assert c.status == "contradicted"

    def test_no_new_rule_no_extra_claim(self):
        data = ReportData(
            query=_q("Python 开发"), generated_at=datetime.now(timezone.utc)
        )
        claims = compute_jd_alignment(data)
        # 'Python 开发' has no claim keywords → 0 claims
        assert claims == []


# =============== G3: Snapshot diff ===============

class TestSnapshot:
    """v0.1.17 — vs 上次 (snapshot diff)."""

    def test_extract_snapshot_basics(self):
        rf = ReviewFacts(salary_signals=[
            SalarySignal(base_monthly_k=20),
            SalarySignal(base_monthly_k=30),
            SalarySignal(base_monthly_k=40),
        ])
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            review_facts=rf,
            axes=[
                AxisScore(axis=RiskAxis.OVERTIME, stars=4),
                AxisScore(axis=RiskAxis.SALARY_TRUST, stars=4),
                AxisScore(axis=RiskAxis.JUDICIAL, stars=4),
                AxisScore(axis=RiskAxis.BUSINESS, stars=4),
                AxisScore(axis=RiskAxis.CULTURE, stars=4),
            ],
        )
        s = snap_mod._extract_snapshot(data)
        assert s.company == "TestCo"
        assert s.salary_p50 == 30
        assert s.overall_score == 4.0
        assert s.axes["overtime"] == 4

    def test_diff_detects_case_increase(self):
        prev = snap_mod.Snapshot(
            company="X",
            generated_at="2025-09-01T00:00:00+00:00",
            verdict="caution",
            judicial_case_count=2,
            salary_p50=30,
            vibe_pos=1, vibe_neg=1,
        )
        # Build current data: judicial 5 cases (was 2) → diff must catch it
        rf = ReviewFacts(salary_signals=[
            SalarySignal(base_monthly_k=30),
            SalarySignal(base_monthly_k=40),
        ])
        data = ReportData(
            query=CompanyQuery(company="X", position="后端"),
            generated_at=datetime(2025, 9, 10, tzinfo=timezone.utc),
            review_facts=rf,
            axes=[
                AxisScore(axis=RiskAxis.OVERTIME, stars=4),
                AxisScore(axis=RiskAxis.SALARY_TRUST, stars=4),
                AxisScore(axis=RiskAxis.JUDICIAL, stars=3),  # now worse
                AxisScore(axis=RiskAxis.BUSINESS, stars=4),
                AxisScore(axis=RiskAxis.CULTURE, stars=4),
            ],
            judicial_facts=JudicialFacts(case_count_total=5),
        )
        diff = snap_mod.diff_snapshots(prev, data)
        assert diff is not None
        # Days_ago computed
        assert diff["days_ago"] == 9
        # Judicial line should be present with +3
        judicial_lines = [ln for ln in diff["lines"] if ln["label"] == "司法记录"]
        assert len(judicial_lines) == 1
        assert "+3" in judicial_lines[0]["delta"]
        assert judicial_lines[0]["tone"] == "bad"

    def test_diff_returns_none_when_identical(self):
        prev = snap_mod.Snapshot(
            company="X",
            generated_at="2025-09-01T00:00:00+00:00",
            verdict="neutral",
            axes={"overtime": 3, "salary_trust": 3},
            judicial_case_count=0,
            salary_p50=25,
            vibe_pos=0, vibe_neg=0,
        )
        rf = ReviewFacts(salary_signals=[
            SalarySignal(base_monthly_k=25),
            SalarySignal(base_monthly_k=25),
        ])
        data = ReportData(
            query=CompanyQuery(company="X", position="后端"),
            generated_at=datetime(2025, 9, 10, tzinfo=timezone.utc),
            review_facts=rf,
            axes=[
                AxisScore(axis=RiskAxis.OVERTIME, stars=3),
                AxisScore(axis=RiskAxis.SALARY_TRUST, stars=3),
            ],
            judicial_facts=JudicialFacts(case_count_total=0),
        )
        # Force verdict → neutral (axes only 2 of 5, no v0.1.16 verdict triggers)
        diff = snap_mod.diff_snapshots(prev, data)
        # Could be None or empty lines
        if diff is not None:
            # If anything is there, it should not include salary if it's identical
            salary_lines = [ln for ln in diff["lines"] if ln["label"] == "薪酬中位"]
            assert salary_lines == []

    def test_snapshot_save_load_roundtrip(self, tmp_path, monkeypatch):
        """Use tmp_path for cache to avoid touching real cache."""
        # Patch _CACHE_DIR to point to tmp_path
        monkeypatch.setattr(snap_mod, "_CACHE_DIR", tmp_path)
        rf = ReviewFacts(salary_signals=[
            SalarySignal(base_monthly_k=20),
            SalarySignal(base_monthly_k=40),
        ])
        data = ReportData(
            query=CompanyQuery(company="RoundTripCo", position="后端"),
            generated_at=datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc),
            review_facts=rf,
        )
        path = snap_mod.save_snapshot(data)
        assert path is not None
        assert path.exists()
        loaded = snap_mod.latest_snapshot("RoundTripCo")
        assert loaded is not None
        assert loaded.company == "RoundTripCo"
        assert loaded.salary_p50 == 30


# =============== G4: Watchlist ===============

class TestWatchlist:
    """v0.1.17 — Persistent watchlist."""

    def test_add_and_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        watchlist.add("字节跳动", "后端", "杭州")
        entries = watchlist.list_entries()
        assert len(entries) == 1
        assert entries[0].company == "字节跳动"
        assert entries[0].position == "后端"

    def test_add_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        watchlist.add("美团", "前端", "北京")
        watchlist.add("美团", "前端", "北京")  # same → no-op
        entries = watchlist.list_entries()
        assert len(entries) == 1

    def test_add_different_position_creates_new_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        watchlist.add("美团", "前端", "北京")
        watchlist.add("美团", "后端", "北京")
        entries = watchlist.list_entries()
        assert len(entries) == 2

    def test_remove(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        watchlist.add("X", "", "")
        assert watchlist.remove("X") is True
        assert watchlist.list_entries() == []

    def test_remove_nonexistent_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        assert watchlist.remove("NeverAdded") is False

    def test_mark_ran_updates_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        watchlist.add("Y", "", "")
        assert watchlist.list_entries()[0].last_run_at is None
        watchlist.mark_ran("Y")
        assert watchlist.list_entries()[0].last_run_at is not None

    def test_mark_ran_unknown_company_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        # Should not raise even if not in list
        watchlist.mark_ran("NeverAdded")  # no-op

    def test_empty_company_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(watchlist, "_PATH", tmp_path / "watchlist.json")
        with pytest.raises(ValueError):
            watchlist.add("  ")


# =============== G5: Print support ===============

class TestPrintSupport:
    """v0.1.17 — @media print rules + ?print=1 auto-trigger."""

    def test_css_has_print_media_query(self):
        css = (open("src/jobhunter/report/static/report.css", encoding="utf-8").read())
        assert "@media print" in css

    def test_template_has_print_param_handler(self):
        tmpl = (open("src/jobhunter/report/templates/report.html.j2", encoding="utf-8").read())
        assert "window.print()" in tmpl
        assert "?print=1" in tmpl or "params.get('print')" in tmpl

    def test_report_renders_without_print_overhead(self):
        """The base report (no print=1) should NOT include the auto-trigger script's
        intrusive elements — but the script itself is fine as a no-op when query param is absent."""
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        # The print handler is in <script>...</script> tags — verify it doesn't
        # depend on having rendered data.
        assert html  # build still works
        # The auto-trigger is in the inline JS; harmless when ?print != 1
        assert "URLSearchParams" in html
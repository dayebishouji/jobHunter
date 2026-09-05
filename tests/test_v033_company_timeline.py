"""v0.3.3 — Company timeline + age helpers + SVG generator.

Three pure-deterministic additions:
  - builder.compute_company_age(founded_year, generated_at) → int | None
  - builder.compute_company_timeline(CompanyProfile)       → dict | None
  - charts.company_timeline_svg(events)                    → str (SVG or "")
"""

from __future__ import annotations

from datetime import datetime

import pytest

from jobhunter.report.builder import (
    compute_company_age,
    compute_company_timeline,
)
from jobhunter.report.charts import company_timeline_svg


# ---------- compute_company_age ----------

class TestComputeCompanyAge:
    """2 cases — pure math, no LLM."""

    def test_returns_age_when_founded_year_past(self):
        age = compute_company_age(2014, datetime(2026, 9, 5))
        assert age == 12

    def test_returns_none_when_founded_year_missing_or_future(self):
        assert compute_company_age(None, datetime(2026, 9, 5)) is None
        assert compute_company_age(2030, datetime(2026, 9, 5)) is None
        assert compute_company_age("not-a-year", datetime(2026, 9, 5)) is None


# ---------- compute_company_timeline ----------

class TestComputeCompanyTimeline:
    """4 cases — deterministic event assembly from CompanyProfile fields."""

    def test_returns_none_when_no_founded_year(self):
        from types import SimpleNamespace
        cp = SimpleNamespace(founded_year=None, funding_stage=None, investors=[])
        assert compute_company_timeline(cp) is None

    def test_emits_found_event_with_year(self):
        from types import SimpleNamespace
        cp = SimpleNamespace(founded_year=2014, funding_stage=None, investors=[])
        tl = compute_company_timeline(cp)
        assert tl is not None
        assert tl["events"][0] == {"when": "2014", "label": "成立"}
        assert tl["span_start"] == 2014

    def test_emits_funding_event_when_stage_set(self):
        from types import SimpleNamespace
        cp = SimpleNamespace(founded_year=2014, funding_stage="B轮", investors=[])
        tl = compute_company_timeline(cp)
        labels = [e["label"] for e in tl["events"]]
        assert any("B 轮" in lab for lab in labels)

    def test_emits_investors_and_clamps_to_5_events(self):
        from types import SimpleNamespace
        cp = SimpleNamespace(
            founded_year=2010,
            funding_stage="C轮",
            investors=["红杉资本", "IDG", "高瓴", "经纬创投"],
        )
        tl = compute_company_timeline(cp)
        assert tl is not None
        assert len(tl["events"]) <= 5
        labels = " ".join(e["label"] for e in tl["events"])
        # Top-2 investor names should appear, plus "等"
        assert "红杉资本" in labels
        assert "等" in labels


# ---------- company_timeline_svg ----------

class TestCompanyTimelineSvg:
    """2 cases — pure string output, empty / populated."""

    def test_empty_when_no_events(self):
        assert company_timeline_svg([]) == ""
        assert company_timeline_svg(None) == ""

    def test_renders_svg_with_events(self):
        events = [
            {"when": "2014", "label": "成立"},
            {"when": "—", "label": "B 轮 · 红杉领投"},
            {"when": "2026", "label": "至今"},
        ]
        svg = company_timeline_svg(events)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert 'class="company-timeline-svg"' in svg
        # 3 dots for 3 events
        assert svg.count("<circle") == 3
        # Native tooltips carry the label
        assert "<title>" in svg
        assert "成立" in svg

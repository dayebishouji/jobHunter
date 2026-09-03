"""Chart helpers (SVG / distribution) — pure logic."""

from __future__ import annotations

import pytest

from jobhunter.models.facts import OvertimeSignal, SalarySignal
from jobhunter.models.scoring import AxisScore, RiskAxis
from jobhunter.report.charts import (
    overtime_distribution,
    radar_svg,
    salary_distribution,
    score_ring_svg,
)


def test_radar_svg_includes_pentagon_and_labels():
    axes = [AxisScore(axis=a, stars=3, rationale="x") for a in RiskAxis]
    s = radar_svg(axes)
    assert "<svg" in s
    assert "polygon" in s  # data polygon
    assert "加班强度" in s  # label
    assert "薪酬诚信" in s


def test_radar_svg_handles_empty():
    assert radar_svg([]) == ""


def test_score_ring_svg_includes_value_and_ring():
    s = score_ring_svg(3.5)
    assert "<svg" in s
    assert "stroke-dashoffset" in s
    assert "3.5" in s


def test_overtime_distribution_counts_by_pattern():
    signals = [
        OvertimeSignal(pattern="996", intensity="high"),
        OvertimeSignal(pattern="996", intensity="high"),
        OvertimeSignal(pattern="弹性", intensity="low"),
    ]
    dist = overtime_distribution(signals)
    assert dist[0]["pattern"] == "996"
    assert dist[0]["count"] == 2
    assert dist[1]["pattern"] == "弹性"
    assert sum(d["pct"] for d in dist) >= 99  # rounding


def test_salary_distribution_buckets_correctly():
    signals = [
        SalarySignal(base_monthly_k=8.0),
        SalarySignal(base_monthly_k=18.0),
        SalarySignal(base_monthly_k=18.0),
        SalarySignal(base_monthly_k=35.0),
        SalarySignal(base_monthly_k=60.0),
    ]
    dist = salary_distribution(signals)
    by_label = {d["label"]: d["count"] for d in dist}
    assert by_label["<10"] == 1
    assert by_label["10-20"] == 2
    assert by_label["30-40"] == 1
    assert by_label["50+"] == 1
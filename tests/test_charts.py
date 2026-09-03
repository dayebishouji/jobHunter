"""Chart helpers (SVG / distribution) — pure logic."""

from __future__ import annotations

import pytest

from jobhunter.models.facts import (
    CaseItem,
    NewsItem,
    OvertimeSignal,
    SalarySignal,
    Shareholder,
    VibeSignal,
)
from jobhunter.models.scoring import AxisScore, RiskAxis
from jobhunter.report.charts import (
    case_timeline_svg,
    case_year_buckets,
    funding_stage_position,
    news_items_for_timeline,
    overtime_distribution,
    radar_svg,
    salary_distribution,
    score_ring_svg,
    shareholder_pie_svg,
    vibe_donut_svg,
    vibe_sentiment_counts,
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


# ---------- New editorial primitives ----------


def test_vibe_sentiment_counts_sorts_by_count():
    signals = [
        VibeSignal(sentiment="mixed"),
        VibeSignal(sentiment="mixed"),
        VibeSignal(sentiment="positive"),
        VibeSignal(sentiment="negative"),
    ]
    counts = vibe_sentiment_counts(signals)
    assert counts[0]["label"] == "混合"
    assert counts[0]["count"] == 2
    assert any(c["label"] == "正面" and c["tone"] == "good" for c in counts)
    assert any(c["label"] == "负面" and c["tone"] == "bad" for c in counts)


def test_vibe_sentiment_counts_empty():
    assert vibe_sentiment_counts([]) == []


def test_vibe_donut_svg_renders_segments():
    counts = vibe_sentiment_counts([
        VibeSignal(sentiment="positive"),
        VibeSignal(sentiment="negative"),
    ])
    s = vibe_donut_svg(counts)
    assert "<svg" in s
    assert "stroke-dasharray" in s
    assert "2" in s  # total count rendered in center


def test_vibe_donut_svg_empty_renders_placeholder():
    s = vibe_donut_svg([])
    assert "<svg" in s
    assert "无数据" in s


def test_shareholder_pie_svg_with_percentages():
    s = shareholder_pie_svg([
        Shareholder(name="A", stake_pct=60.0),
        Shareholder(name="B", stake_pct=30.0),
        Shareholder(name="C", stake_pct=10.0),
    ])
    assert "<svg" in s
    assert "stroke-dasharray" in s
    # 3 segments
    assert s.count('stroke-dasharray') == 3


def test_shareholder_pie_svg_equal_fallback_when_no_percentages():
    s = shareholder_pie_svg([
        Shareholder(name="A", stake_pct=None),
        Shareholder(name="B", stake_pct=None),
    ])
    assert "<svg" in s


def test_shareholder_pie_svg_empty():
    s = shareholder_pie_svg([])
    assert "<svg" in s
    assert "—" in s


def test_case_year_buckets_groups_correctly():
    items = [
        CaseItem(title="a", year=2024),
        CaseItem(title="b", year=2024),
        CaseItem(title="c", year=2023),
        CaseItem(title="d", year=None),  # ignored
    ]
    buckets = case_year_buckets(items, this_year=2026)
    years = {b["year"]: b for b in buckets}
    assert years[2024]["count"] == 2
    assert years[2024]["tone"] == "warn"  # 1-2 → warn
    assert years[2023]["count"] == 1
    assert years[2023]["tone"] == "warn"  # 1-2 → warn
    assert years[2025]["count"] == 0
    assert years[2025]["tone"] == "good"  # 0 → good


def test_case_year_buckets_empty_inputs_yield_zero_buckets():
    buckets = case_year_buckets([], this_year=2026)
    assert len(buckets) == 6  # last 6 years inclusive
    assert all(b["count"] == 0 for b in buckets)


def test_case_timeline_svg_renders_bars():
    buckets = case_year_buckets([
        CaseItem(title="x", year=2026),
        CaseItem(title="x", year=2026),
        CaseItem(title="x", year=2024),
    ], this_year=2026)
    s = case_timeline_svg(buckets)
    assert "<svg" in s
    assert "<rect" in s
    # Year labels rendered (e.g. "'26")
    assert "'26" in s


def test_case_timeline_svg_empty_returns_empty():
    assert case_timeline_svg([]) == ""


def test_funding_stage_position_known_stages():
    assert funding_stage_position("天使轮") == 1
    assert funding_stage_position("A轮") == 2
    assert funding_stage_position("B轮") == 3
    assert funding_stage_position("C轮") == 4
    assert funding_stage_position("D轮及以上") == 4
    assert funding_stage_position("已上市") == 5
    assert funding_stage_position("未融资") == 0


def test_funding_stage_position_unknown_returns_negative():
    assert funding_stage_position(None) == -1
    assert funding_stage_position("") == -1
    assert funding_stage_position("随便写写") == -1


def test_news_items_for_timeline_sorted_desc():
    # NewsItem.published_at is str (ISO date string); sort lexicographically
    items = [
        NewsItem(title="old", url="https://a.com/1", published_at="2024-01-01"),
        NewsItem(title="new", url="https://a.com/2", published_at="2026-06-01"),
        NewsItem(title="mid", url="https://a.com/3", published_at="2025-03-01"),
    ]
    out = news_items_for_timeline(items)
    assert out[0]["title"] == "new"
    assert out[1]["title"] == "mid"
    assert out[2]["title"] == "old"
    assert all("when" in x for x in out)
    assert all("summary" in x for x in out)


def test_news_items_for_timeline_handles_no_dates():
    items = [NewsItem(title="x", url="https://a.com/1")]
    out = news_items_for_timeline(items)
    assert out[0]["when"] == "—"
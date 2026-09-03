"""Normalize / crosscheck / query-templates tests (no I/O)."""

from __future__ import annotations

import pytest

from jobhunter.models.facts import (
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.processing.crosscheck import (
    all_notes,
    detect_overtime_consensus,
    detect_salary_conflicts,
    sentiment_majority,
)
from jobhunter.processing.normalize import normalize
from jobhunter.search.query_templates import news_queries, review_queries


def _ri(title: str, url: str, snippet: str = "x") -> RawItem:
    return RawItem(source="tavily:test", url=url, title=title, snippet=snippet)


class TestNormalize:
    def test_dedup_by_url(self):
        items = [_ri("a", "https://x.com/1"), _ri("a (dup)", "https://x.com/1")]
        r = CollectorResult(
            collector="tavily_reviews", domain="reviews",
            company_query=CompanyQuery(company="X"), items=items,
        )
        out = normalize([r])
        assert len(out["reviews"]) == 1

    def test_fuzzy_dedup_by_title(self):
        items = [
            _ri("加班严重，每天到 10 点", "https://a.com/1"),
            _ri("加班严重，每天到 10 点", "https://b.com/2"),
        ]
        r = CollectorResult(
            collector="tavily_reviews", domain="reviews",
            company_query=CompanyQuery(company="X"), items=items,
        )
        out = normalize([r])
        assert len(out["reviews"]) == 1

    def test_buckets_by_domain(self):
        r1 = CollectorResult(
            collector="r", domain="reviews",
            company_query=CompanyQuery(company="X"),
            items=[_ri("a", "https://x.com/1")],
        )
        r2 = CollectorResult(
            collector="n", domain="news",
            company_query=CompanyQuery(company="X"),
            items=[_ri("b", "https://y.com/2")],
        )
        out = normalize([r1, r2])
        assert len(out["reviews"]) == 1
        assert len(out["news"]) == 1
        assert out["business"] == []
        assert out["judicial"] == []

    def test_skips_errored_results(self):
        r = CollectorResult(
            collector="r", domain="reviews",
            company_query=CompanyQuery(company="X"),
            error="some error",
        )
        out = normalize([r])
        assert out["reviews"] == []


class TestCrosscheck:
    def test_no_salary_no_conflict(self):
        r = ReviewFacts()
        assert detect_salary_conflicts(r) == []

    def test_high_spread_triggers_conflict(self):
        r = ReviewFacts(
            salary_signals=[
                SalarySignal(base_monthly_k=15.0),
                SalarySignal(base_monthly_k=35.0),
            ]
        )
        notes = detect_salary_conflicts(r)
        assert notes and "差异" in notes[0]

    def test_overtime_consensus(self):
        r = ReviewFacts(
            overtime_signals=[
                OvertimeSignal(pattern="996"),
                OvertimeSignal(pattern="996"),
                OvertimeSignal(pattern="弹性"),
            ]
        )
        assert detect_overtime_consensus(r.overtime_signals) == "996"

    def test_sentiment_majority(self):
        assert sentiment_majority(["positive", "positive", "negative"]) == "positive"
        assert sentiment_majority(["positive", "negative"]) == "mixed"
        assert sentiment_majority([]) == "neutral"

    def test_all_notes_includes_overtime_when_heavy(self):
        r = ReviewFacts(
            overtime_signals=[OvertimeSignal(pattern="996"), OvertimeSignal(pattern="996")],
            vibe_signals=[VibeSignal(sentiment="negative")],
        )
        notes = all_notes(r)
        assert any("996" in n or "负面" in n for n in notes)


class TestQueryTemplates:
    def test_review_queries_basics(self):
        q = review_queries(CompanyQuery(company="阿里", position="后端"))
        assert any("阿里" in s for s in q)
        assert any("后端" in s for s in q)
        assert any("加班" in s for s in q)

    def test_news_queries_have_year(self):
        qs = news_queries(CompanyQuery(company="X"))
        assert any("2026" in s or "最新" in s for s in qs)

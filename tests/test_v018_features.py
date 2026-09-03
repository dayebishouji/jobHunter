"""Tests for v0.1.8 features: per-chapter confidence, diversity KPI, news timeline SVG,
entity extraction prompt+helper."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.facts import (
    NewsFacts,
    NewsItem,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.pipeline import _compute_confidence


def _item(url: str, title: str, snippet: str, score: float | None = None) -> RawItem:
    payload: dict = {}
    if score is not None:
        payload["score"] = score
    return RawItem(
        source="tavily:web",
        url=url,
        title=title,
        snippet=snippet,
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
        payload=payload,
    )


class TestPerChapterConfidence:
    """v0.1.8 changed _compute_confidence to return per-chapter dict."""

    def test_returns_dict_with_five_chapters_and_overall(self):
        out = _compute_confidence({}, None)
        assert isinstance(out, dict)
        assert set(out.keys()) == {"company", "business", "judicial", "reviews", "news", "overall"}

    def test_empty_run_is_all_low(self):
        out = _compute_confidence({}, None)
        assert all(v == "low" for v in out.values())

    def test_only_reviews_with_struct_signals_is_reviews_high_others_low(self):
        by_domain = {"reviews": [_item("https://x.com", "t", "s")]}
        findings = type("F", (), {})()  # minimal stub
        findings.reviews = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0)]
        )
        findings.business = None
        findings.judicial = None
        findings.news = None
        findings.company_profile = None
        out = _compute_confidence(by_domain, findings)
        assert out["reviews"] == "high"
        assert out["overall"] in ("low", "medium")

    def test_news_with_raw_and_struct_is_high(self):
        by_domain = {"news": [_item("https://x.com", "t", "s")]}
        findings = type("F", (), {})()
        findings.reviews = ReviewFacts()
        findings.business = None
        findings.judicial = None
        # NewsFacts._drop_url_missing only accepts dicts (LLM-side); pass dicts.
        findings.news = NewsFacts.model_validate({
            "items": [{"title": "x", "url": "https://x.com", "published_at": "2026-05-01"}]
        })
        findings.company_profile = None
        out = _compute_confidence(by_domain, findings)
        assert out["news"] == "high"

    def test_news_with_struct_but_no_raw_is_medium(self):
        # Conservative: medium if either side, high only when both.
        by_domain: dict = {"news": []}
        findings = type("F", (), {})()
        findings.reviews = ReviewFacts()
        findings.business = None
        findings.judicial = None
        findings.news = NewsFacts.model_validate({
            "items": [{"title": "x", "url": "https://x.com", "published_at": "2026-05-01"}]
        })
        findings.company_profile = None
        out = _compute_confidence(by_domain, findings)
        assert out["news"] == "medium"


class TestComputeDiversityKpi:
    """Hero meta KPI for source diversity."""

    def test_empty_returns_zero_signal_label(self):
        from jobhunter.report.builder import compute_diversity_kpi
        out = compute_diversity_kpi(None, [])
        assert out["total_signals"] == 0
        assert out["corroborated_count"] == 0
        assert out["distinct_domains"] == []
        assert out["tier_label_zh"] == "无信号"

    def test_single_source_single_domain(self):
        from jobhunter.report.builder import compute_diversity_kpi
        rf = ReviewFacts(
            salary_signals=[
                SalarySignal(position="p", base_monthly_k=30.0, url="https://zhihu.com/q/1"),
                SalarySignal(position="p", base_monthly_k=30.0, url="https://v2ex.com/t/2"),
            ]
        )
        out = compute_diversity_kpi(rf, [])
        assert out["total_signals"] == 2
        assert out["tier_distribution"]["single-source"] == 2
        assert sorted(out["distinct_domains"]) == ["v2ex.com", "zhihu.com"]
        assert out["corroborated_count"] == 0

    def test_multi_domain_with_supporting_urls_counted(self):
        from jobhunter.report.builder import compute_diversity_kpi
        rf = ReviewFacts(
            salary_signals=[SalarySignal(
                position="p", base_monthly_k=30.0,
                url="https://zhihu.com/q/1",
                supporting_urls=["https://v2ex.com/t/2", "https://maimai.cn/article/3"],
            )],
            overtime_signals=[OvertimeSignal(
                pattern="996", intensity="high",
                url="https://nowcoder.com/d/4",
                supporting_urls=["https://www.kanzhun.com/r/6"],
            )],
        )
        out = compute_diversity_kpi(rf, [])
        assert out["total_signals"] == 2
        # salary signal: 3 urls / 3 distinct domains → multi-domain
        # overtime signal: 2 urls / 2 distinct domains → corroborated
        assert out["corroborated_count"] == 2
        assert sorted(out["distinct_domains"]) == ["kanzhun.com", "maimai.cn", "nowcoder.com", "v2ex.com", "zhihu.com"]
        assert out["tier_label_zh"] in ("高", "中")


class TestNewsTimelineSvg:
    """SVG generator for the news chronology axis."""

    def test_empty_items_returns_empty_string(self):
        from jobhunter.report.charts import news_timeline_svg
        assert news_timeline_svg([]) == ""

    def test_items_without_dates_returns_empty(self):
        from jobhunter.report.charts import news_timeline_svg
        items = [{"when": "—", "title": "x", "url": "https://x.com"}]
        assert news_timeline_svg(items) == ""

    def test_items_with_dates_produces_svg(self):
        from jobhunter.report.charts import news_timeline_svg
        items = [
            {"when": "2026-09-01", "title": "最新", "url": "https://a.com"},
            {"when": "2026-07-15", "title": "中间", "url": "https://b.com"},
            {"when": "2026-05-01", "title": "最早", "url": "https://c.com"},
        ]
        out = news_timeline_svg(items, sentiment="mixed")
        assert "<svg" in out
        assert "</svg>" in out
        assert "news-timeline-svg" in out
        assert "最新" in out  # <title> tooltip
        # Three dots
        assert out.count("<circle") >= 3

    def test_positive_sentiment_uses_good_color(self):
        from jobhunter.report.charts import news_timeline_svg
        items = [{"when": "2026-09-01", "title": "好", "url": "https://a.com"}]
        out = news_timeline_svg(items, sentiment="positive")
        # good color hex
        assert "#4f6a3a" in out


class TestEntityExtractionHelper:
    """list_company_entities filters out the company name and short/long junk."""

    @pytest.mark.asyncio
    async def test_filters_company_name_and_short_strings(self):
        from jobhunter.llm.client import LLMClient, list_company_entities

        class FakeLLM:
            def __init__(self):
                self.last_kwargs = None

            async def structured_call(self, **kwargs):
                self.last_kwargs = kwargs
                return {"entities": ["有赞", "x", "菜鸟驿站一", "菜鸟", "钉钉" * 5]}

            def budget_ok(self):
                return True

        llm = FakeLLM()
        items = [_item("https://x.com", "title", "snippet")]
        out = await list_company_entities(llm, "有赞", items, max_items=5)
        # "有赞" == company → dropped; "x" < 2 chars → dropped;
        # "菜鸟驿站一" not in our banned list, kept; "菜鸟" 2 chars kept
        # The 25-char string is dropped (>12 chars)
        assert "有赞" not in out
        assert "x" not in out
        assert any("菜鸟" in e for e in out)
        # Pushed tool_name + entity schema
        assert llm.last_kwargs["tool_name"] == "list_company_entities"
        assert "entities" in llm.last_kwargs["tool_schema"]["properties"]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        from jobhunter.llm.client import list_company_entities

        class FakeLLM:
            async def structured_call(self, **kwargs):
                return {}
            def budget_ok(self):
                return True

        llm = FakeLLM()
        assert await list_company_entities(llm, "有赞", []) == []
        assert await list_company_entities(llm, "", [_item("https://x.com", "t", "s")]) == []

    @pytest.mark.asyncio
    async def test_handles_bad_llm_payload(self):
        from jobhunter.llm.client import list_company_entities

        class FakeLLM:
            async def structured_call(self, **kwargs):
                return {"entities": "not-a-list"}
            def budget_ok(self):
                return True

        llm = FakeLLM()
        out = await list_company_entities(llm, "有赞", [_item("https://x.com", "t", "s")])
        assert out == []


class TestReportRendersNewBadges:
    """End-to-end: build_report must include diversity KPI and per-chapter badges."""

    def test_diversity_kpi_in_hero(self):
        from jobhunter.models.report import ReportData
        from jobhunter.report.builder import build_report

        q = CompanyQuery(company="TestCo", position="p", city="杭州")
        reviews = ReviewFacts(
            salary_signals=[SalarySignal(
                position="p", base_monthly_k=30.0,
                url="https://zhihu.com/q/1",
                supporting_urls=["https://v2ex.com/t/2"],
            )],
            overtime_signals=[OvertimeSignal(
                pattern="996", intensity="high", url="https://nowcoder.com/d/3",
            )],
        )
        data = ReportData(
            query=q,
            generated_at=datetime.now(timezone.utc),
            review_facts=reviews,
            chapter_confidence={"reviews": "medium", "overall": "medium"},
        )
        html = build_report(data)
        assert "数据多样性" in html
        assert "印证" in html

    def test_chapter_confidence_badge_renders_when_not_high(self):
        from jobhunter.models.report import ReportData
        from jobhunter.report.builder import build_report

        q = CompanyQuery(company="TestCo", position="p", city="杭州")
        data = ReportData(
            query=q,
            generated_at=datetime.now(timezone.utc),
            chapter_confidence={"reviews": "low", "overall": "low"},
        )
        html = build_report(data)
        assert "conf-badge" in html
        assert "conf-low" in html

    def test_chapter_confidence_high_does_not_render_badge(self):
        from jobhunter.models.report import ReportData
        from jobhunter.report.builder import build_report

        q = CompanyQuery(company="TestCo", position="p", city="杭州")
        data = ReportData(
            query=q,
            generated_at=datetime.now(timezone.utc),
            chapter_confidence={"reviews": "high", "overall": "high"},
        )
        html = build_report(data)
        # Badge only renders when != high; the CSS contains 'conf-badge' as
        # selectors, so we count actual rendered badge spans, not the CSS.
        import re
        n_rendered = len(re.findall(r'<span class="conf-badge', html))
        assert n_rendered == 0

    def test_news_timeline_svg_renders_when_news_items_present(self):
        from jobhunter.models.report import ReportData
        from jobhunter.report.builder import build_report

        q = CompanyQuery(company="TestCo", position="p", city="杭州")
        # _drop_url_missing only accepts dicts; model_validate bypasses
        # Python-side instance coercion.
        news = NewsFacts.model_validate({
            "items": [{"title": "好新闻", "url": "https://x.com", "published_at": "2026-09-01"}],
            "sentiment": "positive",
        })
        data = ReportData(
            query=q,
            generated_at=datetime.now(timezone.utc),
            news_facts=news,
        )
        html = build_report(data)
        assert "news-timeline-svg" in html
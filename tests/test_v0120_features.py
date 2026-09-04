"""v0.1.20 — Sogou WeChat collector + collector_notes banner rendering."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobhunter.collectors.registry import build_all
from jobhunter.collectors.sogou_weixin import SogouWeixinCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.processing.normalize import normalize
from jobhunter.report.builder import build_report, extract_collector_notes
from jobhunter.search.cache import FileCache
from jobhunter.search.tavily_client import TavilyClient
from jobhunter.models.facts import (
    BusinessFacts,
    NewsFacts,
    NewsItem,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
    AggregatedFindings,
    CompanyProfile,
    JudicialFacts,
)
from datetime import datetime, timezone


# ----- canned sogou HTML fixtures ----------------------------------------

def _canned_results_html() -> str:
    """Two news-list entries pointing at mp.weixin.qq.com (plus one bad
    link we want filtered out). Body deliberately padded past 1KB so it
    sails over the anti-bot minimum-length threshold."""
    return """
<html><body>
<!-- padding to exceed anti-bot min-length -->
<p>欢迎使用搜狗微信搜索</p>
<p>推荐文章 / 最新文章 / 公众号</p>
<ul class="news-list">
  <li class="news-list-li">
    <div class="txt-box">
      <h3><a href="https://mp.weixin.qq.com/s?__biz=foo1">棒谷科技福利与加班体验</a></h3>
      <p class="txt-info">入职一年感受：薪资中等，加班偏多，团队氛围 OK。</p>
    </div>
  </li>
  <li class="news-list-li">
    <div class="txt-box">
      <h3><a href="https://mp.weixin.qq.com/s?__biz=foo2">棒谷跨境电商运营面试</a></h3>
      <p class="txt-info">面试两轮技术 + HR，问项目深，节奏快。</p>
    </div>
  </li>
  <li class="news-list-li">
    <div class="txt-box">
      <h3><a href="https://example.com/not-weixin">垃圾站外链接</a></h3>
      <p class="txt-info">不应该被采纳。</p>
    </div>
  </li>
</ul>
</body></html>
""".strip()


def _antispider_html() -> str:
    """Anti-bot challenge page — short body + keyword."""
    return "<html><body>antispider — 请输入验证码以继续访问</body></html>"


def _empty_html() -> str:
    """Empty results page (real but no hits)."""
    return "<html><body><div class='news-list'></div></body></html>" * 30  # long enough


# ----- stubs ---------------------------------------------------------------

class _StubResponse:
    def __init__(self, text: str, encoding: str = "utf-8") -> None:
        self.text = text
        self.encoding = encoding


def _make_http_stub(html: str, calls: list[tuple[str, str]] | None = None) -> MagicMock:
    """Return an AsyncMock httpx client that records (url, referer) per call."""
    http = MagicMock()
    async def _get(url: str, *, headers: dict | None = None, follow_redirects: bool = True):
        if calls is not None:
            calls.append((url, (headers or {}).get("Referer", "")))
        return _StubResponse(html)
    http.get = _get
    return http


@pytest.fixture
def cache_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _settings(**overrides) -> Settings:
    """Test settings — keep throttle intervals tiny to avoid slowing tests."""
    s = Settings(anthropic_api_key="x", tavily_api_key="y")
    s.sogou_weixin_min_interval = 0.001
    s.sogou_weixin_max_interval = 0.002
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ============================================================================
# Parser
# ============================================================================

class TestSogouWeixinParse:
    def test_parses_two_valid_results(self, cache_dir):
        http = _make_http_stub(_canned_results_html())
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(_settings(), http=http, cache=cache)
        result = asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))

        assert result.error is None
        assert result.collector == "sogou_weixin"
        assert result.domain == "reviews"
        # Third link is to example.com, not mp.weixin.qq.com — must be filtered out.
        assert len(result.items) == 2
        assert all("mp.weixin.qq.com" in str(it.url) for it in result.items)
        assert all(it.source == "sogou_weixin:article" for it in result.items)
        assert result.confidence == "low"  # 2 < 3

    def test_referrer_header_sent(self, cache_dir):
        calls: list[tuple[str, str]] = []
        http = _make_http_stub(_canned_results_html(), calls=calls)
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(_settings(), http=http, cache=cache)
        asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))

        assert calls, "http.get should have been called"
        url, referer = calls[0]
        assert "weixin.sogou.com/weixin" in url
        assert "query=" in url
        assert referer == "https://weixin.sogou.com/"


# ============================================================================
# Anti-bot detection
# ============================================================================

class TestSogouWeixinAntiBot:
    def test_short_body_treated_as_blocked(self, cache_dir):
        http = _make_http_stub("<html></html>")  # 13 bytes
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(_settings(), http=http, cache=cache)
        result = asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))

        assert result.error == "anti_bot_redirect"
        assert result.confidence == "none"

    def test_antispider_keyword_treated_as_blocked(self, cache_dir):
        http = _make_http_stub(_antispider_html())
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(_settings(), http=http, cache=cache)
        result = asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))

        assert result.error == "anti_bot_redirect"


# ============================================================================
# Cache
# ============================================================================

class TestSogouWeixinCache:
    def test_second_collect_uses_cache(self, cache_dir):
        calls: list[tuple[str, str]] = []
        http = _make_http_stub(_canned_results_html(), calls=calls)
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(_settings(), http=http, cache=cache)

        asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))
        n_first = len(calls)
        asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))
        # Cache hit means http.get is NOT called a second time.
        assert len(calls) == n_first, "second collect should be served from cache"


# ============================================================================
# Throttle
# ============================================================================

class TestSogouWeixinThrottle:
    def test_min_interval_respected(self, cache_dir):
        s = _settings(sogou_weixin_min_interval=0.05, sogou_weixin_max_interval=0.06)
        http = _make_http_stub(_canned_results_html())
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(s, http=http, cache=cache)
        # Use a query with 2 aliases so 2 HTTP requests fire (after one throttle each).
        q = CompanyQuery(company="棒谷科技", aliases=["棒谷", "Banggood"])
        import time
        start = time.monotonic()
        asyncio.run(coll.collect(q))
        elapsed = time.monotonic() - start
        # 2 throttles × ≥0.05s = ≥0.10s, with overhead
        assert elapsed >= 0.08, f"throttle should add ≥~0.10s; got {elapsed:.3f}s"


# ============================================================================
# Disabled by setting
# ============================================================================

class TestSogouWeixinDisabled:
    def test_disabled_by_setting(self, cache_dir):
        calls: list[tuple[str, str]] = []
        http = _make_http_stub(_canned_results_html(), calls=calls)
        cache = FileCache(cache_dir)
        coll = SogouWeixinCollector(
            _settings(sogou_weixin_enabled=False),
            http=http, cache=cache,
        )
        result = asyncio.run(coll.collect(CompanyQuery(company="棒谷科技")))

        assert result.error == "disabled_by_setting"
        assert result.items == []
        assert calls == []


# ============================================================================
# Registry integration
# ============================================================================

class TestBuildAllIncludesSogouWeixin:
    def test_sogou_weixin_in_default_registry(self, cache_dir):
        s = _settings()
        tavily = TavilyClient(s, FileCache(cache_dir))
        http = _make_http_stub("")
        cache = FileCache(cache_dir)
        collectors = build_all(s, tavily=tavily, http=http, cache=cache)
        names = [c.name for c in collectors]
        assert "sogou_weixin" in names
        # Domain must be reviews so normalize() routes it correctly.
        sw = next(c for c in collectors if c.name == "sogou_weixin")
        assert sw.domain == "reviews"


# ============================================================================
# Normalize routing
# ============================================================================

class TestSogouItemsLandInReviewsBucket:
    def test_normalize_buckets_by_domain(self):
        items = [
            RawItem(source="sogou_weixin:article", url="https://mp.weixin.qq.com/s/x",
                    title="x", snippet="y"),
        ]
        r = CollectorResult(
            collector="sogou_weixin", domain="reviews",
            company_query=CompanyQuery(company="X"),
            items=items,
        )
        out = normalize([r])
        assert len(out["reviews"]) == 1
        assert out["reviews"][0].source == "sogou_weixin:article"
        # Other buckets stay empty
        assert out["news"] == [] and out["business"] == []


# ============================================================================
# extract_collector_notes
# ============================================================================

class TestExtractCollectorNotes:
    def test_returns_only_errored_collectors(self):
        ok = CollectorResult(collector="tavily_reviews", domain="reviews",
                             company_query=CompanyQuery(company="X"),
                             items=[RawItem(source="s", url="https://x.com/1",
                                            title="t", snippet="s")])
        blocked = CollectorResult(collector="sogou_weixin", domain="reviews",
                                  company_query=CompanyQuery(company="X"),
                                  items=[], error="anti_bot_redirect")
        notes = extract_collector_notes([ok, blocked])
        assert notes == {"sogou_weixin": "anti_bot_redirect"}

    def test_empty_input(self):
        assert extract_collector_notes([]) == {}
        assert extract_collector_notes(None) == {}

    def test_full_error_string_used_when_no_token(self):
        r = CollectorResult(collector="gsxt", domain="business",
                            company_query=CompanyQuery(company="X"),
                            error="ConnectError: timeout connecting")
        notes = extract_collector_notes([r])
        # First whitespace-separated token is the canonical marker.
        assert notes["gsxt"] == "ConnectError:"


# ============================================================================
# Banner rendering in template
# ============================================================================

def _minimal_report_data(collector_notes: dict[str, str] | None = None):
    """Build a ReportData sufficient to render the reviews chapter."""
    from jobhunter.models.scoring import AxisScore, RiskAxis
    from jobhunter.models.report import ReportData

    rf = ReviewFacts(
        salary_signals=[SalarySignal(position="后端", base_monthly_k=30.0,
                                     url="https://example.com/a",
                                     evidence="月薪 30K", supporting_urls=[])],
        overtime_signals=[],
        vibe_signals=[VibeSignal(sentiment="mixed", evidence="还行",
                                 url="https://example.com/b")],
    )
    findings = AggregatedFindings(
        company_query_summary="X 后端 杭州",
        reviews=rf,
        business=BusinessFacts(status="存续", legal_rep="张三"),
        news=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial=JudicialFacts(),
        company_profile=CompanyProfile(description="X 公司"),
    )
    return ReportData(
        query=CompanyQuery(company="X", position="后端", city="杭州"),
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        axes=[
            AxisScore(axis=RiskAxis.OVERTIME, stars=3, rationale="r"),
            AxisScore(axis=RiskAxis.SALARY_TRUST, stars=4, rationale="r"),
        ],
        review_facts=rf,
        business_facts=BusinessFacts(status="存续", legal_rep="张三"),
        news_facts=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial_facts=JudicialFacts(),
        company_profile=CompanyProfile(description="X 公司"),
        overall_confidence="medium",
        chapter_confidence={"overall": "medium", "reviews": "high", "business": "medium",
                            "news": "low", "judicial": "low", "company": "medium"},
        data_gaps=[],
        collector_notes=collector_notes or {},
    )


class TestSogouBannerRendering:
    def test_banner_renders_when_sogou_blocked(self):
        data = _minimal_report_data(collector_notes={"sogou_weixin": "anti_bot_redirect"})
        html = build_report(data)
        assert "搜狗微信搜索被反爬拦截" in html
        assert "weixin.sogou.com" in html

    def test_banner_absent_when_no_marker(self):
        data = _minimal_report_data(collector_notes={})
        html = build_report(data)
        assert "搜狗微信搜索被反爬拦截" not in html

    def test_banner_absent_when_other_collector_failed(self):
        data = _minimal_report_data(collector_notes={"gsxt": "ConnectError"})
        html = build_report(data)
        assert "搜狗微信搜索被反爬拦截" not in html

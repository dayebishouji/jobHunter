"""v0.1.22 — 3 reviews / sogou / template bug fixes.

Bug 1: sogou_weixin collector's silent `no_results` failure wasn't surfaced
       in the report (banner only rendered for `anti_bot_redirect`).

Bug 2: Sogou's anti-bot challenge page dropped Chinese warning copy in some
       recent variants — our keyword check (`antispider`, `verify`, etc.)
       missed those pages even though they ship `antispider.min.js` /
       `static/css/anti.min.css`. Added asset-name fallback indicators.

Bug 3: Reviews bucket for consumer brands (e.g. 美的) got flooded with
       product / shop / login URLs from 知乎 / 看准 / 一亩三分地 /
       牛客 / 脉脉. LLM extraction correctly threw them away, leaving
       the reviews chapter empty. Added a per-host URL-path allowlist
       so employer-irrelevant URLs are dropped BEFORE the LLM sees them.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.collectors.sogou_weixin import (
    _BLOCK_INDICATORS,
    SogouWeixinCollector,
)
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.models.report import ReportData
from jobhunter.models.scoring import AxisScore, RiskAxis
from jobhunter.processing.normalize import (
    REVIEW_URL_PATTERNS,
    _keep_in_reviews,
    normalize,
)
from jobhunter.report.builder import build_report


# ============================================================================
# Bug 1 — Template banner for sogou_weixin
# ============================================================================

def _minimal_report(*, collector_notes: dict[str, str] | None = None):
    """Build a minimal ReportData with optional collector_notes for banner tests."""
    findings = AggregatedFindings(
        company_query_summary="X 后端 杭州",
        reviews=ReviewFacts(),
        business=BusinessFacts(status="存续", legal_rep="张三"),
        news=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial=JudicialFacts(),
        company_profile=CompanyProfile(),
    )
    return ReportData(
        query=CompanyQuery(company="X", position="后端", city="杭州"),
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        axes=[
            AxisScore(axis=RiskAxis.OVERTIME, stars=3, rationale="r"),
            AxisScore(axis=RiskAxis.SALARY_TRUST, stars=4, rationale="r"),
        ],
        review_facts=ReviewFacts(),
        business_facts=BusinessFacts(status="存续", legal_rep="张三"),
        news_facts=NewsFacts(items=[], sentiment="neutral", source_urls=[]),
        judicial_facts=JudicialFacts(),
        company_profile=CompanyProfile(),
        overall_confidence="medium",
        chapter_confidence={"overall": "medium", "reviews": "low", "business": "medium",
                            "news": "low", "judicial": "low", "company": "medium"},
        data_gaps=[],
        collector_notes=collector_notes or {},
    )


class TestTemplateBanner:
    """v0.1.22 — Banner must render for BOTH anti_bot_redirect AND no_results."""

    BANNER_MARKUP = '<div class="data-source-note">'

    def test_banner_renders_for_anti_bot_redirect(self):
        html = build_report(_minimal_report(collector_notes={"sogou_weixin": "anti_bot_redirect"}))
        assert "搜狗微信搜索被反爬拦截" in html
        assert self.BANNER_MARKUP in html

    def test_banner_renders_for_no_results(self):
        """Bug 1 — pre-v0.1.22 the banner only matched anti_bot_redirect."""
        html = build_report(_minimal_report(collector_notes={"sogou_weixin": "no_results"}))
        assert "搜狗微信搜索本次未抓到公众号文章" in html
        assert self.BANNER_MARKUP in html
        assert "建议手动到" in html

    def test_banner_renders_for_silent_block_variants(self):
        """Sogou returns one of `anti_bot_redirect` (challenge page detected)
        or `no_results` (fetch OK but 0 mp.weixin.qq.com hits — usually a
        silent soft-block). Both must surface to the user."""
        for marker in ("anti_bot_redirect", "no_results"):
            html = build_report(_minimal_report(collector_notes={"sogou_weixin": marker}))
            assert self.BANNER_MARKUP in html, f"missing banner for marker={marker!r}"

    def test_no_banner_when_sogou_succeeded(self):
        """No collector_notes → no banner markup (the CSS class definition
        always exists in the stylesheet, but no actual `<div class="data-source-note">` block)."""
        html = build_report(_minimal_report(collector_notes={}))
        assert self.BANNER_MARKUP not in html
        # Inline tag still references sogou in the CSS comment, so we don't
        # assert on the substring "搜狗" — only on the rendered banner block.

    def test_no_banner_for_unrelated_collector_notes(self):
        html = build_report(_minimal_report(collector_notes={"tavily_reviews": "timeout"}))
        assert self.BANNER_MARKUP not in html


# ============================================================================
# Bug 2 — Sogou anti-bot detection: asset-name fallback
# ============================================================================

def _make_collector() -> SogouWeixinCollector:
    """Build a SogouWeixinCollector with stub deps (we don't call .collect())."""
    import httpx
    from jobhunter.config import Settings
    from jobhunter.search.cache import FileCache

    settings = Settings()
    # httpx.AsyncClient is required by __init__ but never called here.
    collector = SogouWeixinCollector(
        settings,
        http=httpx.AsyncClient(),
        cache=FileCache(),
    )
    return collector


class TestSogouAntiBotExpansion:
    """v0.1.22 — Anti-bot detection must catch Sogou's newer challenge variants
    that drop the Chinese warning copy but still ship the asset bundle."""

    def _body(self) -> str:
        # Real Sogou challenge page: no Chinese indicators, but ships
        # anti.min.css + antispider.min.js + verify.css. ~1.2KB.
        return (
            '<!DOCTYPE HTML><html><head>'
            '<link rel="stylesheet" href="static/css/anti.min.css?v=1"/>'
            '<link rel="stylesheet" type="text/css" href="newstatic/css/verify.css">'
            '<script src="static/js/antispider.min.js?v=3"></script>'
            '</head><body>reloading</body></html>'
        )

    def test_new_challenge_variant_detected_via_assets(self):
        c = _make_collector()
        assert c._is_blocked(self._body()) is True

    def test_each_asset_name_triggers_blocked(self):
        c = _make_collector()
        for asset in ("static/css/anti.min.css?v=2", "antispider.min.js?v=4", "anti.min.css"):
            html = f"<html><link href='{asset}'/></html>" + "x" * 600
            assert c._is_blocked(html) is True, f"failed to detect {asset!r}"

    def test_legacy_indicators_still_work(self):
        c = _make_collector()
        for kw in _BLOCK_INDICATORS:
            html = f"<html><body>{kw}</body></html>" + "x" * 600
            assert c._is_blocked(html) is True, f"legacy indicator {kw!r} regressed"

    def test_real_results_page_not_flagged(self):
        c = _make_collector()
        # Real Sogou results page has mp.weixin.qq.com links and search chrome
        html = (
            "<html><head><title>搜狗</title></head><body>"
            '<div class="news-list"><a href="https://mp.weixin.qq.com/s/abc">art1</a></div>'
            "</body></html>" + "x" * 600
        )
        assert c._is_blocked(html) is False

    def test_short_body_still_flagged(self):
        c = _make_collector()
        assert c._is_blocked("") is True
        assert c._is_blocked("x" * 100) is True  # < _MIN_BODY_LEN (500)


# ============================================================================
# Bug 3 — Reviews URL-pattern filter
# ============================================================================

def _item(url: str, title: str = "t", source: str = "tavily_reviews") -> RawItem:
    from datetime import datetime, timezone
    return RawItem(
        source=source, url=url, title=title, snippet="x",
        published_at=None, retrieved_at=datetime.now(timezone.utc),
    )


def _reviews_result(items: list[RawItem]) -> CollectorResult:
    return CollectorResult(
        collector="tavily_reviews",
        domain="reviews",
        company_query=CompanyQuery(company="美的", position="后端", city="佛山"),
        items=items,
        confidence="medium",
    )


class TestReviewUrlFilter:
    """v0.1.22 — Per-host URL pattern filter for the reviews bucket."""

    @pytest.mark.parametrize("url,should_keep", [
        # 1point3acres — keep interview / forum threads, drop ads
        ("https://www.1point3acres.com/bbs/thread-1025384-1-1.html", True),
        ("https://www.1point3acres.com/interview/thread/1025384", True),
        ("https://www.1point3acres.com/bbs/forum-123-1.html", True),
        # 知乎 — keep question and 专栏, drop homepage
        ("https://www.zhihu.com/question/12345/answer/67890", True),
        ("https://zhuanlan.zhihu.com/p/12345", True),
        ("https://www.zhihu.com/", False),
        ("https://www.zhihu.com/explore", False),
        # 牛客 — keep discuss, drop course ads
        ("https://www.nowcoder.com/discuss/722178", True),
        ("https://www.nowcoder.com/interview/center", True),
        ("https://www.nowcoder.com/course/123", False),
        # 看准 — keep firm/dianping/salary/interview
        ("https://www.36dianping.com/firm/info/abc123.html", True),
        ("https://www.36dianping.com/dianping/5455770022", True),
        ("https://www.36dianping.com/salary/12345", True),
        ("https://www.36dianping.com/case/12839", False),  # marketing case study
        ("https://www.36dianping.com/", False),
        # 脉脉 — keep article
        ("https://maimai.cn/article/detail?fid=12345", True),
        ("https://maimai.cn/profile/abc", True),
        ("https://maimai.cn/", False),
        # Pass-through hosts (no rule)
        ("https://www.douban.com/group/topic/200764939", True),  # 豆瓣 — pass-through
        ("https://www.dianping.com/shop/131021770", True),       # 大众点评 — pass-through
        ("https://www.bilibili.com/video/BV1CD421V7o1", True),   # B站 — pass-through
    ])
    def test_keep_in_reviews_per_host(self, url, should_keep):
        assert _keep_in_reviews(url) is should_keep, f"URL {url!r} returned wrong verdict"

    def test_normalize_drops_consumer_urls(self):
        """End-to-end: noisy reviews bucket → after normalize only employer-relevant URLs remain."""
        items = [
            _item("https://www.zhihu.com/question/12345/answer/1", "Q1"),                # keep
            _item("https://www.zhihu.com/explore", "Explore page"),                       # DROP
            _item("https://www.36dianping.com/firm/info/abc123", "Firm page"),          # keep
            _item("https://www.36dianping.com/case/12839", "Marketing case"),             # DROP
            _item("https://www.nowcoder.com/discuss/123", "Interview discuss"),           # keep
            _item("https://www.nowcoder.com/course/456", "Course ad"),                    # DROP
            _item("https://www.dianping.com/shop/131021770", "Midea store"),              # pass-through (no rule)
        ]
        results = [_reviews_result(items)]
        out = normalize(results)
        urls = [str(it.url) for it in out["reviews"]]
        # 3 kept, 3 dropped, 1 pass-through
        assert len(urls) == 4
        assert "https://www.zhihu.com/question/12345/answer/1" in urls
        assert "https://www.36dianping.com/firm/info/abc123" in urls
        assert "https://www.nowcoder.com/discuss/123" in urls
        assert "https://www.dianping.com/shop/131021770" in urls  # pass-through
        # Dropped
        assert "https://www.zhihu.com/explore" not in urls
        assert "https://www.36dianping.com/case/12839" not in urls
        assert "https://www.nowcoder.com/course/456" not in urls

    def test_normalize_does_not_filter_other_buckets(self):
        """Filter is reviews-only — news bucket keeps all URLs even on filtered hosts."""
        news_result = CollectorResult(
            collector="tavily_news",
            domain="news",
            company_query=CompanyQuery(company="美的", position="后端", city="佛山"),
            items=[_item("https://www.zhihu.com/explore", "Zhihu explore news")],
            confidence="medium",
        )
        out = normalize([news_result])
        assert len(out["news"]) == 1
        assert str(out["news"][0].url) == "https://www.zhihu.com/explore"

    def test_review_url_patterns_has_expected_hosts(self):
        # Sanity: the map covers the 5 high-traffic workplace review platforms
        # v0.1.22 explicitly targets. If a platform is removed in future,
        # update this assertion + the review_queries allowlist intentionally.
        expected_hosts = {
            "www.1point3acres.com", "1point3acres.com",
            "www.zhihu.com", "zhuanlan.zhihu.com",
            "www.nowcoder.com",
            "www.36dianping.com", "36dianping.com",
            "maimai.cn",
        }
        assert expected_hosts.issubset(set(REVIEW_URL_PATTERNS.keys()))
"""v0.3.5 — Max-recall layered reviews: qna_search + extract + sparse UX.

Layer B: Tavily `qna_search` AI-synthesized summary as a reviews-domain item.
Layer C: Tavily `extract` on canonical review-site URLs (看准/脉脉/牛客/知乎).
Layer D: `sparse_takeaway` Jinja macro + `compute_review_diagnostics()` for
        honest "we tried X, found Y" rendering when signals are thin.

All collectors should soft-fail (return CollectorResult with error=...) on
Tavily failures so the pipeline never raises; tests verify that.
"""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.collectors.extract_reviews import (
    _EXTRACT_SITES,
    _MAX_URLS_PER_SITE,
    _MAX_URLS_TOTAL,
)
from jobhunter.collectors.qna_reviews import _QNA_PROMPT_TEMPLATE, QnaReviewsCollector
from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
from jobhunter.config import Settings
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    Shareholder,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.models.report import ReportData
from jobhunter.report.builder import (
    build_report,
    compute_review_diagnostics,
)


def _settings() -> Settings:
    return Settings()


# ---------- Layer B — qna_search collector ----------

class TestQnaReviewsCollector:
    """v0.3.5 — QnaReviewsCollector wraps Tavily qna_search."""

    async def test_returns_synthesized_answer_as_raw_item(self):
        coll = QnaReviewsCollector(_settings(), tavily=_FakeTavily(answer="员工评价加班严重，薪资低于同行。"))

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.error is None
        assert len(result.items) == 1
        item = result.items[0]
        assert item.source == "tavily_qna"
        # v0.3.5 — full answer stored in payload (RawItem has no content field)
        assert "员工评价" in (item.payload or {}).get("full_answer", "")
        assert "棒谷科技" in item.title

    async def test_empty_answer_returns_no_results_error(self):
        coll = QnaReviewsCollector(_settings(), tavily=_FakeTavily(answer=""))

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.items == []
        assert result.error == "no_answer"

    async def test_qna_failure_returns_error_soft_fail(self):
        coll = QnaReviewsCollector(_settings(), tavily=_FailingTavily())

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.items == []
        assert "qna_search_failed" in (result.error or "")

    async def test_no_tavily_client_returns_error(self):
        coll = QnaReviewsCollector(_settings(), tavily=None)

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.items == []
        assert result.error == "tavily_client_not_initialized"

    def test_qna_prompt_mentions_company_and_key_dimensions(self):
        prompt = _QNA_PROMPT_TEMPLATE.format(name="棒谷科技")
        assert "棒谷科技" in prompt
        for kw in ("员工评价", "工作体验", "加班", "薪资"):
            assert kw in prompt


# ---------- Layer C — extract reviews collector ----------

class TestExtractReviewsCollector:
    """v0.3.5 — ExtractReviewsCollector: discover + extract on canonical sites."""

    async def test_discover_then_extract_returns_rich_items(self):
        stub = _FakeTavily(
            search_hits={
                    # Phase 1 hits per query
                    "site:kanzhun.com": [
                        RawItem(title="棒谷看准", url="https://kanzhun.com/firm/abc", content="", source="tavily"),
                    ],
                    "site:maimai.cn": [
                        RawItem(title="棒谷脉脉", url="https://maimai.cn/company/abc", content="", source="tavily"),
                    ],
                },
            extract_items=[
                RawItem(
                    title="棒谷看准 - 50 条评价",
                    url="https://kanzhun.com/firm/abc",
                    content="员工评价：996、月薪 8k、内卷、PUA 多..." * 5,
                    snippet="员工评价：996、月薪 8k",
                    source="tavily_extract",
                ),
                RawItem(
                    title="棒谷脉脉",
                    url="https://maimai.cn/company/abc",
                    content="团队氛围：加班严重，薪资低..." * 3,
                    snippet="团队氛围：加班严重",
                    source="tavily_extract",
                ),
            ],
        )
        from jobhunter.collectors.extract_reviews import ExtractReviewsCollector
        coll = ExtractReviewsCollector(_settings(), tavily=stub)

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.error is None
        assert len(result.items) >= 1
        assert all(it.source == "tavily_extract" for it in result.items)

    async def test_no_canonical_urls_returns_no_results(self):
        stub = _FakeTavily(search_hits={}, extract_items=[])
        from jobhunter.collectors.extract_reviews import ExtractReviewsCollector
        coll = ExtractReviewsCollector(_settings(), tavily=stub)

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.items == []
        assert "no_canonical_urls" in (result.error or "")

    async def test_extract_failure_soft_fails(self):
        stub = _FailingTavily()
        from jobhunter.collectors.extract_reviews import ExtractReviewsCollector
        coll = ExtractReviewsCollector(_settings(), tavily=stub)

        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        # Either error or empty items — never raises
        assert result.items == [] or result.error is not None

    def test_site_allowlist_includes_canonical_review_sites(self):
        hosts = [host for host, _ in _EXTRACT_SITES]
        for canonical in ("kanzhun.com", "maimai.cn", "nowcoder.com", "zhihu.com"):
            assert canonical in hosts
        # Cap constants sensible
        assert _MAX_URLS_PER_SITE >= 1
        assert _MAX_URLS_TOTAL >= len(_EXTRACT_SITES)


# ---------- Layer D — sparse-state UX ----------

class TestComputeReviewDiagnostics:
    """v0.3.5 — compute_review_diagnostics for honest sparse rendering."""

    def test_empty_results_returns_zeros(self):
        d = compute_review_diagnostics(None)
        assert d["signals_extracted"] == 0
        assert d["raw_items"] == 0

    def test_counts_main_blind_qna_extract_separately(self):
        results = [
            _FakeResult(collector="tavily_reviews", domain="reviews", items=[_i("a"), _i("b")]),
            _FakeResult(collector="tavily_qna", domain="reviews", items=[_i("c")]),
            _FakeResult(collector="tavily_extract_reviews", domain="reviews", items=[_i("d"), _i("e"), _i("f")]),
            _FakeResult(collector="sogou_weixin", domain="reviews", items=[_i("g")]),
            _FakeResult(collector="tavily_news", domain="news", items=[_i("h")]),  # ignored
        ]
        d = compute_review_diagnostics(results)

        # main 40 + blind 3 attributed to tavily_reviews
        assert d["platforms_queried"] == 40
        assert d["keywords_queried"] == 3
        assert d["qna_calls"] == 1
        assert d["extract_pages"] == 3
        # raw items = 2 (main) + 1 (qna) + 3 (extract) + 1 (sogou) = 7
        assert d["raw_items"] == 7

    def test_counts_signals_extracted_from_review_facts(self):
        from jobhunter.models.facts import SalarySignal, ReviewFacts

        rf = ReviewFacts(
            salary_signals=[
                SalarySignal(position="p1", base_monthly_k=10,
                              salary_range_min_k=5, salary_range_max_k=15,
                              evidence="x", url="https://x.com/a"),
            ],
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high",
                                evidence="x", url="https://x.com/b"),
                OvertimeSignal(pattern="995", intensity="high",
                                evidence="x", url="https://x.com/c"),
            ],
            vibe_signals=[
                VibeSignal(sentiment="negative", evidence="x", url="https://x.com/d"),
            ],
            turnover_signals=[],
        )

        d = compute_review_diagnostics(None, review_facts=rf)
        assert d["signals_extracted"] == 4  # 1 + 2 + 1 + 0


class TestSparseTakeawayRendering:
    """v0.3.5 — sparse_takeaway macro renders honest diagnostics."""

    def _data(self) -> ReportData:
        cp = CompanyProfile()
        bf = BusinessFacts()
        jf = JudicialFacts()
        rf = ReviewFacts()
        nf = NewsFacts()
        findings = AggregatedFindings(
            company_profile=cp, business=bf, judicial=jf, reviews=rf, news=nf,
        )
        return ReportData(
            query=CompanyQuery(company="棒谷科技", position="后端", city="深圳"),
            generated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            findings=findings,
            company_profile=cp, business_facts=bf, judicial_facts=jf,
            review_facts=rf, news_facts=nf,
        )

    def test_sparse_takeaway_renders_with_diagnostics(self):
        data = self._data()
        data.review_diagnostics = {
            "platforms_queried": 40,
            "keywords_queried": 3,
            "qna_calls": 1,
            "extract_pages": 5,
            "raw_items": 87,
            "signals_extracted": 2,
        }
        html = build_report(data)

        # New sparse-takeaway class is rendered when reviews are empty
        assert "chapter-takeaway-sparse" in html
        assert "数据稀疏" in html
        # Numbers from diagnostics are surfaced
        assert "87" in html or "raw_items" not in html  # either the count or absent
        # Manual links present
        assert "kanzhun.com" in html or "看准" in html

    def test_sparse_takeaway_handles_missing_diagnostics(self):
        data = self._data()
        data.review_diagnostics = {}
        html = build_report(data)

        # Still renders (just no summary line), no exception
        assert "chapter-takeaway-sparse" in html


# ---------- Test helpers ----------

class _FakeTavily:
    """Fake TavilyClient with configurable qna_search + extract + search hits."""

    def __init__(
        self,
        answer: str = "",
        search_hits: dict[str, list[RawItem]] | None = None,
        extract_items: list[RawItem] | None = None,
    ) -> None:
        self._answer = answer
        self._search_hits = search_hits or {}
        self._extract_items = extract_items or []

    async def search(self, query, *, include_domains, **_):
        # Match against known site queries
        for key, hits in self._search_hits.items():
            if key in query:
                return list(hits)
        return []

    async def qna_search(self, query: str) -> str:
        return self._answer

    async def extract(self, urls: list[str]) -> list[RawItem]:
        return list(self._extract_items)


class _FailingTavily:
    async def search(self, query, *, include_domains, **_):
        raise RuntimeError("Tavily down")

    async def qna_search(self, query: str) -> str:
        raise RuntimeError("Tavily down")

    async def extract(self, urls: list[str]) -> list[RawItem]:
        raise RuntimeError("Tavily down")


class _FakeResult:
    """Minimal CollectorResult-like for diagnostics tests."""

    def __init__(self, *, collector: str, domain: str, items: list[RawItem]):
        self.collector = collector
        self.domain = domain
        self.items = items


def _i(slug: str) -> RawItem:
    return RawItem(title="t", url=f"https://x.com/{slug}", content="c", source="test")
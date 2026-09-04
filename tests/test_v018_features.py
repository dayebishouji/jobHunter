"""Tests for v0.1.18 — Reviews recall fix:

A. Two-pass review collection: pass-1 with allowlist (cheap), pass-2 without
   allowlist (broad recall) when pass-1 returns <3 hits. The 棒谷科技 report
   shipped with 0 review hits despite 6 pass-1 queries because Tavily can't
   deep-index UGC on xiaohongshu/maimai/zhihu — pass-2 trades ~3x credits
   for hitting content the strict allowlist would filter out.

B. Alias fallback in `_all_names`: when LLM alias generation fails or returns
   empty, fall back to local heuristic (Chinese corporate suffix strip +
   CamelCase split). 棒谷科技 → 棒谷科技, 棒谷 — UGC posts almost never use
   the legal name, so without this single fix pass-1 was querying a single
   useless string.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector, _dedup_by_url
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.search.query_templates import (
    _all_names,
    _local_name_variants,
    review_pass2_queries,
    review_queries,
)


# =============== B: alias fallback ===============

class TestLocalNameVariants:
    """v0.1.18 — Cheap local aliases when LLM returns empty."""

    def test_strips_chinese_tech_suffix(self):
        # The exact case from 棒谷科技 — without LLM aliases this was the
        # only name being queried, and 棒谷科技 has zero mentions in UGC.
        assert "棒谷" in _local_name_variants("棒谷科技")

    def test_strips_longest_suffix_first(self):
        # "科技股份有限公司" should be tried before "科技".
        variants = _local_name_variants("某公司科技股份有限公司")
        assert "某公司" in variants

    def test_keeps_short_names_intact(self):
        # Don't strip if it would leave <2 chars.
        assert _local_name_variants("字节") == []

    def test_no_suffix_to_strip_returns_empty(self):
        # "字节跳动" — no common corporate suffix, nothing to strip.
        assert _local_name_variants("字节跳动") == []

    def test_camelcase_split_english(self):
        # "AlibabaGroup" → "Alibaba"
        variants = _local_name_variants("AlibabaGroup")
        assert "Alibaba" in variants

    def test_camelcase_split_byte_dance(self):
        # "ByteDance" splits at the lowercase→uppercase boundary ("Byte|Dance");
        # we emit only the first chunk to bound variant count.
        variants = _local_name_variants("ByteDance")
        assert "Byte" in variants
        # Original "ByteDance" is NOT in variants — _all_names adds the
        # company field separately; this helper only emits *additional* names.
        assert "ByteDance" not in variants


class TestAllNamesFallback:
    """v0.1.18 — `_all_names` invokes heuristic when q.aliases is empty."""

    def test_includes_original_company(self):
        q = CompanyQuery(company="棒谷科技")
        names = _all_names(q)
        assert names[0] == "棒谷科技"

    def test_appends_stripped_when_no_aliases(self):
        # This is the bug: with empty aliases, previously only "棒谷科技"
        # was queried. Now 棒谷 is added.
        q = CompanyQuery(company="棒谷科技")
        names = _all_names(q)
        assert "棒谷" in names

    def test_no_heuristic_when_aliases_present(self):
        # If LLM gave aliases, don't pile on heuristic noise.
        q = CompanyQuery(company="棒谷科技", aliases=["Banggood"])
        names = _all_names(q)
        assert "棒谷" not in names  # LLM already supplied an alias
        assert "Banggood" in names

    def test_respects_max_n_cap(self):
        q = CompanyQuery(company="某科技股份有限公司", aliases=["某", "A", "B", "C"])
        names = _all_names(q, max_n=3)
        assert len(names) == 3


class TestReviewQueriesUseFallback:
    """v0.1.18 — `review_queries` benefits from the heuristic automatically."""

    def test_queries_include_stripped_name(self):
        # Without aliases the queries used to be all "棒谷科技 ..." — which
        # matches nothing in UGC. Now they include "棒谷 ..." forms too.
        q = CompanyQuery(company="棒谷科技")
        queries = review_queries(q)
        joined = " ".join(queries)
        assert "棒谷" in joined

    def test_queries_still_use_original(self):
        q = CompanyQuery(company="棒谷科技")
        queries = review_queries(q)
        joined = " ".join(queries)
        assert "棒谷科技" in joined


class TestReviewPass2Queries:
    """v0.1.18 — Pass-2 broad-recall queries (no allowlist)."""

    def test_emits_broad_recall_queries(self):
        q = CompanyQuery(company="棒谷科技")
        queries = review_pass2_queries(q)
        joined = " ".join(queries)
        # The three recall terms that surface UGC not in the allowlist.
        assert "知乎" in joined
        assert "小红书" in joined
        assert "体验" in joined

    def test_capped_at_max_n(self):
        q = CompanyQuery(company="棒谷科技", aliases=["Banggood"])
        queries = review_pass2_queries(q, max_n=2)
        assert len(queries) <= 2

    def test_uses_first_two_names(self):
        q = CompanyQuery(company="某科技", aliases=["SomeTech", "ST"])
        queries = review_pass2_queries(q)
        joined = " ".join(queries)
        assert "某科技" in joined  # primary name
        # 3 templates × 1 name = 3 queries (since we cap at max_n=2 but emit
        # templates until we hit the cap; with primary only, we get 3).

    def test_no_slang_in_pass2(self):
        # Pass-2 is for name-based broad recall, not slang.
        q = CompanyQuery(company="棒谷科技", slang_queries=["内卷", "996"])
        queries = review_pass2_queries(q)
        joined = " ".join(queries)
        assert "内卷" not in joined
        assert "996" not in joined


# =============== A: two-pass collector ===============

class TestDedupByUrl:
    """v0.1.18 — Merge pass-1 + pass-2 results without URL duplication."""

    def test_dedupes_same_url(self):
        a = RawItem(title="A", url="https://zhihu.com/q/1", content="x", source="test")
        b = RawItem(title="A duplicate", url="https://zhihu.com/q/1/", content="y", source="test")
        out = _dedup_by_url([a, b])
        assert len(out) == 1
        assert out[0].title == "A"  # first wins

    def test_keeps_distinct_urls(self):
        a = RawItem(title="A", url="https://zhihu.com/q/1", content="x", source="test")
        b = RawItem(title="B", url="https://maimai.cn/q/2", content="y", source="test")
        out = _dedup_by_url([a, b])
        assert len(out) == 2

    def test_empty_list(self):
        assert _dedup_by_url([]) == []


class _StubTavily:
    """In-memory Tavily stub — controllable per-query response map."""

    def __init__(self, response_map: dict[str, list[RawItem]]) -> None:
        self.response_map = response_map
        self.calls: list[tuple[str, list[str] | None]] = []

    async def search(self, q: str, *, include_domains=None, **_kwargs):
        self.calls.append((q, include_domains))
        return list(self.response_map.get(q, []))


def _q() -> CompanyQuery:
    return CompanyQuery(company="棒谷科技")


def _item(url: str, title: str = "T") -> RawItem:
    return RawItem(title=title, url=url, content="", source="test")


@pytest.mark.asyncio
class TestTwoPassReviews:
    """v0.1.18 — Pass-2 fires when pass-1 returns <3 hits."""

    async def test_pass1_sufficient_skips_pass2(self):
        # Pass-1 returns 5+ hits → pass-2 must NOT run (cost control).
        pass1_q = review_queries(_q())[0]
        tavily = _StubTavily({
            pass1_q: [_item(f"https://x.com/{i}") for i in range(5)],
        })
        coll = TavilyReviewsCollector(Settings(), tavily=tavily)
        result = await coll.collect(_q())

        assert len(result.items) == 5  # 5 from pass1
        # All calls should be pass-1 (with allowlist)
        assert all(c[1] is not None for c in tavily.calls)

    async def test_pass1_thin_triggers_pass2(self):
        # Pass-1 returns <3 hits → pass-2 must run.
        pass1_q = review_queries(_q())[0]
        # Use a pass-2-only query (small红书) to disambiguate from pass-1's
        # "知乎" / "体验" which overlap.
        pass2_q = review_pass2_queries(_q())[1]  # "棒谷科技" 小红书
        tavily = _StubTavily({
            pass1_q: [_item("https://x.com/only-one")],
            pass2_q: [_item("https://other-site.com/post1"),
                      _item("https://another.com/post2")],
        })
        coll = TavilyReviewsCollector(Settings(), tavily=tavily)
        result = await coll.collect(_q())

        assert len(result.items) == 3  # 1 from pass1 + 2 from pass2
        # Pass-2 calls should have include_domains=None
        pass2_calls = [c for c in tavily.calls if c[0] == pass2_q]
        assert len(pass2_calls) == 1
        assert pass2_calls[0][1] is None

    async def test_pass2_results_dedup_with_pass1(self):
        # Same URL appears in both passes — should appear once.
        pass1_q = review_queries(_q())[0]
        pass2_q = review_pass2_queries(_q())[0]
        shared_url = "https://x.com/shared"
        tavily = _StubTavily({
            pass1_q: [_item(shared_url, "from pass1")],
            pass2_q: [_item(shared_url, "from pass2")],
        })
        coll = TavilyReviewsCollector(Settings(), tavily=tavily)
        result = await coll.collect(_q())

        urls = [i.url for i in result.items]
        assert len(urls) == len(set(urls))  # dedup
        # First-wins keeps the pass1 instance
        assert result.items[0].title == "from pass1"

    async def test_both_passes_empty_returns_error(self):
        # Pass-1 empty + pass-2 empty → CollectorResult with error, no crash.
        tavily = _StubTavily({})
        coll = TavilyReviewsCollector(Settings(), tavily=tavily)
        result = await coll.collect(_q())
        assert result.items == []
        assert result.error == "no_results"

    async def test_pass1_exception_falls_through_to_pass2(self):
        # If pass-1 throws, pass-2 still runs (best-effort recall).
        class ExplodingTavily:
            def __init__(self):
                self.search = AsyncMock(side_effect=RuntimeError("network blip"))
        coll = TavilyReviewsCollector(Settings(), tavily=ExplodingTavily())
        # Pass-1 swallows the exception (logs warning), pass-2 also swallows.
        # Result: error captured but pipeline doesn't crash.
        result = await coll.collect(_q())
        assert result.items == []
        assert "network blip" in result.error
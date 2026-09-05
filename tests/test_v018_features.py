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
    """v0.1.18 — `review_queries` benefits from the heuristic automatically.
    v0.1.19 — Updated to extract text from (text, allowlist) tuples."""

    def test_queries_include_stripped_name(self):
        # Without aliases the queries used to be all "棒谷科技 ..." — which
        # matches nothing in UGC. Now they include "棒谷 ..." forms too.
        q = CompanyQuery(company="棒谷科技")
        queries = review_queries(q)
        texts = [t for t, _ in queries]
        assert '"棒谷"' in texts

    def test_queries_still_use_original(self):
        q = CompanyQuery(company="棒谷科技")
        queries = review_queries(q)
        texts = [t for t, _ in queries]
        assert '"棒谷科技"' in texts


class TestReviewPass2Queries:
    """v0.1.19 — review_pass2_queries is a deprecated stub."""

    def test_legacy_returns_empty(self):
        from jobhunter.search.query_templates import review_pass2_queries
        q = CompanyQuery(company="棒谷科技")
        assert review_pass2_queries(q) == []

    def test_no_broad_recall_keywords_anymore(self):
        # v0.1.19 — pure name-only; pass-2's old keywords removed.
        from jobhunter.search.query_templates import review_pass2_queries
        queries = review_pass2_queries(CompanyQuery(company="棒谷科技"))
        joined = " ".join(queries)
        assert "知乎" not in joined
        assert "小红书" not in joined
        assert "体验" not in joined


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
class TestV0119PerDomainQueries:
    """v0.1.19 — review_queries() returns (text, allowlist) pairs."""

    def test_returns_tuples_of_text_and_single_domain_allowlist(self):
        from jobhunter.models.query import CompanyQuery
        from jobhunter.search.query_templates import review_queries
        pairs = review_queries(CompanyQuery(company="棒谷科技"))
        # v0.1.22 hotfix — 20 GENERAL_REVIEW_DOMAINS × 2 names (primary +
        # heuristic-stripped) = 40 pairs. Empty position triggers the full
        # REVIEW_DOMAINS union path but only GENERAL is preserved by the cap.
        assert len(pairs) == 40
        for text, allowlist in pairs:
            assert isinstance(text, str)
            assert isinstance(allowlist, list)
            assert len(allowlist) == 1
            # Quote-wrapped name only
            assert text in ('"棒谷科技"', '"棒谷"')

    def test_no_keywords_in_text(self):
        from jobhunter.models.query import CompanyQuery
        from jobhunter.search.query_templates import review_queries
        pairs = review_queries(CompanyQuery(company="X"))
        texts = [t for t, _ in pairs]
        joined = " ".join(texts)
        # v0.1.19 strips all keyword suffixes
        for kw in ["加班", "离职率", "知乎", "体验", "脉脉", "看准", "避雷"]:
            assert kw not in joined

    def test_each_domain_appears_in_some_allowlist(self):
        from jobhunter.models.query import CompanyQuery
        from jobhunter.search.query_templates import (
            GENERAL_REVIEW_DOMAINS,
            MAX_DOMAINS_PER_RUN,
            review_queries,
        )
        pairs = review_queries(CompanyQuery(company="X"))
        seen_domains = set()
        for _, allowlist in pairs:
            seen_domains.update(allowlist)
        # v0.1.22 hotfix — GENERAL_REVIEW_DOMAINS are NEVER truncated by the
        # cap; only vertical extras are. So seen_domains may exceed
        # MAX_DOMAINS_PER_RUN as long as it stays ≤ GENERAL ∪ (a subset of
        # vertical extras).
        assert len(seen_domains) >= len(GENERAL_REVIEW_DOMAINS)

    def test_legacy_review_pass2_returns_empty(self):
        """v0.1.19 — review_pass2_queries is deprecated stub."""
        from jobhunter.models.query import CompanyQuery
        from jobhunter.search.query_templates import review_pass2_queries
        assert review_pass2_queries(CompanyQuery(company="X")) == []


class TestV0119CollectorOnePass:
    """v0.1.19 — tavily_reviews collector is single-pass now (no pass-2)."""

    async def test_iterates_pairs_with_per_domain_allowlist(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
        from jobhunter.config import Settings
        from jobhunter.models.query import CompanyQuery
        from jobhunter.models.raw import RawItem

        calls: list[tuple[str, list[str] | None]] = []

        class _Stub:
            async def search(self, q, *, include_domains=None, **_):
                calls.append((q, include_domains))
                return [RawItem(title="t", url=f"https://x.com/{len(calls)}", content="", source="test")]

        coll = TavilyReviewsCollector(Settings(), tavily=_Stub())
        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        # Every call gets exactly one domain in allowlist
        for _q, allowlist in calls:
            assert allowlist is not None
            assert len(allowlist) == 1
        # Got results back
        assert len(result.items) > 0

    async def test_no_pass2_fires_regardless_of_pass1_size(self):
        """v0.1.19 — single-pass design. Even if pass-1 returns 0, we don't
        run a separate 'broad' pass. v0.3.4 — adds a blind (no-allowlist)
        fallback of 3 calls when main loop yields 0; that layer is
        deliberately distinct from v0.1.18's keyword allowlist pass-2."""
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
        from jobhunter.config import Settings
        from jobhunter.models.query import CompanyQuery

        call_count = 0

        class _Stub:
            async def search(self, q, *, include_domains=None, **_):
                nonlocal call_count
                call_count += 1
                return []  # always empty

        coll = TavilyReviewsCollector(Settings(), tavily=_Stub())
        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        # v0.1.22 hotfix — 20 GENERAL_REVIEW_DOMAINS × 2 names = 40 main calls
        # v0.3.4 — +3 blind fallback calls (no allowlist) when main is empty
        assert call_count == 43
        assert result.items == []
        assert result.error == "no_results"

    async def test_dedupes_across_calls(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
        from jobhunter.config import Settings
        from jobhunter.models.query import CompanyQuery
        from jobhunter.models.raw import RawItem

        class _Stub:
            async def search(self, q, *, include_domains=None, **_):
                return [RawItem(title="t", url="https://shared.com/p/1", content="", source="test")]

        coll = TavilyReviewsCollector(Settings(), tavily=_Stub())
        result = await coll.collect(CompanyQuery(company="棒谷科技"))
        # Same URL from multiple queries → deduped to 1
        assert len(result.items) == 1

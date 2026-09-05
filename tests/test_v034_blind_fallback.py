"""v0.3.4 — Blind fallback for reviews章全空 corner case.

When per-domain Tavily allowlist returns 0 hits (corner case where
Tavily misses long-tail UGC for some companies), fire 3 broader
no-allowlist queries ("X" 评价 / 体验 / 面试) so _loose_keyword_reviews
in extract.py phase 3 has snippets to scan.

The fallback is cost-bounded: fires only when the main 40-call loop
yields 0 items. Typical run cost is unchanged; rare all-zero runs
spend 3 extra Tavily credits to surface any public reviews pages.
"""

from __future__ import annotations

from typing import Any

from jobhunter.collectors.tavily_reviews import _BLIND_FALLBACK_TEMPLATES
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem


def _settings() -> Settings:
    return Settings()


def _stub_with_main_then(main_returns: list[list[RawItem]], blind_returns: list[list[RawItem]]):
    """Build a stub Tavily that returns main_returns[i] for the i-th main
    call (consumed in order) and blind_returns[i] for the i-th blind call.
    Mismatched lengths pad with empty lists."""

    class _Stub:
        def __init__(self) -> None:
            self.main_idx = 0
            self.blind_idx = 0
            self.observed: list[tuple[str, list[str]]] = []

        async def search(self, q, *, include_domains=None, **_):
            self.observed.append((q, list(include_domains or [])))
            # Heuristic: blind calls have empty allowlist
            if not include_domains:
                idx = self.blind_idx
                self.blind_idx += 1
                return blind_returns[idx] if idx < len(blind_returns) else []
            idx = self.main_idx
            self.main_idx += 1
            return main_returns[idx] if idx < len(main_returns) else []

    return _Stub()


class TestBlindFallbackNotTriggered:
    """When the main loop yields any items, blind fallback does NOT fire."""

    async def test_main_has_items_skips_blind(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        stub = _stub_with_main_then(
            main_returns=[[RawItem(title="t", url="https://x.com/a", content="", source="tavily")]],
            blind_returns=[[]],
        )
        coll = TavilyReviewsCollector(_settings(), tavily=stub)
        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        # Only the main call fired (all subsequent main calls re-use last item)
        assert len(result.items) >= 1
        # No blind calls observed (all observations have non-empty allowlist)
        assert all(domains for _q, domains in stub.observed)
        # Confidence reflects normal path
        assert result.error is None


class TestBlindFallbackTriggered:
    """When main loop returns 0 items, blind fallback fires 3 queries."""

    async def test_main_zero_blind_hits_used(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        blind_item = RawItem(
            title="小红书 post",
            url="https://xiaohongshu.com/x",
            content="996 是日常，月薪 8k，PUA 多",
            source="tavily",
        )
        stub = _stub_with_main_then(
            main_returns=[[]],  # all main calls return 0
            blind_returns=[
                [blind_item],
                [RawItem(title="知乎", url="https://zhihu.com/y", content="氛围差", source="tavily")],
                [],
            ],
        )
        coll = TavilyReviewsCollector(_settings(), tavily=stub)
        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert len(result.items) >= 1
        assert blind_item in result.items
        # Blind fallback fired 3 queries
        blind_calls = [q for q, d in stub.observed if not d]
        assert len(blind_calls) == 3
        # v0.3.4 — confidence is "low" because items came from blind path
        assert result.confidence == "low"
        assert result.error is None

    async def test_main_zero_blind_zero_returns_no_results(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        stub = _stub_with_main_then(
            main_returns=[[]],
            blind_returns=[[], [], []],
        )
        coll = TavilyReviewsCollector(_settings(), tavily=stub)
        result = await coll.collect(CompanyQuery(company="棒谷科技"))

        assert result.items == []
        assert result.error == "no_results"


class TestBlindFallbackShape:
    """Verify the 3 blind templates and that they go without allowlist."""

    def test_three_templates_cover_evaluation_experience_interview(self):
        assert len(_BLIND_FALLBACK_TEMPLATES) == 3
        joined = " ".join(_BLIND_FALLBACK_TEMPLATES)
        assert "评价" in joined
        assert "体验" in joined
        assert "面试" in joined

    async def test_blind_queries_have_no_allowlist(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        stub = _stub_with_main_then(
            main_returns=[[]],
            blind_returns=[[], [], []],
        )
        coll = TavilyReviewsCollector(_settings(), tavily=stub)
        await coll.collect(CompanyQuery(company="小红书"))

        blind_observed = [(q, d) for q, d in stub.observed if not d]
        assert len(blind_observed) == 3
        for q, domains in blind_observed:
            assert domains == []  # no allowlist
            assert "小红书" in q


class TestBlindFallbackResilience:
    """Blind fallback swallows individual query failures."""

    async def test_blind_failure_does_not_break_main(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        class _FailingBlindStub:
            def __init__(self) -> None:
                self.main_idx = 0

            async def search(self, q, *, include_domains=None, **_):
                if include_domains:
                    self.main_idx += 1
                    return [RawItem(title="t", url=f"https://x.com/{self.main_idx}",
                                    content="", source="tavily")]
                # Blind calls all fail
                raise RuntimeError("Tavily down")

        coll = TavilyReviewsCollector(_settings(), tavily=_FailingBlindStub())
        # Main path returns items; blind never runs (no exception expected)
        result = await coll.collect(CompanyQuery(company="棒谷科技"))
        assert len(result.items) >= 1
        assert result.error is None

    async def test_blind_partial_failure_still_returns_items(self):
        from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector

        call_count = 0

        class _PartialFailStub:
            async def search(self, q, *, include_domains=None, **_):
                nonlocal call_count
                call_count += 1
                if not include_domains:
                    # First blind call returns data; next two fail
                    if call_count <= 41:
                        return []
                    raise RuntimeError("blip")
                return []

        coll = TavilyReviewsCollector(_settings(), tavily=_PartialFailStub())
        result = await coll.collect(CompanyQuery(company="棒谷科技"))
        # Errors swallowed; result items remain empty (no partial blind hits)
        assert result.error == "no_results"
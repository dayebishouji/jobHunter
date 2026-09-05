"""Tavily-backed collector for employee reviews."""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.search.query_templates import review_queries
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


def _dedup_by_url(items: list[RawItem]) -> list[RawItem]:
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        # pydantic HttpUrl is not a str; coerce via str() then normalize trailing slash
        u = str(it.url or "").strip().rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append(it)
        elif not u:
            # No URL — keep once
            out.append(it)
    return out


# v0.3.4 — Blind fallback queries when per-domain allowlist returns 0 hits.
# Used only when the main loop produces an empty bucket, so the per-call cost
# is bounded to ~3 Tavily credits in the rare all-zero corner case.
_BLIND_FALLBACK_TEMPLATES = (
    '"{name}" 评价',
    '"{name}" 体验',
    '"{name}" 面试',
)


class TavilyReviewsCollector(BaseCollector):
    name = "tavily_reviews"
    domain = "reviews"

    def __init__(self, settings: Settings, *, tavily: TavilyClient) -> None:
        super().__init__(settings, tavily=tavily)

    async def _blind_fallback(self, query: CompanyQuery) -> list[RawItem]:
        """v0.3.4 — Fire 3 broader (no-allowlist) Tavily queries to surface
        long-tail UGC that per-domain search misses (e.g. 小红书/知乎/贴吧
        posts that Tavily's per-domain recall returns 0 on).

        Items returned here land in the same `by_domain["reviews"]` bucket
        and feed `_loose_keyword_reviews()` in extract.py phase 3, so even a
        few keyword-bearing snippets can light up overtime / vibe / salary /
        turnover signals.

        Cost: at most 3 Tavily calls, only when the main loop yields 0.
        """
        items: list[RawItem] = []
        for tmpl in _BLIND_FALLBACK_TEMPLATES:
            q_text = tmpl.format(name=query.company)
            try:
                items.extend(await self._tavily.search(q_text, include_domains=[]))
            except Exception as e:  # noqa: BLE001
                logger.warning("reviews blind fallback failed: %s | %s", q_text, e)
        return _dedup_by_url(items)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        """v0.1.19 — Pure name-only UGC recall.

        Iterates `(query_text, allowlist)` pairs from `review_queries()`.
        Each pair is a single Tavily call with that ONE domain as allowlist.
        No keywords — LLM extraction step does the semantic classification.

        Up to 30 queries per company (15 domains × 2 names). About the same
        cost as v0.1.18's 2-pass (24+3) but with broader recall.

        v0.3.4 — When per-domain recall returns 0 hits, fire 3 blind (no-
        allowlist) fallback queries so _loose_keyword_reviews() can still
        scan snippets for keywords (996 / 月薪 / PUA / 氛围). Cost: bounded
        to ~3 Tavily credits in the rare all-zero corner case.
        """
        if self._tavily is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="tavily_client_not_initialized",
            )
        items: list[RawItem] = []
        errors: list[str] = []

        for q_text, allowlist in review_queries(query):
            try:
                items.extend(
                    await self._tavily.search(q_text, include_domains=allowlist)
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("reviews query failed: %s | %s", q_text, e)
                errors.append(f"{q_text}: {e}")

        items = _dedup_by_url(items)

        # v0.3.5 — blind fallback now ALWAYS fires (gate dropped). The 3
        # broader keyword queries (评价/体验/面试) catch long-tail UGC that
        # the per-domain allowlist misses. Cost: +3 Tavily credits / run.
        blind_used = False
        blind = await self._blind_fallback(query)
        if blind:
            blind_used = True
            # Merge main + blind (dedup by URL)
            seen = {str(it.url or "").rstrip("/") for it in items}
            for it in blind:
                u = str(it.url or "").rstrip("/")
                if u not in seen:
                    items.append(it)
                    seen.add(u)

        if not items:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error=("; ".join(errors) if errors else "no_results"),
            )
        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            items=items,
            confidence="low" if blind_used and len(items) < 5 else ("medium" if len(items) >= 5 else "low"),
        )

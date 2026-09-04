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


class TavilyReviewsCollector(BaseCollector):
    name = "tavily_reviews"
    domain = "reviews"

    def __init__(self, settings: Settings, *, tavily: TavilyClient) -> None:
        super().__init__(settings, tavily=tavily)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        """v0.1.19 — Pure name-only UGC recall.

        Iterates `(query_text, allowlist)` pairs from `review_queries()`.
        Each pair is a single Tavily call with that ONE domain as allowlist.
        No keywords — LLM extraction step does the semantic classification.

        Up to 30 queries per company (15 domains × 2 names). About the same
        cost as v0.1.18's 2-pass (24+3) but with broader recall.
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
            confidence="medium" if len(items) >= 5 else "low",
        )

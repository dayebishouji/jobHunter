"""Tavily-backed collector for employee reviews."""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.search.query_templates import domains_for_position, review_queries
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


class TavilyReviewsCollector(BaseCollector):
    name = "tavily_reviews"
    domain = "reviews"

    def __init__(self, settings: Settings, *, tavily: TavilyClient) -> None:
        super().__init__(settings, tavily=tavily)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        if self._tavily is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="tavily_client_not_initialized",
            )
        items = []
        errors: list[str] = []
        # Cost-control: when the user supplied a recognized industry position
        # (e.g. "后端", "医生", "跨境运营"), restrict Tavily's allowlist to the
        # relevant verticals instead of querying all 24 domains. Empty /
        # unrecognized positions fall back to the full REVIEW_DOMAINS union.
        allowlist = domains_for_position(query.position)
        for q_text in review_queries(query):
            try:
                items.extend(
                    await self._tavily.search(q_text, include_domains=allowlist)
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("reviews query failed: %s | %s", q_text, e)
                errors.append(f"{q_text}: {e}")
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

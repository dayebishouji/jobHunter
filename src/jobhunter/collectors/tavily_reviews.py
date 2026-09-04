"""Tavily-backed collector for employee reviews."""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.search.query_templates import (
    domains_for_position,
    review_pass2_queries,
    review_queries,
)
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


# v0.1.18 — Threshold below which we run pass-2 (broad recall, no allowlist).
# Tuned from the 棒谷科技 report which returned 0 hits on pass-1 with the full
# 46-domain allowlist because UGC on xiaohongshu/maimai/zhihu isn't in Tavily's
# deep index. Pass-2 trades ~3x credits per query for hitting content that the
# strict allowlist filters away.
PASS2_TRIGGER_THRESHOLD = 3


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
        if self._tavily is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="tavily_client_not_initialized",
            )
        items: list[RawItem] = []
        errors: list[str] = []

        # Cost-control: when the user supplied a recognized industry position
        # (e.g. "后端", "医生", "跨境运营"), restrict Tavily's allowlist to the
        # relevant verticals instead of querying all 24 domains. Empty /
        # unrecognized positions fall back to the full REVIEW_DOMAINS union.
        allowlist = domains_for_position(query.position)

        # ---- Pass 1: targeted queries with allowlist (cheap, bounded) ----
        for q_text in review_queries(query):
            try:
                items.extend(
                    await self._tavily.search(q_text, include_domains=allowlist)
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("reviews pass1 failed: %s | %s", q_text, e)
                errors.append(f"{q_text}: {e}")

        # ---- Pass 2: broad recall, no allowlist — only if pass-1 was thin ----
        # Trigger when pass-1 returned fewer than the threshold (i.e. UGC recall
        # is broken). Pass-2 cost is bounded by `review_pass2_queries` (capped).
        if len(items) < PASS2_TRIGGER_THRESHOLD:
            logger.info(
                "reviews pass1 thin (%d items) — running pass2 without allowlist",
                len(items),
            )
            for q_text in review_pass2_queries(query):
                try:
                    items.extend(
                        await self._tavily.search(q_text, include_domains=None)
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("reviews pass2 failed: %s | %s", q_text, e)
                    errors.append(f"pass2 {q_text}: {e}")

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

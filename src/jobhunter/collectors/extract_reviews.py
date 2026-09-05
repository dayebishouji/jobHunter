"""v0.3.5 — Tavily extract reviews collector.

Two-phase:
1. Search 4 canonical review sites for the company page URL.
2. Extract full markdown of the top 1-2 URLs per site (max 6 total).

Output: RawItems with the full review-page content in `content`,
source = `tavily_extract`, domain = `reviews`. These pages typically
hold 30-200 employee reviews each and have high signal density, but
Tavily's per-domain search sometimes misses them — direct extract
sidesteps that.

Cost: 4 search + up to 6 extract = ~10 Tavily credits per run when
all sites have a canonical company page. Cache + deduplicate by URL
so repeat runs within the TTL are zero-cost.
"""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


# Site allowlist + URL pattern for canonical company review pages.
_EXTRACT_SITES: list[tuple[str, str]] = [
    ("kanzhun.com", "site:kanzhun.com"),
    ("maimai.cn", "site:maimai.cn"),
    ("nowcoder.com", "site:nowcoder.com"),
    ("zhihu.com", "site:zhihu.com"),
]
_MAX_URLS_PER_SITE = 2
_MAX_URLS_TOTAL = 6


class ExtractReviewsCollector(BaseCollector):
    name = "tavily_extract_reviews"
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

        # Phase 1 — discover canonical review-page URLs
        candidate_urls: list[str] = []
        per_site: dict[str, list[str]] = {}
        errors: list[str] = []

        for host, site_query in _EXTRACT_SITES:
            q = f'{site_query} "{query.company}"'
            try:
                hits = await self._tavily.search(q, include_domains=[host])
            except Exception as e:  # noqa: BLE001
                logger.warning("extract discover failed: %s | %s", q, e)
                errors.append(f"{q}: {e}")
                continue
            urls: list[str] = []
            for it in hits:
                u = str(it.url or "").strip()
                if u and u not in per_site.get(host, []):
                    urls.append(u)
                    per_site.setdefault(host, []).append(u)
                if len(urls) >= _MAX_URLS_PER_SITE:
                    break
            candidate_urls.extend(urls)

        # Trim to total cap, preserving per-site diversity
        candidate_urls = candidate_urls[:_MAX_URLS_TOTAL]

        if not candidate_urls:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error=("; ".join(errors) if errors else "no_canonical_urls"),
            )

        # Phase 2 — extract full content from the URLs
        try:
            items = await self._tavily.extract(candidate_urls)
        except Exception as e:  # noqa: BLE001
            logger.warning("extract failed: %s | urls=%s", e, candidate_urls[:3])
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error=f"extract_failed: {e}",
            )

        if not items:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error="extract_returned_empty",
            )

        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            items=items,
            confidence="high" if len(items) >= 2 else "medium",
        )
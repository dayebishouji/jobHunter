"""Tavily search client — async, cached, rate-limited."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from tavily import AsyncTavilyClient

from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.search.cache import FileCache

logger = logging.getLogger(__name__)


class TavilyClient:
    """Async wrapper around AsyncTavilyClient with cache + token-bucket rate limit."""

    def __init__(self, settings: Settings, cache: FileCache) -> None:
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY is required")
        self._settings = settings
        self._cache = cache
        self._client = AsyncTavilyClient(api_key=settings.tavily_api_key)
        self._bucket = asyncio.Semaphore(1)
        self._last_request_at = 0.0

    def _cache_key(self, query: str, domains: list[str], depth: str, max_results: int, days: int | None) -> str:
        return "|".join(
            [
                "tavily",
                depth,
                str(max_results),
                days is not None and str(days) or "*",
                ",".join(sorted(domains)),
                query.strip(),
            ]
        )

    async def _throttle(self) -> None:
        """Token-bucket: ensure >= 1/rate seconds between calls."""
        async with self._bucket:
            now = asyncio.get_event_loop().time()
            wait = (1.0 / self._settings.tavily_rate_per_sec) - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = asyncio.get_event_loop().time()

    async def search(
        self,
        query: str,
        *,
        include_domains: list[str],
        search_depth: str | None = None,
        max_results: int | None = None,
        days: int | None = None,
    ) -> list[RawItem]:
        """Execute one Tavily search; return a list of RawItem (possibly empty)."""
        depth = search_depth or self._settings.tavily_search_depth
        maxr = max_results or self._settings.tavily_max_results
        key = self._cache_key(query, include_domains, depth, maxr, days)

        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Tavily cache hit: %s", query)
            return [RawItem.model_validate(item) for item in cached]

        await self._throttle()
        try:
            params: dict[str, Any] = {
                "query": query,
                "include_domains": include_domains,
                "search_depth": depth,
                "max_results": maxr,
            }
            if days is not None:
                params["days"] = days
            raw = await self._client.search(**params)
        except Exception as e:  # noqa: BLE001 - we want to surface anything
            logger.warning("Tavily search failed: %s | query=%s", e, query)
            raise

        results: list[RawItem] = []
        for item in raw.get("results", []):
            try:
                results.append(
                    RawItem(
                        source=f"tavily:{item.get('source', 'web')}",
                        url=item["url"],
                        title=item.get("title", ""),
                        snippet=item.get("content", "")[:1000],
                        published_at=_parse_date(item.get("published_date")),
                        retrieved_at=datetime.now(timezone.utc),
                        payload={"score": item.get("score")},
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("Skipping malformed Tavily result: %s", e)
                continue

        # Cache even zero-result to avoid re-querying empty queries
        self._cache.set(
            key,
            [json.loads(r.model_dump_json()) for r in results],
            ttl_seconds=self._settings.cache_ttl_hours * 3600,
        )
        return results

    async def qna_search(self, query: str) -> str:
        """v0.3.5 — Tavily qna_search: AI-synthesized answer from public web.

        Returns the answer as a plain string. Caller is responsible for
        packaging it as a RawItem (with `tavily_qna` source so the LLM
        extract step treats it differently from search snippets).
        No cache here — qna answers are short, and Tavily's own caching
        is per-API-call.
        """
        await self._throttle()
        try:
            result = await self._client.qna_search(query=query)
        except Exception as e:  # noqa: BLE001
            logger.warning("Tavily qna_search failed: %s | query=%s", e, query)
            raise
        answer = (result.get("answer") or "").strip()
        return answer

    async def extract(self, urls: list[str]) -> list[RawItem]:
        """v0.3.5 — Tavily extract: fetch full markdown of given URLs.

        Used by the extract-reviews collector to grab canonical review
        pages on 看准 / 脉脉 / 牛客 / 知乎 etc. Returns one RawItem per
        successful URL with the full content in `content` field.
        """
        if not urls:
            return []
        await self._throttle()
        try:
            result = await self._client.extract(urls=urls)
        except Exception as e:  # noqa: BLE001
            logger.warning("Tavily extract failed: %s | urls=%s", e, urls[:3])
            raise
        items: list[RawItem] = []
        for r in result.get("results", []) or []:
            url = r.get("url") or ""
            raw = (r.get("raw_content") or "").strip()
            if not url or not raw:
                continue
            try:
                items.append(
                    RawItem(
                        source="tavily_extract",
                        url=url,
                        title=(r.get("title") or "")[:200],
                        snippet=raw[:1500],
                        retrieved_at=datetime.now(timezone.utc),
                        payload={"full_content": raw[:5000]},
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("Skipping malformed Tavily extract result: %s", e)
                continue
        return items


def _parse_date(s: str | None) -> datetime | None:
    """Best-effort date parse — Tavily date strings are loose."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None

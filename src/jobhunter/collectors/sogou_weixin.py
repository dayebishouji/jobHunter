"""Sogou WeChat search collector (direct HTTP).

v0.1.20 — Adds 微信公众号 full-text index as a reviews-domain source.
Tavily indexes 小红书 / 知乎 UGC poorly; Sogou WeChat is the most authoritative
Chinese-language UGC signal we can reach without login. Cost-bounded: ≤3
queries per run, 24h cache, random 2-5s throttle. Soft-fails when anti-bot
challenges the request — the report renders a small banner suggesting manual
核查 at weixin.sogou.com.

Direct HTTP scraping has legal/ToS risk (Sogou forbids bots). Treat as best-
effort: if the IP gets blocked, set JOBHUNTER_SOGOU_WEIXIN_ENABLED=false in
.env to disable permanently.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.search.cache import FileCache
from jobhunter.search.query_templates import _all_names

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Substrings that, when present in the response body, indicate Sogou served
# its JS anti-bot challenge instead of search results. Sogou has changed its
# challenge wording a few times; these are the stable markers as of 2025-09.
_BLOCK_INDICATORS: tuple[str, ...] = (
    "antispider",
    "请输入验证码",
    "verify",
    "您的访问过于频繁",
)

# Minimum reasonable body length for a real results page (with multiple
# news-list entries). Anti-bot stubs and transport errors are typically
# < 500 chars; real Sogou result pages are 5KB+.
_MIN_BODY_LEN = 500

# How many names (primary + aliases) to actually query this run. With 24h
# cache the cost is amortized across reruns; bound for safety.
_PER_RUN_QUERY_LIMIT = 3


class SogouWeixinCollector(BaseCollector):
    """Scrape `weixin.sogou.com` for 微信公众号 articles about the company.

    Domain: reviews — items land in the same bucket as Tavily reviews,
    feeding the existing LLM extract step without any prompt change.
    """

    name: ClassVar[str] = "sogou_weixin"
    domain: ClassVar[str] = "reviews"
    BASE_URL: ClassVar[str] = "https://weixin.sogou.com/weixin"
    CACHE_TTL_SECONDS: ClassVar[int] = 24 * 60 * 60  # 24h

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient,
        cache: FileCache,
    ) -> None:
        super().__init__(settings, http=http)
        self._cache = cache
        # Track the most recent throttle interval so tests can assert on it.
        self._last_throttle_sec: float = 0.0

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        if self._http is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="http_client_not_initialized",
            )

        # Honor user kill switch (.env: SOGOU_WEIXIN_ENABLED=false)
        if not getattr(self._settings, "sogou_weixin_enabled", True):
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="disabled_by_setting",
            )

        names = _all_names(query, max_n=_PER_RUN_QUERY_LIMIT)
        items: list[RawItem] = []
        errors: list[str] = []
        blocked = False

        for name in names:
            await self._throttle()
            cache_key = f"sogou_weixin|{name}"
            cached = self._cache.get(cache_key)
            if cached:
                items.extend(self._deserialize_items(cached))
                continue

            try:
                html = await self._fetch_search(name)
            except Exception as e:  # noqa: BLE001
                logger.warning("sogou_weixin fetch failed: %s | %r", name, e)
                errors.append(f"{name}: {type(e).__name__}: {e}")
                continue

            if self._is_blocked(html):
                logger.warning("sogou_weixin anti-bot triggered for %s", name)
                blocked = True
                break  # Don't waste further queries once blocked.

            parsed = self._parse_results(name, html)
            if parsed:
                self._cache.set(cache_key, self._serialize_items(parsed), self.CACHE_TTL_SECONDS)
            items.extend(parsed)

        items = _dedup_by_url(items)
        items = items[:30]  # hard cap to prevent cache blowup + LLM context bloat

        if blocked:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=items,
                error="anti_bot_redirect",
                confidence="none",
            )
        if not items:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error=("; ".join(errors) if errors else "no_results"),
                confidence="low",
            )
        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            items=items,
            confidence="medium" if len(items) >= 3 else "low",
        )

    # ------------------------------------------------------------------
    # Throttle + HTTP
    # ------------------------------------------------------------------

    async def _throttle(self) -> None:
        """Sleep a random interval between [min, max] seconds.

        Defaults: 2-5s per request. Tunable via settings.
        """
        lo = getattr(self._settings, "sogou_weixin_min_interval", 2.0)
        hi = getattr(self._settings, "sogou_weixin_max_interval", 5.0)
        # lo ≤ hi, but guard against misconfiguration.
        interval = random.uniform(min(lo, hi), max(lo, hi))
        self._last_throttle_sec = interval
        await asyncio.sleep(interval)

    async def _fetch_search(self, name: str) -> str:
        url = f"{self.BASE_URL}?type=2&query={quote(name)}&ie=utf8"
        # Referer helps avoid the immediate anti-bot bounce that requests
        # without a Referer sometimes get.
        resp = await self._http.get(
            url,
            headers={"Referer": "https://weixin.sogou.com/"},
            follow_redirects=True,
        )
        # Force UTF-8 decode — Sogou sometimes returns GBK.
        if resp.encoding and resp.encoding.lower() not in ("utf-8", "utf8"):
            resp.encoding = resp.encoding  # use detected
        return resp.text

    # ------------------------------------------------------------------
    # Anti-bot detection
    # ------------------------------------------------------------------

    def _is_blocked(self, body: str) -> bool:
        if not body:
            return True
        if len(body) < _MIN_BODY_LEN:
            return True
        low = body.lower()
        return any(ind.lower() in low for ind in _BLOCK_INDICATORS)

    # ------------------------------------------------------------------
    # Parse HTML → RawItems
    # ------------------------------------------------------------------

    def _parse_results(self, name: str, html: str) -> list[RawItem]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:  # noqa: BLE001
            logger.warning("sogou_weixin parse failed: %r", e)
            return []

        items: list[RawItem] = []

        # Sogou has used two markup shapes over the years. Try both, dedup at end.
        # (a) Modern: each article is in <div class="news-list"> or <li class="news-list-li">
        # (b) Older: <div class="txt-box"> with title anchor + snippet
        for block in soup.select("div.news-list li, li.news-list-li, div.news-list"):
            title_anchor = block.select_one("h3 a, a[uigs], a")
            if not title_anchor:
                continue
            url = title_anchor.get("href") or ""
            title = title_anchor.get_text(strip=True)
            snippet_el = block.select_one("p.txt, p[class*='txt']")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if not url or not title:
                continue
            if "mp.weixin.qq.com" not in url and "weixin.sogou.com" not in url:
                # We only want actual 公众号 article links (mp.weixin.qq.com)
                # or relative Sogou redirects to them.
                continue
            try:
                items.append(
                    RawItem(
                        source="sogou_weixin:article",
                        url=url,
                        title=title[:200],
                        snippet=snippet[:1000],
                        payload={"query_name": name},
                    )
                )
            except Exception as e:  # noqa: BLE001 — pydantic validation failures
                logger.debug("sogou_weixin dropped malformed item: %r", e)
                continue

        return items

    # ------------------------------------------------------------------
    # Cache serialization (RawItem not JSON-native — HttpUrl, datetime)
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_items(items: list[RawItem]) -> list[dict]:
        return [
            {
                "source": it.source,
                "url": str(it.url),
                "title": it.title,
                "snippet": it.snippet,
                "published_at": (
                    it.published_at.isoformat() if it.published_at else None
                ),
                "payload": dict(it.payload or {}),
            }
            for it in items
        ]

    @staticmethod
    def _deserialize_items(blobs: list[dict]) -> list[RawItem]:
        from datetime import datetime

        out: list[RawItem] = []
        for b in blobs or []:
            try:
                pub = b.get("published_at")
                if isinstance(pub, str):
                    try:
                        pub_dt = datetime.fromisoformat(pub)
                    except ValueError:
                        pub_dt = None
                else:
                    pub_dt = None
                out.append(
                    RawItem(
                        source=b.get("source", "sogou_weixin:article"),
                        url=b["url"],
                        title=b.get("title", ""),
                        snippet=b.get("snippet", ""),
                        published_at=pub_dt,
                        payload=dict(b.get("payload") or {}),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return out


def _dedup_by_url(items: list[RawItem]) -> list[RawItem]:
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        u = str(it.url or "").strip().rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append(it)
        elif not u:
            out.append(it)
    return out

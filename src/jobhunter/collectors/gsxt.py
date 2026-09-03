"""GSXT collector — best-effort.

The official site (gsxt.gov.cn) is geo-restricted and aggressively anti-bot.
v0.1 only does a probe; if reachable, we record that and emit a soft result,
leaving actual table parsing to a future version.
"""

from __future__ import annotations

import httpx

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult

GSXT_HOME = "https://www.gsxt.gov.cn/index.html"


class GSXTCollector(BaseCollector):
    name = "gsxt"
    domain = "business"

    def __init__(self, settings: Settings, *, http: httpx.AsyncClient) -> None:
        super().__init__(settings, http=http)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        if self._http is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="http_client_not_initialized",
            )
        try:
            r = await self._http.get(GSXT_HOME, timeout=15.0)
        except httpx.HTTPError as e:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error=f"gsxt_unreachable: {e}",
            )

        if r.status_code in (403, 503, 521):
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error=f"gsxt_blocked_status_{r.status_code}",
            )

        # v0.1: we do NOT attempt full table parsing. The goal is presence-only.
        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            items=[],
            confidence="low",
            error="gsxt_reachable_but_parsing_not_implemented_v0.1",
        )

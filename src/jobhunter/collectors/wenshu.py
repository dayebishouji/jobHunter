"""Wenshu (裁判文书网) collector — v0.1 stub.

Wenshu's V5 API uses dynamic cookies + slider captcha. Direct scraping is
out of scope for v0.1; the collector returns a soft-fail that the report
renders as "请人工到裁判文书网/执行信息公开网核查" + a manual-link note.
"""

from __future__ import annotations

import httpx

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult


class WenshuCollector(BaseCollector):
    name = "wenshu"
    domain = "judicial"

    def __init__(self, settings: Settings, *, http: httpx.AsyncClient) -> None:
        super().__init__(settings, http=http)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        if not query.include_judicial:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="judicial_disabled_by_user",
            )

        # Best-effort home probe — purely for transparency.
        if self._http is not None:
            try:
                r = await self._http.get("https://wenshu.court.gov.cn/", timeout=10.0)
                if r.status_code >= 400:
                    return CollectorResult(
                        collector=self.name,
                        domain=self.domain,
                        company_query=query,
                        error=f"wenshu_unreachable_status_{r.status_code}",
                    )
            except httpx.HTTPError:
                # fall through to stub
                pass

        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            error="wenshu_blocked_v0.1_stub_see_report_for_manual_check_links",
        )

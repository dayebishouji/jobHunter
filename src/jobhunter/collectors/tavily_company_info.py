"""Tavily-backed collector for company profile data (主营业务 / 产品 / 融资 / 规模).

Sources: 百度百科 / 搜狗百科 (encyclopedia), IT桔子 / 创业邦 / 投资界 (startup
databases), plus qcc / tianyancha aggregator pages. We do NOT scrape the
official website directly — Tavily snippets from the encyclopedia typically
mention the official URL, which is extracted downstream as a field.
"""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.search.query_templates import COMPANY_INFO_DOMAINS, company_info_queries
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


class TavilyCompanyInfoCollector(BaseCollector):
    name = "tavily_company_info"
    domain = "company_info"

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
        for q_text in company_info_queries(query):
            try:
                items.extend(
                    await self._tavily.search(
                        q_text,
                        include_domains=COMPANY_INFO_DOMAINS,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("company_info query failed: %s | %s", q_text, e)
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
            confidence="medium" if len(items) >= 3 else "low",
        )
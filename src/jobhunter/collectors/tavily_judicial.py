"""Tavily-backed collector for judicial risk / court records.

Fills the role of WenshuCollector when wenshu.court.gov.cn is unreachable from
non-CN IPs. Pulls snapshots from 中国裁判文书网 / 人民法院公告网 / 中国执行信息公开网 /
天眼查 (judicial section).
"""

from __future__ import annotations

import logging

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.search.query_templates import JUDICIAL_DOMAINS, judicial_queries
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


class TavilyJudicialCollector(BaseCollector):
    name = "tavily_judicial"
    domain = "judicial"

    def __init__(self, settings: Settings, *, tavily: TavilyClient) -> None:
        super().__init__(settings, tavily=tavily)

    async def collect(self, query: CompanyQuery) -> CollectorResult:
        if not query.include_judicial:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="judicial_disabled_by_user",
            )
        if self._tavily is None:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error="tavily_client_not_initialized",
            )
        items = []
        errors: list[str] = []
        for q_text in judicial_queries(query):
            try:
                items.extend(
                    await self._tavily.search(
                        q_text,
                        include_domains=JUDICIAL_DOMAINS,
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("judicial query failed: %s | %s", q_text, e)
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
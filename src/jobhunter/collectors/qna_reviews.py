"""v0.3.5 — Tavily qna_search reviews collector.

Wraps Tavily's `qna_search` API to fetch an AI-synthesized summary of
public employee reviews / overtime / salary / management style for a
given company. Output is a single RawItem with the synthesized answer
in `content`, source = `tavily_qna`, fed into the reviews bucket so the
LLM extraction step can mine it for signals just like search snippets.

Cost: 1 Tavily credit per run (always fires; opt-in via settings).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from jobhunter.collectors.base import BaseCollector
from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult, RawItem
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


_QNA_PROMPT_TEMPLATE = (
    '"{name}" 公司的员工评价、工作体验、加班情况、薪资水平、'
    '管理风格、团队氛围如何？请综合多个公开来源给出客观摘要，'
    '并尽量覆盖正反两面的声音。'
)


class QnaReviewsCollector(BaseCollector):
    name = "tavily_qna"
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

        prompt = _QNA_PROMPT_TEMPLATE.format(name=query.company)
        try:
            answer = await self._tavily.qna_search(prompt)
        except Exception as e:  # noqa: BLE001
            logger.warning("qna_search failed for %s: %s", query.company, e)
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                error=f"qna_search_failed: {e}",
            )

        if not answer:
            return CollectorResult(
                collector=self.name,
                domain=self.domain,
                company_query=query,
                items=[],
                error="no_answer",
            )

        item = RawItem(
            source="tavily_qna",
            url="https://tavily.com/qna",
            title=f"{query.company} — Tavily AI 员工评价摘要",
            snippet=answer[:8000],
            retrieved_at=datetime.now(timezone.utc),
            payload={"full_answer": answer[:8000]},
        )
        return CollectorResult(
            collector=self.name,
            domain=self.domain,
            company_query=query,
            items=[item],
            confidence="medium",
        )
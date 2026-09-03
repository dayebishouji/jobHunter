"""End-to-end pipeline test with mocked Tavily + mocked Anthropic.

Verifies the whole chain: collectors → normalize → LLM extract → consolidate
→ crosscheck → score → render → write file.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobhunter.config import Settings
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    InferredClaim,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    ReviewFacts,
    SalarySignal,
    OvertimeSignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.pipeline import run as pipeline_run
from jobhunter.search.tavily_client import TavilyClient


CANNED_REVIEWS_ITEMS = [
    RawItem(
        source="tavily:zhihu",
        url="https://www.zhihu.com/question/123",
        title="在 A 公司的两年体验",
        snippet="加班比较多，平均 10 点下班。团队氛围还行，节奏快。",
    ),
    RawItem(
        source="tavily:kanzhun",
        url="https://www.kanzhun.com/reviews/abc",
        title="A 公司 - 后端工程师 面试体验",
        snippet="HR 说月 base 30K，年终 4 个月，14 薪。",
    ),
]

CANNED_NEWS_ITEMS = [
    RawItem(
        source="tavily:36kr",
        url="https://36kr.com/p/acme-news",
        title="A 公司完成 C 轮融资",
        snippet="2026 年 5 月，公司宣布完成 C 轮 5 亿元融资。",
    ),
]


@pytest.fixture
def fake_tavily(monkeypatch):
    """Replace TavilyClient.search with a canned async function."""
    calls: list[tuple[str, list[str]]] = []

    async def fake_search(self, query, *, include_domains, search_depth=None, max_results=None, days=None):
        calls.append((query, include_domains))
        if any(d in include_domains for d in ("36kr.com", "weibo.com")):
            return list(CANNED_NEWS_ITEMS)
        return list(CANNED_REVIEWS_ITEMS)

    monkeypatch.setattr(TavilyClient, "search", fake_search)
    return calls


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace LLMClient methods with canned deterministic responses."""
    # structured_call: return dict based on tool_name
    async def fake_structured(self, **kwargs):
        tool = kwargs["tool_name"]
        if tool == "record_business_facts":
            return BusinessFacts(status="存续", legal_rep="张三").model_dump()
        if tool == "record_review_facts":
            return ReviewFacts(
                salary_signals=[SalarySignal(position="后端", base_monthly_k=30.0, url="https://www.kanzhun.com/r/1")],
                overtime_signals=[OvertimeSignal(pattern="996", intensity="high", evidence="平均 10 点下班", url="https://www.zhihu.com/q/123")],
                vibe_signals=[VibeSignal(sentiment="mixed", evidence="节奏快", url="https://www.zhihu.com/q/123")],
                source_urls=["https://www.zhihu.com/q/123", "https://www.kanzhun.com/r/1"],
            ).model_dump(mode="json")
        if tool == "record_news_facts":
            return NewsFacts(
                items=[NewsItem(title="A 公司完成 C 轮融资", summary="5 亿元融资", url="https://36kr.com/p/x", published_at="2026-05-01")],
                sentiment="positive",
                source_urls=["https://36kr.com/p/x"],
            ).model_dump(mode="json")
        if tool == "record_judicial_facts":
            return {}  # empty, forcing null
        if tool == "record_aggregated_findings":
            return AggregatedFindings(
                company_query_summary="A 公司 后端工程师 杭州",
                inferences=[InferredClaim(claim="加班偏重，面试可询问节奏")],
                data_gaps=["司法数据未能获取（本机 gsxt 不可达）"],
            ).model_dump(mode="json")
        return {}

    async def fake_chat(self, *, system, user):
        return "1. 您团队最近一次调薪是什么时候？\n2. 平均下班时间是？"

    monkeypatch.setattr(__import__("jobhunter.llm.client", fromlist=["LLMClient"]).LLMClient, "structured_call", fake_structured)
    monkeypatch.setattr(__import__("jobhunter.llm.client", fromlist=["LLMClient"]).LLMClient, "chat", fake_chat)
    return None


@pytest.mark.asyncio
async def test_end_to_end_pipeline(tmp_path: Path, fake_tavily, fake_llm):
    settings = Settings(
        anthropic_api_key="x",
        tavily_api_key="y",
        output_dir=tmp_path,
        cache_ttl_hours=1,
    )
    query = CompanyQuery(company="A 公司", position="后端工程师", city="杭州")

    arts = await pipeline_run(query, settings=settings, output_dir=tmp_path, open_browser=False)

    # 1. File was written
    assert arts.path.exists()
    assert arts.path.suffix == ".html"
    assert arts.path.stat().st_size > 5000

    # 2. Content sanity
    html = arts.path.read_text(encoding="utf-8")
    assert "A 公司" in html
    assert "加班强度" in html  # axis label
    assert "来源附录" in html  # sources section (chapter title)
    assert "www.zhihu.com" in html  # source URL surfaced

    # 3. Confidence is at least medium (we have reviews + news)
    assert arts.data.overall_confidence in ("medium", "high")

    # 4. Interview questions surface
    assert arts.data.interview_questions
    assert any("调薪" in q or "下班" in q for q in arts.data.interview_questions)

    # 5. Tavily was actually called
    assert fake_tavily, "Tavily should have been called"
    assert any("加班" in q[0] for q in fake_tavily)

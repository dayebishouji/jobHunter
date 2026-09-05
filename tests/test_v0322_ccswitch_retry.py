"""Tests for v0.3.2 hotfix A+B: ccswitch / relay plain-text-response defenses.

Bug: ccswitch (api.minimaxi.com/anthropic) sometimes degrades and emits plain
text instead of a `tool_use` block for tool-forced calls. The previous code
returned `{}` immediately, losing the entire `record_aggregated_findings`
extraction and forcing reviews/judicial/etc chapters to render empty.

Fixes:
  (A) `consolidate()` retries via `chat()` + JSON regex when `structured_call`
      returns `{}`. Same pattern as `list_company_entities()`.
  (B) `structured_call()` retries the LLM call when the response has no
      tool_use block. Default policy: 3 attempts total; strict: 2 attempts
      total (tenacity handles transport-level retries separately).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobhunter.config import Settings
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.query import CompanyQuery


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="sk-test",
        tavily_api_key="tvly-test",
        retry_attempts=3,
        retry_min_wait=1,
        retry_max_wait=5,
        # Disable LLM cache so each test gets fresh mock responses
        llm_cache_enabled=False,
    )


def _query() -> CompanyQuery:
    return CompanyQuery(company="有赞", position="后端", city="杭州")


def _facets() -> dict[str, object | None]:
    """Minimal facet set so consolidate() can build its user prompt."""
    return {
        "business": BusinessFacts(status="存续"),
        "reviews": ReviewFacts(),
        "news": NewsFacts(),
        "judicial": None,
        "company_info": CompanyProfile(),
    }


def _text_only_response() -> MagicMock:
    """A fake Anthropic response with only a text block — no tool_use."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "对不起，我无法按你的要求返回结构化数据。"
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    response = MagicMock()
    response.content = [text_block]
    response.usage = usage
    response.stop_reason = "end_turn"
    return response


def _tool_use_response(payload: dict[str, Any]) -> MagicMock:
    """A fake Anthropic response with a successful tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = payload
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    response = MagicMock()
    response.content = [tool_block]
    response.usage = usage
    response.stop_reason = "tool_use"
    return response


# =============== A: consolidate() chat()+JSON regex fallback ===============

class TestConsolidateFallback:
    """A — When structured_call returns {} (tool_use failed), consolidate()
    must try chat() + JSON regex before giving up."""

    @pytest.mark.asyncio
    async def test_chat_fallback_recovers_from_plain_text(self):
        """structured_call returns {}, chat() returns valid JSON → consolidate
        must parse it and return a populated AggregatedFindings."""
        from jobhunter.processing.extract import consolidate

        # JSON that schema-validates as AggregatedFindings (minimal)
        json_text = (
            '{"company_query_summary":"有赞 · 后端 · 杭州",'
            '"inferences":[],'
            '"data_gaps":["司法数据缺失"]}'
        )

        llm = MagicMock()
        llm.structured_call = AsyncMock(return_value={})
        llm.chat = AsyncMock(return_value=json_text)

        agg = await consolidate(llm, _query(), _facets())

        # Fallback path was taken (chat called)
        assert llm.chat.await_count == 1
        # AggregatedFindings built from the JSON fallback, NOT from raw facets
        assert agg is not None
        assert agg.company_query_summary == "有赞 · 后端 · 杭州"
        assert agg.data_gaps == ["司法数据缺失"]

    @pytest.mark.asyncio
    async def test_chat_fallback_silent_on_invalid_json(self):
        """When chat() returns garbage, consolidate() falls back to raw
        facets instead of raising."""
        from jobhunter.processing.extract import consolidate

        llm = MagicMock()
        llm.structured_call = AsyncMock(return_value={})
        llm.chat = AsyncMock(return_value="抱歉，我无法回答这个问题。")

        agg = await consolidate(llm, _query(), _facets())

        assert agg is not None
        # Built from raw facets (best-effort stub)
        assert agg.company_query_summary == "有赞 · 后端 · 杭州"
        assert agg.business is not None  # we passed BusinessFacts in

    @pytest.mark.asyncio
    async def test_no_fallback_when_structured_call_succeeds(self):
        """Happy path: structured_call returns a valid payload → chat() must
        NOT be called (saves tokens + avoids double-charge)."""
        from jobhunter.processing.extract import consolidate

        payload = {
            "company_query_summary": "有赞 · 后端 · 杭州",
            "inferences": [],
            "data_gaps": [],
        }
        llm = MagicMock()
        llm.structured_call = AsyncMock(return_value=payload)
        llm.chat = AsyncMock(return_value="should not be called")

        agg = await consolidate(llm, _query(), _facets())

        assert llm.chat.await_count == 0
        assert agg is not None


# =============== B: structured_call retries on plain-text response ===============

class TestStructuredCallPlainTextRetry:
    """B — When the response has no tool_use block, retry up to N times
    (default=2 retries / 3 total attempts; strict=1 retry / 2 total attempts)."""

    @pytest.mark.asyncio
    async def test_recovers_on_second_attempt(self):
        """1st call returns text-only; 2nd call returns proper tool_use."""
        from jobhunter.llm.client import LLMClient

        valid_payload = {"entities": ["钉钉"]}
        responses = [_text_only_response(), _tool_use_response(valid_payload)]

        # Build a minimal LLMClient without going through __init__
        settings = _settings()
        client = LLMClient.__new__(LLMClient)
        client._settings = settings
        client._tokens_in = 0
        client._tokens_out = 0
        client._budget_blocked = False
        # v0.2.2 cache needs a real instance; use a stub that always returns None
        client._cache = MagicMock()
        client._cache.get = MagicMock(return_value=None)
        client._cache.set = MagicMock()

        # Patch the inner messages.create to return responses in order
        create_mock = AsyncMock(side_effect=responses)
        client._client = MagicMock()
        client._client.messages = MagicMock()
        client._client.messages.create = create_mock
        client._retry = MagicMock(side_effect=lambda f: f())  # no-op passthrough

        result = await client.structured_call(
            system="sys",
            user="usr",
            tool_name="test_tool",
            tool_description="desc",
            tool_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )

        assert result == valid_payload
        assert create_mock.await_count == 2  # 2 attempts

    @pytest.mark.asyncio
    async def test_returns_empty_after_all_attempts_default_policy(self):
        """Default policy = 3 total attempts; all return text-only → {}."""
        from jobhunter.llm.client import LLMClient

        settings = _settings()
        client = LLMClient.__new__(LLMClient)
        client._settings = settings
        client._tokens_in = 0
        client._tokens_out = 0
        client._budget_blocked = False
        client._cache = MagicMock()
        client._cache.get = MagicMock(return_value=None)
        client._cache.set = MagicMock()

        create_mock = AsyncMock(side_effect=[
            _text_only_response(),
            _text_only_response(),
            _text_only_response(),
        ])
        client._client = MagicMock()
        client._client.messages = MagicMock()
        client._client.messages.create = create_mock
        client._retry = MagicMock(side_effect=lambda f: f())

        result = await client.structured_call(
            system="sys",
            user="usr",
            tool_name="test_tool",
            tool_description="desc",
            tool_schema={"type": "object"},
        )

        assert result == {}
        assert create_mock.await_count == 3  # default = 3 attempts

    @pytest.mark.asyncio
    async def test_strict_policy_makes_only_2_attempts(self):
        """retry_policy='strict' = 2 total attempts (1 retry)."""
        from jobhunter.llm.client import LLMClient

        settings = _settings()
        client = LLMClient.__new__(LLMClient)
        client._settings = settings
        client._tokens_in = 0
        client._tokens_out = 0
        client._budget_blocked = False
        client._cache = MagicMock()
        client._cache.get = MagicMock(return_value=None)
        client._cache.set = MagicMock()

        create_mock = AsyncMock(side_effect=[
            _text_only_response(),
            _text_only_response(),
        ])
        client._client = MagicMock()
        client._client.messages = MagicMock()
        client._client.messages.create = create_mock
        # strict policy uses llm_retry_strict; mock it as a passthrough
        client._retry = MagicMock(side_effect=lambda f: f())

        result = await client.structured_call(
            system="sys",
            user="usr",
            tool_name="record_aggregated_findings",
            tool_description="desc",
            tool_schema={"type": "object"},
            retry_policy="strict",
        )

        assert result == {}
        assert create_mock.await_count == 2  # strict = 2 attempts
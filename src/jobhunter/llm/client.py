"""Anthropic SDK wrapper with `tool_use` structured output and cost guard."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from jobhunter.config import Settings
from jobhunter.utils.retry import llm_retry as _retry_builder

logger = logging.getLogger(__name__)

# Approximate USD per million tokens for Sonnet 4.5 (Sept 2026).
_PRICE_INPUT_PER_M = 3.0
_PRICE_OUTPUT_PER_M = 15.0


class LLMClient:
    """Async Anthropic client with structured-output and budget tracking."""

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self._settings = settings
        kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._tokens_in = 0
        self._tokens_out = 0
        self._budget_blocked = False
        self._retry = _retry_builder(settings)

    # ---------- bookkeeping ----------

    @property
    def tokens_in(self) -> int:
        return self._tokens_in

    @property
    def tokens_out(self) -> int:
        return self._tokens_out

    @property
    def cost_usd(self) -> float:
        return (self._tokens_in / 1_000_000) * _PRICE_INPUT_PER_M + (
            self._tokens_out / 1_000_000
        ) * _PRICE_OUTPUT_PER_M

    def budget_ok(self) -> bool:
        return not self._budget_blocked

    # ---------- primary API ----------

    async def chat(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Plain chat (no tool_use). Used for free-text interview-question generation."""
        if not self.budget_ok():
            return ""
        kwargs = dict(
            model=model or self._settings.model,
            max_tokens=max_tokens or self._settings.max_tokens_per_call,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        async def _do() -> Any:
            return await self._client.messages.create(**kwargs)

        response = await self._retry(_do)
        self._tokens_in += response.usage.input_tokens
        self._tokens_out += response.usage.output_tokens
        if self._tokens_in + self._tokens_out > self._settings.budget_tokens_per_run:
            self._budget_blocked = True
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    async def structured_call(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send the user message, force the named tool call, and return the parsed input dict.

        On budget exhaustion: returns `{}` without calling the API.
        On a normal completion: returns the tool's input as a dict.
        """
        if not self.budget_ok():
            logger.warning("LLM budget exhausted; returning empty result for %s", tool_name)
            return {}

        kwargs = dict(
            model=model or self._settings.model,
            max_tokens=max_tokens or self._settings.max_tokens_per_call,
            system=system,
            tools=[
                {
                    "name": tool_name,
                    "description": tool_description,
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )

        async def _do_call() -> Any:
            return await self._client.messages.create(**kwargs)

        response = await self._retry(_do_call)

        # Bookkeeping
        self._tokens_in += response.usage.input_tokens
        self._tokens_out += response.usage.output_tokens
        if self._tokens_in + self._tokens_out > self._settings.budget_tokens_per_run:
            self._budget_blocked = True

        # Find the tool_use block
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input

        # Some ccswitch / relay responses lose tool_use blocks. Surface what we
        # actually got so the user can diagnose (e.g., relay returned text instead).
        block_types = [getattr(b, "type", "?") for b in response.content]
        stop_reason = getattr(response, "stop_reason", "?")
        logger.warning(
            "No tool_use block for %s (got block types=%s, stop_reason=%s); returning empty",
            tool_name, block_types, stop_reason,
        )
        return {}


def to_json_schema(model_cls: type) -> dict[str, Any]:
    """Pydantic → JSON Schema for `tool_use.input_schema`."""
    schema = model_cls.model_json_schema()
    # Anthropic requires top-level "type": "object"; some Pydantic versions omit it for primitives.
    schema.setdefault("type", "object")
    return schema


def safe_dumps(d: dict[str, Any]) -> str:
    """JSON dump with UTF-8, failsafe."""
    return json.dumps(d, ensure_ascii=False, indent=2)

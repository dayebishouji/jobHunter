"""Tests for v0.2.1: tenacity retry behavior on LLM transient failures.

Bug fixed: previously `llm_retry()` only caught `httpx.TransportError` /
`ConnectionError` / `TimeoutError`. A single Anthropic / ccswitch 5xx / 429 /
529 blip would propagate to `consolidate()` and force a fallback to raw facets,
losing the cross-domain inferences block. Now `anthropic.APIError` and all its
subclasses (`APIConnectionError`, `APIStatusError`, `RateLimitError`,
`APITimeoutError`) are also retried.

Additionally `consolidate()` opts into `retry_policy="strict"` (≥3 attempts,
1-20s backoff) because it's the highest-value LLM call in the pipeline —
a transient blip should not drop the inferences block to a fallback.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import anthropic
import httpx
import pytest
import tenacity

from jobhunter.config import Settings
from jobhunter.utils.retry import llm_retry, llm_retry_strict


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="sk-test",
        retry_attempts=3,
        retry_min_wait=1,
        retry_max_wait=10,
    )


# =============== retry builder: exception type coverage ===============

class TestLLMRetryExceptionCoverage:
    """v0.2.1 — every transient Anthropic / ccswitch exception must trigger retry."""

    @pytest.mark.parametrize("exc_factory", [
        lambda: anthropic.APIConnectionError(request=MagicMock()),
        lambda: anthropic.APITimeoutError(request=MagicMock()),
        lambda: httpx.ConnectError("connection refused"),
        lambda: httpx.ReadTimeout("timeout"),
        lambda: ConnectionError("refused"),
        lambda: TimeoutError("timeout"),
    ])
    def test_retry_recovers_on_transient_error(self, exc_factory):
        """Each transient exception type must trigger a retry, then succeed."""
        attempts: list[int] = []
        exc = exc_factory()

        async def _call() -> str:
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise exc
            return "ok"

        retry = llm_retry(_settings())
        import asyncio
        result_value = asyncio.run(_call_with(retry, _call))
        assert result_value == "ok"
        assert len(attempts) == 2  # failed once, recovered on attempt 2

    def test_anthropic_api_error_subclass_is_retried(self):
        """The contract: APIError parent class in retry list → any subclass retries.

        This is verified via source rather than runtime, because constructing
        every Anthropic SDK exception subclass (APIStatusError, RateLimitError)
        requires a real httpx.Response, which is brittle. The source contract
        `anthropic.APIError` in the retry tuple is what makes the contract true.
        """
        import inspect

        from jobhunter.utils import retry as retry_mod

        src = inspect.getsource(retry_mod.llm_retry)
        assert "anthropic.APIError" in src, (
            "anthropic.APIError must be in llm_retry exception tuple — "
            "without it, future SDK subclasses (and current APIStatusError / "
            "RateLimitError) bypass retry."
        )

    def test_strict_retry_has_more_attempts_than_default(self):
        s = _settings()
        strict = llm_retry_strict(s)
        default = llm_retry(s)
        assert strict.stop.max_attempt_number >= default.stop.max_attempt_number
        assert strict.wait.max >= default.wait.max


async def _call_with(retry_obj, fn):
    """Wrap tenacity.AsyncRetrying for asyncio.run."""
    coro = retry_obj(fn)
    return await coro


# =============== consolidate uses strict policy ===============

class TestConsolidateRetryPolicy:
    """v0.2.1 — consolidate() must opt into retry_policy='strict'."""

    def test_consolidate_calls_structured_call_with_strict_policy(self):
        import inspect

        from jobhunter.processing.extract import consolidate

        src = inspect.getsource(consolidate)
        assert 'retry_policy="strict"' in src or "retry_policy='strict'" in src, (
            "consolidate() must opt into strict retry — without it, a transient "
            "API blip drops the cross-domain inferences block to a facets fallback."
        )


# =============== structured_call honors retry_policy param ===============

class TestStructuredCallRetryPolicy:
    """v0.2.1 — LLMClient.structured_call() accepts retry_policy param."""

    def test_structured_call_signature_includes_retry_policy(self):
        import inspect

        from jobhunter.llm.client import LLMClient

        sig = inspect.signature(LLMClient.structured_call)
        assert "retry_policy" in sig.parameters
        assert sig.parameters["retry_policy"].default == "default"

    def test_default_policy_uses_client_retry(self):
        """When retry_policy='default' (or unset), self._retry is used.

        Verify by reading the source: structured_call branches on retry_policy
        and falls back to self._retry when not 'strict'. No LLM call needed.
        """
        import inspect

        from jobhunter.llm.client import LLMClient

        src = inspect.getsource(LLMClient.structured_call)
        assert "self._retry" in src, "default path must use self._retry"
        assert "else" in src, "default path must fall through else branch"
        # Confirm 'strict' branch exists
        assert 'retry_policy == "strict"' in src or "retry_policy == 'strict'" in src

    def test_strict_policy_invokes_strict_retry_builder(self):
        """When retry_policy='strict', llm_retry_strict() is invoked.

        Verify by patching the `llm_retry_strict` import path used inside
        structured_call. The function imports lazily:
            from jobhunter.utils.retry import llm_retry_strict as _strict_retry
        so we patch jobhunter.utils.retry.llm_retry_strict to a fake that
        records the call, then drive structured_call with a stub SDK.
        """
        import asyncio

        from jobhunter.llm.client import LLMClient
        from jobhunter import utils

        calls: list[Settings] = []

        real_strict = utils.retry.llm_retry_strict

        def _fake_strict(settings: Settings) -> tenacity.AsyncRetrying:
            calls.append(settings)
            return real_strict(settings)

        # Patch where the import statement in structured_call will look it up.
        utils.retry.llm_retry_strict = _fake_strict  # type: ignore[assignment]
        try:
            settings = _settings()
            client = LLMClient(settings)

            # Stub the SDK: messages.create always raises.
            async def _fake_create(**_kwargs):
                raise anthropic.APIConnectionError(request=MagicMock())
            client._client.messages.create = _fake_create  # type: ignore[assignment]

            with pytest.raises(anthropic.APIConnectionError):
                asyncio.run(
                    client.structured_call(
                        system="sys", user="usr",
                        tool_name="t", tool_description="d",
                        tool_schema={"type": "object"},
                        retry_policy="strict",
                    )
                )
            assert len(calls) == 1, (
                f"Expected llm_retry_strict to be invoked once, got {len(calls)}"
            )
        finally:
            utils.retry.llm_retry_strict = real_strict  # type: ignore[assignment]


# =============== retry succeeds on 2nd attempt ===============

class TestRetryRecovery:
    """Tenacity must actually retry — one transient failure + one success = ok."""

    @pytest.mark.asyncio
    async def test_recovers_after_one_failure(self):
        attempts: list[int] = []

        async def _call() -> str:
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise anthropic.APIConnectionError(request=MagicMock())
            return "ok"

        retry = llm_retry(_settings())
        result = await retry(_call)
        assert result == "ok"
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_reraises_after_max_attempts(self):
        attempts: list[int] = []

        async def _call() -> str:
            attempts.append(len(attempts) + 1)
            raise anthropic.APIConnectionError(request=MagicMock())

        retry = llm_retry(_settings())
        with pytest.raises(anthropic.APIConnectionError):
            await retry(_call)
        assert len(attempts) == 3
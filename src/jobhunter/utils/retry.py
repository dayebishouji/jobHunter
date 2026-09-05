"""Tenacity presets — used by collectors and the LLM client."""

from __future__ import annotations

import anthropic
import httpx
import tenacity

from jobhunter.config import Settings


def network_retry(settings: Settings) -> tenacity.AsyncRetrying:
    """Retry on transient HTTP/network errors. Re-raises the last exception on exhaustion."""
    return tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(settings.retry_attempts),
        wait=tenacity.wait_exponential(
            multiplier=1, min=settings.retry_min_wait, max=settings.retry_max_wait
        ),
        retry=tenacity.retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, ConnectionError, TimeoutError)
        ),
        reraise=True,
    )


def llm_retry(settings: Settings) -> tenacity.AsyncRetrying:
    """Retry the LLM client on transient API errors.

    v0.2.1 — Widened scope to catch `anthropic.APIError` and all its subclasses
    (`APIConnectionError`, `APIStatusError`, `RateLimitError`, `APITimeoutError`).
    Previously only `httpx.TransportError` / `ConnectionError` / `TimeoutError`
    were caught — that left 5xx / 429 / overloaded 529 / empty tool_use blocks
    unretried, so a single transient ccswitch / Anthropic blip would knock
    `consolidate()` out of the box and force a fallback to raw facets.
    """
    return tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(settings.retry_attempts),
        wait=tenacity.wait_exponential(
            multiplier=1, min=settings.retry_min_wait, max=settings.retry_max_wait
        ),
        retry=tenacity.retry_if_exception_type(
            (
                httpx.TransportError,
                ConnectionError,
                TimeoutError,
                anthropic.APIError,
            )
        ),
        reraise=True,
    )


def llm_retry_strict(settings: Settings) -> tenacity.AsyncRetrying:
    """Stricter variant for high-value LLM calls (consolidate, interview Qs).

    More attempts + longer max wait — these calls are expensive to lose because
    they carry cross-domain synthesis that local fallback can't reproduce.
    """
    return tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(max(3, settings.retry_attempts)),
        wait=tenacity.wait_exponential(
            multiplier=1, min=settings.retry_min_wait, max=max(20, settings.retry_max_wait)
        ),
        retry=tenacity.retry_if_exception_type(
            (
                httpx.TransportError,
                ConnectionError,
                TimeoutError,
                anthropic.APIError,
            )
        ),
        reraise=True,
    )

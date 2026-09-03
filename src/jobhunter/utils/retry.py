"""Tenacity presets — used by collectors and the LLM client."""

from __future__ import annotations

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
    """Retry the LLM client on transient API errors. Same shape, narrower scope."""
    return tenacity.AsyncRetrying(
        stop=tenacity.stop_after_attempt(settings.retry_attempts),
        wait=tenacity.wait_exponential(
            multiplier=1, min=settings.retry_min_wait, max=settings.retry_max_wait
        ),
        retry=tenacity.retry_if_exception_type(
            (httpx.TransportError, ConnectionError, TimeoutError)
        ),
        reraise=True,
    )

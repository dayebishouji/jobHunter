"""Shared httpx.AsyncClient factory with realistic browser-like defaults."""

from __future__ import annotations

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def make_client(
    *,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Return a configured httpx.AsyncClient.

    Caller is responsible for `await client.aclose()` (use `async with`).
    """
    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )

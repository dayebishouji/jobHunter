"""Disk-backed cache for structured LLM responses.

v0.2.2 — Mirrors the `FileCache` pattern used for Tavily responses
(see `src/jobhunter/search/cache.py`) but is dedicated to LLM outputs.

Why a separate cache?
  - Tavily cache is keyed by raw search query (string). LLM cache is keyed
    by (system prompt + user prompt + tool_name) so a different model /
    extraction schema yields a different cache entry even if the user
    prompt content overlaps.
  - Different TTLs: Tavily uses cache_ttl_hours=24 for fresh search
    results; LLM responses are stable across days/weeks (the extraction
    schema doesn't change day-to-day), so the LLM TTL is naturally longer.
    We still respect the same `settings.cache_ttl_hours` knob for
    operational consistency — users can override via .env if they want a
    longer LLM TTL.
  - LLM cache must NOT cache empty dict results (LLM failure path / budget
    exhausted / empty tool_use block) — otherwise a transient API blip
    permanently locks in a poisoned cache entry. The `set()` method
    silently no-ops on falsy values; callers don't need to check.

Cache key format: SHA1(system + "|" + user + "|" + tool_name)[:32]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import platformdirs

logger = logging.getLogger(__name__)


def default_llm_cache_dir() -> Path:
    """Return the LLM cache subdirectory under the user cache root.

    Layout: <user_cache_dir>/llm_cache/<digest>.json
    The Tavily cache lives at <user_cache_dir>/<digest>.json (one level up).
    """
    p = Path(platformdirs.user_cache_dir("jobhunter", appauthor=False)) / "llm_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_key(system: str, user: str, tool_name: str) -> str:
    """Stable hash key from the three call-identifying strings."""
    raw = f"{system}|{user}|{tool_name}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


class LLMResponseCache:
    """Disk-backed cache for `LLMClient.structured_call` responses.

    Usage:
        cache = LLMResponseCache(ttl_hours=24)
        cached = cache.get(system, user, tool_name)
        if cached is not None:
            return cached
        # ... call LLM ...
        cache.set(system, user, tool_name, response_dict)

    Thread-safety: not guaranteed (single-process assumption matches the
    rest of jobHunter). For multi-process safety, wrap get/set in a
    `filelock`-style lock — not currently needed.
    """

    def __init__(
        self,
        dir_path: Path | None = None,
        ttl_hours: int = 24,
        enabled: bool = True,
    ) -> None:
        self.dir = dir_path or default_llm_cache_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl_hours = ttl_hours
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, system: str, user: str, tool_name: str) -> dict[str, Any] | None:
        """Return the cached dict if present and fresh; else None.

        On miss / expired / decode-error: returns None (never raises).
        """
        if not self.enabled:
            return None
        key = _make_key(system, user, tool_name)
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("llm cache: failed to read %s", p.name)
            return None
        expires_at = data.get("expires_at", 0)
        if expires_at and expires_at < time.time():
            # lazy expiry
            try:
                p.unlink()
            except OSError:
                pass
            return None
        value = data.get("value")
        if not isinstance(value, dict):
            logger.warning("llm cache: %s has non-dict value, ignoring", p.name)
            return None
        return value

    def set(
        self,
        system: str,
        user: str,
        tool_name: str,
        value: dict[str, Any],
    ) -> None:
        """Persist a successful response. Silently no-ops on:
            - disabled cache
            - empty dict value (LLM failure path — never poison the cache)

        """
        if not self.enabled:
            return
        if not value:
            # Empty dict means LLM call returned nothing (budget exhausted,
            # empty tool_use, ccswitch moderation block). Caching this would
            # poison the cache for 24h.
            return
        key = _make_key(system, user, tool_name)
        p = self._path(key)
        payload = {
            "value": value,
            "expires_at": int(time.time()) + self.ttl_hours * 3600,
        }
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            # Cache write failures are non-fatal — LLM call already succeeded.
            logger.warning("llm cache: failed to write %s: %s", p.name, e)

    def clear(self) -> int:
        """Delete all cache files. Returns count of files removed.

        Useful for: testing, debugging, manual eviction via CLI subcommand
        (potential v0.3.0 feature: `jobhunter cache clear`).
        """
        count = 0
        for p in self.dir.glob("*.json"):
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
        return count

    def stats(self) -> dict[str, int]:
        """Return file count + total bytes for diagnostic display."""
        files = list(self.dir.glob("*.json"))
        total_bytes = sum((f.stat().st_size for f in files), 0)
        return {"files": len(files), "bytes": total_bytes}
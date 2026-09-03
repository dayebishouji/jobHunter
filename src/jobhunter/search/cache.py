"""Filesystem cache for Tavily responses and (optionally) other collectors."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import platformdirs


def default_cache_dir() -> Path:
    """Return the per-user cache directory for jobhunter (created if missing)."""
    p = Path(platformdirs.user_cache_dir("jobhunter", appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


class FileCache:
    """Simple JSON-file cache keyed by arbitrary strings."""

    def __init__(self, dir_path: Path | None = None) -> None:
        self.dir = dir_path or default_cache_dir()
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Hash-like: 32-char hex avoids filesystem-unsafe chars
        import hashlib

        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:32]
        return self.dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        expires_at = data.get("expires_at", 0)
        if expires_at and expires_at < time.time():
            try:
                p.unlink()
            except OSError:
                pass
            return None
        return data.get("value")

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        p = self._path(key)
        payload = {"value": value, "expires_at": int(time.time()) + ttl_seconds}
        # atomic-ish write
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

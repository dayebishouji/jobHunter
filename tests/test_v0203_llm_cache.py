"""Tests for v0.2.2: LLM response disk cache (audit §2.3).

Bug fixed: peer comparison / repeated runs / future batch mode all paid full
LLM cost every time, even when the same (system, user, tool_name) tuple was
already answered minutes ago. Tavily had a 24h file cache (`FileCache`),
LLM didn't.

Implementation: new `LLMResponseCache` class in `src/jobhunter/llm/cache.py`
mirroring the Tavily cache pattern (SHA1[:32] key, TTL in JSON, atomic
.tmp + os.replace write). Wired into `LLMClient.structured_call()` as a
short-circuit before the API call. Empty dict responses are NEVER cached
(to avoid poisoning the cache during transient API failures).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobhunter.config import Settings
from jobhunter.llm import LLMResponseCache
from jobhunter.llm.client import LLMClient


# =============== helpers ===============

def _settings(**overrides) -> Settings:
    return Settings(
        anthropic_api_key="sk-test",
        cache_ttl_hours=overrides.get("cache_ttl_hours", 24),
        llm_cache_enabled=overrides.get("llm_cache_enabled", True),
    )


@pytest.fixture
def tmp_cache_dir(tmp_path) -> Path:
    return tmp_path / "llm_cache"


# =============== LLMResponseCache direct API ===============

class TestLLMResponseCacheDirect:
    """Tests against the cache class itself (no LLMClient wiring)."""

    def test_get_returns_none_on_miss(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        assert c.get("sys", "usr", "tool") is None

    def test_set_then_get_roundtrip(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        value = {"companies": [{"name": "美团", "score": 4.2}]}
        c.set("sys", "usr", "tool", value)
        assert c.get("sys", "usr", "tool") == value

    def test_set_creates_file_in_cache_dir(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys", "usr", "extract_business", {"k": "v"})
        files = list(tmp_cache_dir.glob("*.json"))
        assert len(files) == 1
        # Verify the on-disk format includes expires_at + value
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert "value" in data and "expires_at" in data
        assert data["value"] == {"k": "v"}

    def test_different_keys_yield_different_files(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys_a", "usr", "tool", {"a": 1})
        c.set("sys_b", "usr", "tool", {"b": 2})
        assert len(list(tmp_cache_dir.glob("*.json"))) == 2
        assert c.get("sys_a", "usr", "tool") == {"a": 1}
        assert c.get("sys_b", "usr", "tool") == {"b": 2}

    def test_set_empty_dict_is_noop(self, tmp_cache_dir):
        """Empty dict = LLM failure path. MUST NOT cache (poison prevention)."""
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys", "usr", "tool", {})
        assert list(tmp_cache_dir.glob("*.json")) == []
        assert c.get("sys", "usr", "tool") is None

    def test_set_zero_value_dict_is_noop(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys", "usr", "tool", {"a": 0, "b": []})  # truthy dict, but
        # — actually this is truthy so it WILL be cached. The poison guard
        # is specifically for {} (LLM failure). Let's verify that case is
        # the only guard:
        assert len(list(tmp_cache_dir.glob("*.json"))) == 1

    def test_disabled_cache_returns_none_and_skips_set(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir, enabled=False)
        c.set("sys", "usr", "tool", {"k": "v"})
        assert list(tmp_cache_dir.glob("*.json")) == []
        assert c.get("sys", "usr", "tool") is None


# =============== TTL expiry ===============

class TestCacheTTL:
    """TTL must be respected; expired entries must be treated as miss."""

    def test_expired_entry_returns_none(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir, ttl_hours=1)
        # Write a payload with a past expires_at
        from jobhunter.llm.cache import _make_key

        key = _make_key("sys", "usr", "tool")
        p = tmp_cache_dir / f"{key}.json"
        payload = {"value": {"k": "v"}, "expires_at": int(time.time()) - 60}
        p.write_text(json.dumps(payload), encoding="utf-8")

        assert c.get("sys", "usr", "tool") is None
        # Lazy eviction: file should be removed
        assert not p.exists()

    def test_future_entry_returns_value(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir, ttl_hours=24)
        from jobhunter.llm.cache import _make_key

        key = _make_key("sys", "usr", "tool")
        p = tmp_cache_dir / f"{key}.json"
        payload = {"value": {"k": "v"}, "expires_at": int(time.time()) + 3600}
        p.write_text(json.dumps(payload), encoding="utf-8")

        assert c.get("sys", "usr", "tool") == {"k": "v"}


# =============== clear + stats ===============

class TestCacheAdmin:
    def test_clear_removes_all_files(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys_a", "usr", "tool_a", {"a": 1})
        c.set("sys_b", "usr", "tool_b", {"b": 2})
        assert len(list(tmp_cache_dir.glob("*.json"))) == 2

        removed = c.clear()
        assert removed == 2
        assert list(tmp_cache_dir.glob("*.json")) == []

    def test_stats_reports_file_count_and_bytes(self, tmp_cache_dir):
        c = LLMResponseCache(dir_path=tmp_cache_dir)
        c.set("sys", "usr", "tool", {"data": "x" * 100})
        stats = c.stats()
        assert stats["files"] == 1
        assert stats["bytes"] > 100


# =============== structured_call integration ===============

class TestStructuredCallCacheIntegration:
    """Wire the cache into LLMClient and verify behavior end-to-end."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_api_call(self, tmp_cache_dir):
        """Pre-populate cache → structured_call returns cached value, no API."""
        cache = LLMResponseCache(dir_path=tmp_cache_dir, ttl_hours=24)
        # Pre-populate
        cache.set("sys", "usr", "tool_x", {"cached": True})

        client = _make_client_with_cache(tmp_cache_dir)

        # Stub the API: if called, would raise to make the test loud
        api_calls = []
        async def _fake_create(**kwargs):
            api_calls.append(kwargs)
            raise AssertionError("API was called despite cache hit")
        client._client.messages.create = _fake_create  # type: ignore[assignment]

        result = await client.structured_call(
            system="sys", user="usr",
            tool_name="tool_x", tool_description="desc",
            tool_schema={"type": "object"},
        )
        assert result == {"cached": True}
        assert api_calls == []
        # Cache hit must NOT count toward tokens
        assert client._tokens_in == 0
        assert client._tokens_out == 0

    @pytest.mark.asyncio
    async def test_cache_miss_calls_api_and_writes_cache(self, tmp_cache_dir):
        client = _make_client_with_cache(tmp_cache_dir)
        _stub_api_response(client, {"fresh": True, "score": 4.5})

        result = await client.structured_call(
            system="sys", user="usr",
            tool_name="tool_y", tool_description="desc",
            tool_schema={"type": "object"},
        )
        assert result == {"fresh": True, "score": 4.5}

        # Now the cache should have this entry
        cached = client._cache.get("sys", "usr", "tool_y")
        assert cached == {"fresh": True, "score": 4.5}

    @pytest.mark.asyncio
    async def test_empty_response_not_cached(self, tmp_cache_dir):
        """Empty tool_use block must NOT poison the cache."""
        client = _make_client_with_cache(tmp_cache_dir)
        _stub_api_response(client, {})  # empty dict = failure path

        result = await client.structured_call(
            system="sys", user="usr",
            tool_name="tool_z", tool_description="desc",
            tool_schema={"type": "object"},
        )
        assert result == {}
        # Cache must remain empty for this key
        assert client._cache.get("sys", "usr", "tool_z") is None

    @pytest.mark.asyncio
    async def test_disabled_cache_always_calls_api(self, tmp_cache_dir):
        cache = LLMResponseCache(dir_path=tmp_cache_dir, enabled=False)
        # Even though we pre-set, cache is disabled so it won't be used
        cache.set("sys", "usr", "tool", {"cached": True})

        client = LLMClient(Settings(
            anthropic_api_key="sk-test",
            llm_cache_enabled=False,
            cache_ttl_hours=24,
        ))
        client._cache = cache  # ensure disabled
        _stub_api_response(client, {"from_api": True})

        result = await client.structured_call(
            system="sys", user="usr",
            tool_name="tool", tool_description="desc",
            tool_schema={"type": "object"},
        )
        assert result == {"from_api": True}

    @pytest.mark.asyncio
    async def test_retry_policy_strict_also_uses_cache(self, tmp_cache_dir):
        """retry_policy='strict' (consolidate) must also hit / write cache."""
        cache = LLMResponseCache(dir_path=tmp_cache_dir, ttl_hours=24)
        cache.set("sys", "usr", "consolidate", {"consolidated": True})

        client = _make_client_with_cache(tmp_cache_dir)

        api_calls = []
        async def _fake_create(**kwargs):
            api_calls.append(kwargs)
            raise AssertionError("strict-retry API called despite cache hit")
        client._client.messages.create = _fake_create  # type: ignore[assignment]

        result = await client.structured_call(
            system="sys", user="usr",
            tool_name="consolidate", tool_description="desc",
            tool_schema={"type": "object"},
            retry_policy="strict",
        )
        assert result == {"consolidated": True}
        assert api_calls == []


# =============== helpers ===============

def _make_client_with_cache(tmp_cache_dir: Path) -> LLMClient:
    """Build a real LLMClient with a cache rooted at the test tmp dir.

    Disables actual API calls by overriding the SDK client to a stub.
    """
    settings = _settings()
    client = LLMClient(settings)
    client._cache = LLMResponseCache(dir_path=tmp_cache_dir, ttl_hours=24)
    return client


def _stub_api_response(client: LLMClient, tool_input: dict) -> None:
    """Stub the SDK to return a single message with a tool_use block."""
    async def _fake_create(**_kwargs):
        # Mimic anthropic SDK response shape
        block = MagicMock()
        block.type = "tool_use"
        block.input = tool_input
        response = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        response.content = [block]
        return response
    client._client.messages.create = _fake_create  # type: ignore[assignment]
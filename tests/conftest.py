"""Shared test fixtures."""

from __future__ import annotations

import pytest

from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery


@pytest.fixture
def settings() -> Settings:
    return Settings(
        anthropic_api_key="test-anthropic",
        tavily_api_key="test-tavily",
        cache_ttl_hours=1,
        output_dir=__import__("pathlib").Path("reports"),
    )


@pytest.fixture
def base_query() -> CompanyQuery:
    return CompanyQuery(company="阿里云", position="后端工程师", city="杭州")

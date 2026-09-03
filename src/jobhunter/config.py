"""Settings — pydantic-settings loaded from .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All fields can be overridden via environment variables or via a local
    .env file at the project root (bare KEY=... convention; case-insensitive).
    """

    model_config = SettingsConfigDict(
        # No env_prefix — .env files use bare KEY=... convention (ANTHROPIC_API_KEY, TAVILY_API_KEY)
        # which is the standard documented in .env.example. Setting a prefix here would force
        # users to write JOBHUNTER_ANTHROPIC_API_KEY in .env, which is unexpected.
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", description="Anthropic API key (required)")
    anthropic_base_url: str = Field(default="", description="Custom Anthropic endpoint (for ccswitch / relay proxies)")
    tavily_api_key: str = Field(default="", description="Tavily API key (required)")

    model: str = Field(default="claude-sonnet-4-5", description="Claude model id")
    max_tokens_per_call: int = Field(default=4096, ge=256, le=8000)
    budget_tokens_per_run: int = Field(default=200_000, ge=10_000)

    cache_ttl_hours: int = Field(default=24, ge=1)
    tavily_max_results: int = Field(default=10, ge=1, le=20)
    tavily_search_depth: str = Field(default="advanced", pattern="^(basic|advanced)$")
    tavily_rate_per_sec: float = Field(default=2.0, gt=0)

    collector_timeout_seconds: float = Field(default=60.0, gt=0)
    retry_attempts: int = Field(default=3, ge=1)
    retry_min_wait: float = Field(default=2.0, gt=0)
    retry_max_wait: float = Field(default=10.0, gt=0)

    output_dir: Path = Field(default=Path("reports"))
    cache_dir: Path = Field(default=Path(""))  # filled in __init__

    def is_ready(self) -> tuple[bool, list[str]]:
        """Return (ok, missing_keys). ok=True iff required keys are present."""
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        return (not missing, missing)


def load_settings(env_file: Path | None = None) -> Settings:
    """Load Settings, optionally with a custom .env path."""
    if env_file is not None:
        # pydantic-settings supports a single env_file; rebuild for this override
        return Settings(_env_file=str(env_file))
    return Settings()

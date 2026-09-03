"""Base collector interface. All collectors MUST implement `collect()`."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import CollectorResult
from jobhunter.search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract data collector.

    Concrete subclasses MUST set:
    - `name`: short id (e.g. "gsxt")
    - `domain`: one of "business" | "judicial" | "reviews" | "news"
    """

    name: ClassVar[str] = ""
    domain: ClassVar[str] = ""  # validated by CollectorResult Literal

    def __init__(
        self,
        settings: Settings,
        *,
        tavily: TavilyClient | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._tavily = tavily
        self._http = http

    @abstractmethod
    async def collect(self, query: CompanyQuery) -> CollectorResult: ...

    async def safe_collect(self, query: CompanyQuery) -> CollectorResult:
        """Wrap collect() with a hard timeout and never raise."""
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.collect(query), timeout=self._settings.collector_timeout_seconds
            )
        except asyncio.TimeoutError:
            result = CollectorResult(
                collector=self.name,
                domain=self.domain,  # type: ignore[arg-type]
                company_query=query,
                error=f"timeout_after_{self._settings.collector_timeout_seconds}s",
            )
        except Exception as e:  # noqa: BLE001 - intentional broad catch
            logger.warning("collector %s failed: %s", self.name, e)
            result = CollectorResult(
                collector=self.name,
                domain=self.domain,  # type: ignore[arg-type]
                company_query=query,
                error=f"{type(e).__name__}: {e}",
            )
        result.duration_seconds = time.monotonic() - start
        return result

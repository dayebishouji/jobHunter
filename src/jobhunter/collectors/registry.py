"""Registry of all built-in collectors."""

from __future__ import annotations

import httpx

from jobhunter.collectors.base import BaseCollector
from jobhunter.collectors.gsxt import GSXTCollector
from jobhunter.collectors.tavily_business import TavilyBusinessCollector
from jobhunter.collectors.tavily_judicial import TavilyJudicialCollector
from jobhunter.collectors.tavily_news import TavilyNewsCollector
from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
from jobhunter.collectors.wenshu import WenshuCollector
from jobhunter.config import Settings
from jobhunter.search.tavily_client import TavilyClient


def build_all(
    settings: Settings,
    *,
    tavily: TavilyClient,
    http: httpx.AsyncClient,
) -> list[BaseCollector]:
    """Construct all collectors with shared dependencies.

    GSXTCollector + WenshuCollector are direct-fetch (fail on non-CN IP).
    TavilyBusinessCollector + TavilyJudicialCollector are aggregator-backed
    fallbacks. On CN IP both may run; on non-CN IP only the Tavily ones succeed.
    `normalize()` combines their items by domain, so duplicates collapse naturally.
    """
    return [
        GSXTCollector(settings, http=http),
        TavilyBusinessCollector(settings, tavily=tavily),
        WenshuCollector(settings, http=http),
        TavilyJudicialCollector(settings, tavily=tavily),
        TavilyReviewsCollector(settings, tavily=tavily),
        TavilyNewsCollector(settings, tavily=tavily),
    ]


__all__ = ["BaseCollector", "build_all"]

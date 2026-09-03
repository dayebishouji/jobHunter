"""Registry of all built-in collectors."""

from __future__ import annotations

import httpx

from jobhunter.collectors.base import BaseCollector
from jobhunter.collectors.gsxt import GSXTCollector
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
    """Construct all collectors with shared dependencies."""
    return [
        GSXTCollector(settings, http=http),
        WenshuCollector(settings, http=http),
        TavilyReviewsCollector(settings, tavily=tavily),
        TavilyNewsCollector(settings, tavily=tavily),
    ]


__all__ = ["BaseCollector", "build_all"]

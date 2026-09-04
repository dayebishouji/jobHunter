"""Registry of all built-in collectors."""

from __future__ import annotations

import httpx

from jobhunter.collectors.base import BaseCollector
from jobhunter.collectors.gsxt import GSXTCollector
from jobhunter.collectors.sogou_weixin import SogouWeixinCollector
from jobhunter.collectors.tavily_business import TavilyBusinessCollector
from jobhunter.collectors.tavily_company_info import TavilyCompanyInfoCollector
from jobhunter.collectors.tavily_judicial import TavilyJudicialCollector
from jobhunter.collectors.tavily_news import TavilyNewsCollector
from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
from jobhunter.collectors.wenshu import WenshuCollector
from jobhunter.config import Settings
from jobhunter.search.cache import FileCache
from jobhunter.search.tavily_client import TavilyClient


def build_all(
    settings: Settings,
    *,
    tavily: TavilyClient,
    http: httpx.AsyncClient,
    cache: FileCache,
) -> list[BaseCollector]:
    """Construct all collectors with shared dependencies.

    GSXTCollector + WenshuCollector are direct-fetch (fail on non-CN IP).
    TavilyBusinessCollector + TavilyJudicialCollector + TavilyCompanyInfoCollector
    are aggregator-backed fallbacks. On CN IP both old + new may run; on non-CN
    IP only the Tavily ones succeed. SogouWeixinCollector is a v0.1.20
    direct-HTTP supplement for the reviews domain (微信公众号 full-text
    index). `normalize()` combines items by domain, so duplicates collapse.
    """
    return [
        GSXTCollector(settings, http=http),
        TavilyBusinessCollector(settings, tavily=tavily),
        WenshuCollector(settings, http=http),
        TavilyJudicialCollector(settings, tavily=tavily),
        TavilyCompanyInfoCollector(settings, tavily=tavily),
        TavilyReviewsCollector(settings, tavily=tavily),
        TavilyNewsCollector(settings, tavily=tavily),
        SogouWeixinCollector(settings, http=http, cache=cache),
    ]


__all__ = ["BaseCollector", "build_all"]

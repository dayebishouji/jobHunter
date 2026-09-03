"""Search layer — Tavily wrapper, query templates, cache."""

from jobhunter.search.cache import FileCache, default_cache_dir
from jobhunter.search.query_templates import (
    NEWS_DOMAINS,
    REVIEW_DOMAINS,
    news_queries,
    review_queries,
)
from jobhunter.search.tavily_client import TavilyClient

__all__ = [
    "FileCache",
    "NEWS_DOMAINS",
    "REVIEW_DOMAINS",
    "TavilyClient",
    "default_cache_dir",
    "news_queries",
    "review_queries",
]

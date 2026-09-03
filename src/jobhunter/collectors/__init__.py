"""Collector implementations and the registry."""

from jobhunter.collectors.base import BaseCollector
from jobhunter.collectors.gsxt import GSXTCollector
from jobhunter.collectors.registry import build_all
from jobhunter.collectors.tavily_news import TavilyNewsCollector
from jobhunter.collectors.tavily_reviews import TavilyReviewsCollector
from jobhunter.collectors.wenshu import WenshuCollector

__all__ = [
    "BaseCollector",
    "GSXTCollector",
    "TavilyNewsCollector",
    "TavilyReviewsCollector",
    "WenshuCollector",
    "build_all",
]

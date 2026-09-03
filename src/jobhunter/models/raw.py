"""Raw data shapes produced by collectors, before normalization/extraction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from jobhunter.models.query import CompanyQuery

Confidence = Literal["high", "medium", "low", "none"]


class RawItem(BaseModel):
    """A single fetched item from a collector."""

    source: str = Field(..., description="来源标识，如 'kaoyan.看准网'")
    url: HttpUrl
    title: str = ""
    snippet: str = ""
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict = Field(default_factory=dict, description="任何额外结构化字段")


class CollectorResult(BaseModel):
    """Result of one collector's run. Never empty — on failure carries `error`."""

    collector: str
    domain: Literal["business", "judicial", "reviews", "news", "company_info"]
    company_query: CompanyQuery
    items: list[RawItem] = Field(default_factory=list)
    error: str | None = None
    confidence: Confidence = "none"
    duration_seconds: float = 0.0

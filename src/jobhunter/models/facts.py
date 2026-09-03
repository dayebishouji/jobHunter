"""Structured facts produced by the LLM extraction step.

These pydantic models serve a dual purpose:
1. Schema passed to Anthropic `tool_use` for structured output enforcement
2. Template input to the HTML report
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

BusinessStatus = Literal["存续", "注销", "吊销", "迁出", "其他"]
Sentiment = Literal["positive", "neutral", "negative", "mixed"]
Role = Literal["被告", "原告", "第三人", "其他"]


# ---------- Business ----------

class Shareholder(BaseModel):
    name: str
    stake_pct: float | None = None
    contribution: str | None = None


class BusinessFacts(BaseModel):
    legal_rep: str | None = None
    established_at: date | None = None
    registered_capital: str | None = None
    paid_in_capital: str | None = None
    status: BusinessStatus | None = None
    address: str | None = None
    scope: str | None = None
    top_shareholders: list[Shareholder] = Field(default_factory=list)
    external_investments_count: int | None = None
    anomaly_listed: bool | None = None
    source_urls: list[HttpUrl] = Field(default_factory=list)


# ---------- Reviews ----------

class SalarySignal(BaseModel):
    position: str | None = None
    base_monthly_k: float | None = None
    bonus_months: float | None = None
    salary_total_months: int | None = None
    evidence: str = ""
    url: HttpUrl | None = None


class OvertimeSignal(BaseModel):
    pattern: Literal["996", "995", "大小周", "弹性", "不加班", "未知"] = "未知"
    intensity: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""
    url: HttpUrl | None = None


class TurnoverSignal(BaseModel):
    rate: Literal["low", "medium", "high", "unknown"] = "unknown"
    evidence: str = ""
    url: HttpUrl | None = None


class VibeSignal(BaseModel):
    sentiment: Sentiment = "neutral"
    evidence: str = ""
    url: HttpUrl | None = None


class JDGapSignal(BaseModel):
    jd_promise: str = ""
    reality: str = ""
    url: HttpUrl | None = None


class ReviewFacts(BaseModel):
    salary_signals: list[SalarySignal] = Field(default_factory=list)
    overtime_signals: list[OvertimeSignal] = Field(default_factory=list)
    turnover_signals: list[TurnoverSignal] = Field(default_factory=list)
    vibe_signals: list[VibeSignal] = Field(default_factory=list)
    jd_gap_signals: list[JDGapSignal] = Field(default_factory=list)
    source_urls: list[HttpUrl] = Field(default_factory=list)


# ---------- News ----------

class NewsItem(BaseModel):
    title: str
    summary: str = ""
    published_at: str | None = None  # ISO string; do not over-parse
    url: HttpUrl


class NewsFacts(BaseModel):
    items: list[NewsItem] = Field(default_factory=list)
    sentiment: Sentiment = "neutral"
    source_urls: list[HttpUrl] = Field(default_factory=list)


# ---------- Judicial ----------

class CaseItem(BaseModel):
    title: str
    role: Role = "其他"
    year: int | None = None
    url: HttpUrl | None = None


class JudicialFacts(BaseModel):
    case_count_total: int | None = None
    case_count_recent_year: int | None = None
    sample_cases: list[CaseItem] = Field(default_factory=list)
    enforcement_records: int | None = None
    source_urls: list[HttpUrl] = Field(default_factory=list)


# ---------- Aggregated (post-consolidation) ----------

class InferredClaim(BaseModel):
    claim: str = Field(..., description="LLM 推断；UI 上需打'推断'标签")
    grounding_evidence: list[HttpUrl] = Field(default_factory=list)


class AggregatedFindings(BaseModel):
    company_query_summary: str = ""
    business: BusinessFacts | None = None
    reviews: ReviewFacts | None = None
    news: NewsFacts | None = None
    judicial: JudicialFacts | None = None
    inferences: list[InferredClaim] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)

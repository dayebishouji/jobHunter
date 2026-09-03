"""Final report data assembled before Jinja2 rendering."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl
from typing import Literal

from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.scoring import AxisScore

Confidence = Literal["high", "medium", "low"]


class SourceEntry(BaseModel):
    domain: str
    title: str
    url: HttpUrl


class ReportData(BaseModel):
    query: CompanyQuery
    generated_at: datetime
    findings: AggregatedFindings | None = None
    axes: list[AxisScore] = Field(default_factory=list)
    business_facts: BusinessFacts | None = None
    review_facts: ReviewFacts | None = None
    news_facts: NewsFacts | None = None
    judicial_facts: JudicialFacts | None = None
    company_profile: CompanyProfile | None = None
    interview_questions: list[str] = Field(default_factory=list)
    sources: list[SourceEntry] = Field(default_factory=list)
    overall_confidence: Confidence = "low"
    # Per-chapter confidence (company / business / judicial / reviews / news + overall)
    # Drives the small 「数据充足 / 部分缺失 / 需人工核查」badge next to each
    # chapter title. Computed from whether raw items landed AND extract pulled
    # structured signal out of them.
    chapter_confidence: dict[str, Confidence] = Field(default_factory=dict)
    data_gaps: list[str] = Field(default_factory=list)

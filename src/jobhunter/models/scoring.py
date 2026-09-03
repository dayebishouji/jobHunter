"""5-axis risk scoring (deterministic heuristic, not LLM-driven)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class RiskAxis(str, Enum):
    OVERTIME = "overtime"
    SALARY_TRUST = "salary_trust"
    JUDICIAL = "judicial"
    BUSINESS = "business"
    CULTURE = "culture"


AXIS_LABELS_ZH: dict[RiskAxis, str] = {
    RiskAxis.OVERTIME: "加班强度",
    RiskAxis.SALARY_TRUST: "薪酬诚信",
    RiskAxis.JUDICIAL: "司法风险",
    RiskAxis.BUSINESS: "工商风险",
    RiskAxis.CULTURE: "文化氛围",
}


def axis_color(stars: int) -> str:
    """Map 1..5 stars to a CSS color token (green/yellow/red palette)."""
    if stars >= 4:
        return "good"
    if stars >= 3:
        return "warn"
    return "bad"


class AxisScore(BaseModel):
    axis: RiskAxis
    stars: int = Field(..., ge=1, le=5, description="1=最差，5=最好")
    rationale: str = Field("", description="中文一句话理由")
    evidence_urls: list[HttpUrl] = Field(default_factory=list)

    @property
    def label_zh(self) -> str:
        return AXIS_LABELS_ZH[self.axis]

    @property
    def color(self) -> str:
        return axis_color(self.stars)

"""Structured facts produced by the LLM extraction step.

These pydantic models serve a dual purpose:
1. Schema passed to Anthropic `tool_use` for structured output enforcement
2. Template input to the HTML report
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class NullTolerantListBase(BaseModel):
    """LLM sometimes returns `null` for list fields whose schema declares
    `default_factory=list`. Pydantic does not apply the default when value
    is explicitly null. This base coerces any field whose declared default
    is a list and whose incoming value is None into [].

    Also unwraps the `{"item": [...]}` envelope that some ccswitch / relay
    models emit for list fields (OpenAPI 3.1 single-item-array style).
    """

    @model_validator(mode="before")
    @classmethod
    def _null_lists_to_empty(cls, data):
        if not isinstance(data, dict):
            return data
        for field_name, field_info in cls.model_fields.items():
            v = data.get(field_name)
            if v is None:
                default = field_info.default_factory() if field_info.default_factory is not None else None
                if isinstance(default, list):
                    data[field_name] = []
            elif isinstance(v, dict) and field_info.default_factory is not None:
                # Unwrap {"item": [...]} → [...] when the field expects a list
                default = field_info.default_factory()
                if isinstance(default, list):
                    for inner in v.values():
                        if isinstance(inner, list):
                            data[field_name] = inner
                            break
        return data

BusinessStatus = Literal["存续", "注销", "吊销", "迁出", "其他"]
Sentiment = Literal["positive", "neutral", "negative", "mixed"]
Role = Literal["被告", "原告", "第三人", "其他"]


# ---------- Business ----------

class Shareholder(BaseModel):
    name: str
    stake_pct: float | None = None
    contribution: str | None = None


class BusinessFacts(NullTolerantListBase):
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

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v):
        """LLM may return equivalent phrasings ('在业', '正常运营', etc.).
        Snap to the closest enum value; anything unrecognised → '其他'.
        """
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        s = v.strip()
        if s in ("存续", "注销", "吊销", "迁出", "其他"):
            return s
        if s in ("在业", "正常", "正常运营", "存续中", "营业", "active", "Active"):
            return "存续"
        return "其他"


# ---------- Reviews ----------

class SalarySignal(BaseModel):
    position: str | None = None
    base_monthly_k: float | None = None
    bonus_months: float | None = None
    salary_total_months: int | None = None
    evidence: str = ""
    url: HttpUrl | None = None

    @field_validator("salary_total_months", mode="before")
    @classmethod
    def _coerce_total_months(cls, v):
        """LLM sometimes returns '15.4' as a string for total-months (e.g. "15.4薪").

        Coerce string-floats to int (rounded); reject anything we can't parse.
        """
        if v is None or isinstance(v, bool):
            return None if v is None else int(v)
        if isinstance(v, (int, float)):
            return round(float(v))
        if isinstance(v, str):
            try:
                return round(float(v))
            except (ValueError, TypeError):
                return None
        return None


class OvertimeSignal(BaseModel):
    pattern: Literal["996", "995", "大小周", "弹性", "不加班", "未知"] = "未知"
    intensity: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""
    url: HttpUrl | None = None

    @field_validator("pattern", mode="before")
    @classmethod
    def _coerce_pattern(cls, v):
        if v is None:
            return "未知"
        if not isinstance(v, str):
            return "未知"
        s = v.strip()
        if s in ("996", "995", "大小周", "弹性", "不加班", "未知"):
            return s
        # Synonyms
        if "大小周" in s or "周末" in s or "single-weekend" in s.lower():
            return "大小周"
        if "弹性" in s or "不加班" in s or "flex" in s.lower() or "no overtime" in s.lower():
            return "弹性"
        if "996" in s.replace(" ", "") or "12" in s:
            return "996"
        if "995" in s.replace(" ", ""):
            return "995"
        return "未知"

    @field_validator("intensity", mode="before")
    @classmethod
    def _coerce_intensity(cls, v):
        if not isinstance(v, str):
            return "medium"
        s = v.strip().lower()
        if s in ("low", "medium", "high"):
            return s
        # Chinese / English synonyms
        if s in ("低", "轻", "少见", "偶尔", "low/medium"):
            return "low"
        if s in ("中", "中等", "一般", "medium/high"):
            return "medium"
        if s in ("高", "重", "频繁", "严重", "天天"):
            return "high"
        return "medium"


class TurnoverSignal(BaseModel):
    rate: Literal["low", "medium", "high", "unknown"] = "unknown"
    evidence: str = ""
    url: HttpUrl | None = None

    @field_validator("rate", mode="before")
    @classmethod
    def _coerce_rate(cls, v):
        if not isinstance(v, str):
            return "unknown"
        s = v.strip().lower()
        if s in ("low", "medium", "high", "unknown"):
            return s
        if s in ("低", "少", "稳定"):
            return "low"
        if s in ("中", "中等"):
            return "medium"
        if s in ("高", "频繁", "严重"):
            return "high"
        return "unknown"


class VibeSignal(BaseModel):
    sentiment: Sentiment = "neutral"
    evidence: str = ""
    url: HttpUrl | None = None

    @field_validator("sentiment", mode="before")
    @classmethod
    def _coerce_sentiment(cls, v):
        if not isinstance(v, str):
            return "neutral"
        s = v.strip().lower()
        if s in ("positive", "neutral", "negative", "mixed"):
            return s
        if "正" in s or "好" in s or "positive" in s:
            return "positive"
        if "负" in s or "差" in s or "烂" in s or "negative" in s:
            return "negative"
        if "混" in s or "mixed" in s:
            return "mixed"
        return "neutral"


class JDGapSignal(BaseModel):
    jd_promise: str = ""
    reality: str = ""
    url: HttpUrl | None = None


class ReviewFacts(NullTolerantListBase):
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


class NewsFacts(NullTolerantListBase):
    items: list[NewsItem] = Field(default_factory=list)
    sentiment: Sentiment = "neutral"
    source_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _drop_url_missing(cls, v):
        """Drop news items that lack a URL — they're unverifiable and
        would fail NewsItem validation downstream."""
        if not isinstance(v, list):
            return v
        return [
            item for item in v
            if isinstance(item, dict) and item.get("url")
        ]

    @field_validator("sentiment", mode="before")
    @classmethod
    def _coerce_sentiment(cls, v):
        if not isinstance(v, str):
            return "neutral"
        s = v.strip().lower()
        if s in ("positive", "neutral", "negative", "mixed"):
            return s
        if "正" in s or "好" in s:
            return "positive"
        if "负" in s or "差" in s:
            return "negative"
        if "混" in s:
            return "mixed"
        return "neutral"


# ---------- Judicial ----------

class CaseItem(BaseModel):
    title: str
    role: Role = "其他"
    year: int | None = None
    url: HttpUrl | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, v):
        if not isinstance(v, str):
            return "其他"
        s = v.strip()
        if s in ("被告", "原告", "第三人", "其他"):
            return s
        if "原" in s or "plaintiff" in s.lower():
            return "原告"
        if "被" in s or "defendant" in s.lower():
            return "被告"
        if "第三" in s or "third" in s.lower():
            return "第三人"
        return "其他"


class JudicialFacts(NullTolerantListBase):
    case_count_total: int | None = None
    case_count_recent_year: int | None = None
    sample_cases: list[CaseItem] = Field(default_factory=list)
    enforcement_records: int | None = None
    source_urls: list[HttpUrl] = Field(default_factory=list)


# ---------- Aggregated (post-consolidation) ----------

class InferredClaim(BaseModel):
    claim: str = Field(..., description="LLM 推断；UI 上需打'推断'标签")
    grounding_evidence: list[HttpUrl] = Field(default_factory=list)

    @field_validator("grounding_evidence", mode="before")
    @classmethod
    def _unwrap_dict(cls, v):
        """Some ccswitch / relay models wrap single-element arrays in
        `{"item": ["url1"]}` (OpenAPI 3.1 single-item-array style). Unwrap.
        """
        if isinstance(v, dict):
            # Take the first list-shaped value
            for val in v.values():
                if isinstance(val, list):
                    return val
            return []
        if v is None:
            return []
        return v


class AggregatedFindings(NullTolerantListBase):
    company_query_summary: str = ""
    business: BusinessFacts | None = None
    reviews: ReviewFacts | None = None
    news: NewsFacts | None = None
    judicial: JudicialFacts | None = None
    inferences: list[InferredClaim] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)

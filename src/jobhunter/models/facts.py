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
            # Only guard fields whose declared default is a list
            if field_info.default_factory is None:
                continue
            default = field_info.default_factory()
            if not isinstance(default, list):
                continue
            v = data.get(field_name)
            if v is None:
                data[field_name] = []
            elif isinstance(v, list):
                pass  # already a list
            elif isinstance(v, dict):
                # Unwrap {"item": [...]} → [...] (OpenAPI 3.1 single-item-array quirk)
                unwrapped: list | None = None
                for inner in v.values():
                    if isinstance(inner, list):
                        unwrapped = inner
                        break
                data[field_name] = unwrapped if unwrapped is not None else []
            else:
                # Anything else (int, str, bool, …) → empty list
                data[field_name] = []
        return data

BusinessStatus = Literal["存续", "注销", "吊销", "迁出", "其他"]
Sentiment = Literal["positive", "neutral", "negative", "mixed"]
Role = Literal["被告", "原告", "第三人", "其他"]


def _coerce_signal_date(v):
    """v0.1.16 — shared date validator for review signal `published_at`.

    LLM may return date / datetime / ISO string / '2024年5月' / '未知'.
    Output: `date` instance on success; None otherwise.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, date):
        return v
    if hasattr(v, "isoformat"):
        try:
            return v.date() if hasattr(v, "date") else v  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s in ("未知", "?", "无", "约"):
        return None
    import re
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            return date(int(y), int(mo), int(d))
        except ValueError:
            return None
    m2 = re.search(r"(\d{4})[-/.年](\d{1,2})", s)
    if m2:
        y, mo = m2.groups()
        try:
            return date(int(y), int(mo), 1)
        except ValueError:
            return None
    # ISO fallback
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


# ---------- Business ----------

class Shareholder(BaseModel):
    name: str
    stake_pct: float | None = None
    contribution: str | None = None

    @field_validator("stake_pct", mode="before")
    @classmethod
    def _coerce_pct(cls, v):
        """LLM may return '35%' / '约 40' / '不详'. Pull a number; else None."""
        if v is None or isinstance(v, bool):
            return None if v is None else float(v)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            import re
            m = re.search(r"\d+(\.\d+)?", v.replace(",", ""))
            if m:
                try:
                    return float(m.group())
                except (ValueError, TypeError):
                    return None
        return None


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

    @field_validator("external_investments_count", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        """LLM often returns numeric counts as strings ("约 8 起", "10+", "未知").
        Coerce parseable strings to int; otherwise None."""
        if v is None or isinstance(v, bool):
            return None if v is None else int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            import re
            m = re.search(r"\d+", v.replace(",", ""))
            if m:
                try:
                    return int(m.group())
                except (ValueError, TypeError):
                    return None
        return None

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

    @field_validator("established_at", mode="before")
    @classmethod
    def _coerce_date(cls, v):
        """LLM often returns partial dates or '未知' / '约 2010 年'.
        Only accept a parseable YYYY-MM-DD; anything else → None."""
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s or s in ("未知", "未知", "约", "?", "无", "未知"):
                return None
            from datetime import date as _date
            try:
                return _date.fromisoformat(s)
            except ValueError:
                return None
        return None

    @field_validator("anomaly_listed", mode="before")
    @classmethod
    def _coerce_bool(cls, v):
        """LLM sometimes returns '否' / '是' / '未列入' instead of bool."""
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s in ("是", "有", "列入", "true", "True", "yes", "Yes", "1"):
                return True
            if s in ("否", "无", "未列入", "false", "False", "no", "No", "0", ""):
                return False
            return None
        return None


# ---------- Reviews ----------

class SalarySignal(NullTolerantListBase):
    position: str | None = None
    base_monthly_k: float | None = None
    salary_range_min_k: float | None = None
    salary_range_max_k: float | None = None
    bonus_months: float | None = None
    salary_total_months: int | None = None
    evidence: str = ""
    published_at: date | None = None  # v0.1.16 — when this signal was posted (for decay display)
    url: HttpUrl | None = None
    supporting_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_signal_date(cls, v):
        return _coerce_signal_date(v)

    @field_validator("base_monthly_k", "bonus_months", "salary_range_min_k", "salary_range_max_k", mode="before")
    @classmethod
    def _coerce_float(cls, v):
        """LLM often returns non-numeric strings ("面议", "20k-40k", "未知")
        for numeric fields. Coerce parseable strings to float; anything we
        can't read becomes None so the signal still validates."""
        if v is None or isinstance(v, bool):
            return None if v is None else float(v)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip()
            # Pull a leading/first numeric token from strings like "20k-40k" or "20K"
            import re
            m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
            if m:
                try:
                    return float(m.group(0))
                except (ValueError, TypeError):
                    return None
        return None

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


class OvertimeSignal(NullTolerantListBase):
    pattern: Literal["996", "995", "大小周", "弹性", "不加班", "未知"] = "未知"
    intensity: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""
    published_at: date | None = None  # v0.1.16 — when this signal was posted
    url: HttpUrl | None = None
    supporting_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_signal_date(cls, v):
        return _coerce_signal_date(v)

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


class TurnoverSignal(NullTolerantListBase):
    rate: Literal["low", "medium", "high", "unknown"] = "unknown"
    evidence: str = ""
    published_at: date | None = None  # v0.1.16 — when this signal was posted
    url: HttpUrl | None = None
    supporting_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_signal_date(cls, v):
        return _coerce_signal_date(v)

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


class VibeSignal(NullTolerantListBase):
    sentiment: Sentiment = "neutral"
    evidence: str = ""
    published_at: date | None = None  # v0.1.16 — when this signal was posted
    url: HttpUrl | None = None
    supporting_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_signal_date(cls, v):
        return _coerce_signal_date(v)

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


class InterviewSignal(BaseModel):
    """v0.1.15 — Interview-process fact extracted from review UGC.

    Captures one observation about how this company runs interviews
    (round count, question types, difficulty), with evidence + url so the
    reader can sanity-check against the original post.
    """
    aspect: Literal["rounds", "style", "difficulty", "process", "feedback"] = "process"
    observation: str = ""  # e.g. "3 轮技术面 + 1 轮 HR"
    evidence: str = ""
    url: HttpUrl | None = None


class SlangEntry(BaseModel):
    """A workplace / internet slang term surfaced in UGC reviews,
    with a plain-Chinese gloss so report readers can parse it."""
    term: str = Field(..., min_length=1, max_length=20)
    meaning: str = Field(default="", max_length=200)
    count: int = 1
    url: HttpUrl | None = None

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, v):
        if v is None or isinstance(v, bool):
            return 1 if v is None else int(v)
        if isinstance(v, int):
            return max(1, v)
        if isinstance(v, float):
            return max(1, int(v))
        if isinstance(v, str):
            import re
            m = re.search(r"\d+", v.replace(",", ""))
            return max(1, int(m.group())) if m else 1
        return 1

    @field_validator("term", mode="before")
    @classmethod
    def _coerce_term(cls, v):
        """LLM sometimes emits numeric slang like `996` as an int. Coerce."""
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return str(v)
        return v


class ReviewFacts(NullTolerantListBase):
    salary_signals: list[SalarySignal] = Field(default_factory=list)
    overtime_signals: list[OvertimeSignal] = Field(default_factory=list)
    turnover_signals: list[TurnoverSignal] = Field(default_factory=list)
    vibe_signals: list[VibeSignal] = Field(default_factory=list)
    jd_gap_signals: list[JDGapSignal] = Field(default_factory=list)
    slang_glossary: list[SlangEntry] = Field(default_factory=list)
    source_urls: list[HttpUrl] = Field(default_factory=list)
    # v0.1.15 — Interview-process snapshot (typical rounds / style / difficulty).
    # Driven by InterviewSignal.aspect so the LLM can capture heterogeneous
    # observations (some posts mention rounds, others mention question style).
    interview_rounds: int | None = None
    interview_style: list[str] = Field(default_factory=list)
    interview_difficulty: Literal["easy", "medium", "hard", "未知"] | None = None
    interview_signals: list[InterviewSignal] = Field(default_factory=list)

    # v0.1.21 — UGC-extracted canonical answer for "what time does the team
    # typically leave the office?". Free-text so we keep ambiguity (some teams
    # are 弹性 9-6, some are rigid 10 PM) rather than coercing to an enum.
    typical_off_time: str | None = None  # e.g. "约 10:00 PM" / "弹性 9-6" / "21 点左右"
    typical_off_time_evidence: str = ""  # short quoted line, ≤30 字
    typical_off_time_url: HttpUrl | None = None

    @field_validator("typical_off_time_url", mode="before")
    @classmethod
    def _coerce_off_time_url(cls, v):
        """v0.3.2 hotfix — LLM sometimes returns `""` (empty string) for
        typical_off_time_url when no source URL is available. Pydantic v2
        treats empty string as invalid URL even though the field type is
        `HttpUrl | None`; coerce blank / whitespace values to None so the
        run doesn't crash on the validation step."""
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v


# ---------- News ----------

class NewsItem(BaseModel):
    title: str
    summary: str = ""
    published_at: str | None = None  # ISO string; do not over-parse

    @field_validator("published_at", mode="before")
    @classmethod
    def _coerce_published_at(cls, v):
        """LLM sometimes returns dates as date / datetime objects, None, or
        loose strings like '2024 年 5 月'. Coerce parseable dates to ISO
        YYYY-MM-DD; otherwise drop to None."""
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            try:
                return v.isoformat()[:10]
            except Exception:  # noqa: BLE001
                return None
        if not isinstance(v, str):
            return None
        s = v.strip()
        if not s or s in ("未知", "未知", "?", "无", "约"):
            return None
        # Strip Chinese date markers
        import re
        m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        m2 = re.search(r"(\d{4})[-/.年](\d{1,2})", s)
        if m2:
            y, mo = m2.groups()
            return f"{int(y):04d}-{int(mo):02d}-01"
        return s  # leave it as-is and let downstream try

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

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_year(cls, v):
        """LLM sometimes returns '2023年' / '约 2024' / '2023-01' for case year.
        Extract a 4-digit year; otherwise drop to None."""
        if v is None or isinstance(v, bool):
            return None if v is None else None
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            import re
            m = re.search(r"\b(?:19|20)\d{2}\b", v)
            if m:
                return int(m.group())
            try:
                return int(float(v.strip().rstrip("年").strip()))
            except (ValueError, TypeError):
                return None
        return None


class JudicialFacts(NullTolerantListBase):
    case_count_total: int | None = None
    case_count_recent_year: int | None = None
    sample_cases: list[CaseItem] = Field(default_factory=list)
    enforcement_records: int | None = None
    source_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("case_count_total", "case_count_recent_year", "enforcement_records", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        """LLM often returns numeric counts as strings ("约 8 起", "10+", "未知").
        Coerce parseable strings to int; otherwise None."""
        if v is None or isinstance(v, bool):
            return None if v is None else int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            import re
            m = re.search(r"\d+", v.replace(",", ""))
            if m:
                try:
                    return int(m.group())
                except (ValueError, TypeError):
                    return None
        return None


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
    company_profile: "CompanyProfile | None" = None
    inferences: list[InferredClaim] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


# ---------- Company profile ----------

class CompanyProfile(NullTolerantListBase):
    """Structured company-profile facts extracted from encyclopedia / startup
    databases / aggregator pages. Distinct from BusinessFacts (legal registration)
    — this captures qualitative info: what the company does, where it's headed,
    its size/funding."""

    description: str | None = None  # 一句话简介
    official_website: HttpUrl | None = None
    main_business: list[str] = Field(default_factory=list)  # 主营业务 / 经营范围概括
    products: list[str] = Field(default_factory=list)  # 主要产品 / 产品线
    industries: list[str] = Field(default_factory=list)  # 所属行业
    company_size: str | None = None  # e.g. "100-500人" / "5000-10000人"
    # v0.1.21 — Actual employee count from 天眼查 / 招聘 / 官网. Distinct from
    # `company_size` which is a band string ("100-500人") — `employee_count`
    # is the precise integer when available, e.g. "1,200 人".
    employee_count: int | None = None
    # v0.1.21 — Social insurance participants (社保参保人数). Strongest public
    # proxy for actual workforce — much higher signal than registered scale.
    # Often missing for very small / private companies; null is fine.
    insured_count: int | None = None
    founded_year: int | None = None
    funding_stage: str | None = None  # 天使 / A轮 / B轮 / C轮 / D轮及以上 / 已上市 / 未融资
    total_funding: str | None = None  # 累计融资额 e.g. "约 5 亿元"
    investors: list[str] = Field(default_factory=list)
    headquarters: str | None = None  # 总部所在地
    prospects: str | None = None  # 发展前景概述（基于新闻 + 财报 + 公开战略）
    source_urls: list[HttpUrl] = Field(default_factory=list)

    @field_validator("founded_year", mode="before")
    @classmethod
    def _coerce_year(cls, v):
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            import re
            m = re.search(r"\b(?:19|20)\d{2}\b", v)
            if m:
                return int(m.group())
            try:
                return int(float(v.strip().rstrip("年").strip()))
            except (ValueError, TypeError):
                return None
        return None

    @field_validator("employee_count", "insured_count", mode="before")
    @classmethod
    def _coerce_count(cls, v):
        """v0.1.21 — Coerce messy LLM strings into a plain int.

        Accepts: 1200, "1200", "1,200", "约 1200 人", "1200余人", "1200+".
        Returns None for unparseable strings ("未知", "未披露", "N/A").
        """
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if not isinstance(v, str):
            return None
        s = v.strip()
        if not s:
            return None
        # Strip the noise Chinese LLMs add: 约/近/余/大概 + 人 suffix + ,
        import re
        s = re.sub(r"[,\s]", "", s)
        s = re.sub(r"(约|近|大概|大约|余|超过|左右)", "", s)
        s = re.sub(r"(人|名|位|余)$", "", s)
        s = s.rstrip("+")
        if not s or s in ("未知", "未披露", "N/A", "—", "-"):
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

    @field_validator("official_website", mode="before")
    @classmethod
    def _coerce_website(cls, v):
        """LLM often returns bare hostnames like 'example.com' (no scheme) or
        with trailing slashes / paths. Normalize to a real URL or None."""
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            return None
        s = v.strip().rstrip("/")
        if not s:
            return None
        if not s.startswith(("http://", "https://")):
            s = "https://" + s
        # Drop any path beyond the first segment
        from urllib.parse import urlparse
        parsed = urlparse(s)
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
        return None

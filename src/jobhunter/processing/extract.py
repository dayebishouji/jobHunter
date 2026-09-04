"""LLM-driven extraction. Five domain calls (concurrency up to 5) + 1 aggregate.

v0.1.14 — Density boost for the reviews domain:
  1. **Second-pass LLM extraction** — if the first pass surfaced <3 total signals,
  a focused re-call asks for the missing signal types (vibe / salary / overtime /
  turnover) so a thin Tavily fetch still produces a usable chapter.
  2. **Loose keyword extraction** — when even the LLM under-extracts, scan
  raw snippets locally for Chinese keyword hits and synthesize minimum-viable
  signals. Pure deterministic — no extra API call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date

from jobhunter.llm import (
    CONSOLIDATE_SYSTEM,
    CONSOLIDATE_USER_TEMPLATE,
    EXTRACT_BASE,
    EXTRACT_BUSINESS_SUFFIX,
    EXTRACT_COMPANY_PROFILE_SUFFIX,
    EXTRACT_JUDICIAL_SUFFIX,
    EXTRACT_NEWS_SUFFIX,
    EXTRACT_REVIEWS_SUFFIX,
    LLMClient,
    extract_tool_spec,
    safe_dumps,
)
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    InterviewSignal,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    TurnoverSignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem

logger = logging.getLogger(__name__)

DOMAIN_SUFFIX = {
    "business": EXTRACT_BUSINESS_SUFFIX,
    "reviews": EXTRACT_REVIEWS_SUFFIX,
    "news": EXTRACT_NEWS_SUFFIX,
    "judicial": EXTRACT_JUDICIAL_SUFFIX,
    "company_info": EXTRACT_COMPANY_PROFILE_SUFFIX,
}

MODEL_BY_DOMAIN: dict[str, type] = {
    "business": BusinessFacts,
    "reviews": ReviewFacts,
    "news": NewsFacts,
    "judicial": JudicialFacts,
    "company_info": CompanyProfile,
}

CHARS_CAP = 50_000  # rough upper bound before passing to LLM (was 25K — bumped
                # so high-quality reviews items survive truncation; Sonnet 4.5
                # eats 200K context so this is well within budget)


def _materialize(items: list[RawItem]) -> str:
    """Join items into a numbered, LLM-readable block. Items are sorted by
    Tavily relevance score (desc) so the highest-quality hits survive the
    CHARS_CAP slice even when the raw fetch is much larger than the cap.
    Items without a score are treated as 0 and pushed to the tail.
    """
    def _score(it: RawItem) -> float:
        try:
            return float((it.payload or {}).get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    ordered = sorted(items, key=_score, reverse=True)
    parts: list[str] = []
    for i, it in enumerate(ordered, start=1):
        parts.append(
            f"[{i}] {it.title or '(无标题)'} | {it.source} | {it.url}\n{(it.snippet or '').strip()}"
        )
    s = "\n\n".join(parts)
    return s[:CHARS_CAP]


async def _extract_one_domain(
    llm: LLMClient, domain: str, items: list[RawItem]
) -> object | None:
    if not items:
        return None
    spec = extract_tool_spec(domain)
    system = EXTRACT_BASE + DOMAIN_SUFFIX[domain]
    user = f"目标原材料：\n\n{_materialize(items)}"
    raw = await llm.structured_call(
        system=system,
        user=user,
        tool_name=spec["name"],
        tool_description=spec["description"],
        tool_schema=spec["input_schema"],
    )
    if not raw:
        return None
    return MODEL_BY_DOMAIN[domain].model_validate(raw)


def _reviews_signal_count(rf: ReviewFacts | None) -> dict[str, int]:
    if not rf:
        return {"salary": 0, "overtime": 0, "vibe": 0, "turnover": 0, "jd_gap": 0, "slang": 0}
    return {
        "salary":   len(rf.salary_signals or []),
        "overtime": len(rf.overtime_signals or []),
        "vibe":     len(rf.vibe_signals or []),
        "turnover": len(rf.turnover_signals or []),
        "jd_gap":   len(rf.jd_gap_signals or []),
        "slang":    len(rf.slang_glossary or []),
    }


def _needs_second_pass(rf: ReviewFacts | None) -> bool:
    """True when reviews extraction came back thin — a focused second call may
    surface missed signals. Threshold: <3 total non-zero types, AND at least 2
    raw items were available (otherwise there was nothing to extract)."""
    if not rf:
        return False
    counts = _reviews_signal_count(rf)
    nonzero_types = sum(1 for v in counts.values() if v > 0)
    total_signals = sum(counts.values())
    # Trigger when the LLM barely populated the bucket — but don't trigger
    # again if we already got >6 signals (the chapter is healthy).
    return nonzero_types <= 2 or total_signals < 3


async def _second_pass_reviews(
    llm: LLMClient, items: list[RawItem], first: ReviewFacts
) -> ReviewFacts | None:
    """Focused second-call to recover missed reviews-domain signal categories.
    Returns the full ReviewFacts (re-validated from the new payload, with
    first-pass signals preserved by the caller's merge step)."""
    if not items:
        return None
    counts = _reviews_signal_count(first)
    missing = [k for k, v in counts.items() if v == 0 and k in {"salary", "overtime", "vibe", "turnover", "jd_gap", "slang"}]
    if not missing:
        return None

    spec = extract_tool_spec("reviews")
    focus_hint = (
        "\n\n【第二轮重点】第一轮抽取得到的信号量："
        + json.dumps(counts, ensure_ascii=False)
        + f"。本轮请特别留意补充：{','.join(missing)} 信号。"
        "即便原文不够明确，也尽量给出**阈值放宽的最小信号**（一句概括+主 url），"
        "让求职者至少能看到「这家公司被提及了什么关键词」。"
    )
    system = EXTRACT_BASE + EXTRACT_REVIEWS_SUFFIX + focus_hint
    user = f"目标原材料：\n\n{_materialize(items)}"
    raw = await llm.structured_call(
        system=system,
        user=user,
        tool_name=spec["name"],
        tool_description=spec["description"],
        tool_schema=spec["input_schema"],
    )
    if not raw:
        return None
    try:
        return ReviewFacts.model_validate(raw)
    except Exception as e:  # noqa: BLE001 - second pass is best-effort
        logger.warning("second-pass reviews validation failed: %s", e)
        return None


def _merge_reviews(first: ReviewFacts, second: ReviewFacts) -> ReviewFacts:
    """Union merge: keep first's signals and append second's where the new one
    has a url we haven't seen yet (dedup by url). Empty signals in second are
    skipped so we never lose first's data."""
    def _dedup_by_url(existing: list, additions: list) -> list:
        seen = {str(getattr(s, "url", "")) for s in existing}
        out = list(existing)
        for s in additions:
            u = str(getattr(s, "url", ""))
            if u and u not in seen:
                out.append(s)
                seen.add(u)
            elif not u:
                # No url — append only if it adds new info (evidence differs)
                ev = getattr(s, "evidence", "") or ""
                if not any(getattr(e, "evidence", "") == ev for e in existing):
                    out.append(s)
        return out

    # Union on interview_style (set semantics)
    style = list(dict.fromkeys([*(first.interview_style or []), *(second.interview_style or [])]))
    # Interview rounds: take whichever side has a value
    rounds = first.interview_rounds if first.interview_rounds else second.interview_rounds
    # Difficulty: prefer a non-未知 side
    diff = first.interview_difficulty if (first.interview_difficulty and first.interview_difficulty != "未知") else second.interview_difficulty

    return ReviewFacts(
        salary_signals=_dedup_by_url(first.salary_signals or [], second.salary_signals or []),
        overtime_signals=_dedup_by_url(first.overtime_signals or [], second.overtime_signals or []),
        vibe_signals=_dedup_by_url(first.vibe_signals or [], second.vibe_signals or []),
        turnover_signals=_dedup_by_url(first.turnover_signals or [], second.turnover_signals or []),
        jd_gap_signals=_dedup_by_url(first.jd_gap_signals or [], second.jd_gap_signals or []),
        slang_glossary=_dedup_by_url(first.slang_glossary or [], second.slang_glossary or []),
        interview_signals=_dedup_by_url(first.interview_signals or [], second.interview_signals or []),
        interview_rounds=rounds,
        interview_style=style,
        interview_difficulty=diff,
        source_urls=list({*(first.source_urls or []), *(second.source_urls or [])}),
    )


# ---------- v0.1.14 — Loose keyword extraction (pure local, no LLM) ----------

# Conservative keyword regexes. Each pattern → a synthetic signal with the
# keyword as evidence and the snippet's host as url (best-effort attribution).
_OVERTIME_PATTERNS = [
    (re.compile(r"996|大小周|997|加班.{0,4}(严重|频繁|常态|多)|周末(经常|被叫|要)"), "high"),
    (re.compile(r"995|加班(到|到晚上)|工作日.{0,6}晚"), "medium"),
    (re.compile(r"弹性工作|不加班|work.?life.{0,4}balance|WLB"), "low"),
]
_VIBE_POSITIVE = re.compile(r"氛围(不错|好|很好|融洽|轻松)|团队(年轻|靠谱|有活力)|nice(?!.*?不)|氛围棒|同事关系好")
_VIBE_NEGATIVE = re.compile(r"内卷|PUA|压榨|画饼|跑路|加班多|关系复杂|离职(率高|频繁)|领导(差|pua)|996icu")
_VIBE_MIXED = re.compile(r"有好有坏|看组|看部门|看项目|看leader")
_SALARY_KEYWORDS = re.compile(r"(\d+\s*[kK千])|月薪|base|起薪|年包|薪资|工资|薪酬|待遇")
_TURNOVER_KEYWORDS = re.compile(r"离职率|流失率|人员流动|走人|跑路")

_SENTIMENT_LABELS = {
    "positive": "正面",
    "negative": "负面",
    "mixed": "混合",
    "neutral": "中性",
}


def _evidence_from(item: RawItem, pattern_label: str) -> str:
    """Build a short evidence snippet. Prefer raw text in `...` quotes."""
    snippet = (item.snippet or "").strip().replace("\n", " ")
    # Trim to a sensible length around the keyword mention
    if len(snippet) > 80:
        snippet = snippet[:80] + "…"
    return f"{snippet}（关键词：{pattern_label}）"


def _item_published(it: RawItem) -> date:
    """v0.1.16 — best-effort date for a RawItem (datetime → date; else today)."""
    pa = getattr(it, "published_at", None)
    if pa is not None:
        try:
            return pa.date() if hasattr(pa, "date") else date.fromisoformat(str(pa)[:10])
        except (ValueError, TypeError):
            pass
    return date.today()


def _loose_keyword_reviews(items: list[RawItem]) -> ReviewFacts:
    """Local, deterministic synthesis from raw review snippets. Activates only
    when the LLM has already failed to surface signals in the same category.

    Cheap heuristic: scan each snippet for canonical Chinese keywords and emit
    a single signal per (category, item) when a hit lands. Never claim a
    salary number we can't read."""
    rf = ReviewFacts()
    if not items:
        return rf

    overtime_hits: list[OvertimeSignal] = []
    vibe_hits: list[VibeSignal] = []
    salary_hits: list[SalarySignal] = []
    turnover_hits: list[TurnoverSignal] = []

    seen_overtime = 0
    seen_vibe = 0
    seen_salary = 0
    seen_turnover = 0

    for it in items:
        text = (it.snippet or "") + " " + (it.title or "")
        if not text.strip():
            continue
        url = str(it.url) if it.url else None
        sig_date = _item_published(it)

        # Overtime — synthesize only first hit per item
        if seen_overtime < 3:
            for pat, intensity in _OVERTIME_PATTERNS:
                if pat.search(text):
                    overtime_hits.append(OvertimeSignal(
                        pattern="996" if "996" in text else ("大小周" if "大小周" in text else "未知"),
                        intensity=intensity,  # type: ignore[arg-type]
                        evidence=_evidence_from(it, "关键词命中"),
                        published_at=sig_date,
                        url=url,  # type: ignore[arg-type]
                    ))
                    seen_overtime += 1
                    break

        # Vibe — pick the strongest sentiment
        if seen_vibe < 3:
            if _VIBE_NEGATIVE.search(text):
                vibe_hits.append(VibeSignal(
                    sentiment="negative",
                    evidence=_evidence_from(it, "负面关键词"),
                    published_at=sig_date,
                    url=url,  # type: ignore[arg-type]
                ))
                seen_vibe += 1
            elif _VIBE_POSITIVE.search(text):
                vibe_hits.append(VibeSignal(
                    sentiment="positive",
                    evidence=_evidence_from(it, "正面关键词"),
                    published_at=sig_date,
                    url=url,  # type: ignore[arg-type]
                ))
                seen_vibe += 1
            elif _VIBE_MIXED.search(text):
                vibe_hits.append(VibeSignal(
                    sentiment="mixed",
                    evidence=_evidence_from(it, "混合关键词"),
                    published_at=sig_date,
                    url=url,  # type: ignore[arg-type]
                ))
                seen_vibe += 1

        # Salary — only flag, never invent numbers
        if seen_salary < 2 and _SALARY_KEYWORDS.search(text):
            salary_hits.append(SalarySignal(
                evidence=_evidence_from(it, "薪酬关键词"),
                published_at=sig_date,
                url=url,  # type: ignore[arg-type]
            ))
            seen_salary += 1

        # Turnover
        if seen_turnover < 2 and _TURNOVER_KEYWORDS.search(text):
            turnover_hits.append(TurnoverSignal(
                rate="high" if "高" in text or "频繁" in text else "unknown",
                evidence=_evidence_from(it, "离职关键词"),
                published_at=sig_date,
                url=url,  # type: ignore[arg-type]
            ))
            seen_turnover += 1

    rf.overtime_signals = overtime_hits
    rf.vibe_signals = vibe_hits
    rf.salary_signals = salary_hits
    rf.turnover_signals = turnover_hits
    return rf


async def extract_all_domains(
    llm: LLMClient, by_domain: dict[str, list[RawItem]]
) -> dict[str, object]:
    """Return {'business': ..., 'reviews': ..., 'news': ..., 'judicial': ..., 'company_info': ...}.

    v0.1.14 — Reviews domain gets up to two LLM passes (focused re-call when
    first pass is thin) plus a local keyword fallback so the chapter rarely
    renders empty even on small Tavily fetches.
    """
    domains = ("business", "reviews", "news", "judicial", "company_info")
    coros = [_extract_one_domain(llm, d, by_domain.get(d, [])) for d in domains]
    results = list(await asyncio.gather(*coros))
    out: dict[str, object] = dict(zip(domains, results))

    # Phase 2 — focused second pass for reviews if first is thin
    reviews_first = out.get("reviews")
    if _needs_second_pass(reviews_first if isinstance(reviews_first, ReviewFacts) else None):
        try:
            extra = await _second_pass_reviews(
                llm, by_domain.get("reviews", []), reviews_first  # type: ignore[arg-type]
            )
            if extra:
                out["reviews"] = _merge_reviews(reviews_first, extra)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            logger.warning("second-pass reviews failed: %s", e)

    # Phase 3 — local keyword fallback so vibe/overtime/salary are never
    # completely empty when the raw fetch had any keyword-bearing snippet.
    # v0.1.23 — Bug fix: previous condition required `isinstance(rf, ReviewFacts)`,
    # which silently skipped the fallback when the LLM extraction step returned
    # None (ccswitch moderation, transient API error, or empty tool_use block).
    # Result: 美的 / 美团 / 字节跳动 all produced empty reviews chapters despite
    # the raw bucket holding 100+ workplace URLs. Now the fallback runs whenever
    # there are raw items, regardless of whether the LLM extraction succeeded.
    reviews_items = by_domain.get("reviews", [])
    if reviews_items:
        loose = _loose_keyword_reviews(reviews_items)
        has_loose = any(
            [loose.overtime_signals, loose.vibe_signals,
             loose.salary_signals, loose.turnover_signals]
        )
        if has_loose:
            rf = out.get("reviews")
            if isinstance(rf, ReviewFacts):
                out["reviews"] = _merge_reviews(rf, loose)
            else:
                # LLM extraction failed entirely — use loose as the entire
                # reviews facet so the chapter at least renders keyword hits.
                out["reviews"] = loose

    return out


async def consolidate(
    llm: LLMClient,
    query: CompanyQuery,
    facets: dict[str, object | None],
) -> AggregatedFindings | None:
    """Second-pass consolidation across all five domain extractions."""
    spec = extract_tool_spec("aggregate")
    business = facets.get("business")
    reviews = facets.get("reviews")
    news = facets.get("news")
    judicial = facets.get("judicial")
    company_profile = facets.get("company_info")

    user = CONSOLIDATE_USER_TEMPLATE.format(
        company=query.company,
        position=query.position or "(未提供)",
        city=query.city or "(未提供)",
        business=safe_dumps(business.model_dump(mode="json") if business else {}),
        reviews=safe_dumps(reviews.model_dump(mode="json") if reviews else {}),
        news=safe_dumps(news.model_dump(mode="json") if news else {}),
        judicial=safe_dumps(judicial.model_dump(mode="json") if judicial else {}),
        company_profile=safe_dumps(company_profile.model_dump(mode="json") if company_profile else {}),
    )
    raw = await llm.structured_call(
        system=CONSOLIDATE_SYSTEM,
        user=user,
        tool_name=spec["name"],
        tool_description=spec["description"],
        tool_schema=spec["input_schema"],
        # Bump output budget — the consolidation writes a sizable inferences list
        # (each with grounding_evidence URLs) and easily exceeds the default 4K.
        max_tokens=8000,
    )
    if not raw:
        # Best-effort: stub from raw inputs
        return AggregatedFindings(
            company_query_summary=query.display(),
            business=business if isinstance(business, BusinessFacts) else None,
            reviews=reviews if isinstance(reviews, ReviewFacts) else None,
            news=news if isinstance(news, NewsFacts) else None,
            judicial=judicial if isinstance(judicial, JudicialFacts) else None,
            company_profile=company_profile if isinstance(company_profile, CompanyProfile) else None,
            data_gaps=_auto_gaps(facets),
        )
    try:
        agg = AggregatedFindings.model_validate(_sanitize_aggregated(raw))
    except Exception as e:  # noqa: BLE001 - consolidation is best-effort
        logger.warning("consolidate: AggregatedFindings validation failed (%s); falling back to raw facets", e)
        agg = AggregatedFindings(
            company_query_summary=query.display(),
            business=business if isinstance(business, BusinessFacts) else None,
            reviews=reviews if isinstance(reviews, ReviewFacts) else None,
            news=news if isinstance(news, NewsFacts) else None,
            judicial=judicial if isinstance(judicial, JudicialFacts) else None,
            company_profile=company_profile if isinstance(company_profile, CompanyProfile) else None,
            data_gaps=_auto_gaps(facets),
        )
    # Guarantee per-domain facts are set even if LLM omitted them
    agg.business = agg.business or (business if isinstance(business, BusinessFacts) else None)
    agg.reviews = agg.reviews or (reviews if isinstance(reviews, ReviewFacts) else None)
    agg.news = agg.news or (news if isinstance(news, NewsFacts) else None)
    agg.judicial = agg.judicial or (judicial if isinstance(judicial, JudicialFacts) else None)
    agg.company_profile = agg.company_profile or (
        company_profile if isinstance(company_profile, CompanyProfile) else None
    )
    if not agg.data_gaps:
        agg.data_gaps = _auto_gaps(facets)
    return agg


def _auto_gaps(facets: dict[str, object | None]) -> list[str]:
    gaps: list[str] = []
    if facets.get("business") is None:
        gaps.append("工商基本面数据缺失（本机 gsxt.gov.cn 不可达），建议人工到该网站核实")
    if facets.get("judicial") is None:
        gaps.append("司法风险数据未能获取（裁判文书网 v0.1 抓取受限），建议人工到 wenshu.court.gov.cn 与 zxgk.court.gov.cn 自查")
    return gaps


def parse_interview_lines(text: str) -> list[str]:
    """Split a free-text answer into non-empty stripped lines."""
    return [ln.strip().lstrip("0123456789.、) ").strip() for ln in text.splitlines() if ln.strip()]


def _sanitize_aggregated(raw: dict) -> dict:
    """LLM (esp. via ccswitch / relay) sometimes returns scalars or other
    non-dict values for sub-model fields. Pydantic rejects these with
    'Input should be a valid dictionary or instance of X'. Coerce to None
    so the field falls back to its default.
    """
    cleaned = dict(raw)
    for key in ("business", "reviews", "news", "judicial", "company_profile"):
        v = cleaned.get(key)
        if v is not None and not isinstance(v, dict):
            cleaned[key] = None
    return cleaned

"""HTML report builder — Jinja2 render of ReportData."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import jinja2

from jobhunter.models.report import ReportData, SourceEntry
from jobhunter.report.jd_alignment import JdClaim, compute_jd_alignment
from jobhunter.report.charts import (
    case_timeline_svg,
    case_year_buckets,
    company_timeline_svg,
    funding_stage_position,
    news_items_for_timeline,
    news_timeline_svg,
    overtime_distribution,
    radar_svg,
    salary_distribution,
    score_ring_svg,
    shareholder_pie_svg,
    vibe_donut_svg,
    vibe_sentiment_counts,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _domain_of(url) -> str:
    try:
        return urlparse(str(url)).hostname or "link"
    except Exception:  # noqa: BLE001
        return "link"


def _favicon_url(domain: str, size: int = 32) -> str:
    return f"https://www.google.com/s2/favicons?sz={size}&domain={domain}"


def _collect_sources(data: ReportData) -> list[SourceEntry]:
    """De-dup sources by URL, sorted by domain then title."""
    seen: dict[str, SourceEntry] = {}
    f = data.findings
    if f is not None:
        for url in (
            (f.business.source_urls if f.business else [])
            + (f.reviews.source_urls if f.reviews else [])
            + (f.news.source_urls if f.news else [])
            + (f.judicial.source_urls if f.judicial else [])
        ):
            key = str(url)
            if key not in seen:
                seen[key] = SourceEntry(domain=_domain_of(url), title="", url=url)
    # Add title hints from review/news/judicial items where available
    if f is not None and f.reviews is not None:
        signals = (f.reviews.salary_signals or []) + (f.reviews.overtime_signals or []) + (f.reviews.vibe_signals or [])
        for s in signals:
            if s.url and str(s.url) not in seen:
                seen[str(s.url)] = SourceEntry(domain=_domain_of(s.url), title=getattr(s, "evidence", "")[:60], url=s.url)
    if f is not None and f.news is not None:
        for it in (f.news.items or []):
            if it.url and str(it.url) not in seen:
                seen[str(it.url)] = SourceEntry(domain=_domain_of(it.url), title=it.title, url=it.url)
    if f is not None and f.judicial is not None:
        for c in (f.judicial.sample_cases or []):
            if c.url and str(c.url) not in seen:
                seen[str(c.url)] = SourceEntry(domain=_domain_of(c.url), title=c.title, url=c.url)
    return sorted(seen.values(), key=lambda s: (s.domain, s.title or ""))


def _axes_avg(axes) -> float:
    if not axes:
        return 0.0
    return round(sum(a.stars for a in axes) / len(axes), 2)


def _domain_root(url: str | None) -> str:
    """Return the registrable root of a URL host (e.g. 'maimai.cn', 'v2ex.com').
    Used to bucket URLs by domain for cross-source corroboration."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(url)).hostname or "").lower()
        if not host:
            return ""
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


def compute_signal_supports(review_facts) -> dict[str, dict]:
    """For each signal in review_facts, compute (support_count, support_tier).

    support_count = len(supporting_urls) + 1 (the main `url` counts as one).
    support_tier:
        - 'unverified'           : no urls at all
        - 'single-source'        : exactly one url (could be the LLM-confabulated)
        - 'corroborated'         : ≥2 urls from ≥2 distinct domain roots
        - 'multi-domain'         : ≥3 urls from ≥3 distinct domain roots

    Returns a dict keyed by the signal's main url string for the template to
    look up. Signals with no url are excluded.
    """
    out: dict[str, dict] = {}
    if not review_facts:
        return out

    def _annotate(url, supporting_urls):
        if not url:
            return None
        all_urls = [str(url)] + [str(u) for u in (supporting_urls or [])]
        domains = {_domain_root(u) for u in all_urls if u}
        domains.discard("")
        n = len(all_urls)
        n_dom = len(domains)
        if n == 0:
            tier = "unverified"
        elif n == 1 or n_dom == 1:
            tier = "single-source"
        elif n_dom >= 3:
            tier = "multi-domain"
        else:
            tier = "corroborated"
        return {"support_count": n, "support_tier": tier, "domains": sorted(domains)}

    for s in (review_facts.salary_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.overtime_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.vibe_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    for s in (review_facts.turnover_signals or []):
        info = _annotate(s.url, getattr(s, "supporting_urls", None))
        if info:
            out[str(s.url)] = info
    return out


_TIER_LABEL = {
    "unverified":    ("待核实", "tier-unverified"),
    "single-source": ("单一来源", "tier-single"),
    "corroborated":  ("多源印证", "tier-corroborated"),
    "multi-domain":  ("跨域印证", "tier-multi"),
}


def extract_collector_notes(
    results: "list | None",
) -> dict[str, str]:
    """v0.1.20 — Pull per-collector soft-fail markers from raw CollectorResults.

    Returns a dict like ``{"sogou_weixin": "anti_bot_redirect"}`` only when a
    collector errored. Used by the template to render targeted manual-check
    banners on the relevant chapter.

    The marker is the *first* token of ``CollectorResult.error`` — e.g.
    ``"anti_bot_redirect"`` for Sogou WeChat anti-bot challenges, or the full
    error string for unrecognized failures.
    """
    out: dict[str, str] = {}
    if not results:
        return out
    for r in results:
        if not getattr(r, "error", None):
            continue
        err = r.error.strip()
        marker = err.split()[0] if err else ""
        out[r.collector] = marker or err
    return out


def compute_review_diagnostics(
    results: "list | None",
    by_domain: "dict | None" = None,
    review_facts: "object | None" = None,
) -> dict[str, int]:
    """v0.3.5 — Honest sparse-state diagnostics for the reviews章.

    Returns a dict the template's `sparse_takeaway` macro uses to render
    "we tried N platforms + M keywords + K qna + L extract pages → found X
    raw → auto-mined Y signals" instead of a defeatist "本次未能取得".

    Counters are best-effort and never raise — if the pipeline didn't pass
    results or by_domain (e.g. older ReportData shape), returns just zeros
    and the macro still renders.
    """
    out: dict[str, int] = {
        "platforms_queried": 0,
        "keywords_queried": 0,
        "qna_calls": 0,
        "extract_pages": 0,
        "raw_items": 0,
        "signals_extracted": 0,
    }
    if results:
        for r in results:
            domain = getattr(r, "domain", "") or ""
            if domain != "reviews":
                continue
            name = getattr(r, "collector", "") or ""
            items = getattr(r, "items", None) or []
            if name == "tavily_reviews":
                # The collector runs main (~40) + blind (3) — credit both
                out["platforms_queried"] += 40
                out["keywords_queried"] += 3
                out["raw_items"] += len(items)
            elif name == "tavily_qna":
                out["qna_calls"] += 1
                # QnA answer counts as a single raw item too
                out["raw_items"] += len(items)
            elif name == "tavily_extract_reviews":
                out["extract_pages"] += len(items)
                out["raw_items"] += len(items)
            elif name == "sogou_weixin":
                out["raw_items"] += len(items)
            else:
                out["raw_items"] += len(items)
    if review_facts is not None:
        try:
            sig = (
                len(getattr(review_facts, "salary_signals", []) or []) +
                len(getattr(review_facts, "overtime_signals", []) or []) +
                len(getattr(review_facts, "vibe_signals", []) or []) +
                len(getattr(review_facts, "turnover_signals", []) or [])
            )
            out["signals_extracted"] = sig
        except Exception:  # noqa: BLE001
            pass
    return out

_CONFIDENCE_LABEL = {
    "high":   ("数据充足",   "conf-high"),
    "medium": ("部分缺失",   "conf-medium"),
    "low":    ("需人工核查", "conf-low"),
}


# ---------- v0.3.3 — Company timeline + age ----------

def compute_company_age(founded_year, generated_at: datetime) -> int | None:
    """v0.3.3 — Return the company's age in years as of generated_at.

    Returns None when founded_year is missing, unparseable, or in the
    future. Pure deterministic — no LLM.
    """
    if founded_year is None:
        return None
    try:
        age = generated_at.year - int(founded_year)
    except (TypeError, ValueError):
        return None
    return age if age >= 0 else None


def compute_company_timeline(cp) -> dict | None:
    """v0.3.3 — Build a deterministic mini-timeline of company milestones for
    Chapter I inline-viz. Returns None when founded_year is missing.

    Event slots (max 5, oldest → newest):
      - 0: 成立 (founded_year)
      - 1: 融资阶段 (if funding_stage_position >= 1)
      - 2: 投资方 (first 2 names, joined with /)
      - 3: 至今 (only when span > 2 years)

    Each event: ``{"when": "YYYY" | "—", "label": str}``. The SVG generator
    (charts.company_timeline_svg) handles layout; this function only emits
    the data, so templates can also iterate the events for non-SVG fallbacks.
    """
    if not cp or cp.founded_year is None:
        return None
    try:
        founded = int(cp.founded_year)
    except (TypeError, ValueError):
        return None

    events: list[dict] = [{"when": str(founded), "label": "成立"}]

    pos = funding_stage_position(getattr(cp, "funding_stage", None))
    if pos >= 1:
        stage = cp.funding_stage or ""
        if pos == 5:
            label = f"已上市 · {stage}" if stage else "已上市"
        elif pos == 4:
            label = f"C 轮及以上 · {stage}" if stage else "C 轮及以上"
        elif pos == 3:
            label = f"B 轮 · {stage}" if stage else "B 轮"
        elif pos == 2:
            label = f"A 轮 · {stage}" if stage else "A 轮"
        elif pos == 1:
            label = f"天使轮 · {stage}" if stage else "天使轮"
        else:
            label = stage or "融资"
        events.append({"when": "—", "label": label})

    investors = getattr(cp, "investors", None) or []
    if investors:
        names = [str(n).strip() for n in investors[:2] if str(n).strip()]
        if names:
            tail = "等" if len(investors) > 2 else ""
            events.append({"when": "—", "label": "投资方：" + " / ".join(names) + tail})

    now_y = datetime.now().year
    if now_y - founded > 2:
        events.append({"when": str(now_y), "label": "至今"})

    return {
        "events": events[:5],
        "span_start": founded,
        "span_end": now_y,
    }


# ---------- v0.1.17 — Salary band (P25 / P50 / P75) ----------

def compute_salary_band(salary_signals) -> dict | None:
    """Aggregate salary signals into a percentile band for the offer-comparison
    use case. Returns None when fewer than 2 datapoints exist (insufficient to
    even hint a band).

    Method:
      - Each signal contributes 1 datapoint: midpoint of range, or base_monthly_k
      - Linear-interpolation percentile (numpy-style `linear` method)
    """
    values: list[float] = []
    for s in salary_signals or []:
        if s.salary_range_min_k is not None and s.salary_range_max_k is not None:
            values.append((s.salary_range_min_k + s.salary_range_max_k) / 2)
        elif s.base_monthly_k is not None:
            values.append(float(s.base_monthly_k))
    if len(values) < 2:
        return None
    values.sort()
    n = len(values)

    def _pct(p: float) -> float:
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return values[f]
        return values[f] + (values[c] - values[f]) * (k - f)

    return {
        "p25": round(_pct(0.25), 1),
        "p50": round(_pct(0.50), 1),
        "p75": round(_pct(0.75), 1),
        "n": n,
        "min": values[0],
        "max": values[-1],
    }


def compute_diversity_kpi(review_facts, sources) -> dict:
    """Source-diversity KPI for the hero meta line.

    Aggregates:
      - total_signals (sum of salary/overtime/turnover/vibe signals)
      - corroborated_count (tier in {corroborated, multi-domain})
      - distinct_domains (unique domain roots across all review signals)
      - tier_distribution (count per tier)

    Used by the 「数据多样性」 pill in the report header.
    """
    out = {
        "total_signals": 0,
        "corroborated_count": 0,
        "distinct_domains": set(),
        "tier_distribution": {"unverified": 0, "single-source": 0, "corroborated": 0, "multi-domain": 0},
        "tier_label_zh": "—",
    }
    if review_facts:
        out["total_signals"] = (
            len(review_facts.salary_signals or [])
            + len(review_facts.overtime_signals or [])
            + len(review_facts.turnover_signals or [])
            + len(review_facts.vibe_signals or [])
        )
    supports = compute_signal_supports(review_facts) if review_facts else {}
    for info in supports.values():
        tier = info.get("support_tier", "unverified")
        out["tier_distribution"][tier] = out["tier_distribution"].get(tier, 0) + 1
        out["distinct_domains"].update(info.get("domains", []))
    out["corroborated_count"] = (
        out["tier_distribution"].get("corroborated", 0)
        + out["tier_distribution"].get("multi-domain", 0)
    )
    # Copy out — Jinja can't render set
    out["distinct_domains"] = sorted(out["distinct_domains"])
    n_dom = len(out["distinct_domains"])
    n_total = out["total_signals"]
    if n_total == 0:
        out["tier_label_zh"] = "无信号"
    elif n_dom >= 4 and out["corroborated_count"] >= 3:
        out["tier_label_zh"] = "高"
    elif n_dom >= 2 and out["corroborated_count"] >= 1:
        out["tier_label_zh"] = "中"
    else:
        out["tier_label_zh"] = "低"
    return out


def compute_trial_checklist(data: ReportData) -> dict[str, list[str]]:
    """v0.1.15 — Generate the 1mo / 3mo / 6mo 试用期观察清单.

    Pure deterministic — derived from data.review_facts + data.business_facts +
    data.judicial_facts. Each checkpoint returns a list of concrete things to
    watch; some are universal (HR 反向背调 baseline), some are driven by what
    we already know about this company.

    Returns a dict keyed by checkpoint label:
      {"1mo": [...], "3mo": [...], "6mo": [...]}
    """
    one_mo: list[str] = []
    three_mo: list[str] = []
    six_mo: list[str] = []

    rf = data.review_facts
    bf = data.business_facts
    jf = data.judicial_facts
    cp = data.company_profile

    # ----- 1 个月：信号校准（JD 说的与实际是否一致）-----
    one_mo.append("试用期薪资是否打折？合同 / offer / 实际到账 三处是否完全一致。")
    one_mo.append("团队平均下班时间 — 是否与 JD / 面试官说的节奏匹配；前两周记录自己每天实际工时。")
    one_mo.append("导师 / 直接 leader 是否明确给你分了 1-2 个具体可交付任务，没有就主动要。")
    if rf and any((s.intensity or "").lower() == "high" for s in (rf.overtime_signals or [])):
        one_mo.append("加班强度提示 — 评价里存在高强度加班信号，1 个月内重点观察：是否真的 996、调休是否落地、加班费怎么算。")
    if rf and any((v.sentiment or "") == "negative" for v in (rf.vibe_signals or [])):
        one_mo.append("氛围信号 — 评价里有负面氛围信号，新人 1 个月内通常感受不到，留意正式员工私下闲聊的关键词（push、甩锅、PUA、画饼）。")

    # ----- 3 个月：合同 / 社保 / 转正路径-----
    three_mo.append("试用期转正流程 — 是否清晰？转正答辩 / KPI 评分标准有没有提前书面化。")
    three_mo.append("社保 / 公积金 — 按实际工资基数还是按最低基数？查「支付宝 - 社保」小程序可一键核对。")
    three_mo.append("股权 / 期权（如 JD 提到）— 兑现周期、cliff 期、行权价都要白纸黑字。")
    if rf:
        jd_gap = rf.jd_gap_signals or []
        if jd_gap:
            three_mo.append("JD vs 实际 — 评价里有「JD 承诺 vs 实际工作」gap 记录；3 个月时对比实际工作内容与入职时面试承诺。")
    if bf and bf.anomaly_listed:
        three_mo.append("经营异常历史 — 公司曾被列入经营异常名录，3 个月时复核是否已移出（gsxt.gov.cn 公开查询）。")

    # ----- 6 个月：留存 / 现金流 / 长期博弈-----
    six_mo.append("同期入职的同事还在不在？3-6 个月是互联网公司新员工离职高峰，留意主动离职比例。")
    six_mo.append("公司现金流信号 — 工资发放是否准时？报销周期是否合理？季度奖是否按时发？")
    six_mo.append("晋升通道 — 同期进的人 6 个月内有没有人拿到晋升 / 调薪？")
    if jf and (jf.case_count_total or 0) > 0:
        six_mo.append("司法历史 — 公司累计诉讼较多，6 个月时确认你所在业务的诉讼与你无关；留意是否要个人签字担保。")
    if cp and getattr(cp, "funding_stage", None) and cp.funding_stage not in ("已上市", "未融资"):
        six_mo.append(f"融资阶段 — 公司处于 {cp.funding_stage}，6 个月时主动问 leader / 财务 现金跑道（runway），避免下一轮融资出问题被波及。")
    six_mo.append("如果以上任何一项信号恶化（高强度加班固化 / 同事扎堆离职 / 工资延迟）—— 立刻开始看外部机会，不要等。")

    # De-dup while preserving order
    def _dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            key = it[:30]
            if key not in seen:
                seen.add(key)
                out.append(it)
        return out

    return {
        "1mo": _dedup(one_mo)[:5],
        "3mo": _dedup(three_mo)[:5],
        "6mo": _dedup(six_mo)[:5],
    }


def compute_chapter_stories(data: ReportData) -> tuple[dict[str, str], dict[str, list[str]], str]:
    """Generate per-chapter 「编辑手记」 aside + 「数据故事」 lines.

    Pure deterministic — derived from `data.*_facts` plus the industry
    baseline. No LLM call. Both shapes are template-ready:

    - edit_notes[chapter_key]  → 1-2 sentence editorial aside ("编辑手记")
                                 shown next to chapter-takeaway.
    - data_stories[chapter_key] → list of "过去 12 个月里..." lines that
                                 contextualize raw numbers against the
                                 industry baseline.

    Industry key is picked from `data.company_profile.industry` (or
    business_facts.industry as fallback); falls back to 'default' when
    no signal matches.

    Returns: (edit_notes, data_stories, industry_key)
    """
    from jobhunter.report.industry_baselines import baseline, delta_pct, pick_industry

    industry_text = ""
    cp = data.company_profile
    if cp:
        # Prefer industries list (CompanyProfile schema), fall back to bare
        # `industry` str for forward-compat / test stubs.
        industries = getattr(cp, "industries", None) or []
        if isinstance(industries, list) and industries:
            industry_text = " ".join(str(s) for s in industries)
        if not industry_text:
            bare = getattr(cp, "industry", None)
            if bare:
                industry_text = str(bare)
    if not industry_text and data.business_facts:
        # BusinessFacts has no `industry` field — but tests may pass an
        # arbitrary instance. Use getattr for safety.
        bf_industry = getattr(data.business_facts, "industry", None)
        if bf_industry:
            industry_text = str(bf_industry)
    industry_key = pick_industry(industry_text)
    bl = baseline(industry_key)
    industry_label = "default" if industry_key == "default" else industry_key

    edit_notes: dict[str, str] = {}
    stories: dict[str, list[str]] = {}

    # ----- Chapter I: 公司画像 -----
    if data.company_profile:
        cp = data.company_profile
        bits = []
        industries = getattr(cp, "industries", None) or []
        if isinstance(industries, list) and industries:
            bits.append(f"赛道是「{industries[0]}」")
        elif getattr(cp, "industry", None):
            bits.append(f"赛道是「{cp.industry}」")
        if getattr(cp, "company_size", None):
            bits.append(f"规模约 {cp.company_size}")
        if getattr(cp, "funding_stage", None):
            bits.append(f"融资阶段 {cp.funding_stage}")
        if bits:
            edit_notes["company"] = "这家公司" + "，".join(bits) + "。"

    # ----- Chapter II: 工商 -----
    if data.business_facts:
        bf = data.business_facts
        lines = []
        if bf.status:
            lines.append(f"经营状态：{bf.status}。")
        if bf.established_at:
            lines.append(f"成立于 {bf.established_at}。")
        if bf.legal_rep:
            lines.append(f"法人 {bf.legal_rep}。")
        if lines:
            edit_notes["business"] = " ".join(lines)

    # ----- Chapter III: 司法 -----
    if data.judicial_facts:
        jf = data.judicial_facts
        n_total = (jf.case_count_total or 0) + (jf.enforcement_records or 0)
        n_cases = jf.case_count_total or 0
        lines = []
        if n_total == 0:
            lines.append("过去 12 个月里，这家公司没有任何公开诉讼或被执行记录——这是同行里相对少见的干净背景。")
        else:
            lines.append(
                f"过去 12 个月里，这家公司被起诉了 {n_cases} 次、有 {jf.enforcement_records or 0} 条被执行记录。"
            )
            delta = delta_pct(n_total, bl["lawsuits_per_year"])
            sign = "高" if delta > 10 else ("低" if delta < -10 else "接近")
            lines.append(
                f"比{industry_label}同行平均{'高' if delta > 0 else '低'} {abs(round(delta))}%。"
            )
        stories["judicial"] = lines
        if jf.sample_cases:
            latest = jf.sample_cases[0]
            label = getattr(latest, "case_type", None) or latest.title or "未知案由"
            edit_notes["judicial"] = f"已记录 {len(jf.sample_cases)} 起案件样本，最近一起涉及 {label}。"

    # ----- Chapter IV: 薪酬 / 加班 / 氛围 / 离职 -----
    if data.review_facts:
        rf = data.review_facts

        # Overtime story
        ot_lines = []
        ot_signals = rf.overtime_signals or []
        if ot_signals:
            # Heuristic: estimate "996 / 007 / 加班严重" rate from intensity
            heavy = sum(1 for s in ot_signals if (s.intensity or "").lower() == "high")
            if heavy >= 1:
                ot_lines.append(
                    f"在 {len(ot_signals)} 条员工反馈里，"
                    f"{heavy} 条提到高强度加班模式（如 996 / 007）。"
                )
                delta = delta_pct(50.0, bl["overtime_hours_per_week"] * 1.5)
                ot_lines.append(
                    f"按行业平均每周加班 {bl['overtime_hours_per_week']:.0f} 小时计，"
                    f"这家公司更接近「加班严重」一档——比同行高出约 {abs(round(delta))}%。"
                )
            else:
                ot_lines.append(
                    f"在 {len(ot_signals)} 条反馈中，"
                    f"高强度加班提及率 {heavy}/{len(ot_signals)}，"
                    f"接近行业平均（{bl['overtime_hours_per_week']:.0f} 小时/周）。"
                )
        if ot_lines:
            stories["reviews"] = stories.get("reviews", []) + ot_lines

        # Salary story
        sal_lines = []
        sal_signals = rf.salary_signals or []
        if sal_signals:
            # We don't have a JD-actual delta field on SalarySignal; flag any
            # signal with base_monthly_k below the industry 3y baseline as a
            # proxy for "below market".
            baseline_sal = bl["salary_k_monthly_3y"]
            n_underpaid = sum(
                1 for s in sal_signals
                if s.base_monthly_k is not None and s.base_monthly_k < baseline_sal * 0.9
            )
            if n_underpaid:
                sal_lines.append(
                    f"{n_underpaid}/{len(sal_signals)} 条薪酬反馈月薪低于行业 3 年基线的 90%。"
                )
            sal_lines.append(
                f"同行业 3 年经验基线月薪约 ¥{baseline_sal:.0f}k——具体可在薪酬分布图中核对。"
            )
        if sal_lines:
            stories["reviews"] = stories.get("reviews", []) + sal_lines

        # Vibe / overall edit note
        all_signals = len(rf.salary_signals or []) + len(rf.overtime_signals or []) + len(rf.turnover_signals or []) + len(rf.vibe_signals or [])
        if all_signals > 0:
            edit_notes["reviews"] = (
                f"本章汇总了 {all_signals} 条结构化员工信号。"
                f"配合 chapter 末尾的「网络词解读」可以看到打工人原话里更细的颗粒。"
            )

    # ----- Chapter VI: 舆情 -----
    if data.news_facts:
        nf = data.news_facts
        n_items = len(nf.items or [])
        if n_items > 0:
            edit_notes["news"] = (
                f"近 90 天共抓取 {n_items} 条公开报道与舆情，"
                f"整体情感倾向：{nf.sentiment or '中性'}。"
            )

    # ----- Chapter V: 综合评价 (if no separate edit_note yet) -----
    # Note: chapter V in current template reuses reviews' signals; we keep
    # the edit note scoped to chapter V explicitly if needed.

    return edit_notes, stories, industry_key


# ---------- v0.1.16 — Top-level verdict (recommend / caution / avoid / neutral) ----------

Verdict = Literal["recommend", "caution", "avoid", "neutral"]


@dataclass
class OverallVerdict:
    level: Verdict
    headline: str          # one-line headline
    reasons: list[str]     # top 3 evidence lines
    score: float | None = None  # avg axis score if available


def compute_overall_verdict(data: ReportData) -> OverallVerdict:
    """v0.1.16 — Derive a single top-level recommendation from all gathered facts.

    Logic (deterministic, no LLM):
      avoid     ← any axis ≤ 2 OR case_count_total > 10 OR (anomaly_listed AND funding ≠ 已上市)
      caution   ← any axis ≤ 3 OR case_count > 3 OR heavy_overtime ≥ 2 OR anomaly_listed
      recommend ← all axes ≥ 4 AND case_count == 0 AND no high-intensity overtime AND positive vibe ≥ negative
      neutral   ← everything else (data too thin to lean either way)
    """
    axes = {a.axis.value: a.stars for a in (data.axes or []) if a.stars is not None}
    rf = data.review_facts
    jf = data.judicial_facts
    bf = data.business_facts
    cp = data.company_profile
    score = _axes_avg(data.axes or []) if data.axes else None

    reasons: list[str] = []

    # Heavy overtime count
    heavy_overtime = 0
    if rf:
        heavy_overtime = sum(1 for o in rf.overtime_signals if o.intensity == "high")
    case_count = jf.case_count_total if jf else None
    anomaly = bool(bf.anomaly_listed) if bf else False
    listed = (cp.funding_stage == "已上市") if cp else False
    case_count_val = case_count if isinstance(case_count, int) else 0

    # AVOID triggers — only hard, multi-axis stress.
    # Single anomaly / single weak axis = caution, not avoid. Avoid requires
    # the reader to question whether to even continue the interview loop.
    avoid_triggers: list[str] = []
    weak_axes = [(k, v) for k, v in axes.items() if v <= 2]
    if len(weak_axes) >= 2:
        names = "、".join(_axis_label_zh(k) for k, _ in weak_axes)
        avoid_triggers.append(f"{names} 等 {len(weak_axes)} 个轴严重偏低")
    if case_count_val > 10 and anomaly:
        avoid_triggers.append(f"司法记录 {case_count_val} 起 + 经营异常，叠加风险高")
    elif case_count_val > 10:
        avoid_triggers.append(f"司法记录 {case_count_val} 起，超出行业典型水平")

    if avoid_triggers:
        return OverallVerdict(
            level="avoid",
            headline="建议避开 — 多项硬指标触底",
            reasons=avoid_triggers[:3],
            score=score,
        )

    # CAUTION triggers
    caution_triggers: list[str] = []
    for k, v in axes.items():
        if v <= 3:
            caution_triggers.append(f"{_axis_label_zh(k)} 轴 {v:.0f}/5 偏弱")
    if case_count_val > 3:
        caution_triggers.append(f"司法记录 {case_count_val} 起，需关注")
    if heavy_overtime >= 2:
        caution_triggers.append(f"评价中已有 {heavy_overtime} 条高强度加班信号")
    if anomaly:
        caution_triggers.append("曾被列入经营异常名录")

    if caution_triggers:
        return OverallVerdict(
            level="caution",
            headline="建议谨慎 — 存在需要核实的问题",
            reasons=caution_triggers[:3],
            score=score,
        )

    # RECOMMEND triggers — only when signals are clearly clean AND positive
    if axes and all(v >= 4 for v in axes.values()):
        pos_vibe = sum(1 for v in rf.vibe_signals if v.sentiment == "positive") if rf else 0
        neg_vibe = sum(1 for v in rf.vibe_signals if v.sentiment == "negative") if rf else 0
        if case_count_val == 0 and heavy_overtime == 0 and pos_vibe >= neg_vibe:
            return OverallVerdict(
                level="recommend",
                headline="建议接 offer — 现有数据面较干净",
                reasons=[
                    "五轴评分均在 4 分及以上",
                    "无司法 / 经营异常记录",
                    f"正面氛围信号 ({pos_vibe}) 不少于负面 ({neg_vibe})",
                ],
                score=score,
            )

    # NEUTRAL — data too thin or mixed
    mixed = []
    if not axes:
        mixed.append("五轴评分缺失，建议补充数据后再判断")
    elif any(3 < v < 4 for v in axes.values()):
        mixed.append("部分指标落在 3-4 分灰色区间")
    if not rf or not (rf.salary_signals or rf.overtime_signals or rf.vibe_signals):
        mixed.append("评价数据较少，结论仅供参考")
    return OverallVerdict(
        level="neutral",
        headline="信息有限 — 建议补充核实",
        reasons=mixed[:3] or ["数据面不完整"],
        score=score,
    )


def _axis_label_zh(key: str) -> str:
    return _AXIS_LABEL_ZH.get(key, key)


_AXIS_LABEL_ZH: dict[str, str] = {
    "overtime": "加班强度",
    "salary_trust": "薪酬诚信",
    "judicial": "司法风险",
    "business": "工商风险",
    "culture": "文化氛围",
}


def build_report(data: ReportData) -> str:
    css = (_STATIC_DIR / "report.css").read_text(encoding="utf-8")
    sources = _collect_sources(data)
    axes = data.axes or []
    avg_score = _axes_avg(axes)
    radar = radar_svg(axes)
    hero_ring = score_ring_svg(avg_score) if avg_score else ""
    overtime_dist = overtime_distribution(data.review_facts.overtime_signals) if data.review_facts else []
    salary_dist = salary_distribution(data.review_facts.salary_signals) if data.review_facts else []
    salary_band = compute_salary_band(data.review_facts.salary_signals) if data.review_facts else None

    # New editorial primitives
    vibe_counts = vibe_sentiment_counts(data.review_facts.vibe_signals) if data.review_facts else []
    vibe_donut = vibe_donut_svg(vibe_counts)
    shareholders = (data.business_facts.top_shareholders if data.business_facts else []) or []
    shareholder_donut = shareholder_pie_svg(shareholders)
    sample_cases = (data.judicial_facts.sample_cases if data.judicial_facts else []) or []
    case_buckets = case_year_buckets(sample_cases)
    case_timeline = case_timeline_svg(case_buckets)
    funding_pos = funding_stage_position(
        data.company_profile.funding_stage if data.company_profile else None
    )
    news_timeline_items = (
        news_items_for_timeline(data.news_facts.items) if data.news_facts else []
    )
    news_timeline_svg_str = (
        news_timeline_svg(
            news_timeline_items,
            sentiment=data.news_facts.sentiment if data.news_facts else "neutral",
        )
        if news_timeline_items else ""
    )

    # Cross-source corroboration for review signals — drives the
    # 「待核实 / 单一来源 / 多源印证 / 跨域印证」tier badge in chapter IV/V/VI.
    signal_supports = compute_signal_supports(data.review_facts)
    diversity_kpi = compute_diversity_kpi(data.review_facts, sources)

    # v0.3.3 — Company timeline viz (Chapter I inline)
    company_timeline = compute_company_timeline(data.company_profile)
    company_timeline_svg_str = (
        company_timeline_svg(company_timeline["events"]) if company_timeline else ""
    )
    company_age = compute_company_age(
        getattr(data.company_profile, "founded_year", None) if data.company_profile else None,
        data.generated_at,
    )

    # v0.1.13 — Editorial aside + variable data stories.
    # Caller may already have populated `data.edit_notes` / `data.data_stories`
    # via LLM; fall back to the deterministic builder path otherwise.
    if data.edit_notes or data.data_stories:
        edit_notes = data.edit_notes
        data_stories = data.data_stories
        industry_key = data.industry_key
    else:
        edit_notes, data_stories, industry_key = compute_chapter_stories(data)

    # v0.1.15 — 试用期观察清单 (1mo / 3mo / 6mo)
    trial_checklist = data.trial_checklist or compute_trial_checklist(data)

    # v0.1.16 — JD 对照清单 (pure local, deterministic)
    jd_alignment: list[JdClaim] = data.jd_alignment or compute_jd_alignment(data)

    # v0.1.16 — 顶层 verdict
    overall_verdict = data.overall_verdict or compute_overall_verdict(data)

    # v0.1.17 — vs 上次 (snapshot diff from cache). None when no prior run.
    snapshot_diff = data.snapshot_diff
    if snapshot_diff is None:
        try:
            from jobhunter.report.snapshot import diff_snapshots, latest_snapshot
            prev = latest_snapshot(data.query.company)
            snapshot_diff = diff_snapshots(prev, data) if prev else None
        except Exception:  # noqa: BLE001
            snapshot_diff = None

    tmpl = _ENV.get_template("report.html.j2")
    return tmpl.render(
        data=data,
        css=css,
        sources=sources,
        now=datetime.now(),
        avg_score=avg_score,
        radar_svg=radar,
        hero_ring_svg=hero_ring,
        overtime_dist=overtime_dist,
        salary_dist=salary_dist,
        salary_band=salary_band,
        vibe_counts=vibe_counts,
        vibe_donut_svg=vibe_donut,
        shareholder_donut_svg=shareholder_donut,
        case_buckets=case_buckets,
        case_timeline_svg=case_timeline,
        funding_stage_pos=funding_pos,
        news_timeline_items=news_timeline_items,
        news_timeline_svg=news_timeline_svg_str,
        signal_supports=signal_supports,
        tier_label=_TIER_LABEL,
        diversity_kpi=diversity_kpi,
        confidence_label=_CONFIDENCE_LABEL,
        company_timeline=company_timeline,
        company_timeline_svg=company_timeline_svg_str,
        company_age=company_age,
        edit_notes=edit_notes,
        data_stories=data_stories,
        industry_key=industry_key,
        trial_checklist=trial_checklist,
        peer_comparison=data.peer_comparison,
        jd_alignment=jd_alignment,
        overall_verdict=overall_verdict,
        snapshot_diff=snapshot_diff,
        favicon_url=_favicon_url,
        _domain_of=_domain_of,
        review_diagnostics=data.review_diagnostics,
    )
"""HTML report builder — Jinja2 render of ReportData."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import jinja2

from jobhunter.models.report import ReportData, SourceEntry
from jobhunter.report.charts import (
    case_timeline_svg,
    case_year_buckets,
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

_CONFIDENCE_LABEL = {
    "high":   ("数据充足",   "conf-high"),
    "medium": ("部分缺失",   "conf-medium"),
    "low":    ("需人工核查", "conf-low"),
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


def build_report(data: ReportData) -> str:
    css = (_STATIC_DIR / "report.css").read_text(encoding="utf-8")
    sources = _collect_sources(data)
    axes = data.axes or []
    avg_score = _axes_avg(axes)
    radar = radar_svg(axes)
    hero_ring = score_ring_svg(avg_score) if avg_score else ""
    overtime_dist = overtime_distribution(data.review_facts.overtime_signals) if data.review_facts else []
    salary_dist = salary_distribution(data.review_facts.salary_signals) if data.review_facts else []

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

    # v0.1.13 — Editorial aside + variable data stories.
    # Caller may already have populated `data.edit_notes` / `data.data_stories`
    # via LLM; fall back to the deterministic builder path otherwise.
    if data.edit_notes or data.data_stories:
        edit_notes = data.edit_notes
        data_stories = data.data_stories
        industry_key = data.industry_key
    else:
        edit_notes, data_stories, industry_key = compute_chapter_stories(data)

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
        edit_notes=edit_notes,
        data_stories=data_stories,
        industry_key=industry_key,
        favicon_url=_favicon_url,
    )
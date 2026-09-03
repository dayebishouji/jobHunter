"""Inline SVG chart generators. Zero JS, single-file portability."""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

from jobhunter.models.facts import (
    OvertimeSignal,
    SalarySignal,
    Sentiment,
    Shareholder,
    VibeSignal,
)
from jobhunter.models.scoring import AxisScore, RiskAxis, axis_color

# ---------- Palette (warm editorial) ----------

# These mirror the CSS custom properties so server-side SVG embeds match.
_PALETTE = {
    "ink":       "#2a1f15",
    "ink_soft":  "#6b5641",
    "ink_faint": "#9a8369",
    "rule":      "#c9b89c",
    "paper":     "#f4ece0",
    "accent":    "#7c1d24",   # 暗酒红
    "accent_2":  "#b06b1c",   # 焦糖
    "caramel":   "#c89762",
    "good":      "#4f6a3a",
    "warn":      "#b06b1c",
    "bad":       "#8a2521",
}

# ---------- Radar chart ----------

_GRID_LEVELS = (1, 3, 5)  # inner-to-outer pentagons (1=worst, 5=best)
_RADAR_PALETTE = {
    "good": _PALETTE["good"],
    "warn": _PALETTE["warn"],
    "bad":  _PALETTE["bad"],
}

_SENTIMENT_TONE: dict[Sentiment, str] = {
    "positive": "good",
    "neutral":  "neutral",
    "negative": "bad",
    "mixed":    "warn",
}

_SENTIMENT_COLOR: dict[str, str] = {
    "good":    _PALETTE["good"],
    "warn":    _PALETTE["warn"],
    "bad":     _PALETTE["bad"],
    "neutral": _PALETTE["caramel"],
}


def _pentagon_points(cx: float, cy: float, r: float, n: int = 5, start_deg: float = -90.0) -> list[tuple[float, float]]:
    pts = []
    for i in range(n):
        deg = start_deg + i * (360.0 / n)
        rad = math.radians(deg)
        pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    return pts


def _polar_xy(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


def radar_svg(axes: list[AxisScore], *, size: int = 280, padding: int = 36) -> str:
    """Return SVG string for a 5-axis radar (clock-aligned, top = overtime)."""
    if not axes:
        return ""
    n = len(axes)
    cx = cy = size / 2
    max_r = (size / 2) - padding

    # Background pentagons at 1, 3, 5 levels (centered)
    grid_polys: list[str] = []
    for level in _GRID_LEVELS:
        r = (level / 5) * max_r
        pts = _pentagon_points(cx, cy, r, n=n)
        opacity = 0.10 if level == 5 else (0.18 if level == 3 else 0.25)
        grid_polys.append(
            f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in pts)}" '
            f'fill="none" stroke="currentColor" stroke-width="1" opacity="{opacity}"/>'
        )

    # Axes lines (center → vertices) at the 5 axis directions
    axis_lines = []
    label_data: list[tuple[float, float, str]] = []
    for i in range(n):
        deg = -90.0 + i * (360.0 / n)
        x1, y1 = cx, cy
        x2, y2 = _polar_xy(cx, cy, max_r, deg)
        axis_lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="currentColor" stroke-width="1" opacity="0.18"/>'
        )
        lx, ly = _polar_xy(cx, cy, max_r + 14, deg)
        label_data.append((lx, ly, axes[i].label_zh))

    # Data polygon
    data_pts: list[tuple[float, float]] = []
    vertex_dots = []
    for i, ax in enumerate(axes):
        deg = -90.0 + i * (360.0 / n)
        r = (max(1, min(5, ax.stars)) / 5) * max_r
        x, y = _polar_xy(cx, cy, r, deg)
        data_pts.append((x, y))
        vertex_dots.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" '
            f'fill="{_RADAR_PALETTE[axis_color(ax.stars)]}" stroke="white" stroke-width="1.5"/>'
        )

    data_poly = (
        f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in data_pts)}" '
        f'fill="{_RADAR_PALETTE[axis_color(sum(a.stars for a in axes) / len(axes))]}" '
        f'fill-opacity="0.22" '
        f'stroke="{_RADAR_PALETTE[axis_color(sum(a.stars for a in axes) / len(axes))]}" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )

    # Labels with anchor based on quadrant
    label_svg = []
    for x, y, text in label_data:
        # anchor by relative position
        if x < cx - 10:
            anchor = "end"
        elif x > cx + 10:
            anchor = "start"
        else:
            anchor = "middle"
        dy = -6 if y < cy else 14
        label_svg.append(
            f'<text x="{x:.2f}" y="{y + dy:.2f}" text-anchor="{anchor}" '
            f'font-size="12" font-weight="600" fill="currentColor">{text}</text>'
        )

    # Numeric values per axis
    value_svg = []
    for i, ax in enumerate(axes):
        deg = -90.0 + i * (360.0 / n)
        r = (max(1, min(5, ax.stars)) / 5) * max_r
        vx, vy = _polar_xy(cx, cy, r, deg)
        value_svg.append(
            f'<text x="{vx:.2f}" y="{vy - 6:.2f}" text-anchor="middle" '
            f'font-size="9" font-weight="700" fill="{_RADAR_PALETTE[axis_color(ax.stars)]}">{ax.stars}</text>'
        )

    return (
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'class="radar-svg" aria-label="5 轴雷达图">'
        + "".join(grid_polys)
        + "".join(axis_lines)
        + data_poly
        + "".join(vertex_dots)
        + "".join(value_svg)
        + "".join(label_svg)
        + "</svg>"
    )


# ---------- Hero score ring ----------


def score_ring_svg(avg_score: float, *, size: int = 120, stroke: int = 10) -> str:
    """Radial gauge showing the 0-100 score with a colored ring.

    `avg_score` is 1..5; we map to 0..100.
    """
    pct = (max(1.0, min(5.0, avg_score)) - 1.0) / 4.0  # 0..1
    r = (size - stroke) / 2
    cx = cy = size / 2
    circumference = 2 * math.pi * r
    dash_offset = circumference * (1 - pct)
    if avg_score >= 4:
        color = _RADAR_PALETTE["good"]
    elif avg_score >= 3:
        color = _RADAR_PALETTE["warn"]
    else:
        color = _RADAR_PALETTE["bad"]

    return (
        f'<svg viewBox="0 0 {size} {size}" class="score-ring-svg" aria-label="综合得分">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" opacity="0.15"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})" '
        f'stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{dash_offset:.2f}"/>'
        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="28" font-weight="700" fill="{color}">{avg_score:.1f}</text>'
        f'<text x="{cx}" y="{cy + 26}" text-anchor="middle" font-size="9" '
        f'fill="currentColor" opacity="0.6">综合 / 5.0</text>'
        f"</svg>"
    )


# ---------- Distribution helpers (returned as plain Python; rendered in HTML/CSS) ----------


def overtime_distribution(signals: list[OvertimeSignal]) -> list[dict]:
    """Count OvertimeSignal entries per pattern. Returns sorted by count desc."""
    counts: dict[str, dict] = {}
    for s in signals:
        bucket = counts.setdefault(
            s.pattern, {"pattern": s.pattern, "count": 0, "intensity": s.intensity}
        )
        bucket["count"] += 1
    items = sorted(counts.values(), key=lambda b: (-b["count"], b["pattern"]))
    total = sum(b["count"] for b in items) or 1
    for b in items:
        b["pct"] = round(b["count"] / total * 100)
    return items


def salary_distribution(signals: list[SalarySignal]) -> list[dict]:
    """Bucket SalarySignal.base_monthly_k into 10K bins (10,20,30,40,50+)."""
    buckets: list[tuple[int, int]] = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 200)]
    counts = [0] * len(buckets)
    for s in signals:
        if s.base_monthly_k is None:
            continue
        for idx, (lo, hi) in enumerate(buckets):
            if lo <= s.base_monthly_k < hi:
                counts[idx] += 1
                break
    result = []
    for (lo, hi), c in zip(buckets, counts):
        label = f"{hi}+" if hi >= 200 else f"{lo}-{hi}"
        # Simpler labels
        if hi >= 200:
            label = f"{lo}+"
        elif lo == 0:
            label = f"<{hi}"
        else:
            label = f"{lo}-{hi}"
        result.append({"label": label, "count": c})
    return [r for r in result if r["count"] > 0] or result  # never return [] for empty inputs


# ---------- New editorial primitives ----------


def vibe_sentiment_counts(signals: list[VibeSignal]) -> list[dict]:
    """Count vibe signals by sentiment. Returns list of {tone, label, count} sorted desc.

    `tone` is one of good|warn|bad|neutral; UI uses it to pick colors.
    """
    counter: Counter[str] = Counter()
    for s in signals:
        counter[s.sentiment] += 1
    label_map = {"positive": "正面", "negative": "负面", "mixed": "混合", "neutral": "中性"}
    out: list[dict] = []
    for sent in ("positive", "negative", "mixed", "neutral"):
        c = counter.get(sent, 0)
        if c <= 0:
            continue
        out.append({
            "tone": _SENTIMENT_TONE.get(sent, "neutral"),
            "label": label_map[sent],
            "count": c,
        })
    out.sort(key=lambda x: -x["count"])
    return out


def vibe_donut_svg(counts: list[dict], *, size: int = 160, stroke: int = 22) -> str:
    """SVG donut for vibe sentiment ratios. Center is empty (could show %).

    Returns SVG string. When counts is empty, returns a hollow neutral donut.
    """
    cx = cy = size / 2
    r = (size - stroke) / 2
    circumference = 2 * math.pi * r
    total = sum(c["count"] for c in counts)
    if total <= 0:
        # Empty placeholder ring
        return (
            f'<svg viewBox="0 0 {size} {size}" class="donut-svg" '
            f'aria-label="氛围信号分布">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{_PALETTE["rule"]}" stroke-width="{stroke}" opacity="0.4"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
            f'font-family="Cormorant Garamond, Georgia, serif" font-size="14" '
            f'font-style="italic" fill="{_PALETTE["ink_soft"]}">无数据</text>'
            f'</svg>'
        )

    segments: list[str] = []
    offset = 0.0
    for c in counts:
        color = _SENTIMENT_COLOR.get(c["tone"], _PALETTE["accent"])
        frac = c["count"] / total
        # Show a 1px gap between segments by clipping the arc slightly
        seg_len = circumference * frac
        gap = min(1.5, seg_len * 0.05)
        draw_len = max(0.5, seg_len - gap)
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="butt" '
            f'transform="rotate(-90 {cx} {cy})" '
            f'stroke-dasharray="{draw_len:.2f} {circumference:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += seg_len

    return (
        f'<svg viewBox="0 0 {size} {size}" class="donut-svg" '
        f'aria-label="氛围信号分布">'
        + "".join(segments)
        + f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" '
        f'font-family="IBM Plex Mono, monospace" font-size="22" font-weight="700" '
        f'fill="{_PALETTE["ink"]}">{total}</text>'
        + f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" '
        f'font-family="Inter, sans-serif" font-size="9" letter-spacing="1.5" '
        f'fill="{_PALETTE["ink_soft"]}">条信号</text>'
        + '</svg>'
    )


def shareholder_pie_svg(shareholders: list[Shareholder], *, size: int = 160, stroke: int = 22) -> str:
    """SVG donut for top shareholder ownership. If no percentages, shows equal slices.

    Always returns an SVG; when data is empty, returns a hollow ring + '—'.
    """
    cx = cy = size / 2
    r = (size - stroke) / 2
    circumference = 2 * math.pi * r
    if not shareholders:
        return (
            f'<svg viewBox="0 0 {size} {size}" class="donut-svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{_PALETTE["rule"]}" stroke-width="{stroke}" opacity="0.4"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
            f'font-family="Inter, sans-serif" font-size="11" fill="{_PALETTE["ink_soft"]}">—</text>'
            f'</svg>'
        )

    palette = [_PALETTE["accent"], _PALETTE["accent_2"], _PALETTE["caramel"],
               _PALETTE["ink_soft"], _PALETTE["ink_faint"]]
    # Normalize stake_pct: if all None, fall back to equal weights
    weights = [s.stake_pct if s.stake_pct is not None else 0 for s in shareholders]
    if all(w == 0 for w in weights):
        weights = [1.0] * len(shareholders)
    total = sum(weights) or 1

    segments: list[str] = []
    offset = 0.0
    for i, w in enumerate(weights):
        frac = w / total
        seg_len = circumference * frac
        gap = min(1.5, seg_len * 0.04)
        draw_len = max(0.5, seg_len - gap)
        color = palette[i % len(palette)]
        segments.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="butt" '
            f'transform="rotate(-90 {cx} {cy})" '
            f'stroke-dasharray="{draw_len:.2f} {circumference:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}"/>'
        )
        offset += seg_len

    return (
        f'<svg viewBox="0 0 {size} {size}" class="donut-svg" aria-label="股东持股">'
        + "".join(segments)
        + '</svg>'
    )


def case_year_buckets(items, *, this_year: int | None = None) -> list[dict]:
    """Group CaseItem-like objects (with .year attr) into a 6-year span ending at this_year.

    Returns [{year: 2026, count: 3, tone: 'bad'|'warn'|'good'}].
    Tone is heuristic: count 0 = neutral, 1-2 = warn, 3+ = bad.
    """
    from datetime import datetime
    if this_year is None:
        this_year = datetime.now().year
    span_start = this_year - 5
    buckets: dict[int, int] = {y: 0 for y in range(span_start, this_year + 1)}
    for it in items:
        y = getattr(it, "year", None)
        if isinstance(y, int) and y in buckets:
            buckets[y] += 1
    out = []
    for y in sorted(buckets.keys()):
        c = buckets[y]
        if c == 0:
            tone = "good"
        elif c <= 2:
            tone = "warn"
        else:
            tone = "bad"
        out.append({"year": y, "count": c, "tone": tone})
    return out


def case_timeline_svg(buckets: list[dict], *, size_w: int = 360, size_h: int = 120,
                      bar_gap: int = 8) -> str:
    """Compact horizontal-bar timeline of case counts per year."""
    if not buckets:
        return ""
    pad_l, pad_r, pad_t, pad_b = 28, 8, 12, 22
    inner_w = size_w - pad_l - pad_r
    inner_h = size_h - pad_t - pad_b
    n = len(buckets)
    bar_w = max(8, (inner_w - bar_gap * (n - 1)) / n)
    max_count = max((b["count"] for b in buckets), default=1) or 1
    color_for = {
        "good": _PALETTE["good"],
        "warn": _PALETTE["warn"],
        "bad":  _PALETTE["bad"],
    }

    parts: list[str] = [
        f'<svg viewBox="0 0 {size_w} {size_h}" class="case-timeline-svg" '
        f'xmlns="http://www.w3.org/2000/svg" aria-label="案件年度分布">'
    ]
    # Baseline + tick labels for years
    for i, b in enumerate(buckets):
        x = pad_l + i * (bar_w + bar_gap)
        ratio = b["count"] / max_count if max_count else 0
        h = max(2, ratio * inner_h)
        y = pad_t + (inner_h - h)
        color = color_for.get(b["tone"], _PALETTE["accent"])
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" '
            f'rx="1" fill="{color}"/>'
        )
        # count above bar
        if b["count"] > 0:
            parts.append(
                f'<text x="{x + bar_w / 2:.2f}" y="{y - 4:.2f}" text-anchor="middle" '
                f'font-family="IBM Plex Mono, monospace" font-size="10" font-weight="700" '
                f'fill="{_PALETTE["ink"]}">{b["count"]}</text>'
            )
        # year label below — show "'26" for 2026
        parts.append(
            f'<text x="{x + bar_w / 2:.2f}" y="{size_h - 6:.2f}" text-anchor="middle" '
            f'font-family="IBM Plex Mono, monospace" font-size="10" '
            f'fill="{_PALETTE["ink_soft"]}">\'{str(b["year"])[-2:]}</text>'
        )
    parts.append('</svg>')
    return "".join(parts)


def funding_stage_position(stage: str | None) -> int:
    """Map a free-text funding stage to its position on the 6-step ladder.

    0 = 未融资, 1 = 天使, 2 = A, 3 = B, 4 = C及以上, 5 = 已上市.
    Unknown / None returns -1 (no step highlighted).
    """
    if not stage:
        return -1
    s = stage.strip().lower()
    if "上市" in s or "ipo" in s or "已上市" in s:
        return 5
    if "d" in s and ("d+" in s or "轮" in s or "及以上" in s or "pre-ipo" in s):
        return 4
    if "c" in s:
        return 4
    if "b" in s:
        return 3
    if "a" in s:
        return 2
    if "天使" in s or "angel" in s:
        return 1
    if "未融资" in s or "无融资" in s or "未披露" in s:
        return 0
    return -1


def news_items_for_timeline(items) -> list[dict]:
    """Return news items sorted by published_at desc, mapped to {when, title, summary, url, tone}."""
    def _parse(d):
        if not d:
            return ""
        if hasattr(d, "year"):
            try:
                return d.strftime("%Y-%m-%d")
            except Exception:
                return str(d)[:10]
        s = str(d)
        return s[:10] if len(s) >= 10 else s

    enriched: list[dict] = []
    for it in items:
        when = _parse(getattr(it, "published_at", None))
        enriched.append({
            "when": when or "—",
            "title": getattr(it, "title", "") or "(无标题)",
            "summary": getattr(it, "summary", "") or "",
            "url": str(getattr(it, "url", "") or ""),
        })
    enriched.sort(key=lambda x: x["when"], reverse=True)
    return enriched


__all__ = [
    "radar_svg",
    "score_ring_svg",
    "overtime_distribution",
    "salary_distribution",
    "vibe_sentiment_counts",
    "vibe_donut_svg",
    "shareholder_pie_svg",
    "case_year_buckets",
    "case_timeline_svg",
    "funding_stage_position",
    "news_items_for_timeline",
]

"""Inline SVG chart generators. Zero JS, single-file portability."""

from __future__ import annotations

import math
from typing import Iterable

from jobhunter.models.facts import OvertimeSignal, SalarySignal
from jobhunter.models.scoring import AxisScore, RiskAxis, axis_color

# ---------- Radar chart ----------

_GRID_LEVELS = (1, 3, 5)  # inner-to-outer pentagons (1=worst, 5=best)
_RADAR_PALETTE = {
    "good": "#15803d",
    "warn": "#b45309",
    "bad": "#b91c1c",
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


__all__ = [
    "radar_svg",
    "score_ring_svg",
    "overtime_distribution",
    "salary_distribution",
]

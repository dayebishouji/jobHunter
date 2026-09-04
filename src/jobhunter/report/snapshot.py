"""v0.1.17 — Per-company snapshot history (in cache dir, no SQLite).

Each `jobhunter run` saves a lightweight JSON snapshot to:
    ~/.cache/jobhunter/snapshots/{company_slug}/{YYYYMMDD-HHMM}.json

On the next run for the same company, the report's hero renders a compact
"vs 上次 (X 天前)" line showing what changed (case count, salary median,
verdict, anomaly flag). This makes repeated runs addictive — you can see
deterioration / repair in real time.

Schema is intentionally compact: just the deltas a reader actually wants to
notice. Raw snippets stay in the HTML report itself, not in the snapshot.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir

from jobhunter.models.report import ReportData


_CACHE_DIR = Path(user_cache_dir("jobhunter", "dayebishouji")) / "snapshots"


def _slug(company: str) -> str:
    """Filesystem-safe slug from company name (Chinese allowed but slash/colon stripped)."""
    s = company.strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80] or "unknown"


@dataclass
class Snapshot:
    """Compact per-run summary persisted between runs."""
    company: str
    generated_at: str           # ISO timestamp
    verdict: str | None = None
    overall_score: float | None = None
    axes: dict[str, int] = field(default_factory=dict)
    judicial_case_count: int | None = None
    anomaly_listed: bool | None = None
    salary_p50: float | None = None
    vibe_pos: int | None = None
    vibe_neg: int | None = None
    news_sentiment: str | None = None
    funding_stage: str | None = None


def _extract_snapshot(data: ReportData) -> Snapshot:
    """Build a Snapshot from current ReportData."""
    from jobhunter.report.builder import compute_overall_verdict, compute_salary_band

    verdict = compute_overall_verdict(data)
    band = compute_salary_band(data.review_facts.salary_signals) if data.review_facts else None
    axes = {a.axis.value: a.stars for a in (data.axes or []) if a.stars is not None}
    rf = data.review_facts
    jf = data.judicial_facts
    bf = data.business_facts
    cp = data.company_profile
    nf = data.news_facts
    return Snapshot(
        company=data.query.company,
        generated_at=data.generated_at.isoformat(),
        verdict=verdict.level,
        overall_score=verdict.score,
        axes=axes,
        judicial_case_count=(jf.case_count_total if jf else None),
        anomaly_listed=(bf.anomaly_listed if bf else None),
        salary_p50=(band["p50"] if band else None),
        vibe_pos=sum(1 for v in rf.vibe_signals if v.sentiment == "positive") if rf else None,
        vibe_neg=sum(1 for v in rf.vibe_signals if v.sentiment == "negative") if rf else None,
        news_sentiment=(nf.sentiment if nf else None),
        funding_stage=(cp.funding_stage if cp else None),
    )


def _snapshot_path(company: str, when: datetime) -> Path:
    slug = _slug(company)
    fname = when.strftime("%Y%m%d-%H%M") + ".json"
    p = _CACHE_DIR / slug
    p.mkdir(parents=True, exist_ok=True)
    return p / fname


def save_snapshot(data: ReportData) -> Path | None:
    """Persist the current run as a snapshot. Returns the path on success.
    Best-effort: never raises — snapshot is supplementary, not load-bearing."""
    try:
        snap = _extract_snapshot(data)
        path = _snapshot_path(data.query.company, data.generated_at)
        path.write_text(
            json.dumps(asdict(snap), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:  # noqa: BLE001
        return None


def latest_snapshot(company: str) -> Snapshot | None:
    """Load the most recent snapshot for `company`. None if none on disk."""
    if not company:
        return None
    p = _CACHE_DIR / _slug(company)
    if not p.exists():
        return None
    files = sorted(p.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        return Snapshot(**raw)
    except Exception:  # noqa: BLE001
        return None


def diff_snapshots(prev: Snapshot, curr_data: ReportData) -> dict[str, Any] | None:
    """Compute a compact diff between `prev` snapshot and current ReportData.

    Returns None if there is nothing meaningful to compare (e.g., identical).
    The dict shape is consumed directly by the template.
    """
    if prev is None:
        return None
    curr = _extract_snapshot(curr_data)
    lines: list[dict[str, Any]] = []

    # Verdict change (most important signal)
    if prev.verdict and curr.verdict and prev.verdict != curr.verdict:
        lines.append({
            "icon": "↑" if _verdict_rank(curr.verdict) > _verdict_rank(prev.verdict) else "↓",
            "label": "综合判断",
            "before": _verdict_label_zh(prev.verdict),
            "after": _verdict_label_zh(curr.verdict),
            "tone": "good" if _verdict_rank(curr.verdict) > _verdict_rank(prev.verdict) else "bad",
        })

    # Judicial case count
    if prev.judicial_case_count is not None and curr.judicial_case_count is not None:
        delta = curr.judicial_case_count - prev.judicial_case_count
        if delta != 0:
            lines.append({
                "icon": "+" if delta > 0 else "−",
                "label": "司法记录",
                "before": f"{prev.judicial_case_count} 起",
                "after": f"{curr.judicial_case_count} 起",
                "tone": "bad" if delta > 0 else "good",
                "delta": f"{'+' if delta > 0 else ''}{delta}",
            })

    # Salary P50
    if prev.salary_p50 is not None and curr.salary_p50 is not None:
        delta = round(curr.salary_p50 - prev.salary_p50, 1)
        if abs(delta) >= 1.0:
            lines.append({
                "icon": "+" if delta > 0 else "−",
                "label": "薪酬中位",
                "before": f"{prev.salary_p50:.0f}K",
                "after": f"{curr.salary_p50:.0f}K",
                "tone": "good" if delta > 0 else "neutral",
                "delta": f"{'+' if delta > 0 else ''}{delta:.1f}K",
            })

    # Anomaly
    if prev.anomaly_listed is True and curr.anomaly_listed is False:
        lines.append({"icon": "↑", "label": "经营异常", "before": "曾列入", "after": "已撤出", "tone": "good"})
    elif prev.anomaly_listed is False and curr.anomaly_listed is True:
        lines.append({"icon": "↓", "label": "经营异常", "before": "正常", "after": "已列入", "tone": "bad"})

    # Vibe shift
    if prev.vibe_pos is not None and curr.vibe_pos is not None:
        if curr.vibe_pos > prev.vibe_pos:
            lines.append({"icon": "↑", "label": "正面氛围", "before": f"{prev.vibe_pos} 条", "after": f"{curr.vibe_pos} 条", "tone": "good"})
        elif curr.vibe_pos < prev.vibe_pos:
            lines.append({"icon": "↓", "label": "正面氛围", "before": f"{prev.vibe_pos} 条", "after": f"{curr.vibe_pos} 条", "tone": "bad"})

    if not lines:
        return None

    try:
        prev_dt = datetime.fromisoformat(prev.generated_at)
        now_dt = curr_data.generated_at
        if prev_dt.tzinfo is None:
            prev_dt = prev_dt.replace(tzinfo=timezone.utc)
        days_ago = max((now_dt - prev_dt).days, 0)
    except Exception:  # noqa: BLE001
        days_ago = 0

    return {
        "prev_date": prev.generated_at,
        "days_ago": days_ago,
        "lines": lines,
    }


_VERDICT_RANK = {"avoid": 0, "caution": 1, "neutral": 2, "recommend": 3}


def _verdict_rank(level: str) -> int:
    return _VERDICT_RANK.get(level, 2)


def _verdict_label_zh(level: str) -> str:
    return {"recommend": "建议接 offer", "caution": "建议谨慎", "avoid": "建议避开", "neutral": "信息有限"}.get(level, level)
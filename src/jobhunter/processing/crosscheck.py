"""Cross-check heuristics: detect numeric / qualitative conflicts."""

from __future__ import annotations

from collections import Counter

from jobhunter.models.facts import (
    OvertimeSignal,
    ReviewFacts,
    Sentiment,
)


def detect_salary_conflicts(reviews: ReviewFacts) -> list[str]:
    """If salary reports for the same role diverge > 30%, flag it."""
    notes: list[str] = []
    salaries = [s for s in reviews.salary_signals if s.base_monthly_k]
    if len(salaries) < 2:
        return notes
    amounts = sorted(s.base_monthly_k for s in salaries if s.base_monthly_k)
    lo, hi = amounts[0], amounts[-1]
    if hi > 0 and (hi - lo) / hi > 0.30:
        notes.append(
            f"薪酬爆料差异较大：{lo:.0f}K ~ {hi:.0f}K/月 (差距 {(hi-lo)/hi:.0%})，以官方 offer 数字为准"
        )
    return notes


def detect_overtime_consensus(overtime: list[OvertimeSignal]) -> str:
    """Return majority overtime pattern (or '未知' if no signals)."""
    if not overtime:
        return "未知"
    counts = Counter(s.pattern for s in overtime)
    pattern, _ = counts.most_common(1)[0]
    return pattern


def sentiment_majority(sentiments: list[Sentiment]) -> Sentiment:
    """Return majority sentiment; 'mixed' on tie."""
    if not sentiments:
        return "neutral"
    counts = Counter(sentiments)
    top, top_n = counts.most_common(1)[0]
    if top_n == len(sentiments) / 2:
        return "mixed"
    return top


def all_notes(reviews: ReviewFacts) -> list[str]:
    """Human-readable conflict / consensus notes."""
    notes = detect_salary_conflicts(reviews)
    consensus = detect_overtime_consensus(reviews.overtime_signals)
    if consensus not in ("未知", "不加班"):
        notes.append(f"员工反复提到的工作节奏是 {consensus}")
    sent = sentiment_majority([v.sentiment for v in reviews.vibe_signals])
    if sent in ("negative", "mixed"):
        notes.append(f"团队氛围反馈呈偏 {sent} 倾向，注意交叉验证")
    return notes

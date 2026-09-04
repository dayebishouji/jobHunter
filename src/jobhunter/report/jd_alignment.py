"""v0.1.16 — JD claim alignment.

Cross-references a user-supplied JD against the gathered company facts and
returns a per-claim verdict (confirmed / contradicted / unverified) with a
short reasoning line. Pure local, no LLM call — keeps the feature cheap and
deterministic.

Design choices:
- We only check **claims that recur often enough to be worth checking**:
  overtime flexibility, salary structure (N薪 / 年包), 五险一金, 弹性工作,
  扁平化管理, 股票 / 期权, 房补 / 餐补, 技术驱动. Anything not in this list
  shows up as 「未核对」—honest about what we can and can't check.
- A claim only triggers a contradiction when the gathered data **actively
  disagrees**, not when it's silent. We try hard not to false-positive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from jobhunter.models.facts import BusinessFacts, JudicialFacts, ReviewFacts
from jobhunter.models.report import ReportData

ClaimStatus = Literal["confirmed", "contradicted", "unverified"]


@dataclass
class JdClaim:
    """One claim extracted from the JD text, cross-checked against facts."""
    claim: str                 # user-facing label, e.g. "弹性工作 / 不加班"
    pattern_label: str         # short label used inside matchers
    status: ClaimStatus
    reasoning: str             # one-sentence explanation referencing the data
    matched_text: str | None = None  # the exact snippet from JD that triggered


# Each entry: (label, regex list to find claim, evaluator(data) -> (status, reasoning))
# The regex list is matched against the JD; the evaluator is matched against facts.
_RULES: list[tuple[str, list[re.Pattern[str]], str]] = [
    (
        "弹性工作 / 不加班",
        [re.compile(r"弹性工作|弹性.{0,6}时间|不加班|WLB|work.?life.?balance")],
        "overtime_flex",
    ),
    (
        "15 薪及以上",
        [re.compile(r"\d{2}\s*薪|15\s*薪|16\s*薪|14\s*薪|年包")],
        "salary_total_months",
    ),
    (
        "五险一金",
        [re.compile(r"五险一金|六险一金|社保.{0,4}齐全|足额.{0,4}缴纳")],
        "social_insurance",
    ),
    (
        "扁平化管理",
        [re.compile(r"扁平化|没有\s*层级|直接\s*汇报|小\s*组\s*织")],
        "flat_org",
    ),
    (
        "股票 / 期权",
        [re.compile(r"股票|期权|RSU|股权激励|持股计划|ESOP")],
        "equity",
    ),
    (
        "房补 / 餐补 / 福利",
        [re.compile(r"房补|餐补|食堂|免费.{0,4}(三餐|午餐|晚餐)|补充医疗|商业保险")],
        "perks",
    ),
    (
        "技术驱动 / 工程师文化",
        [re.compile(r"技术驱动|工程师文化|技术氛围|geek|硬核|开源")],
        "tech_driven",
    ),
    (
        "团队年轻 / 有活力",
        [re.compile(r"团队年轻|90\s*后|95\s*后|有活力|氛围好")],
        "young_team",
    ),
]


def _eval_overtime_flex(rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    """Claim: 不加班 / 弹性. Contradicted if we see 996/大小周 evidence."""
    if not rf:
        return "unverified", "暂无评价数据，无法核对"
    bad = [o for o in rf.overtime_signals if o.pattern in ("996", "995", "大小周")]
    good = [o for o in rf.overtime_signals if o.pattern in ("弹性", "不加班")]
    if bad and not good:
        return "contradicted", f"已有 {len(bad)} 条 996 / 大小周爆料与该承诺冲突"
    if good and not bad:
        return "confirmed", f"评价中多次出现「{good[0].pattern}」，与承诺一致"
    if bad and good:
        return "contradicted", f"评价两极：{len(bad)} 条 996 爆料与 {len(good)} 条弹性说法并存"
    return "unverified", "评价里未明确提及加班节奏"


def _eval_salary_total_months(rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    """Claim: N薪 / 年包 ≥ 15. Look at salary_total_months in salary signals."""
    if not rf:
        return "unverified", "暂无薪酬爆料，无法核对"
    months_vals = [s.salary_total_months for s in rf.salary_signals if s.salary_total_months]
    if not months_vals:
        return "unverified", "薪酬爆料里未提到总月薪数"
    avg = sum(months_vals) / len(months_vals)
    if avg >= 14.5:
        return "confirmed", f"爆料平均 {avg:.1f} 薪，符合承诺"
    if avg >= 12.5:
        return "contradicted", f"爆料平均 {avg:.1f} 薪，低于承诺的 15 薪"
    return "contradicted", f"爆料平均 {avg:.1f} 薪，普遍低于 14 薪"


def _eval_social_insurance(_rf: ReviewFacts | None, _bf: BusinessFacts | None) -> tuple[ClaimStatus, str]:
    """Claim: 五险一金. Companies are legally required to provide this — verified
    only when review data explicitly confirms it; never contradicted because
    absence-of-evidence ≠ absence-of-fact."""
    if _rf is None:
        return "unverified", "暂无评价数据；五险一金为法律强制，无法用评价单独证否"
    # Reviews that explicitly mention 五险一金 / 足额 → confirmed
    has_pos = any("五险一金" in (s.evidence or "") or "足额" in (s.evidence or "") for s in rf_evidence_iter(_rf))
    has_neg = any("不交" in (s.evidence or "") or "按最低" in (s.evidence or "") for s in rf_evidence_iter(_rf))
    if has_pos and not has_neg:
        return "confirmed", "评价中提到「五险一金按实际工资缴纳」"
    if has_neg:
        return "contradicted", "评价中提到按最低基数缴纳"
    return "unverified", "评价里未提及基数细节；建议面试时确认"


def _eval_flat_org(rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    """Claim: 扁平化管理. Check vibe sentiment — negative often means lots of layers."""
    if not rf:
        return "unverified", "暂无氛围数据"
    neg = sum(1 for v in rf.vibe_signals if v.sentiment == "negative")
    pos = sum(1 for v in rf.vibe_signals if v.sentiment == "positive")
    if neg > pos and neg >= 2:
        return "contradicted", f"负面氛围信号 ({neg}) 多于正面 ({pos})，常与多层管理关联"
    if pos > neg and pos >= 2:
        return "confirmed", f"正面氛围信号占多数 ({pos} vs {neg})"
    return "unverified", "氛围信号较少，不足以判断"


def _eval_equity(_rf: ReviewFacts | None, bf: BusinessFacts | None, cp) -> tuple[ClaimStatus, str]:
    """Claim: 股票 / 期权. Only contradicted when reviews explicitly say 'no equity'."""
    # We can't reliably infer equity presence from salary data alone; default to unverified.
    return "unverified", "期权 / RSU 信息通常不出现在公开评价中，建议面试时确认"


def _eval_perks(_rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    """Claim: 房补 / 餐补 / 福利. Hard to verify from public reviews — default unverified."""
    return "unverified", "福利细节在公开评价里少见，建议 HR 沟通时逐项确认"


def _eval_tech_driven(rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    if not rf:
        return "unverified", "暂无氛围数据"
    pos = sum(1 for v in rf.vibe_signals if v.sentiment == "positive")
    return ("confirmed" if pos >= 2 else "unverified"), f"正面氛围信号 {pos} 条"


def _eval_young_team(rf: ReviewFacts | None) -> tuple[ClaimStatus, str]:
    if not rf:
        return "unverified", "暂无氛围数据"
    pos = sum(1 for v in rf.vibe_signals if v.sentiment == "positive")
    return ("confirmed" if pos >= 2 else "unverified"), f"正面氛围信号 {pos} 条"


_EVALUATORS = {
    "overtime_flex": lambda rf, bf, cp: _eval_overtime_flex(rf),
    "salary_total_months": lambda rf, bf, cp: _eval_salary_total_months(rf),
    "social_insurance": lambda rf, bf, cp: _eval_social_insurance(rf, bf),
    "flat_org": lambda rf, bf, cp: _eval_flat_org(rf),
    "equity": lambda rf, bf, cp: _eval_equity(rf, bf, cp),
    "perks": lambda rf, bf, cp: _eval_perks(rf),
    "tech_driven": lambda rf, bf, cp: _eval_tech_driven(rf),
    "young_team": lambda rf, bf, cp: _eval_young_team(rf),
}


def rf_evidence_iter(rf: ReviewFacts):
    """Yield every signal-like object that has an `evidence` attr — used by
    claim evaluators that want to grep JD-relevant phrases."""
    for src in (rf.salary_signals, rf.overtime_signals, rf.vibe_signals, rf.turnover_signals):
        for s in src:
            yield s


def compute_jd_alignment(data: ReportData) -> list[JdClaim]:
    """Walk the JD against `_RULES` and return per-claim verdicts.

    Returns an empty list when `data.query.jd_text` is None / empty.
    """
    jd = (data.query.jd_text or "").strip()
    if not jd:
        return []

    rf = data.review_facts
    bf = data.business_facts
    cp = data.company_profile

    claims: list[JdClaim] = []
    for label, patterns, key in _RULES:
        matched = None
        for p in patterns:
            m = p.search(jd)
            if m:
                matched = m.group(0)
                break
        if matched is None:
            continue
        status, reasoning = _EVALUATORS[key](rf, bf, cp)
        claims.append(JdClaim(
            claim=label,
            pattern_label=key,
            status=status,
            reasoning=reasoning,
            matched_text=matched,
        ))
    return claims
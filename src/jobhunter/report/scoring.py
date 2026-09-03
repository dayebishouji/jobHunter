"""Heuristic 5-axis scoring — deterministic, no LLM."""

from __future__ import annotations

from datetime import date, datetime, timezone

from jobhunter.models.facts import (
    AggregatedFindings,
    NewsFacts,
    ReviewFacts,
)
from jobhunter.models.raw import RawItem
from jobhunter.models.scoring import AxisScore, RiskAxis


def _overtime_score(reviews: ReviewFacts | None) -> tuple[int, str, list[str]]:
    if not reviews or not reviews.overtime_signals:
        return (3, "暂未拿到加班模式信号；建议面试时主动询问。", [])
    patterns = [s.pattern for s in reviews.overtime_signals]
    bad = sum(1 for p in patterns if p in ("996", "995", "大小周"))
    good = sum(1 for p in patterns if p in ("弹性", "不加班"))
    total = len(patterns)
    if bad / total >= 0.6:
        return (2, f"多数员工提到 {bad}/{total} 反馈 996/大小周 类节奏，加班偏重。", [str(s.url) for s in reviews.overtime_signals if s.url])
    if good / total >= 0.6:
        return (4, f"多数员工反馈 {good}/{total} 节奏偏弹性，加班友好。", [str(s.url) for s in reviews.overtime_signals if s.url])
    return (3, f"员工对加班节奏看法混合（{bad}/{total} 偏重，{good}/{total} 偏轻）。", [str(s.url) for s in reviews.overtime_signals if s.url])


def _salary_trust_score(reviews: ReviewFacts | None, conflicts: list[str]) -> tuple[int, str, list[str]]:
    if not reviews or not reviews.salary_signals:
        return (3, "暂无薪酬爆料。", [])
    base = 5
    if conflicts:
        base -= 1
    if len(reviews.salary_signals) <= 1:
        base = min(base, 3)
    return (max(1, base), f"基于 {len(reviews.salary_signals)} 条爆料" + ("；存在冲突信号" if conflicts else "。"),
            [str(s.url) for s in reviews.salary_signals if s.url])


def _judicial_score(findings: AggregatedFindings | None) -> tuple[int, str, list[str]]:
    j = findings.judicial if findings else None
    if j is None:
        return (3, "司法数据未能获取；建议人工到 wenshu.court.gov.cn 与 zxgk.court.gov.cn 核查。", [])
    score = 5
    note = "暂无显著司法记录"
    if j.case_count_total:
        score -= min(4, j.case_count_total // 10)
        note = f"累计 {j.case_count_total} 条相关案件"
    if j.enforcement_records:
        score -= min(2, j.enforcement_records)
        note += f"，{j.enforcement_records} 条被执行记录"
    return (max(1, min(5, score)), note + "。", [str(u) for u in j.source_urls])


def _business_score(findings: AggregatedFindings | None) -> tuple[int, str, list[str]]:
    b = findings.business if findings else None
    if b is None:
        return (3, "工商基本面未能获取（本机 gsxt.gov.cn 不可达），建议人工核实。", [])
    score = 5
    notes: list[str] = []
    if b.status and b.status != "存续":
        score -= 2
        notes.append(f"经营状态：{b.status}")
    if b.anomaly_listed:
        score -= 2
        notes.append("被列入经营异常名录")
    if b.established_at:
        try:
            est = b.established_at
            if isinstance(est, datetime):
                est = est.date()
            if (date.today() - est).days < 365:
                score -= 1
                notes.append("成立 < 1 年，新公司")
        except Exception:  # noqa: BLE001
            pass
    label = "; ".join(notes) or "工商基本面正常"
    return (max(1, min(5, score)), label + "。", [str(u) for u in b.source_urls])


def _culture_score(reviews: ReviewFacts | None, news: NewsFacts | None) -> tuple[int, str, list[str]]:
    if not reviews or not reviews.vibe_signals:
        if news and news.sentiment == "negative":
            return (3, "近期舆情偏负面，氛围信号不足。", [str(u) for u in news.source_urls])
        return (3, "暂无团队氛围直接信号。", [])
    pos = sum(1 for v in reviews.vibe_signals if v.sentiment == "positive")
    neg = sum(1 for v in reviews.vibe_signals if v.sentiment == "negative")
    total = len(reviews.vibe_signals)
    if pos / total >= 0.6:
        return (4, f"氛围偏正面（{pos}/{total}）。", [str(v.url) for v in reviews.vibe_signals if v.url])
    if neg / total >= 0.6:
        return (2, f"氛围偏负面（{neg}/{total}），注意交叉验证。", [str(v.url) for v in reviews.vibe_signals if v.url])
    return (3, f"氛围信号混合（positive {pos}/{total}, negative {neg}/{total}）。", [str(v.url) for v in reviews.vibe_signals if v.url])


def compute_axes(
    findings: AggregatedFindings | None,
    by_domain: dict[str, list[RawItem]],
    salary_conflicts: list[str],
) -> list[AxisScore]:
    reviews = findings.reviews if findings else None
    news = findings.news if findings else None

    o_stars, o_note, o_urls = _overtime_score(reviews)
    s_stars, s_note, s_urls = _salary_trust_score(reviews, salary_conflicts)
    j_stars, j_note, j_urls = _judicial_score(findings)
    b_stars, b_note, b_urls = _business_score(findings)
    c_stars, c_note, c_urls = _culture_score(reviews, news)

    return [
        AxisScore(axis=RiskAxis.OVERTIME, stars=o_stars, rationale=o_note, evidence_urls=[u for u in o_urls if u]),
        AxisScore(axis=RiskAxis.SALARY_TRUST, stars=s_stars, rationale=s_note, evidence_urls=[u for u in s_urls if u]),
        AxisScore(axis=RiskAxis.JUDICIAL, stars=j_stars, rationale=j_note, evidence_urls=[u for u in j_urls if u]),
        AxisScore(axis=RiskAxis.BUSINESS, stars=b_stars, rationale=b_note, evidence_urls=[u for u in b_urls if u]),
        AxisScore(axis=RiskAxis.CULTURE, stars=c_stars, rationale=c_note, evidence_urls=[u for u in c_urls if u]),
    ]

"""Industry baseline averages for 「比同行高 X%」 data stories.

Pure data — no I/O. Used by `compute_chapter_stories()` to contextualize
a company's numbers against a static industry average. Numbers are
rough heuristics from publicly available industry reports (脉脉人才研究院
/ 智联 / 麦可思); not statistical truth — meant to be illustrative.

A "default" entry exists for unknown industries so we always have a
baseline to compare against rather than silently skipping the data story.
"""

from __future__ import annotations

from typing import Literal

# Baseline schema per industry — all values are normalized per-employee or
# per-company-per-year where applicable.
IndustryKey = Literal[
    "互联网",
    "跨境电商",
    "金融",
    "医疗",
    "教育",
    "制造业",
    "零售",
    "餐饮",
    "物流",
    "房地产",
    "游戏",
    "default",
]

INDUSTRY_BASELINES: dict[IndustryKey, dict[str, float]] = {
    "互联网": {
        "lawsuits_per_year": 0.8,
        "overtime_hours_per_week": 12.0,
        "turnover_rate": 0.18,
        "salary_k_monthly_3y": 22.0,
    },
    "跨境电商": {
        "lawsuits_per_year": 0.6,
        "overtime_hours_per_week": 14.0,
        "turnover_rate": 0.28,
        "salary_k_monthly_3y": 12.0,
    },
    "金融": {
        "lawsuits_per_year": 1.2,
        "overtime_hours_per_week": 8.0,
        "turnover_rate": 0.14,
        "salary_k_monthly_3y": 18.0,
    },
    "医疗": {
        "lawsuits_per_year": 2.5,
        "overtime_hours_per_week": 18.0,
        "turnover_rate": 0.20,
        "salary_k_monthly_3y": 14.0,
    },
    "教育": {
        "lawsuits_per_year": 1.0,
        "overtime_hours_per_week": 10.0,
        "turnover_rate": 0.22,
        "salary_k_monthly_3y": 11.0,
    },
    "制造业": {
        "lawsuits_per_year": 1.5,
        "overtime_hours_per_week": 22.0,
        "turnover_rate": 0.25,
        "salary_k_monthly_3y": 8.0,
    },
    "零售": {
        "lawsuits_per_year": 0.6,
        "overtime_hours_per_week": 12.0,
        "turnover_rate": 0.30,
        "salary_k_monthly_3y": 7.0,
    },
    "餐饮": {
        "lawsuits_per_year": 0.4,
        "overtime_hours_per_week": 16.0,
        "turnover_rate": 0.45,
        "salary_k_monthly_3y": 6.0,
    },
    "物流": {
        "lawsuits_per_year": 0.8,
        "overtime_hours_per_week": 20.0,
        "turnover_rate": 0.35,
        "salary_k_monthly_3y": 8.0,
    },
    "房地产": {
        "lawsuits_per_year": 1.8,
        "overtime_hours_per_week": 14.0,
        "turnover_rate": 0.22,
        "salary_k_monthly_3y": 13.0,
    },
    "游戏": {
        "lawsuits_per_year": 0.5,
        "overtime_hours_per_week": 18.0,
        "turnover_rate": 0.20,
        "salary_k_monthly_3y": 18.0,
    },
    # Fallback when company industry can't be classified.
    "default": {
        "lawsuits_per_year": 1.0,
        "overtime_hours_per_week": 14.0,
        "turnover_rate": 0.22,
        "salary_k_monthly_3y": 12.0,
    },
}

# Industry keyword → IndustryKey. Order matters: more specific matches first.
# Substring match against `industry_text.lower()`.
_INDUSTRY_KEYWORDS: list[tuple[IndustryKey, tuple[str, ...]]] = [
    ("互联网", ("互联网", "软件", "it ", "tech", "科技公司")),
    ("跨境电商", ("跨境", "亚马逊", "amazon", "shopify", "ebay", "temu", "tiktok 电商")),
    ("游戏", ("游戏", "gaming", "电竞")),
    ("金融", ("金融", "银行", "证券", "基金", "保险", "投资", "p2p", "区块链")),
    ("医疗", ("医疗", "医院", "医药", "诊所", "生物", "制药", "互联网医疗")),
    ("教育", ("教育", "培训", "学校", "k12", "在线教育")),
    ("制造业", ("制造", "工厂", "工业", "汽车制造", "电子厂", "机械")),
    ("零售", ("零售", "超市", "便利店", "电商平台", "电商")),
    ("餐饮", ("餐饮", "餐厅", "食品", "外卖", "奶茶")),
    ("物流", ("物流", "快递", "货运", "配送", "仓储")),
    ("房地产", ("房地产", "物业", "中介", "中介服务", "租房")),
]


def pick_industry(industry_text: str | None) -> IndustryKey:
    """Best-effort mapping from free-text industry description to a baseline
    key. Returns 'default' when no specific industry matches.

    Matches via case-insensitive substring against `industry_text`. Falls
    back to 'default' for None / empty / unrecognized text so callers
    never get a KeyError.
    """
    if not industry_text or not industry_text.strip():
        return "default"
    text = industry_text.lower()
    for key, keywords in _INDUSTRY_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return key
    return "default"


def baseline(industry_key: IndustryKey) -> dict[str, float]:
    """Return the baseline dict for the given industry key. Always returns
    a dict (uses 'default' for unknown keys) so callers can index without
    KeyError."""
    return INDUSTRY_BASELINES.get(industry_key, INDUSTRY_BASELINES["default"])


def delta_pct(value: float, baseline_value: float) -> float:
    """Return signed percentage delta vs baseline: (value - baseline) / baseline * 100.
    Returns 0.0 when baseline is zero to avoid division-by-zero noise."""
    if baseline_value == 0:
        return 0.0
    return (value - baseline_value) / baseline_value * 100.0

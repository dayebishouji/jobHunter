"""Search query builders — pure functions, no I/O. Hand-tuned for Chinese UGC."""

from __future__ import annotations

from jobhunter.models.query import CompanyQuery

# Allow-listed domains — these are the only sources Tavily is allowed to use
# for a given domain. Reviews excludes company-controlled corporate sites.
REVIEW_DOMAINS: list[str] = [
    "kanzhun.com",
    "maimai.cn",
    "zhihu.com",
    "xiaohongshu.com",
    "nowcoder.com",
    "douban.com",
    "bilibili.com",
    "tieba.baidu.com",
    "v2ex.com",
    "hupu.com",
    "1point3acres.com",
    "glassdoor.com",
    "lagou.com",
    "zhipin.com",
    "dianping.com",
]

NEWS_DOMAINS: list[str] = [
    "36kr.com",
    "huxiu.com",
    "weibo.com",
    "baijiahao.baidu.com",
    "sina.cn",
    "qq.com",
    "163.com",
    "douyin.com",
]

# Business registration / company info aggregators (替代 gsxt.gov.cn — 后者在非 CN IP 下不可达)
BUSINESS_DOMAINS: list[str] = [
    "aiqicha.baidu.com",
    "tianyancha.com",
    "qcc.com",
    "creditchina.gov.cn",
]

# Judicial risk / court records (替代 wenshu.court.gov.cn — 同上)
JUDICIAL_DOMAINS: list[str] = [
    "wenshu.court.gov.cn",
    "rmfygg.court.gov.cn",
    "zxgk.court.gov.cn",
    "tianyancha.com",
]


def review_queries(q: CompanyQuery) -> list[str]:
    """Generate the set of review-oriented queries for one company."""
    c = q.company
    p = q.position.strip()
    city = q.city.strip()
    base = [c, p] if p else [c]
    label = " ".join(base)

    queries = [
        f'"{c}" 加班',
        f'"{c}" 离职率',
        f'"{c}" 脉脉 爆料',
        f'"{c}" 看准 工资',
        f'"{c}" 知乎',
        f'"{c}" 体验',
    ]
    if p:
        queries.append(f'"{c}" {p} 体验')
        queries.append(f'{p} {c} {"避雷" if not city else f"{city} 避雷"}')
    return queries


def news_queries(q: CompanyQuery) -> list[str]:
    """Generate news/PR-oriented queries for one company."""
    c = q.company
    year = "2026"
    return [
        f'"{c}" 最新',
        f'"{c}" 裁员 OR 倒闭 OR 收购',
        f'"{c}" 融资 OR 上市',
        f'"{c}" {year}',
    ]


def business_queries(q: CompanyQuery) -> list[str]:
    """Business registration / company info queries (aiqicha / tianyancha / qcc / creditchina)."""
    c = q.company
    return [
        f'"{c}" 工商信息',
        f'"{c}" 法人 注册资本',
        f'"{c}" 股东 持股比例',
        f'"{c}" 经营状态 经营异常',
    ]


def judicial_queries(q: CompanyQuery) -> list[str]:
    """Judicial risk / court records queries."""
    c = q.company
    return [
        f'"{c}" 裁判文书',
        f'"{c}" 诉讼 OR 起诉',
        f'"{c}" 被执行',
        f'"{c}" 失信被执行人',
    ]

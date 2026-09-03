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
]

NEWS_DOMAINS: list[str] = [
    "36kr.com",
    "huxiu.com",
    "weibo.com",
    "baijiahao.baidu.com",
    "sina.cn",
    "qq.com",
    "163.com",
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

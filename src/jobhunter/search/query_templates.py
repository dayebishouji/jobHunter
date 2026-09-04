"""Search query builders — pure functions, no I/O. Hand-tuned for Chinese UGC."""

from __future__ import annotations

from jobhunter.models.query import CompanyQuery

# ----------------------------------------------------------------------------
# Reviews-domain allowlist
#
# Two tiers:
# 1. GENERAL_REVIEW_DOMAINS — queried for every company regardless of position.
# 2. Vertical-specific allowlists — only queried when position matches a
#    keyword in POSITION_DOMAIN_HINTS, to keep Tavily credit cost bounded.
#
# REVIEW_DOMAINS (the union) is kept as a back-compat constant for callers that
# want the full list; production code uses domains_for_position() to apply the
# position-aware filter.
# ----------------------------------------------------------------------------

GENERAL_REVIEW_DOMAINS: list[str] = [
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
    # v0.1.11 — A 级全行业通用（黑猫投诉是真正的"风险信号"金矿）
    "tousu.sina.com.cn",   # 黑猫投诉 — 315 投诉平台，全行业
    "36dianping.com",      # 36 氪企服点评 — B2B SaaS / 企业服务评价
    "weibo.com",           # 微博（舆情爆料 — 与 NEWS_DOMAINS 双备案）
    "douyin.com",          # 抖音（视频曝光 — 与 NEWS_DOMAINS 双备案）
    "kuaishou.com",        # 快手（下沉市场 / 本地企业评价）
]

# Vertical-industry UGC platforms (added in v0.1.9 — 跨境小白 discovery).
# Each list is a curated allowlist for that vertical; quality & 吐槽-density
# have been sanity-checked via WebSearch but not via live Tavily runs.
CROSS_BORDER_REVIEW_DOMAINS: list[str] = [
    "kjxb.org",                # 跨境小白 — 跨境电商吐槽/避雷
    "zhiwuwubuyan.com",        # 知无不言 — 跨境圈最活跃论坛
    "amz123.com",              # AMZ123 — 跨境导航 + 人才库
    "10100.com",               # 大数跨境 — 行业媒体
    # v0.1.11 — 跨境电商补充
    "cifnews.com",             # 雨果跨境 — 行业媒体
    "shangjia.com",            # 卖家之家 — 卖家互助社区
]

GAMING_REVIEW_DOMAINS: list[str] = [
    "ngabbs.com",              # NGA — 撕逼/加班/9126 帖高频
]

MEDICAL_REVIEW_DOMAINS: list[str] = [
    "bbs.dxy.com",             # 丁香园 — 300万+ 医生用户
]

DEVELOPER_REVIEW_DOMAINS: list[str] = [
    "juejin.cn",               # 掘金 — 沸点职场话题
    "segmentfault.com",        # 思否
    "oschina.net",             # OSChina — 开源圈吐槽
]

# v0.1.10 — coverage expansion (4 more verticals).
SECURITY_REVIEW_DOMAINS: list[str] = [
    "freebuf.com",             # FreeBuf — 国内安全媒体龙头
    "bbs.pediy.com",           # 看雪论坛 — 25 年老牌逆向社区
]

ECOMMERCE_OPS_REVIEW_DOMAINS: list[str] = [
    "paidai.com",              # 派代 — 电商运营最大社区（淘系 / 京东 / 拼多多）
]

DESIGN_REVIEW_DOMAINS: list[str] = [
    "zcool.com.cn",            # 站酷 — 1700 万+ 设计师
    "ui.cn",                   # UI 中国 — UI/UX 垂直
]

CIVIL_SERVICE_REVIEW_DOMAINS: list[str] = [
    "qzzn.com",                # QZZN — 公务员 / 事业编老牌论坛（已没落但仍有内容）
]

HR_REVIEW_DOMAINS: list[str] = [
    "hrloo.com",               # 三茅人力资源网 — 400 万 HR 用户
]

# v0.1.11 — B 级行业垂类（黑猫投诉是真正的"风险信号"金矿，全行业已入 GENERAL）。
# 这些触发由 POSITION_DOMAIN_HINTS 关键词决定，避免在无关行业烧 credits。
AUTO_REVIEW_DOMAINS: list[str] = [
    "autohome.com.cn",         # 汽车之家 — 车主社区 + 投诉
    "dongchedi.com",           # 懂车帝 — 评测 + 投诉
    "yiche.com",               # 易车 — 行业资讯 + 评价
    "12365auto.com",           # 车质网 — 汽车质量投诉集中地（背调高价值）
]

FINANCE_REVIEW_DOMAINS: list[str] = [
    "xueqiu.com",              # 雪球 — 投资者社区
    "guba.eastmoney.com",      # 东方财富股吧 — 散户讨论
    "10jqka.com.cn",           # 同花顺 — 财经社区
]

REAL_ESTATE_REVIEW_DOMAINS: list[str] = [
    "fang.com",                # 房天下 — 楼盘 + 评价
    "anjuke.com",              # 安居客 — 二手房 / 中介评价
    "ke.com",                  # 贝壳找房 — 经纪人评价
]

LOGISTICS_REVIEW_DOMAINS: list[str] = [
    "360che.com",              # 卡车之家 — 货车司机社区
    "huochebang.com",          # 货车帮 — 司机 / 货主
    "yunmanman.com",           # 运满满 — 货运信息平台
]

REVIEW_DOMAINS: list[str] = sorted({
    *GENERAL_REVIEW_DOMAINS,
    *CROSS_BORDER_REVIEW_DOMAINS,
    *GAMING_REVIEW_DOMAINS,
    *MEDICAL_REVIEW_DOMAINS,
    *DEVELOPER_REVIEW_DOMAINS,
    *SECURITY_REVIEW_DOMAINS,
    *ECOMMERCE_OPS_REVIEW_DOMAINS,
    *DESIGN_REVIEW_DOMAINS,
    *CIVIL_SERVICE_REVIEW_DOMAINS,
    *HR_REVIEW_DOMAINS,
    *AUTO_REVIEW_DOMAINS,
    *FINANCE_REVIEW_DOMAINS,
    *REAL_ESTATE_REVIEW_DOMAINS,
    *LOGISTICS_REVIEW_DOMAINS,
})

# Position keyword → vertical allowlist. Lowercase substring match against
# `q.position.lower()`; multiple matches union their domains.
# Add keywords here (not 1-token over-fits) so the position check stays
# robust against e.g. "高级 Python 后端" matching both "python" and "后端".
POSITION_DOMAIN_HINTS: dict[str, list[str]] = {
    # 跨境电商
    "跨境": CROSS_BORDER_REVIEW_DOMAINS,
    "亚马逊": ["kjxb.org", "zhiwuwubuyan.com", "amz123.com"],
    "amazon": CROSS_BORDER_REVIEW_DOMAINS,
    "shopify": ["zhiwuwubuyan.com", "10100.com"],
    "ebay": ["zhiwuwubuyan.com", "amz123.com"],
    "电商": sorted({*CROSS_BORDER_REVIEW_DOMAINS, *ECOMMERCE_OPS_REVIEW_DOMAINS}),
    "temu": ["zhiwuwubuyan.com", "10100.com"],
    "tiktok": CROSS_BORDER_REVIEW_DOMAINS,
    # 电商运营（淘系 / 京东 / 拼多多 — 派代主场）
    "淘宝": ECOMMERCE_OPS_REVIEW_DOMAINS,
    "天猫": ECOMMERCE_OPS_REVIEW_DOMAINS,
    "京东": ECOMMERCE_OPS_REVIEW_DOMAINS,
    "拼多多": ECOMMERCE_OPS_REVIEW_DOMAINS,
    "淘系": ECOMMERCE_OPS_REVIEW_DOMAINS,
    # 游戏
    "游戏": GAMING_REVIEW_DOMAINS,
    "策划": GAMING_REVIEW_DOMAINS,
    "原画": GAMING_REVIEW_DOMAINS,
    "美术": GAMING_REVIEW_DOMAINS,
    "关卡": GAMING_REVIEW_DOMAINS,
    "ta": GAMING_REVIEW_DOMAINS,  # technical artist
    # 医护
    "医生": MEDICAL_REVIEW_DOMAINS,
    "护士": MEDICAL_REVIEW_DOMAINS,
    "医师": MEDICAL_REVIEW_DOMAINS,
    "药剂": MEDICAL_REVIEW_DOMAINS,
    "临床": MEDICAL_REVIEW_DOMAINS,
    "影像": MEDICAL_REVIEW_DOMAINS,
    # 程序员 / 开发
    "后端": DEVELOPER_REVIEW_DOMAINS,
    "前端": DEVELOPER_REVIEW_DOMAINS,
    "java": ["juejin.cn", "oschina.net"],
    "python": ["juejin.cn", "segmentfault.com"],
    "算法": ["juejin.cn"],
    "运维": ["oschina.net"],
    "测试": ["oschina.net", "juejin.cn"],
    "android": DEVELOPER_REVIEW_DOMAINS,
    "ios": DEVELOPER_REVIEW_DOMAINS,
    "嵌入式": DEVELOPER_REVIEW_DOMAINS,
    # 网安 / 渗透 (v0.1.10)
    "安全": SECURITY_REVIEW_DOMAINS,
    "网安": SECURITY_REVIEW_DOMAINS,
    "渗透": SECURITY_REVIEW_DOMAINS,
    "漏洞": SECURITY_REVIEW_DOMAINS,
    "逆向": SECURITY_REVIEW_DOMAINS,
    "信息安全": SECURITY_REVIEW_DOMAINS,
    # 设计 (v0.1.10)
    "设计": DESIGN_REVIEW_DOMAINS,
    "ui": DESIGN_REVIEW_DOMAINS,
    "ux": DESIGN_REVIEW_DOMAINS,
    "平面": DESIGN_REVIEW_DOMAINS,
    "视觉": DESIGN_REVIEW_DOMAINS,
    "美工": DESIGN_REVIEW_DOMAINS,
    "交互": DESIGN_REVIEW_DOMAINS,
    # 公考 / 事业编 (v0.1.10)
    "公务员": CIVIL_SERVICE_REVIEW_DOMAINS,
    "事业编": CIVIL_SERVICE_REVIEW_DOMAINS,
    "选调生": CIVIL_SERVICE_REVIEW_DOMAINS,
    "公考": CIVIL_SERVICE_REVIEW_DOMAINS,
    "国考": CIVIL_SERVICE_REVIEW_DOMAINS,
    "省考": CIVIL_SERVICE_REVIEW_DOMAINS,
    # HR / 人力 (v0.1.10)
    "hr": HR_REVIEW_DOMAINS,
    "人力": HR_REVIEW_DOMAINS,
    "招聘": HR_REVIEW_DOMAINS,
    "hrbp": HR_REVIEW_DOMAINS,
    # 汽车 (v0.1.11)
    "汽车": AUTO_REVIEW_DOMAINS,
    "车辆": AUTO_REVIEW_DOMAINS,
    "试驾": AUTO_REVIEW_DOMAINS,
    "4s": AUTO_REVIEW_DOMAINS,
    # 金融 (v0.1.11)
    "金融": FINANCE_REVIEW_DOMAINS,
    "银行": FINANCE_REVIEW_DOMAINS,
    "证券": FINANCE_REVIEW_DOMAINS,
    "基金": FINANCE_REVIEW_DOMAINS,
    "股票": FINANCE_REVIEW_DOMAINS,
    "券商": FINANCE_REVIEW_DOMAINS,
    "保险": FINANCE_REVIEW_DOMAINS,
    "投资": FINANCE_REVIEW_DOMAINS,
    "理财": FINANCE_REVIEW_DOMAINS,
    "量化": FINANCE_REVIEW_DOMAINS,
    # 房地产 / 物业 / 中介 (v0.1.11)
    "物业": REAL_ESTATE_REVIEW_DOMAINS,
    "中介": REAL_ESTATE_REVIEW_DOMAINS,
    "租房": REAL_ESTATE_REVIEW_DOMAINS,
    "房产": REAL_ESTATE_REVIEW_DOMAINS,
    "置业": REAL_ESTATE_REVIEW_DOMAINS,
    "楼盘": REAL_ESTATE_REVIEW_DOMAINS,
    "经纪人": REAL_ESTATE_REVIEW_DOMAINS,
    # 物流 / 货运 / 快递 (v0.1.11)
    "物流": LOGISTICS_REVIEW_DOMAINS,
    "货运": LOGISTICS_REVIEW_DOMAINS,
    "快递": LOGISTICS_REVIEW_DOMAINS,
    "卡车": LOGISTICS_REVIEW_DOMAINS,
    "司机": LOGISTICS_REVIEW_DOMAINS,
    "货车": LOGISTICS_REVIEW_DOMAINS,
    "配送": LOGISTICS_REVIEW_DOMAINS,
}


def domains_for_position(position: str) -> list[str]:
    """Return the position-filtered REVIEW_DOMAINS allowlist.

    Cost-control contract:
    - Always includes the 15 GENERAL_REVIEW_DOMAINS.
    - When `position` matches at least one keyword in POSITION_DOMAIN_HINTS,
      adds ONLY the matched verticals. A user searching for "后端" does not
      pay to query 跨境小白 / 丁香园 / NGA.
    - When position is empty OR matches no keyword, returns the full
      REVIEW_DOMAINS union so coverage is never accidentally truncated by an
      unrecognized position string.

    The 6 base review queries run on this allowlist, so reducing it from 24
    to e.g. 18 domains directly cuts Tavily credit cost per query.
    """
    if not position or not position.strip():
        return list(REVIEW_DOMAINS)
    p = position.lower()
    extra: set[str] = set()
    for kw, domains in POSITION_DOMAIN_HINTS.items():
        if kw in p:
            extra.update(domains)
    if not extra:
        return list(REVIEW_DOMAINS)
    return sorted({*GENERAL_REVIEW_DOMAINS, *extra})

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

# Company profile / encyclopedia / startup database sources
# (主营业务 / 产品 / 行业 / 融资阶段 / 规模 / 官网 etc.)
# v0.1.14 — expanded: 虎嗅 (huxiu) / 猎云网 (lieyunwang) / 创业家 (chuangsanjia)
# bring higher-quality profile/financing coverage than the encyclopedias.
COMPANY_INFO_DOMAINS: list[str] = [
    "baike.baidu.com",
    "baike.sogou.com",
    "itjuzi.com",
    "cyzone.cn",
    "pedaily.cn",
    "36kr.com",
    "huxiu.com",
    "lieyunwang.com",
    "chuangsanjia.com",
    "qcc.com",
    "tianyancha.com",
]

# Judicial risk / court records (替代 wenshu.court.gov.cn — 同上)
JUDICIAL_DOMAINS: list[str] = [
    "wenshu.court.gov.cn",
    "rmfygg.court.gov.cn",
    "zxgk.court.gov.cn",
    "tianyancha.com",
]


def review_queries(q: CompanyQuery) -> list[str]:
    """Generate the set of review-oriented queries for one company.

    UGC posts (脉脉 / 知乎 / 小红书 / 看准) usually refer to companies by
    abbreviation or English name, not the full legal name. To improve recall,
    we expand queries across the company name + LLM-generated aliases (capped
    at 4 total names to keep Tavily cost bounded).

    Slang queries (LLM-generated colloquial recall terms — "ICU / 内卷 / 摆烂
    / 跑路 / PUA ...") are emitted once each without name prefix; they are
    site-allowlisted so the search engine applies the same UGC filter, and
    we cap their count to keep Tavily cost bounded.
    """
    p = q.position.strip()
    city = q.city.strip()
    names = _all_names(q)

    queries: list[str] = []
    for n in names:
        queries.extend([
            f'"{n}" 加班',
            f'"{n}" 离职率',
            f'"{n}" 脉脉 爆料',
            f'"{n}" 看准 工资',
            f'"{n}" 知乎',
            f'"{n}" 体验',
        ])
    if p:
        for n in names:
            queries.append(f'"{n}" {p} 体验')
            queries.append(f'{p} {n} {"避雷" if not city else f"{city} 避雷"}')

    # Slang recall: each term gets the primary company name as a soft context
    # anchor so we still bias toward this company, but the term itself drives
    # the search (not the quoted company name). Cap at 8 to bound Tavily cost.
    seen: set[str] = set()
    for raw in (q.slang_queries or [])[:8]:
        term = raw.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        # Primary name + slang term keeps Tavily focused on this company while
        # letting the slang drive vocabulary recall.
        queries.append(f'{q.company} {term}')
        # Also a bare slang query — broader recall when a post doesn't even
        # mention the company name (e.g., a rant that uses just "我们部门").
        queries.append(term)

    return queries


def news_queries(q: CompanyQuery) -> list[str]:
    """Generate news/PR-oriented queries for one company. Uses the full legal
    name only — news aggregators (36kr / huxiu / weibo / etc.) typically index
    articles under the company's official name."""
    c = q.company
    year = "2026"
    return [
        f'"{c}" 最新',
        f'"{c}" 裁员 OR 倒闭 OR 收购',
        f'"{c}" 融资 OR 上市',
        f'"{c}" {year}',
    ]


def business_queries(q: CompanyQuery) -> list[str]:
    """Business registration / company info queries (aiqicha / tianyancha / qcc /
    creditchina). Full legal name only — aggregator pages key on official
    registered names, not casual abbreviations."""
    c = q.company
    return [
        f'"{c}" 工商信息',
        f'"{c}" 法人 注册资本',
        f'"{c}" 股东 持股比例',
        f'"{c}" 经营状态 经营异常',
    ]


def judicial_queries(q: CompanyQuery) -> list[str]:
    """Judicial risk / court records queries. Full legal name only — court
    filings identify parties by their registered name, not by casual alias."""
    c = q.company
    return [
        f'"{c}" 裁判文书',
        f'"{c}" 诉讼 OR 起诉',
        f'"{c}" 被执行',
        f'"{c}" 失信被执行人',
    ]


def company_info_queries(q: CompanyQuery) -> list[str]:
    """Company profile queries (主营业务 / 产品 / 行业 / 融资 / 规模 / 官网).

    v0.1.14 — added per-source queries targeting 36kr / 虎嗅 since
    encyclopedias often miss recent financing rounds.
    """
    c = q.company
    return [
        f'"{c}" 公司简介',
        f'"{c}" 主营业务 产品',
        f'"{c}" 融资 投资',
        f'"{c}" 官网',
        f'"{c}" site:36kr.com',
        f'"{c}" site:huxiu.com',
    ]


def _all_names(q: CompanyQuery, max_n: int = 4) -> list[str]:
    """Return [company, *aliases] deduped and capped. Order preserved.

    v0.1.18 — When the LLM alias step fails or returns empty (common for
    lesser-known companies where round-1 produced no slang), fall back to
    cheap local heuristic expansion:
        棒谷科技 → 棒谷科技, 棒谷
        Alibaba Group → Alibaba Group, Alibaba
        字节跳动 → 字节跳动
    UGC posts rarely use the full legal name — they say 棒谷 / Banggood /
    Alibaba — so this single-line suffix strip materially improves recall
    without an extra LLM call.
    """
    seeds: list[str] = [q.company] + list(q.aliases)
    if not any(a.strip() for a in q.aliases):
        # LLM gave no aliases — apply local heuristic so we don't query with
        # the legal name alone (which is what failed in the 棒谷科技 report).
        for v in _local_name_variants(q.company):
            if v not in seeds:
                seeds.append(v)
    out: list[str] = []
    seen: set[str] = set()
    for n in seeds:
        s = n.strip()
        if s and s not in seen and len(s) <= 50:
            seen.add(s)
            out.append(s)
        if len(out) >= max_n:
            break
    return out


# v0.1.18 — Chinese corporate suffixes, ordered longest-first so greedy match
# strips "科技股份有限公司" before falling back to "科技".
_CN_CORPORATE_SUFFIXES: tuple[str, ...] = (
    "科技股份有限公司", "科技集团有限公司", "集团股份有限公司",
    "股份有限公司", "集团有限公司", "控股集团有限公司",
    "科技集团", "科技股份", "集团", "科技", "股份", "有限公司", "公司",
    "有限责任", "控股",
)


def _local_name_variants(company: str) -> list[str]:
    """Cheap local aliases when LLM returned empty. Strips Chinese corporate
    suffixes and splits CamelCase for English/Latin embedded in the name.
    Returns 0-2 additional names (callers union with the original).
    """
    out: list[str] = []
    s = company.strip()
    if not s:
        return out
    # Chinese suffix strip — only one pass, longest match.
    for suf in _CN_CORPORATE_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf) + 1:
            stripped = s[: -len(suf)].strip()
            if stripped and stripped != s:
                out.append(stripped)
            break
    # CamelCase split (e.g. "AlibabaGroup" or "ByteDance").
    # Only emit if there's a Latin chunk that itself has internal case.
    if any("一" <= ch <= "鿿" for ch in s) is False:
        # Pure Latin — try splitting on lowercase→uppercase boundaries.
        import re
        parts = re.split(r"(?<=[a-z])(?=[A-Z])", s)
        if len(parts) > 1:
            for p in parts:
                p = p.strip()
                if p and p not in out and p != s:
                    out.append(p)
                    break  # one CamelCase variant is enough
    return out


def review_pass2_queries(q: CompanyQuery, max_n: int = 3) -> list[str]:
    """v0.1.18 — Broad-recall queries run without the Tavily include_domains
    filter when pass-1 returns too few hits. These are the queries most likely
    to surface UGC (小红书 / 脉脉职言 / 知乎) that Tavily can index but that
    the strict allowlist rejects.

    Capped at `max_n` to keep credits bounded (each pass-2 query costs ~3x a
    pass-1 query because the search is unfiltered).
    """
    names = _all_names(q, max_n=2)
    out: list[str] = []
    for n in names:
        out.extend([
            f'"{n}" 知乎',
            f'"{n}" 小红书',
            f'"{n}" 体验 评价',
        ])
    # Take only the first max_n to bound cost.
    return out[:max_n]

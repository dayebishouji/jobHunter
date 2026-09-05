# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.14 + hatchling + src/ 布局。Jinja2 模板 + 静态 CSS。**单文件 HTML 输出**：所有 CSS inline、所有 JS inline、零外部运行时依赖；favicons 走 Google Fonts CDN（断网自动隐藏）。数据管线：Tavily async + Anthropic Claude（可走 ccswitch 中转）→ pydantic v2 模型 → Jinja 渲染。输出写到 `reports/{公司}-{岗位}-{YYYYMMDD-HHMM}.html`，gitignored。

## Users

**唯一读者**：用户本人（个人求职者），处于以下任一时点：
- 投递简历前的 5-10 分钟预判（值不值得投）
- 拿到 offer 前的反向背调（值不值得签）
- 面试前的准备（要问什么、试用期要警惕什么）

**用户约束 → 产品决策**：
- **私密场景**：可以保留 UGC 原文引号（995 / 甩锅 / PUA / 内卷 / 跑路），不需要脱敏
- **速读场景**：必须 90 秒给出顶层 verdict，5 分钟给出可行动洞察
- **复用场景**：报告是单文件可分享，但默认仅自用；分享场景靠用户主动发文件
- **无障碍**：dark-mode 自适应 + prefers-reduced-motion 已有；无强制 WCAG 要求

## Product Purpose

替代 ¥29 人工反向背调服务，本地 5-10 分钟出尽调备忘。

**输入**：公司名 + 岗位 + 城市（+ 可选 JD 文本 / 同行业对比公司）

**输出**：单文件 HTML 报告，覆盖：
- 工商 / 司法 / 公司画像 / 薪酬 / 加班 / 离职 / 氛围 / 舆情
- 面试流程 / 面试反问 / 试用期观察清单
- 同行业对比 / 顶层判断（recommend / caution / avoid / neutral）
- 网络词解读 / 数据缺口 / 来源附录

**成功 = 用户读完后能**：
1. 90 秒内知道这家值不值得去（顶层 verdict + 5 轴雷达）
2. 5 分钟内掌握面试要问什么（事实驱动反问清单）
3. 1 个月内知道试用期要警惕什么（1mo / 3mo / 6mo 观察清单）

## Positioning

**机制差异**：所有信号从 Tavily + 公开工商/司法 + Claude 结构化抽取得来，**全部 deterministic + 可溯源**。

**与竞品对比**：
- vs ¥29 人工服务：不可复现、依赖个人经验、付费墙
- vs Glassdoor / 看准单源：只覆盖一个数据源
- vs 知乎爬虫：只覆盖知乎

**独有优势**：
- 5 路 Tavily collector + 搜狗微信公众号（UGC 全量补充）
- LLM 抽取失败时的 deterministic 兜底（`_loose_keyword_reviews()` 关键词兜底）
- 行业基线对比（`industry_baselines.py` 12 个行业）
- 求职专用 UX：试用期清单、面试反问、JD 对照、薪酬 band

## Operating Context

- **单次跑耗时**：5-10 分钟（2 轮 Tavily + LLM 抽取 + consolidation + Jinja 渲染）
- **成本**：50-80 Tavily credits / run + 1-2 LLM calls
- **缓存**：24h Tavily file cache + snapshot diff（vs 上次跑同一公司）
- **CLI 入口**：`python -m jobhunter run -c "公司" -p "岗位" --city "城市"` 或 `scripts/run.bat`
- **watchlist**：自动 mark_ran 监控关注的公司

## Capabilities and Constraints

**Capabilities** (代码已实现):
- 5 路 Tavily collector（工商 / 司法 / 画像 / 评价 / 新闻）
- 搜狗微信公众号 collector（UGC 补充）
- 2 轮 Tavily（round 1 + entity-aliased round 2，硬上限 1 轮 / 5 实体）
- LLM structured extraction + `NullTolerantListBase` 自动 unwrap + per-field 校验器
- 5 轴 deterministic 评分（overtime / salary / judicial / business / vibe）
- 顶层 verdict（recommend / caution / avoid / neutral）
- 行业基线对比（12 industries）
- JD 对照（15 类承诺 vs 公开事实）
- 试用期 1mo / 3mo / 6mo 观察清单
- 薪酬 band P25 / P50 / P75
- 历史快照 diff（vs 上次跑同一公司）
- watchlist CLI（add / list / remove）
- 报告章节 HTML5 native DnD 重排 + localStorage 持久化
- 打印 / PDF（`--print` flag + `?print=1` URL）
- 445 pytest pass（v0.2.0 全量重设计后调整 21 个断言匹配新结构，test count 净变化 = 0）

**Constraints**:
- gsxt.gov.cn / wenshu.court.gov.cn 在非 CN IP 软失败（UI 提示手动核查）
- Tavily 免费档 1000 credits / 月
- ccswitch 中转偶有 list-as-dict schema 偏差（已自动 unwrap）
- 单文件 HTML 输出，favicons 在线加载（断网自动隐藏）
- 报告编辑模式：**默认开启用户主动重构**（v0.1.24+）

**Open decisions**: 无 — 所有产品级决策已确认。

## Brand Commitments

**Name**: jobHunter
**Voice**: 编辑型备忘录风 — 编辑部记者对求职者的内部备忘录，理性但不冷漠。允许引用 UGC 原文，分析层保持克制。

**Voice 例证**：
- ✓ "这公司 996 是真的" / "HR 说话不算话"（保留原文）
- ✓ "公开记录中未发现诉讼或被执行 — 同行里相对少见的干净背景"（正面叙事）
- ✗ "可能存在一些员工反馈"（过度脱敏，失去信号价值）

**Brand assets**: 0（无 logo、无营销站点、无色彩资产）
**Typography**: 用户未指定字体偏好；当前实现用 Cormorant Garamond + IBM Plex Sans/Mono（rebrand 时可换）

## Evidence on Hand

**Available data fields** (代码已实现，模板可访问):

| 字段 | 来源 | 当前利用率 |
|---|---|---|
| `data.query.company/position/city` | 用户输入 | 100%（hero / masthead / 各章 deks） |
| `data.company_profile.{industries, investors, funding_stage, employee_count, insured_count, founded_at, headquarters, business_scope, motto}` | Tavily 画像域 + LLM 抽取 | ~40%（stat strip + 行业标签） |
| `data.business_facts.{registered_capital, legal_rep, established_at, status, stakeholders}` | Tavily 工商域 + LLM 抽取 | ~70%（工商章表格） |
| `data.review_facts.salary_signals/overtime_signals/vibe_signals/turnover_signals/interview_signals` | Tavily reviews + LLM 抽取 + `_loose_keyword_reviews` 兜底 | ~85%（4 个信号章 + tier badge + age badge） |
| `data.review_facts.slang_glossary[{term, meaning, count, url}]` | LLM 抽取 | ~50%（reviews 章末尾） |
| `data.review_facts.{interview_rounds, interview_style, interview_difficulty, typical_off_time}` | LLM 抽取 | ~60%（面试流程章 + 加班章 takeaway） |
| `data.news_facts.items[{title, url, published_at, sentiment, summary}]` | Tavily news + LLM 抽取 | ~75%（舆情章时间线 + 情感摘要） |
| `data.judicial_facts.{sample_cases, case_count_total, enforcement_records, has_court_records}` | Tavily judicial + LLM 抽取 | ~80%（司法章表格） |
| `data.findings.{business, reviews, news, judicial}.source_urls` | 各 collector 原始 URL | ~0%（仅在 sources 附录，去重后） |
| `data.chapter_confidence` | `_compute_confidence` | ~90%（per-chapter conf badge） |
| `data.overall_confidence` | 同上 | 100%（hero meta pill） |
| `avg_score` | 5 轴均值 | 100%（hero meta） |
| `radar_svg` | `report/charts.py` 预渲染 SVG | 100%（hero side） |
| `v.{level, headline, reasons}` | `compute_overall_verdict` | 100%（hero verdict badge） |
| `snapshot_diff.{days_ago, verdict_changed, salary_change, ...}` | `report/snapshot.py` | 80%（hero snapshot diff） |
| `sources` | `_collect_sources` URL 去重 | 30%（附录 + hero diversity KPI） |
| `edit_notes` / `data_stories` | `compute_chapter_stories` 行业对比 | 90%（story-block per 章） |
| `collector_notes` | `extract_collector_notes` | 100%（reviews 章顶部 banner） |
| `data.jd_alignment.{远程, 双休, 出差, ... 15 类}` | `report/jd_alignment.py` | 100%（JD 对照章） |
| `data.peer_summary[]` | `--compare` flag 触发 | 100%（同行业对比章） |
| `data.industry_baseline` | `industry_baselines.pick_industry()` | 100%（data-stories lines） |

**Under-leveraged** (已知信号密度低于其价值):
- `funding_stage` / `investors` / `employee_count` / `insured_count` — 仅 stat strip，未做时间线/对比
- `typical_off_time` — 仅加班章 1 行，应做更突出的视觉
- `slang_glossary` — 章末列表，应做品牌 chip 墙或交互式浮层
- `source_urls` 各域 — 未按域分组做"本报告数据来源图谱"
- `industry_baseline` — 未做完整"行业坐标"页面

## Product Principles

1. **密度优先**：用户一次读完做决策，证据堆得多比堆得少好；每条证据带原文 + 来源 + 时间 + 平台 + 多源交叉状态
2. **原文 > 净化**：UGC 引语是信号，去掉引语就是去掉价值
3. **deterministic > LLM**：每章必须能从数据 deterministic 派生；LLM 只在确定性层之上加洞察
4. **单文件可移植**：报告必须能在任意浏览器离线打开，AirDrop / 微信文件传输分享
5. **零运行时外部依赖**：零 CDN 阻塞、零 JS bundle、零 tracking；只有 CSS + 内联 JS

## Accessibility & Inclusion

用户唯一，无强制 a11y 要求。已有：dark-mode 自适应、prefers-reduced-motion guard。
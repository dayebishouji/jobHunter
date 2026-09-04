# jobHunter — 反向背调 CLI

个人向「反向背调」工具，把图里那种 ¥29 人工服务自动化：输入公司名 + 岗位 + 城市，5–10 分钟产出一份覆盖工商 / 司法 / 薪酬 / 加班 / 氛围 / 舆情 / 公司画像 / 面试反问 / 网络词解读的 HTML 报告。

**形态**：本地 Python CLI（InquirerPy 交互 + Click 非交互），Anthropic Claude 做结构化抽取与综合，Tavily 做评价 / 新闻类搜索，输出可折叠、带源链接、移动端友好、深色模式自适应的单文件 HTML。

数据来源：Tavily（看准 / 脉脉 / 知乎 / 小红书 / 牛客 / 36 氪 / 虎嗅 / 微博等） + Anthropic Claude（结构化抽取与综合）。
gsxt / wenshu 在 v0.1 因网络与反爬限制软失败，README 提示手动核查。

## 安装

```bash
# Python ≥ 3.10，建议 3.14
python -m venv .venv
.venv/Scripts/activate            # Windows
source .venv/bin/activate         # macOS / Linux
pip install -e .
```

## 配置

复制 `.env.example` 为 `.env` 并填入 key：

```
ANTHROPIC_API_KEY=sk-ant-...       # 必填
ANTHROPIC_BASE_URL=                # 可选：走 ccswitch / one-api 中转时填
TAVILY_API_KEY=tvly-...           # 必填
```

`ANTHROPIC_BASE_URL` 支持 ccswitch / one-api 等 Anthropic 协议兼容的中转。

## 使用

```bash
# 交互式
python -m jobhunter

# 非交互式（脚本友好）
python -m jobhunter run -c "阿里云" -p "后端工程师" --city "杭州"
python -m jobhunter run -c "字节跳动" --no-news          # 跳过新闻域（更快）
python -m jobhunter run -c "X" --no-judicial --no-open   # 不查司法、不自动开浏览器
python -m jobhunter --version
```

报告写到 `reports/{公司}-{岗位}-{YYYYMMDD-HHMM}.html`，单文件可直接分享（favicons 是 Google 服务在线加载，断网会自动隐藏）。

## 架构

```
src/jobhunter/
├── cli.py                # Click + InquirerPy
├── config.py             # pydantic-settings，从 .env 读
├── pipeline.py           # run() 编排
├── models/               # Pydantic 数据模型
│   ├── query.py          # CompanyQuery
│   ├── raw.py            # RawItem, CollectorResult
│   ├── facts.py          # BusinessFacts / ReviewFacts / NewsFacts / JudicialFacts / CompanyProfile / SlangEntry
│   ├── scoring.py        # RiskAxis + AxisScore
│   └── report.py         # ReportData
├── collectors/           # gsxt / wenshu (软失败) + 5 路 Tavily(工商/司法/画像/评价/新闻)
├── search/               # TavilyClient (缓存 + 限速) + 查询模板
├── processing/           # normalize / extract / crosscheck
├── llm/                  # Anthropic SDK 封装 + 中文 prompt + tool_use schema
├── report/               # 5 轴打分 + Jinja2 模板 + 图表 SVG 生成
└── utils/                # slug / http / retry / browser
```

5 轴启发式打分（确定性，不走 LLM）：

| 轴 | 数据来源 |
|---|---|
| 加班强度 | `overtime_signals` 中 996 / 大小周计数 |
| 薪酬诚信 | 5 起步，每个冲突 / JD-实际落差扣 1 |
| 司法风险 | 5 起步，按诉讼 + 被执行扣分；缺数据 → 3 |
| 工商风险 | 5 起步；非存续或极新公司扣分；缺数据 → 3 |
| 文化氛围 | vibe_signals 情感倾向 |

## 测试

```bash
pytest                        # 393 tests
pytest tests/test_charts.py   # 图表单元测试
pytest tests/test_pipeline_smoke.py  # 端到端 mock 烟囱测试
```

## 已知限制（v0.1.21）

- **gsxt.gov.cn / wenshu.court.gov.cn** 在非中国大陆 IP 下不可达，会软失败并在报告里提示手动核查链接
- **Tavily 免费档** 1000 credits / 月；v0.1.8 默认跑两轮（round 1 + entity-aliased round 2），单次约 50–80 credits
- **ccswitch / one-api 中转** LLM 输出偶有 schema 偏差，已通过 `NullTolerantListBase` + per-field 校验器兜底；list_company_entities 偶返回纯文本（不走 tool_use），已 fallback 到 chat()+JSON regex
- **inferences 段** 在 consolidation 输出 token 紧张时可能为空，不影响主功能
- **公司画像域** 依赖 Tavily 在百度百科 / IT 桔子 / 创业邦的命中；小众公司可能拿不到完整字段，仅展示已抓到的部分
- **v0.1.6 网络词召回**：依赖 LLM 生成 5–8 个 slang 查询词（内卷 / ICU / 摆烂 / 跑路 …）提升 UGC 召回；抽取后报告 chapter V 末尾会附「网络词解读」列表；如 LLM 失败则跳过
- **v0.1.8 递归 sub-query**：round 1 后用 LLM 抽 3-5 个公司内部实体（产品/品牌/部门/创始人）作为 round 2 查询别名；硬上限 1 轮 / 5 个实体
- **v0.1.8 数据多样性 KPI**：每条 signal 旁的 tier-badge（待核实/单一来源/多源印证/跨域印证）+ hero meta 的「数据多样性」pill 反映 cross-source corroboration
- **v0.1.9+ 召回域扩展**：REVIEW_DOMAINS 经 v0.1.9 / v0.1.10 / v0.1.11 三轮扩到 46 个域名 / 11 个垂直行业；通过 `domains_for_position(position)` 按岗位关键词过滤 Tavily allowlist 实现成本控制
- **v0.1.12 报告「去 AI 味」**：CSS 加 motion 系统（reveal-on-scroll / paper-grain texture / tier-badge hover lift / bullet hover highlight / `.pullquote` 编辑型强调 / focus-visible 描边 / KPI 数字滚动完成时 scale 弹一下）；template `</body>` 前加 inline JS（IntersectionObserver + easeOutCubic counter ticker + prefers-reduced-motion guard）。零外部依赖、单文件可移植性保持
- **v0.1.13 报告「编辑手记 + 数据故事 + 拖拽章节」**：每个章节旁加 `.story-block`（编辑手记 aside + 行业对比数据故事），如「过去 12 个月里，这家公司被起诉了 X 次 — 比同行平均高 Y%」；行业基线在 `src/jobhunter/report/industry_baselines.py`（12 个行业 + default fallback）；7 个主章节可拖拽重排（HTML5 native DnD + localStorage 持久化 + 「重置章节顺序」按钮）；仍是零外部依赖
- **v0.1.14 报告密度提升**：reviews 域信号太稀 → 两轮 LLM 抽取（首轮薄时再补一轮聚焦 missing types）+ 纯本地关键词兜底（996 / 内卷 / PUA / 月薪 → 最小信号）；司法章「零诉讼」改为「公开记录中未发现诉讼或被执行 — 同行里相对少见的干净背景」正面叙事；公司画像域新增 huxiu.com / lieyunwang.com / chuangsanjia.com + `site:36kr.com` / `site:huxiu.com` 双锚点 query；面试反问改事实驱动：自动从司法样本 / 薪酬跨度 / 加班密度 / 经营异常 / 融资阶段 派生针对性问题，前置插入清单
- **v0.1.15 报告「面试流程 + 试用期清单 + 同行业对比」三件套**：(1) ReviewFacts 加 `interview_rounds` / `interview_style` / `interview_difficulty` / `interview_signals`，LLM prompt 要求抽取（轮数 / 题型标签 / 难度），模板新章「面试流程」展示；(2) `compute_trial_checklist()` 派生 1mo / 3mo / 6mo 试用期观察清单（HR 反向背调框架 + 数据驱动 5 条），事实驱动：high_overtime → 1 月观察；anomaly_listed → 3 月复核；case_count > 0 → 6 月确认；融资阶段非上市 → 6 月问 runway；(3) `--compare "美团,京东"` CLI flag 触发跨公司对比，每多 1 家 ≈ 1 次轻量级 pipeline（仅 extract + scoring，跳过 alias/slang/consolidation/interview Qs，Tavily 24h cache 让重复免费），渲染同行业对比表（综合分 / 5 轴 / 典型月薪 / 司法数 / 舆情）
- **v0.1.16 报告「信号新鲜度 + JD 对照 + 顶层判断」三件套**：(1) 每条 review signal 加 `published_at`（LLM 抽不到 → null；`_loose_keyword_reviews` 用今日），模板渲染「X 月前」badge，超过 1 年的信号自动淡化（line-through + 0.5 opacity）；(2) `--jd TEXT` / `--jd-file PATH` CLI 触发，`compute_jd_alignment()` 纯本地判定 6 类常见承诺（弹性 / 15 薪 / 五险一金 / 扁平 / 期权 / 福利）vs 公开事实 — confirmed (绿) / contradicted (红) / unverified (灰)，零 LLM 调用；`(3) `compute_overall_verdict()` 派生顶层 verdict（recommend / caution / avoid / neutral）渲染在 hero side（绿/黄/红/灰 badge + headline + top 3 reasons）。判定规则（deterministic）：avoid = 2+ 轴 ≤2 OR 司法 >10 + 异常；caution = 任一轴 ≤3 OR 司法 >3 OR 重度加班 ≥2 OR 异常；recommend = 全轴 ≥4 AND 司法 0 AND 无重度加班 AND 正面 ≥ 负面
- **v0.1.17 报告「薪酬 band + JD 细粒度 + 历史快照 + watchlist + 打印/PDF」五件套**：(1) `compute_salary_band()` 派生 P25 / P50 / P75（线性插值），模板 `.salary-band` 渲染横条 + 中位标；(2) `jd_alignment` 新增 7 条细粒度（远程 / 双休 / 出差 / 团建 / 培训 / 晋升 / 弹性时间），总 15 类承诺可核对；(3) `report/snapshot.py` 把每次 run 的关键指标（verdict / 司法数 / 薪酬 P50 / 异常 / 氛围）写入 platformdirs cache，下次同公司 run 自动渲染「vs 上次 (X 天前)」差异行，verdict 升降用 ↑ / ↓ 标注；(4) `watchlist` 子命令（`add` / `list` / `remove`）持久化到 cache 目录 JSON；CLI 主流程跑完后自动 mark_ran；(5) `--print` CLI flag 触发 `?print=1` URL，inline JS 调 `window.print()` 让用户在浏览器原生对话框「Save as PDF」；CSS `@media print` 关闭动画 / 隐藏拖拽把手 / 强制单色背景
- **v0.1.18 reviews 域召回修复**（棒谷科技报告薪酬/加班/氛围三章全空，user 在小红书能搜到但 pipeline 搜不到 — 根因：Tavily 对小红书/知乎内文覆盖差被 allowlist 拒掉 + LLM 别名失败时只用全名搜）：(A) reviews 采集器跑 **2 轮**：pass-1 6 query 带 allowlist（cost-bounded），仅当 pass-1 < 3 命中时触发 pass-2，3 个高召回 query（`知乎` / `小红书` / `体验 评价`）**不带** allowlist（成本 ~3x/单 query）；`_dedup_by_url()` 按 URL 去重；(B) `_all_names()` 在 `q.aliases` 为空时启用本地启发式（中文 corporate 后缀 strip：棒谷科技 → 棒谷；CamelCase split：AlibabaGroup → Alibaba），LLM 别名失败时仍能多 query 1-2 个真实称呼。零 LLM 调用增量
- **v0.1.19 reviews 全量 name-only 召回 + LLM 抽取**：抛弃 v0.1.18 的 keyword-based query（`"X" 加班` / `"X" 离职率` / `"X" 知乎` …），改成 **per-domain name-only**：每个域一条 query，文本只是 `"X"`，不挂任何关键词，让 Tavily 返回该域里所有提到公司的内容，由 LLM 抽取步做语义分类（找 salary / overtime / vibe / turnover 信号，不依赖关键词命中）。`review_queries()` 现在返回 `list[(text, allowlist)]`，`MAX_DOMAINS_PER_RUN=15`，每公司 ≤30 query（15 域 × 2名字，含 v0.1.18 别名兜底）。slang 召回删除（LLM 抽取已经能识别 "内卷 / ICU / 摆烂"）。成本与 v0.1.18 相当，但**每 query 更聚焦**（单域 allowlist），LLM 抽取的 signal-to-noise 更好
- **v0.1.20 搜狗微信 reviews 补充源**：直抓 `weixin.sogou.com` 把微信公众号全文索引接进 reviews 域（`domain="reviews"` 复用现有 bucket，下游 LLM 抽取零改动）。每 run 最多 3 query（主名 + 别名，来自 `_all_names`）、24h cache、间隔随机 2-5s throttle。被反爬拦截时软失败，`error="anti_bot_redirect"`，报告 reviews 章顶部加灰字小条提示用户手动到 [weixin.sogou.com](https://weixin.sogou.com) 核查。`.env` 设 `SOGOU_WEIXIN_ENABLED=false` 可关闭（IP 被 ban 时）。⚠️ Sogou ToS 禁止未授权爬虫，跑高频会被封 IP，已用随机 throttle + 24h cache 把风险压到最低
- **v0.1.21 报告加「公司人数 / 参保人数 / 典型下班时间」三件套**：(1) `CompanyProfile` 新增 `employee_count: int | None`（精确员工数，来自天眼查/招聘/官网，模糊字符串 "约 1200 人" 自动 coerce 成 1200）+ `insured_count: int | None`（社保参保人数——判断公司真实规模的最强信号，常缺失 → null 兜底）；(2) `ReviewFacts` 新增 `typical_off_time: str | None`（UGC 反复出现的「团队典型下班时间」，如 "约 10:00 PM" / "弹性 9-6"），配 `typical_off_time_evidence` 一句原文引用 + `typical_off_time_url` 最相关来源；(3) `EXTRACT_COMPANY_PROFILE_SUFFIX` 新 prompt（之前 `processing/extract.py` 里 `"company_info": ""` 是空的，导致 LLM 抽取公司画像时无具体指令经常拿到空 + 之前你看到的 `record_company_profile` warning），现在明确要求抽 A-O 共 15 个字段；(4) 报告公司画像章 stat strip 加「员工数」+「参保人数」两列；加班章加「典型下班时间」突出卡片（border-left + 原文引用 + 来源链接）。测试 +30 (`tests/test_v0121_features.py`)，363 → 393 pass
- 不支持：批量多公司（watch 已有 CRUD，批跑未做）、Web 服务、Playwright

## 下次接手可考虑的深度改动

- **行业路由**（不是岗位路由） — LLM 先判公司行业再选数据源；当前 `domains_for_position()` 是位置路由的妥协，**做全行业路由需要一次额外 LLM 调用**
- **3 级证据等级**（用户主张 / 多源重复出现 / 有公开证据证实） — 当前 `support_tier`（unverified / single-source / corroborated / multi-domain）已经在做类似分级，命名差异可对齐，详见 `src/jobhunter/report/builder.py:compute_signal_supports`

## 免责

仅供个人求职参考，不对外展示，不存储身份信息。请独立判断并自行核实关键事实，并遵守相关网站服务条款。
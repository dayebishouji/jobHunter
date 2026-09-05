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
python -m jobhunter batch -f companies.txt               # v0.3.2 批量横向对比（CSV 输入 + 行尾 [JD:...] 覆盖）
python -m jobhunter batch --from-watchlist               # v0.3.2 从 watchlist 批量
python -m jobhunter --version
```

报告写到 `reports/{公司}-{岗位}-{YYYYMMDD-HHMM}.html`，单文件可直接分享（favicons 是 Google 服务在线加载，断网会自动隐藏）。
`batch` 模式额外生成 `reports/batch/{file_stem}-{YYYYMMDD-HHMM}/index.html` 聚合页（含排序对比表 + verdict badge + 失败列表）。

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
pytest                        # 522 tests
pytest tests/test_charts.py   # 图表单元测试
pytest tests/test_pipeline_smoke.py  # 端到端 mock 烟囱测试
```

## 已知限制（v0.3.5）

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
- **v0.1.22 修 3 个 reviews / sogou 静默 bug**：(1) **template 横幅 bug** — v0.1.20 加的搜狗反爬提示横幅只匹配 `error="anti_bot_redirect"` 一种字符串，当搜狗返回 `no_results`（fetch 成功但解析 0 条，往往是搜狗静默软封）时报告里完全看不到提示；现在 banner 同时匹配两种错误码，且文案区分两种情况；(2) **搜狗反爬检测漏报** — 搜狗近期反爬挑战页去掉了中文警告文案，只剩 `anti.min.css` + `antispider.min.js` 资源 bundle，原来 4 个关键词（`antispider`/`verify`/`请输入验证码`/`您的访问过于频繁`）漏判，新加 3 个资源名 fallback (`static/css/anti`/`antispider.min.js`/`anti.min.css`)，让挑战页 100% 被识别为 `anti_bot_redirect`；(3) **reviews 域消费品品牌检索污染** — Tavily 对消费品品牌（如美的）name-only 查询会返回大量产品评测 / 营销页 / 登录页，LLM 抽取正确剔除但 reviews 章空；现在 `normalize.py` 加 `REVIEW_URL_PATTERNS` host→URL 子串白名单（覆盖 1point3acres/bbs、知乎/question、牛客/discuss、看准/firm、脉脉/article 等），非职场内容在送进 LLM 之前就被过滤掉；其他域（news/business/judicial）不受影响（filter 只对 reviews bucket 生效）。测试 +34 (`tests/test_v0122_features.py`)，393 → 427 pass
- **v0.1.22 hotfix 修 reviews 核心域被静默截断**：`domains_for_position()` 在后端等岗位下 union 出 23 个 domain，但 `MAX_DOMAINS_PER_RUN=15` 把后 8 个（小红书 / 知乎 / 微博 / 看准 / 牛客 / 1point3acres / v2ex / zhipin — 用户最常搜的 UGC 平台）整段砍掉，等于 reviews 章只搜了程序员垂类。`review_queries()` 现在把 `GENERAL_REVIEW_DOMAINS`（20 个 A 级全行业）从 cap 里 carve 出来永远查，truncation 只作用于 vertical extras，单公司 query 30 → 40。测试 +16 (调整 5 个 v0.1.18 contract 断言)，427 → 443 pass
- **v0.1.23 修 reviews 章 LLM 抽取失败时兜底被跳过**：v0.1.14 加的 `_loose_keyword_reviews()` 兜底原本被 `isinstance(rf, ReviewFacts)` 卡住 — LLM 抽取返回 `None` 时 `rf=None` → isinstance=False → 兜底永不执行，reviews 章空即使 raw bucket 有 100+ 职场 URL。美的 / 美团 / 字节跳动三次实测都中招（cache 显示 157 个 牛客/脉脉/知乎/看准 URL 进 reviews bucket，但报告全空）。现在去掉 isinstance 闸门：reviews_items 非空就一定跑兜底，LLM 失败时直接用 loose 作为整个 facet，LLM 有结果时 merge。测试 +3，443 → 446 pass
- **v0.2.0 视觉 + 内容双重重写（broker research + 招股书 hybrid）**：报告结构 redesign — masthead → cover 摘要（top thesis 句 + KPI 带 + 5 轴雷达 + snapshot diff + 来源 chip wall + collector soft-fail 横幅）+ 7 个编号章节（I-VII：公司画像 / 工商 / 司法 / 薪酬 / 加班 / 氛围 / 舆情）+ 4 个侧栏章节（面试准备 / 同行业对比 / JD 对照 / tail 推断 / 缺口 / Σ 来源）+ 风险提示 + Σ 来源附录 + footer。视觉 token：paper-cream `#fbfaf6` + broker-blue `#1a3a6e` + Noto Serif SC（display）/ Sans SC（UI）/ Mono（数据）。`DESIGN.md` 是 token 单一来源，`report.html.j2` 顶部 5 段方向契约是设计回归门。`compute_chapter_stories` / `compute_axes` / `compute_overall_verdict` / `compute_trial_checklist` / `compute_salary_band` / `diff_snapshots` 全部 deterministic + 纯本地，零 LLM 调用。`--version` 输出 `0.2.0`。测试调整 21 个断言匹配新结构（test_report_builder + test_v0120/121/122/013/014/015/016/017），446 → 445 pass
- **v0.2.1 落实 `docs/audits/2026-09-05-pipeline-flow-audit.md` 顶 3 推荐**：(1) **consolidate LLM 调用加 tenacity 重试** — 之前 `llm_retry()` 只捕 `httpx.TransportError` / `ConnectionError` / `TimeoutError`，5xx / 429 / 529 一闪即触发 consolidate fallback 丢跨域 inferences 块；现在 `anthropic.APIError`（覆盖所有子类 `APIConnectionError` / `APIStatusError` / `RateLimitError` / `APITimeoutError`）也进 retry tuple。`consolidate()` 进一步 opt-in `retry_policy="strict"`（≥3 尝试，max 20s backoff，`llm_retry_strict` 新函数）；`LLMClient.structured_call()` 新增 `retry_policy: str = "default"` 参数。(2) **流程图视觉强化 fallback 路径** — `pipeline.mmd` consolidate 失败的 G3→G4 边改 `==>`（粗箭头）+ `:::fail` classDef 红色填充 + edge label "AggregatedFindings = raw facets (best-effort · 整个 run 不挂)"。(3) **流程图节点折叠** — 3 个 `_build_peer_summary` 节点合 1 + "× N peers" 注脚；11 个 compute 盒按角色合 4 独立 + 1 合并盒（H_MISC 含 7 个：conflicts / confidence / collector_notes / snapshot_diff / edit_notes / signal_supports / trial_checklist）；最终渲染 7936×1848, 4.29:1 宽屏。(4) `docs/audits/2026-09-05-pipeline-flow-audit.md` 新文件 — 6 节覆盖 diagram-level (5 项) / pipeline-level (6 项) / product-level (2 项) + 推荐优先级。测试 +14 (`tests/test_v0201_retry.py` 全过)，445 → 459 pass
- **v0.2.2 落实 `docs/audits/2026-09-05-pipeline-flow-audit.md` 第 4 节「下个月做」中的 2 条基础改动**：(1) **Round 2 触发条件改 type-diversity**（§2.2）—— `_needs_second_pass` 重命名为 `_round2_worthwhile`，阈值收紧到「4 个核心信号类型（salary / overtime / vibe / turnover）中 ≤ 1 个有内容才触发」，去掉冗余 `total_signals < 3` OR 子句；新增 `Round2TriggerReason` enum（`SIGNAL_TYPES_LOW` / `NO_FIRST_PASS` / `NOT_TRIGGERED`）+ 结构化 INFO 日志；辅助类型（jd_gap / slang）不计入多样性。语义修复：旧 `None → False`，新 `None → True`（NO_FIRST_PASS）—— LLM 一次失败应该再试。`extract.py:phase 2` caller 也修：`_second_pass_reviews` 接受 `first: ReviewFacts`，None 场景传空 `ReviewFacts()` 即可。(2) **LLM response disk cache**（§2.3）—— 新文件 `src/jobhunter/llm/cache.py` 的 `LLMResponseCache` 类，mirror Tavily `FileCache` 模式：SHA1[:32] key、TTL in JSON、atomic `.tmp + os.replace`、lazy eviction；cache key = SHA1(`system + '|' + user + '|' + tool_name`)；wired 进 `LLMClient.__init__` + `structured_call()` 作为 short-circuit：hit 跳过整个 API call（不计 tokens / 不走 retry）；poison 保护：空 dict 响应（LLM 失败 / budget 耗尽 / 空 tool_use）**绝不**缓存，避免 24h 锁死。`Settings.llm_cache_enabled: bool = True`（默认开，`JOBHUNTER_LLM_CACHE_ENABLED=false` 关停）。cache 目录 `<user_cache_dir>/llm_cache/`，与 Tavily cache 同级但独立子目录。`retry_policy="strict"`（consolidate）也参与 cache —— 重复 run 同公司 24h 内命中 0 成本。测试 +30（`tests/test_v0202_round2.py` 11 个 + `tests/test_v014_features.py` 3 个改名 + `tests/test_v0203_llm_cache.py` 16 个：cache 直接 API 7 + TTL 2 + admin 2 + structured_call 集成 5 含 poison guard / strict-policy / disabled 路径），459 → 489 pass。3.1 Batch 模式（`--batch FILE`，txt 一行一个公司 + # 注释）按用户决策推迟到 v0.3.1
- **v0.3.1 落实 audit §3.1 批量模式（`--batch FILE`）**：(1) **新模块 `src/jobhunter/batch.py`** — `parse_batch_file()` 用标准库 `csv` 解析 `公司,岗位,城市`（自动处理引号内的逗号），跳过 `#` 注释 / 空行 / 畸形行；`run_batch()` asyncio.Semaphore(3) + best-effort，单公司失败不中断 batch；`_salary_median()` 简化 P50 用于聚合表；`build_batch_report_html()` Jinja2 渲染聚合页。(2) **新模板 `src/jobhunter/report/templates/batch.html.j2`** — masthead + KPI strip + 按综合分 desc 排序的对比表（公司/岗位/城市/综合分/verdict badge/5 轴 strip/司法数/异常/薪酬 P50/状态/详情链接）+ 失败区（公司名 + error message）+ footer；视觉同 v0.2.0 broker research world（paper-cream + broker-blue + Noto Serif SC），复用 `report.css` + +208 行 batch-page 专属 CSS；零外部依赖、单文件可移植。(3) **CLI 集成 `cli.py:batch_cmd`** — 12 个选项 `--file/-f` `--city/-y` `--no-judicial` `--no-news` `--jd` `--jd-file` `--output/-o` `--batch-out/-O` `--batch-concurrency`（默认 3）`--strict`（默认 best-effort，CI 友好 fail-fast）`--no-open` `--print`；`main.add_command(batch_cmd, name="batch")`。(4) **`utils/slug.py`** 加 `batch_dir_slug(file_path, ts)`：聚合页目录 `{file_stem}-{ts}`。(5) **复用 v0.2.2 LLMResponseCache + Tavily FileCache**：同次 batch 重复公司 24h 内命中 0 成本；v0.2.2 poison guard 保证 batch 不被空 cache 锁死。用法：`python -m jobhunter batch -f companies.txt --city 上海`；测试 +15（`tests/test_v0301_batch.py`：7 解析 + 3 runner + 3 聚合页 + 2 CLI 集成），489 → 504 pass
- **v0.3.2 batch 增强 3 件套**（用户决策：只做这 3 项，排序走 CSS-only 零 JS）：(1) **per-line `[JD:...]` 覆盖默认 `--jd`** — `parse_batch_file()` 重构为先 regex 扫行尾再 `csv.reader`（避免内嵌逗号被切字段），regex `\[JD:(?P<body>(?:\\.|[^\[\]])*)\](?:\s*)$` 支持 `\[` / `\]` 转义；行内 `[JD:...]` 优先，`--jd TEXT` 作为未指定公司的 fallback。例：`字节跳动,后端,北京 [JD:要求Go,15薪,弹性]`。(2) **CSS-only 聚合页排序（4 维度）** — Python render 时 `rank_rows(rows, by=...)` 预计算 4 份排序（score desc / cases asc / salary desc / verdict severity desc），模板 4 个 hidden `<input type="radio" name="batch-sort">` + 4 个 `<tbody class="tbody-sort tbody-sort-X">`；CSS `#sort-X:checked ~ .tbody-sort-X { display: table; }` + sibling selector 切换；排序 chip 用 `<label for="sort-X">` 绑定；零 `<script>` 标签、零 JS 事件、单文件可移植。verdict severity：`avoid=4 > caution=3 > neutral=2 > recommend=1`，最严重的排顶部。(3) **`--from-watchlist` flag** — `cli.py:batch_cmd` 加 `--from-watchlist` store_true flag，与 `--file` 互斥（同时传 → exit 2，缺一 → exit 2），watchlist 空 → 友好提示 `jobhunter watch add -c X` 加入并 exit 2；`watchlist.entries_to_queries(entries, city_override=city)` 解耦 batch ↔ watchlist，`city_override` 让 `--city` 覆盖所有 entry 的 city。用法：`python -m jobhunter batch --from-watchlist --city 上海`；测试 +18（`tests/test_v0302_batch_enhance.py`：5 per-line JD + 4 rank_rows + 4 HTML 排序结构 + 3 watchlist helper + 2 CLI 互斥），504 → 522 pass
- **v0.3.3 报告「视觉精度 + 内容密度」双升**（用户反馈「现在内容有点空了」）：(1) **视觉精度 A1-A8** — `templates/report.html.j2` + `static/report.css` +~280 行：A1 cover-thesis（居中 serif italic 单行 verdict + 1px 上下 rule）；A2 KPI 5 列响应式（≥1200px 5 列 / 720-1199px 3 列 / <720px 1 列，含「数据多样性」+「已抓取维度」）；A3 masthead-detail 11px sans 6 items meta chip 带（公司/岗位/城市/日期/维度/置信度）；A4 cover-dispatch 升级（serif italic「主编按」+ prose + 3 ordered reasons）；A5 signal-evidence-attribution 15px serif + 36px `"` ::before + 11px ink-faint 来源行；A6 主章 I-VII 之间 6 个 dotted `· · ·` divider；A7 slang 280px grid → 5 列 chip wall（1 字 brand mark + 11px term + 10px count tooltip）；A8 侧栏 1px brand left border + 左上 chip tag；(2) **内容密度 B1-B7 17 字段** — 公司画像 8 字段（official_website / main_business strip / products grid / company_size 合并 / founded_year→age / total_funding / prospects prose / description fallback）+ 公司画像时间线 SVG（founded_year + funding_stage + 前 2 investors）+ 工商 4 字段（paid_in_capital / address / external_investments_count / anomaly_flag red-bg block）+ 司法 2 字段（case_count_recent_year `.case-recent-row` / enforcement_records 引用进 takeaway）+ 薪酬 jd_gap_signals（`.jd-gap-list` 5 pair JD 承诺↔实际）+ 综合推断 `findings.inferences → infer-card`（LLM 推断集终于登场：claim + grounding_evidence HttpUrl 列表 + 「推断」chip mid 色）+ cover-dispatch 首段 `company_query_summary`；(3) **bug fix** `templates/report.html.j2:543` `bf.stakeholders` → `bf.top_shareholders`（之前因检查不存在字段，股东结构 donut 永远不渲染；本次修后回归测试已加）；(4) **compute_* 纯 deterministic** — `builder.py:compute_company_age(founded_year, generated_at)` ~5 行 / `compute_company_timeline(cp)` ~30 行（emit 成立 + 融资阶段 + 前 2 investors + 至今，clamp 5 events），`charts.py:company_timeline_svg()` ~80 行（follow case_timeline_svg 模式，水平 axis + dots + native `<title>` tooltip）；(5) 设计守则保留 v0.2.0 impeccable 边界（craft-floor.md：≤1px border-left on cards / 避免 emoji / mono 仅数据 / 无 gradient / 不引入 card stack / icon lib / CTA 按钮）。零外部依赖、零 LLM 调用增量、单文件 HTML 输出约束保持。测试 +37（`tests/test_v033_company_timeline.py` 8 + `tests/test_v033_content_density.py` 20 + `tests/test_v033_visual.py` 9），522 → 570 pass。`--version` 输出 `0.3.3`
- **v0.3.4 修复 reviews 章兜底失效 bug**（用户现场反馈「又没数据」）：根因 = `_loose_keyword_reviews()` 是「enrich 不是 rescue」—— 当 Tavily 在 30 个 per-domain query 全部返回 0 hits（corner case：长尾 UGC 公司被 per-domain allowlist 漏掉），`by_domain["reviews"]` 全空 → `extract.py:phase 3` 的 `if reviews_items:` 闸门卡死 loose 兜底 → IV 薪酬 / V 加班离职 / VI 氛围三章全 `本次未能取得`。修法 = 在 `tavily_reviews.collect()` 末尾新增 `_blind_fallback()` 方法，当 main 40 query 全 0 时追加 3 条**无 allowlist** Tavily 查询（`"X" 评价` / `"X" 体验` / `"X" 面试`）；命中项流入同一 `by_domain["reviews"]` bucket → Phase 3 `_loose_keyword_reviews` 自然扫到关键词（996 / 月薪 / PUA / 氛围）。Cost: 仅 main 全 0 时触发，至多 +3 Tavily credits / run；正常命中 0 成本。注意：v0.1.18 删掉的 keyword-based pass-2 是给 LLM 别名召回用的；这次的 blind fallback 是给 keyword scanner 喂 snippet —— 不同设计目的。`tests/test_v034_blind_fallback.py` 新增 7 cases（main 有结果不触发 / main 0 + blind 命中 / main 0 + blind 0 / 3 模板 / 无 allowlist / 盲失败被吞 / 部分失败）+ `tests/test_v018_features.py:test_no_pass2_fires_regardless_of_pass1_size` 计数从 40 → 43。570 → 577 pass。`--version` 输出 `0.3.4`
- **v0.3.5 reviews 章最大召回四层架构**（A+B+C+D，用户反馈「不只几条小消息」）：(1) **A — blind fallback 闸门取消** —— `tavily_reviews.collect()` 末尾 3 条无 allowlist query（`"X" 评价/体验/面试`）从「main 全 0 才触发」改为「每 run always」，与 main 通过 URL dedup 合并（+3 Tavily credits always）；(2) **B — Tavily `qna_search` AI 摘要层** —— 新 `src/jobhunter/collectors/qna_reviews.py` 的 `QnaReviewsCollector`，Tavily AI 综合多源返回 1-2 段叙述，包成 `RawItem(source="tavily_qna")` 推入同 bucket（+1 credit always，质变：snippet → AI 综合）；(3) **C — Tavily `extract` 抓 canonical 点评页** —— 新 `src/jobhunter/collectors/extract_reviews.py` 的 `ExtractReviewsCollector`，两阶段：search 4 个 canonical 站（看准 / 脉脉 / 牛客 / 知乎）找公司页 URL，每站 ≤2 URL，总 ≤6，再 `tavily.extract(urls)` 抓全页 markdown 包成 `RawItem(source="tavily_extract")`（+5-8 credits always）；(4) **D — `sparse_takeaway` macro + `compute_review_diagnostics`** —— sparse 章不显示战败文案，改「查了 N 平台 + M 关键词 + 1 次 AI 摘要 + K 个点评页 → 找到 X 条原始 → 自动提炼 Y 条信号 + 手动核查链接」诚实诊断；IV/V/VI 三章「本次未能取得」全替换为 sparse_takeaway（薪酬 manual 看准/脉脉/牛客；加班离职加知乎；氛围加小红书+知乎）。`ReportData.review_diagnostics` 新字段。RawItem 没有 `content` 字段，qna/extract 把全文塞进 `payload["full_answer"]` / `payload["full_content"]`。Cost 总账：Tavily free tier 1000 credits/月 ÷ ~8 runs。`tests/test_v035_max_recall.py` 15 cases + `tests/test_v034_blind_fallback.py` + `tests/test_v018_features.py` 拆分判定。592 pass。`--version` 输出 `0.3.5`
- **v0.3.5 hotfix**（用户 作业帮 实测反馈）修 2 个 v0.3.5 发布时漏的渲染 bug：(1) **薪酬章 6 行 ¥K 空字段** —— `charts.py:salary_distribution()` 原来固定返回 `{label, count}`，template 引用 `{{ s.k }}` 永远 undefined → 渲染 `¥K`。修：chart 改返回 `{label, count, k_lo, k_hi}`，template 改用 `s.label`；sum(counts)==0 时返回 `None`，整张表隐藏。(2) **司法章时间线 6 年横线无 dot** —— LLM 给 `case_count_total=45` 但 `sample_cases=[]`（每个 case 的 .year 都是 None），`case_year_buckets([])` 返回 6 个空 bucket。修：template 加 `{% elif jf and jf.case_count_total %}` fallback 渲染「共 N 起诉讼未关联到具体年份；详见下方裁判文书列表」sparse 兜底。零 LLM 调用增量，零 schema 改动，592 tests 全绿。`commit 8f2322c`
- 不支持：Web 服务、Playwright

## 下次接手可考虑的深度改动

- **行业路由**（不是岗位路由） — LLM 先判公司行业再选数据源；当前 `domains_for_position()` 是位置路由的妥协，**做全行业路由需要一次额外 LLM 调用**
- **3 级证据等级**（用户主张 / 多源重复出现 / 有公开证据证实） — 当前 `support_tier`（unverified / single-source / corroborated / multi-domain）已经在做类似分级，命名差异可对齐，详见 `src/jobhunter/report/builder.py:compute_signal_supports`

## 免责

仅供个人求职参考，不对外展示，不存储身份信息。请独立判断并自行核实关键事实，并遵守相关网站服务条款。
# CLAUDE.md

> jobHunter — 本地 Python 反向背调 CLI。从 GitHub issues / commit 历史能拿到的事，不要在这里复述。这里只写**不查就会犯错的边界与工作流**。

## 项目一句话

输入「公司 + 岗位 + 城市」→ 5–10 分钟生成单文件 HTML 报告（5 轴打分 + 工商/司法/公司画像/薪酬/加班/氛围/舆情 + 面试反问 + 网络词解读）。数据源 Tavily + Claude，输出可分享。

## 怎么跑

```bash
.venv/Scripts/python.exe -m jobhunter run -c "阿里云" -p "后端" --city "杭州" --no-open
scripts/run.bat -c "阿里云" -p "后端"                        # 一键启动器（等价上面，自动 --no-open）
.venv/Scripts/python.exe -m pytest                       # 312 tests
```

`.env` 在 `e:\project\jobHunter\.env`（`ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` 可选走 ccswitch 中转 + `TAVILY_API_KEY`）。

## 技术栈

- Python 3.14 + hatchling + src/ 布局
- pydantic v2（**`mode="json"`** 用于序列化；`Field(default_factory=list)` 不接 None）
- Anthropic SDK（ccswitch 中转走 `api.minimaxi.com/anthropic`）
- Tavily async SDK + `platformdirs` 文件缓存（24h TTL）
- Click + InquirerPy（交互）+ Rich（进度）+ Jinja2（报告）
- httpx + tenacity（重试）

## 目录约定

- `models/facts.py` 是**双重契约**：Claude 约束 + Jinja 输入。改字段两边都改。
- `report/charts.py` 是纯 SVG 生成器（无 JS、单文件可移植）。
- `llm/prompts.py` 是中文 prompt 单一来源。
- 不要碰 `reports/` 目录内容（gitignore）。
- `scripts/regen_sample.py` 仅用于离线重生成示例，**不**作为正式入口。

## 当前边界（v0.1.16）

- gsxt / wenshu 在非 CN IP 下**软失败**（不抛异常，UI 提示手动核查）
- ccswitch 中转的 LLM 会把单元素 list 包成 `{"item": [...]}`（OpenAPI 3.1 风格），已由 `NullTolerantListBase` 自动 unwrap；v0.1.4 起还把任何非 list 标量也 coerce 成 `[]`
- LLM 偶有 enum 同义词（"在业"→存续 / "重"→high），已加 per-field 校验器
- LLM 偶对 Optional 子模型字段（business / reviews / judicial / company_profile）返回非 dict 值，`consolidate` 步调 `_sanitize_aggregated` 清洗成 None
- LLM 偶对数字字段（base_monthly_k / stake_pct / case_count_total / enforcement_records 等）返回中文串 ("约 8 起"、"35%"、"面议")，已加 per-field 校验器把可解析串 coerce 成数字、其余 None
- LLM 偶把 slang `term` 写成数字 ("996") 或把 `anomaly_listed` 写成 "否/是"、把 `established_at` 写成 "未知/约 2010 年"，已加 `_coerce_term` / `_coerce_bool` / `_coerce_date` 校验器兜底
- LLM 偶对 `supporting_urls` 返回非 list 值，4 个 signal 模型（Salary/Overtime/Turnover/Vibe）已继承 `NullTolerantListBase` 自动 coerce
- v0.1.4 起 LLM consolidation 步 `AggregatedFindings.model_validate` 失败会 fallback 到原始 facets（best-effort，不让整个 run 挂掉）
- consolidation 步 max_tokens 已 8000（默认 4096 不够）
- 交互模式在 Python 3.14 下用 `loop.run_in_executor` 跑 InquirerPy，绕开嵌套 asyncio.run
- reviews 域查询会先调一次 LLM 生成公司别名（缩写 / 英文名），别名最多取 3 个；v0.1.6 起再加 slang 召回（5–8 个 2-6 字口语词，如 内卷/ICU/摆烂/跑路/PUA），prompt 明确禁止含公司名
- ReviewFacts 现在带 slang_glossary 字段，chapter V 末尾渲染「网络词解读」列表（≤30 字 meaning + count + url）
- v0.1.7 起 salary/overtime/vibe/turnover 每条 signal 都附 `supporting_urls`，报告 builder 调 `compute_signal_supports` 算 support_tier（unverified / single-source / corroborated / multi-domain），salary 表 / overtime bullets / vibe bullets 旁渲染 tier-badge
- extract 步 CHARS_CAP 已 50_000（原 25K），`_materialize` 按 Tavily score 降序排，确保高分项不被 slice
- v0.1.8 起 pipeline 默认跑两轮：round 1 后用 LLM 从 reviews 原材料抽 3-5 个内部实体（产品/品牌/部门/创始人）作为 round 2 reviews 查询的别名；round 2 完成后 `normalize()` 自然 dedup（URL + 标题）；硬上限 1 轮递归 / 5 个实体，避免成本爆炸
- v0.1.8 起 `_compute_confidence` 返回 per-chapter dict（company/business/judicial/reviews/news + overall），各章标题旁渲染 conf-badge「数据充足 / 部分缺失 / 需人工核查」
- v0.1.8 起 hero meta 加「数据多样性」KPI：`compute_diversity_kpi` 统计 total_signals / corroborated_count / distinct_domains，并据此标 高/中/低
- v0.1.8 起 Chapter VII 舆情新增 SVG 时间线（horizontal axis + dots + native `<title>` tooltip），与原 CSS 时间轴并列
- v0.1.8 起 EXTRACT_REVIEWS_SUFFIX 要求 evidence 字段保留原文引号包裹的关键句（让读者能直接核对原文）
- NewsFacts._drop_url_missing 只接受 dict（LLM 侧）；model_validate 才能传 list[NewsItem] 实例
- NewsItem.published_at 加 `_coerce_published_at`：date/datetime → ISO 字符串，宽松中文日期 → YYYY-MM-DD
- v0.1.9 起 `REVIEW_DOMAINS` 扩到 24 个域名（15 通用 + 4 跨境电商 + 1 游戏 NGA + 1 医护丁香园 + 3 程序员掘金/思否/OSChina），新增 `POSITION_DOMAIN_HINTS` + `domains_for_position(position)` 按岗位关键词过滤 Tavily allowlist 实现成本控制（空岗位/未识别岗位 → 全量 fallback；如 "后端" → 通用+程序员，跳过跨境/医护/游戏）
- v0.1.10 起 `REVIEW_DOMAINS` 扩到 31 个域名，覆盖 9 个垂直行业：新增 网安（freebuf / 看雪） / 电商运营（派代） / 设计（站酷 / UI中国） / 公考（QZZN） / HR（三茅）；POSITION_DOMAIN_HINTS 加 30+ 关键词。"电商" 现在返回 跨境 + 派代 union（cross-border + 淘系）；"淘宝/京东/拼多多/天猫" 只返回派代（精准圈定非跨境电商）
- v0.1.11 起 `REVIEW_DOMAINS` 扩到 46 个域名，新增 5 个 A 级全行业（黑猫投诉 / 36 氪企服点评 / 快手 / 微博 / 抖音 — 后两个与 NEWS_DOMAINS 双备案）+ 4 个 B 级行业垂类（汽车之家 / 懂车帝 / 易车 / 车质网；雪球 / 东方财富股吧 / 同花顺；房天下 / 安居客 / 贝壳；卡车之家 / 货车帮 / 运满满）+ 跨境补 2 个（雨果跨境 / 卖家之家）。POSITION_DOMAIN_HINTS 加 30+ 关键词覆盖 汽车/金融/物业/物流 等行业
- v0.1.12 起报告增加「去 AI 味」视觉打磨：`report.css` +199 行 motion 系统（reveal-on-scroll / paper-grain texture / tier-badge hover lift / bullet row hover highlight / axis-ribbon cell spotlight / `.pullquote` 编辑型强调 / focus-visible 描边 / KPI 数字滚动完成时 scale 弹一下）；template `</body>` 前加 +113 行 inline JS（IntersectionObserver + easeOutCubic counter ticker + prefers-reduced-motion guard + fallback path）。零外部依赖、单文件可移植性保持
- v0.1.13 起报告加「编辑手记 + 数据故事 + 拖拽章节」三件套：(1) `industry_baselines.py` 提供 12 个行业 + default 基线（lawsuits_per_year / overtime_hours_per_week / turnover_rate / salary_k_monthly_3y）+ `pick_industry()` 关键词匹配 + `delta_pct()` 计算；(2) `compute_chapter_stories()` 确定性产出 `edit_notes[chapter_key]` 一句话编辑按语 + `data_stories[chapter_key]` 「过去 12 个月里…比同行平均高 X%」行业对比，纯本地无 LLM 调用；(3) 7 个主章节 wrap 在 `<div class="chapters-container">`，native HTML5 drag-and-drop 重排 + `localStorage` 持久化 + 「重置章节顺序」按钮（可选 tail 章节：interview/infer/gaps/sources 不参与拖拽）；`story_block(chapter_key)` Jinja macro 渲染 `.story-block / .edit-note / .data-story`，CSS 用左 border + arrow bullet 编辑型视觉；模板 7 个章节 `</header>` 后插 `{{ story_block('company') }}` 等；测试 +29 (`tests/test_v013_features.py`)，全 265 pass
- v0.1.14 起报告密度提升：reviews 域信号太稀（实跑经常 salary/vibe 0 条）→ (1) `extract_all_domains` 跑两轮：首轮薄时（<3 total 或 ≤2 types 非零）追加一轮聚焦 missing types 的 LLM 调用；(2) `_loose_keyword_reviews()` 本地关键词兜底（996/995/大小周/内卷/PUA/月薪…），纯确定性、零 LLM 调用；(3) `_merge_reviews()` 按 url dedup 两轮结果。司法章「零诉讼」改为「公开记录中未发现诉讼或被执行 — 同行里相对少见的干净背景」正面叙事（`report.html.j2` ch-judicial 三分支：no data / zero / nonzero）。COMPANY_INFO_DOMAINS 加 huxiu.com / lieyunwang.com / chuangsanjia.com，query 加 `site:36kr.com` / `site:huxiu.com`。`_fact_driven_interview_questions()` 派生 5 条针对性问题（司法样本 / 薪酬跨度 >8K / heavy_overtime ≥2 / anomaly_listed / 非上市融资阶段），与 LLM 产出去重合并、前置插入；LLM 失败降级到纯事实驱动。测试 +29 (`tests/test_v014_features.py`)，全 265 pass
- v0.1.15 起报告加「面试流程 + 试用期清单 + 同行业对比」三件套：(1) ReviewFacts 加 `interview_rounds` / `interview_style` / `interview_difficulty` / `interview_signals`，prompt 强制 LLM 抽取典型轮数/题型标签/难度，新章 `ch-interview-process` 展示；(2) `compute_trial_checklist()` 派生 1mo/3mo/6mo 试用期观察清单（HR 反向背调框架 + 数据驱动 ≤5 条/时点），事实驱动触发：heavy_overtime ≥2 → 1mo 加班强度；anomaly_listed → 3mo 经营异常；case_count > 0 → 6mo 司法核查；funding_stage 非「已上市」→ 6mo 询问 runway；(3) `--compare "美团,京东"` CLI flag 触发跨公司对比，pipeline 新增 `_build_peer_summary()` 轻量级 runner（仅 extract+scoring，跳过 alias/slang/round-2/consolidation/interview Qs），`run_peer_comparison()` 用 `asyncio.Semaphore(2)` 限流，Tavily 24h cache 让重复 0 成本；模板新章 `ch-peers` 渲染同行业对比表（综合分/5 轴/典型月薪/司法数/舆情），目标公司 highlight 在首行；测试 +21 (`tests/test_v015_features.py`)，全 286 pass
- v0.1.16 起报告加「信号新鲜度 + JD 对照 + 顶层判断」三件套（决策闭环最后一公里）：(1) 4 个 review signal model（Salary/Overtime/Turnover/Vibe）加 `published_at: date | None` + `_coerce_signal_date` 校验器（ISO 字符串 / 中文日期 / datetime / 未知 → date | None），EXTRACT_REVIEWS_SUFFIX 要求 LLM 抽每条 signal 的 published_at；`_loose_keyword_reviews()` 优先用 RawItem.published_at、否则 date.today()；模板 `signal_age_badge(s)` macro 渲染「X 天前 / X 月前 / X 年前」，超 1 年 line-through + 0.5 opacity；(2) `report/jd_alignment.py` 纯本地判定 6 类 JD 常见承诺（弹性 / 15 薪 / 五险一金 / 扁平 / 期权 / 福利 / 技术驱动）vs 公开事实 → confirmed/contradicted/unverified；CompanyQuery 加 `jd_text`，CLI `--jd TEXT` / `--jd-file PATH`（二选一，互斥校验），模板新章 `jd-alignment` 渲染「JD 对照清单」；(3) `compute_overall_verdict()` 派生顶层 verdict（recommend/caution/avoid/neutral），判定：avoid = 2+ 轴 ≤2 OR 司法>10；caution = 任一轴 ≤3 OR 司法>3 OR 重度加班≥2 OR 异常；recommend = 全轴≥4 AND 司法0 AND 无重度加班 AND 正面≥负面；其余 neutral；模板 hero-side 加 `.hero-verdict` badge（绿/黄/红/灰）+ headline + top 3 reasons；测试 +26 (`tests/test_v016_features.py`)，全 312 pass
- 用户的两个深度建议记入「下次接手」：**1.** 行业路由（不是岗位路由） — LLM 先判公司行业再选数据源；当前 `domains_for_position()` 是位置路由的妥协，**做全行业路由需要一次额外 LLM 调用**。**2.** 3 级证据等级（用户主张 / 多源重复出现 / 有公开证据证实） — 当前 `support_tier`（unverified / single-source / corroborated / multi-domain）已经在做类似分级，命名差异可对齐，详见 [src/jobhunter/report/builder.py:compute_signal_supports](src/jobhunter/report/builder.py)
- 公司画像（company_info 域）从百度百科 / IT 桔子 / 创业邦 / 投资界 / 企查查 / 天眼查 拿，靠 Tavily allowlist；缺数据时报告 section 仅展示已抓到的字段

## 下次接手该知道

- 改 schema → `pytest -v` 必绿，且 `scripts/regen_sample.py` 重生成样例对比视觉
- 加新 collector → 实现 `BaseCollector.safe_collect()` 即可自动并发，软失败是默认行为
- 加新打分轴 → `models/scoring.py:AXIS_LABELS_ZH` + `report/scoring.py:compute_axes()` + 模板 `overview-grid`
- 加新采集维度 → 6 个串接点必须同步：`query_templates.<DOMAIN>_DOMAINS` / `extract.DOMAIN_SUFFIX + MODEL_BY_DOMAIN` / `llm/schemas._EXTRACT_TOOLS + key_to_idx` / `models/raw.CollectorResult.domain` Literal / `normalize.by_domain` bucket / `pipeline._compute_confidence` 计数 + 模板 section
- **不要**改 `env_prefix` —— 之前被设成 `JOBHUNTER_` 会让裸 `ANTHROPIC_API_KEY` 失效，详见 commit `a00ce8b`
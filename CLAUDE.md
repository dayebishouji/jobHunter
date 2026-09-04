# CLAUDE.md

> jobHunter — 本地 Python 反向背调 CLI。从 GitHub issues / commit 历史能拿到的事，不要在这里复述。这里只写**不查就会犯错的边界与工作流**。

## 项目一句话

输入「公司 + 岗位 + 城市」→ 5–10 分钟生成单文件 HTML 报告（5 轴打分 + 工商/司法/公司画像/薪酬/加班/氛围/舆情 + 面试反问 + 网络词解读）。数据源 Tavily + Claude，输出可分享。

## 怎么跑

```bash
.venv/Scripts/python.exe -m jobhunter run -c "阿里云" -p "后端" --city "杭州" --no-open
scripts/run.bat -c "阿里云" -p "后端"                        # 一键启动器（等价上面，自动 --no-open）
.venv/Scripts/python.exe -m pytest                       # 179 tests
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

## 当前边界（v0.1.9）

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
- 公司画像（company_info 域）从百度百科 / IT 桔子 / 创业邦 / 投资界 / 企查查 / 天眼查 拿，靠 Tavily allowlist；缺数据时报告 section 仅展示已抓到的字段

## 下次接手该知道

- 改 schema → `pytest -v` 必绿，且 `scripts/regen_sample.py` 重生成样例对比视觉
- 加新 collector → 实现 `BaseCollector.safe_collect()` 即可自动并发，软失败是默认行为
- 加新打分轴 → `models/scoring.py:AXIS_LABELS_ZH` + `report/scoring.py:compute_axes()` + 模板 `overview-grid`
- 加新采集维度 → 6 个串接点必须同步：`query_templates.<DOMAIN>_DOMAINS` / `extract.DOMAIN_SUFFIX + MODEL_BY_DOMAIN` / `llm/schemas._EXTRACT_TOOLS + key_to_idx` / `models/raw.CollectorResult.domain` Literal / `normalize.by_domain` bucket / `pipeline._compute_confidence` 计数 + 模板 section
- **不要**改 `env_prefix` —— 之前被设成 `JOBHUNTER_` 会让裸 `ANTHROPIC_API_KEY` 失效，详见 commit `a00ce8b`
# CLAUDE.md

> jobHunter — 本地 Python 反向背调 CLI。从 GitHub issues / commit 历史能拿到的事，不要在这里复述。这里只写**不查就会犯错的边界与工作流**。

## 项目一句话

输入「公司 + 岗位 + 城市」→ 5–10 分钟生成单文件 HTML 报告（5 轴打分 + 工商/司法/薪酬/加班/氛围/舆情 + 面试反问）。数据源 Tavily + Claude，输出可分享。

## 怎么跑

```bash
.venv/Scripts/python.exe -m jobhunter run -c "阿里云" -p "后端" --city "杭州" --no-open
.venv/Scripts/python.exe -m pytest                       # 63 tests
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

## 当前边界（v0.1.3）

- gsxt / wenshu 在非 CN IP 下**软失败**（不抛异常，UI 提示手动核查）
- ccswitch 中转的 LLM 会把单元素 list 包成 `{"item": [...]}`（OpenAPI 3.1 风格），已由 `NullTolerantListBase` 自动 unwrap
- LLM 偶有 enum 同义词（"在业"→存续 / "重"→high），已加 per-field 校验器
- consolidation 步 max_tokens 已 8000（默认 4096 不够）

## 下次接手该知道

- 改 schema → `pytest -v` 必绿，且 `scripts/regen_sample.py` 重生成样例对比视觉
- 加新 collector → 实现 `BaseCollector.safe_collect()` 即可自动并发，软失败是默认行为
- 加新打分轴 → `models/scoring.py:AXIS_LABELS_ZH` + `report/scoring.py:compute_axes()` + 模板 `overview-grid`
- **不要**改 `env_prefix` —— 之前被设成 `JOBHUNTER_` 会让裸 `ANTHROPIC_API_KEY` 失效，详见 commit `a00ce8b`
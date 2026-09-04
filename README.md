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
pytest                        # 192 tests
pytest tests/test_charts.py   # 图表单元测试
pytest tests/test_pipeline_smoke.py  # 端到端 mock 烟囱测试
```

## 已知限制（v0.1.10）

- **gsxt.gov.cn / wenshu.court.gov.cn** 在非中国大陆 IP 下不可达，会软失败并在报告里提示手动核查链接
- **Tavily 免费档** 1000 credits / 月；v0.1.8 默认跑两轮（round 1 + entity-aliased round 2），单次约 50–80 credits
- **ccswitch / one-api 中转** LLM 输出偶有 schema 偏差，已通过 `NullTolerantListBase` + per-field 校验器兜底；list_company_entities 偶返回纯文本（不走 tool_use），已 fallback 到 chat()+JSON regex
- **inferences 段** 在 consolidation 输出 token 紧张时可能为空，不影响主功能
- **公司画像域** 依赖 Tavily 在百度百科 / IT 桔子 / 创业邦的命中；小众公司可能拿不到完整字段，仅展示已抓到的部分
- **v0.1.6 网络词召回**：依赖 LLM 生成 5–8 个 slang 查询词（内卷 / ICU / 摆烂 / 跑路 …）提升 UGC 召回；抽取后报告 chapter V 末尾会附「网络词解读」列表；如 LLM 失败则跳过
- **v0.1.8 递归 sub-query**：round 1 后用 LLM 抽 3-5 个公司内部实体（产品/品牌/部门/创始人）作为 round 2 查询别名；硬上限 1 轮 / 5 个实体
- **v0.1.8 数据多样性 KPI**：每条 signal 旁的 tier-badge（待核实/单一来源/多源印证/跨域印证）+ hero meta 的「数据多样性」pill 反映 cross-source corroboration
- **v0.1.9 垂直行业召回域**：REVIEW_DOMAINS 扩到 24 个域名（跨境 + 游戏 + 医护 + 程序员），通过 `domains_for_position(position)` 按岗位关键词过滤 Tavily allowlist 实现成本控制
- **v0.1.10 召回域覆盖 9 个垂直**：REVIEW_DOMAINS 扩到 31 个域名，新增 网安（freebuf.com / bbs.pediy.com） / 电商运营（paidai.com） / 设计（zcool.com.cn / ui.cn） / 公考（qzzn.com） / HR（hrloo.com）；POSITION_DOMAIN_HINTS 加 30+ 关键词，"淘宝/京东/拼多多/天猫" 精准圈定派代（非跨境），"电商" 触发跨境+派代 union，"UI/UX/平面/视觉" 触发站酷+UI中国
- 不支持：批量多公司、SQLite watchlist、Web 服务、PDF 导出、Playwright（v0.2 候选）

## 免责

仅供个人求职参考，不对外展示，不存储身份信息。请独立判断并自行核实关键事实，并遵守相关网站服务条款。
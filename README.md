# jobHunter

> 公司反向背调命令行工具 —— 给定公司名 + 岗位 + 城市，输出多维度调研报告（HTML）。

把 ¥29 一次的人工「反向背调」自动化。本地 CLI，混合数据源（Anthropic Claude 抽取 / 综合 + Tavily 搜索评价与新闻 + gsxt.gov.cn 工商基本信息）。

---

## 它能回答什么

输入一家公司和岗位，自动产出包含 9 个维度的 HTML 报告：

| 维度 | 数据来源 |
|---|---|
| 加班强度 | 看准网 / 脉脉 / 知乎 / 小红书 / 牛客 公开评价（经 Tavily 搜索） |
| 薪酬结构与 offer 落点 | 同上 + 爆料区 |
| 部门风评 / 团队氛围 | 同上 |
| 离职率 | 同上 + 36氪/虎嗅/微博（人员变动新闻） |
| 岗位真实情况 vs JD | 匿名评价 |
| 工商基本面（法人/成立日期/注册资本/经营状态） | gsxt.gov.cn（**非 CN IP 通常失败**，显示"数据不足"）|
| 司法风险 | 裁判文书网（v0.1 **stub**），报告提示人工自查 |
| 近期舆情 | 36氪 / 虎嗅 / 微博 / 百度新闻 |
| 5 轴风险打分 + 面试反问清单（6-10 条） | 启发式评分 + Claude 综合 |

---

## 安装

需要 **Python 3.10+**。推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
# 克隆并安装
git clone git@github.com:dayebishouji/jobHunter.git
cd jobHunter

# 创建虚拟环境 + 安装依赖（runtime + dev）
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# 配置 API key
cp .env.example .env
# 编辑 .env，填入：
#   ANTHROPIC_API_KEY=sk-ant-...
#   TAVILY_API_KEY=tvly-...
```

获取 key：
- Anthropic：<https://console.anthropic.com/>
- Tavily：<https://tavily.com/>（注册有免费额度）

---

## 用法

### 交互式（最常用）

```bash
jobhunter
```

会逐步提示输入公司 / 岗位 / 城市，确认后运行 5 阶段管道，最后自动打开浏览器。

### 非交互式（脚本友好）

```bash
jobhunter run \
  --company "阿里云" \
  --position "后端工程师" \
  --city "杭州" \
  --output ~/Desktop/reports
```

或简写：

```bash
jobhunter run -c "字节跳动" -p "产品经理" -y "北京"
```

### 选项

| 选项 | 说明 |
|---|---|
| `--company`, `-c` | 公司名（**必填**）|
| `--position`, `-p` | 岗位（可选）|
| `--city`, `-y` | 城市（可选）|
| `--no-judicial` | 跳过司法风险 |
| `--no-news` | 跳过近期舆情 |
| `--output`, `-o` | 自定义输出目录（默认 `reports/`）|
| `--no-open` | 不自动打开浏览器 |
| `--version` | 输出版本 |
| `--help` | 输出帮助 |

---

## 报告示例

报告会写入 `reports/{公司}-{岗位?}-{时间戳}.html`，包含：

- **Header**：公司 + 岗位 + 城市 + 整体置信度 pill
- **5 轴概览**：加班 / 薪酬诚信 / 司法 / 工商 / 文化，每轴 1-5 星 + 一句话理由
- **数据缺口**（如适用）：本次没拿到的关键维度
- **8 个可折叠详情 section**：工商基本面 / 司法风险 / 薪酬与福利 / 加班与工作强度 / 团队氛围与文化 / 岗位 vs JD / 近期舆情 / 面试反问清单
- **数据来源附录**：所有 URL 按域名分组列出

打开后支持：
- 深色模式自适应（`prefers-color-scheme`）
- 移动端 375px 视口友好
- 无 JS 也能读（`<details>` 原生折叠）
- 单文件可移植（CSS inline）

---

## 已知限制（v0.1）

- **gsxt.gov.cn 在非中国内地 IP 下不可达**（Cloudflare 521）。工商 section 在大多数海外环境下显示"数据不足"，并提示人工到该网站核对
- **wenshu.court.gov.cn 反爬较重**。v0.1 司法 collector 是 stub，报告提示人工自查链接
- 仅单家公司查询（无批量 / 无调度 / 无 Web UI）
- 强烈依赖 LLM 的事实抽取；如果 Claude 抽错或漏，UI 上会用 `LLM 推断` 标签明示

---

## 架构概览

```
CLI (Click + InquirerPy)
  ↓
pipeline.run()
  ├─ collectors (并发)
  │  ├─ GSXTCollector        ──┐
  │  ├─ WenshuCollector       │  best-effort：60s timeout + 软失败
  │  ├─ TavilyReviewsCollector│
  │  └─ TavilyNewsCollector ──┘
  ├─ normalize               跨源 URL + 模糊标题去重
  ├─ LLM extract (并发)      Claude tool_use，4 域各一次
  ├─ consolidate             Claude 综合
  ├─ crosscheck              检测薪资冲突等
  ├─ scoring                 5 轴启发式打分
  ├─ LLM interview Q         Claude 自由文本 → 行分割
  └─ build_report            Jinja2 渲染 → HTML 落盘
```

---

## 开发

```bash
# 运行测试
.venv/bin/pytest -v

# 端到端 mock 测试（不消耗 API 额度）
.venv/bin/pytest tests/test_pipeline_smoke.py -v

# Lint
.venv/bin/ruff check src tests
```

模块层次：
- `src/jobhunter/collectors/` —— 数据采集器
- `src/jobhunter/search/` —— Tavily 封装 + 文件缓存
- `src/jobhunter/processing/` —— 归一化 / LLM 抽取 / 冲突检测
- `src/jobhunter/llm/` —— Anthropic SDK 封装 + 中文 prompt + tool_use schema
- `src/jobhunter/report/` —— 启发式评分 + Jinja2 HTML 模板
- `src/jobhunter/models/` —— 全部 Pydantic schema（双重用途：tool_use 输入 + 模板输入）

---

## 路线图

v0.2+ 计划：
- 多公司批量（YAML / JSON 输入）
- 公司"关注列表"持续追踪（SQLite）
- Playwright 兜底抓 wenshu / gsxt（含代理支持）
- PDF 导出（Playwright / weasyprint）
- 拼音 slug（v0.1 时间戳方案已够用）

---

## 免责声明

本工具仅供个人求职参考。所有数据来自公开渠道（看准、脉脉、知乎、小红书、牛客、36氪、虎嗅、微博等）和官方政府网站。每条结论都附带源 URL，请独立判断并自行核实关键事实。请遵守相关网站的服务条款。

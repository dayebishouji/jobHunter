# Design

<!-- impeccable:design-schema 1 -->

## Visual World

**券商深度研报 × 招股书 hybrid** — 投资人备忘录 / sell-side research 注脚 / 招股书业务概况段的视觉语言。

读者拿到的不是博客文章，是「先看完 cover 摘要页，再决定要不要往下翻章节」的备忘。文字密度高、证据多于评论、引用原话多于修辞、grid + 细线 + 编号章节、留白有目的。

## Visual Goals

1. **第一眼 = 一份研报，不是博客** — masthead 顶头、cover 摘要页、7 个编号章节、Σ 来源附录、风险提示收尾。
2. **90 秒给出 verdict、5 分钟给出洞察** — hero KPI 带 + 雷达 SVG + 数据多样性 badge 在 cover 一眼可见。
3. **证据可溯源** — 每条信号必带原文引号 + 来源 URL + 时间 + 平台 + 多源交叉状态。
4. **编辑型语气** — 编辑手记 (`story-block`) 在事实之上加一句按语，行业基线对比 (`data-story`) 把数据放回坐标。

## Reference Points

- **东方财富 / 慧博研究报告** — masthead + 多章节 + 数据表格
- **招股说明书（业务概况 + 财务分析 + 风险因素）** — 编号章节 + 「Σ 来源附录」收尾
- **Bloomberg Terminal / FT Alphaville** — grid + 数据为主 + 极少装饰
- **The Economist (display typography)** — Noto Serif SC 标题 + 正文 grid

## Tokens

| Token | 值 | 用途 |
|---|---|---|
| `--paper` | `#fbfaf6` | 主背景（米黄纸感） |
| `--paper-deep` | `#f1ece0` | 章节底色 / card 底 |
| `--paper-card` | `#fffdf8` | 内嵌 card 底色 |
| `--ink` | `#1a1a1a` | 正文 |
| `--ink-soft` | `#5a5a5a` | 次级文字 |
| `--ink-faint` | `#9a9a9a` | 提示 / meta |
| `--rule` | `#d4cdb8` | 细线 / divider |
| `--rule-strong` | `#1a3a6e` | 强调分隔线 |
| `--brand` | `#1a3a6e` | broker-blue（标题 / verdict / KPI 主色） |
| `--brand-soft` | `#3a5a8e` | 副标题 / link |
| `--good` | `#2e7d32` | 正向信号（绿色） |
| `--bad` | `#c62828` | 负向信号（红色） |
| `--mid` | `#b8854a` | 中性 / 注意（铜色） |
| `--accent-good-bg` | `color-mix(in srgb, var(--good) 8%, var(--paper-card))` | 正面 chip 底 |
| `--accent-bad-bg` | `color-mix(in srgb, var(--bad) 8%, var(--paper-card))` | 负面 chip 底 |
| `--accent-mid-bg` | `color-mix(in srgb, var(--mid) 12%, var(--paper-card))` | 中性 chip 底 |
| `--accent-brand-bg` | `color-mix(in srgb, var(--brand) 10%, var(--paper-card))` | brand chip 底 |

字体：
- Display / 标题 / 章节名：**Noto Serif SC**（衬线，研报感）
- Body / UI：**Noto Sans SC**（无衬线，正文易读）
- Data / 数字 / 代码：**Noto Sans Mono**（等宽，对齐表格）

## Layout

页面纵向 5 段：

1. **masthead** — 顶头横条，左 logo + 报告元信息（公司 / 岗位 / 城市 / 生成时间），右侧 rating（增持 / 中性 / 减持 / 未知）
2. **cover**（一页摘要）— top thesis 句 + KPI 带（综合分 / 5 轴均值 / 数据多样性 / 司法数 / 异常 / 薪酬 P50）+ 雷达 SVG + snapshot diff + chapter index + 数据来源 chip wall + collector soft-fail 提示
3. **7 个编号章节**（I-VII） — 公司画像 / 工商 / 司法 / 薪酬 / 加班 / 氛围 / 舆情。每章 `<section class="chapter" id="ch-X" data-chapter-key="X">` 包在 `.chapters-container` 中，HTML5 native DnD 重排 + `localStorage:jobhunter:chapter-order` 持久化
4. **4 个侧栏章节** — 面试准备 / 同行业对比 / JD 对照 / tail（推断 / 缺口 / Σ 来源）
5. **风险提示 + Σ 来源附录 + footer** — 风险点列表 + 全部数据来源 URL 去重 + 版权信息

## Components

### Cover Thesis（cover 顶部一句话）
- `.cover-thesis` — 16-20px serif，居中或左对齐
- 内容：1 句话定调（基于 verdict level + top 3 reasons）

### KPI 带
- `.kpi-strip` — 6 列 grid，每列 `.kpi-cell`
- 数字大号（32-40px serif），单位 / 标签小号无衬线
- 数字加 `.mono` 类（Noto Sans Mono）保证对齐

### 雷达 SVG
- `.cover-radar` — 1200×1200 SVG，5 边形，5 轴（加班 / 薪酬 / 司法 / 工商 / 氛围）
- 内部填充 `var(--brand)` @ 12% opacity，描边 1.5px
- 轴标签 12px sans

### Chapter Head
- `.chapter-head` — flex row，左侧大号罗马数字（I / II / …）+ 章节标题 + 右侧 conf-badge
- `.chapter-num` — 48px serif，`color: var(--brand)`，30% opacity
- 标题 `<h2>` 24px serif，下方 4px 横线 `var(--rule)`

### Story Block（编辑手记 + 数据故事）
- `.story-block` — left border 3px `var(--brand-soft)` + 浅色底
- `.edit-note` — 顶部一句话编辑按语 + 行业标签 + 数据日期
- `.data-story` — 第二行「过去 12 个月里…比同行平均高 X%」行业基线对比

### Data Table（研报表格）
- `.data-table` — 全宽表格，row divider 1px `var(--rule)`，表头 ink-faint
- 第一列左对齐（事实），数据列居中或右对齐
- 数字列加 `.mono`，负向值 `color: var(--bad)`

### Signal Card（reviews 信号）
- `.signal-card` — 边框 1px `var(--rule)`，hover 抬升 2px
- `.signal-card-head` — flex，标签 + tier-badge + age-badge
- `.signal-card-body` — 原文引号 + 来源 URL + 时间 + 平台
- `.tier-badge` — 4 档（unverified / single-source / corroborated / multi-domain）
- `.signal-age` — 「X 天前 / X 月前 / X 年前」，超 1 年 line-through + 0.5 opacity

### Collector Soft-fail Banner
- `.collector-notes` — 浅灰底 + 左边细线，14px
- 只在 `data.collector_notes.get('sogou_weixin') | 'gsxt' | 'wenshu'` 三个 collector 软失败时渲染
- 文案：「⚠ 搜狗微信搜索被反爬拦截 — 部分公众号内容未纳入。」+ 手动核查链接

### Inline Viz（章节内微可视化）
- `.inline-viz` — 章节 body 内的小型可视化容器，48-120px 高
- `.salary-band` — P25 / P50 / P75 迷你横条，中位标 + 谈薪建议
- `.timeline` — 舆情章 SVG 时间线（horizontal axis + dots + native `<title>` tooltip）

### 章节拖拽
- `.chapters-container` 包住 7 个主章节
- `<section>` 加 `draggable="true"`（JS 启动时），拖拽中 `data-chapter-key` 持久化到 `localStorage:jobhunter:chapter-order`
- 重置按钮（v0.2.0 隐藏 — research-report chrome 克制）

## Motion

- **默认无动画** — prefers-reduced-motion 已 guard
- **数字 ticker** — hero KPI 数字滚动（easeOutCubic），600ms 完成时 scale 弹一下
- **reveal-on-scroll** — 主章节 `<section>` 进入视口时 opacity 0 → 1，translateY 8px → 0
- **tier-badge hover** — translateY -1px + 加深边框
- **bullet row hover** — bg-color-mix tint
- **拖拽中** — 拖起章节 opacity 0.5 + drop target 浅蓝色高亮

## Responsive

- **≥1200px**：cover 两栏（top thesis + KPI 带 + 雷达右置）
- **720-1199px**：cover 单栏，章节章节宽度 100%
- **<720px**：所有 grid 退化为单列，hero KPI 2×3，雷达缩小到 320×320

## Print

- `@media print` 强制白底，关闭动画，隐藏 drag-handle，章节 1-7 强制分页或同页留足空白
- `?print=1` URL 末尾 + inline JS 监听 load 后 600ms 调 `window.print()`
- `--print` CLI flag 启用同样 JS

## Dark Mode

- `prefers-color-scheme: dark` 时自动反转：paper → `#1a1a1a`，ink → `#e8e6e0`，brand → `#6a9adf`
- 章节底色 `--paper-deep` → `#252525`，`--rule` → `#3a3a3a`

## Anti-patterns（明确不做）

- ❌ 卡片堆叠、blog layout、白底现代极简
- ❌ emoji 装饰（除 ⚠️ 这种功能性提示）
- ❌ 渐变色背景 / glassmorphism / 阴影过深
- ❌ "立即注册 / CTA 按钮" 类营销元素
- ❌ 图标库（lucide / feather / heroicons），全部 inline SVG
- ❌ 滚动动画抢戏（默认 `prefers-reduced-motion` 关闭）

## Files

| 文件 | 角色 |
|---|---|
| `src/jobhunter/report/templates/report.html.j2` | 报告主模板（~1200 行，方向契约锁在顶部 5 段注释） |
| `src/jobhunter/report/static/report.css` | 全部样式（~1900 行，token 系统在 `:root`） |
| `src/jobhunter/report/builder.py` | 数据派生 + Jinja 渲染入口 |
| `src/jobhunter/report/charts.py` | 纯 SVG 生成器（雷达 / 时间线 / salary-band / kpi-cell） |
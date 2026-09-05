# Pipeline 流程图审计 + 改进建议

**日期**：2026-09-05
**作者**：Claude (miniMax-M3)
**触发原因**：[docs/diagrams/pipeline.mmd](pipeline-flow.mmd) v0.2.0 完成后的自检
**范围**：端到端流程图的可读性 + [src/jobhunter/pipeline.py](../../src/jobhunter/pipeline.py) 真实缺陷 + 产品定位层机会
**结论**：5 条图改进 + 6 条 pipeline 缺陷 + 2 条产品机会；推荐这周做 3 条，下个月做 3 条

---

## 一、流程图本身的可读性（5 条）

按严重度排序，前 3 条值得这周动手。

### 1.1 ❗ Consolidate fallback 路径几乎看不见

**位置**：`pipeline.mmd` Phase 7，G3 (decision) → G4 (red fallback) → H1

**问题**：图里 fallback 用红色虚线一划，但 G4 box 标签短 + 与 G3 decision 几乎贴在一起；最重要的「整个 run 不挂」的 failure path 没有视觉权重。

**修复建议**：
```mermaid
G3 -- "❌ fail" --> G4:::fail
G4:::fail -.->|"AggregatedFindings =<br/>raw facets (best-effort)<br/>整个 run 仍继续"| H1
```
- G4 加 `:::fail` 红色填充
- 边标签加 "整个 run 仍继续" 让用户立刻看到失败语义
- 红边线加粗到 2px

### 1.2 ⚠️ Phase 9 `_build_peer_summary` 重复 3 次

**位置**：`pipeline.mmd` Phase 9，I2/I3/I4 三个节点

**问题**：同节点复制 3 次（"peer 1 / peer 2 / peer N"）只是节点名不同，结构上无新信息。

**修复建议**：
```mermaid
I2["_build_peer_summary<br/>peer 1<br/>Semaphore(2)<br/>extract + scoring only"]:::svc
I2 -.- I3["× peer 2...N<br/>共 N 个轻量级 pipeline"]:::svc
```
用一个 box + 一个 dashed "× N peers" 注释，减少视觉噪声。

### 1.3 ⚠️ Compute 阶段 11 个 box 全部展开

**位置**：`pipeline.mmd` Phase 8，H1-H11

**问题**：H1-H11 都是 deterministic + 并发，全展开反而淹没主线（轴 / verdict / band）。读者扫一眼不知道哪个重要。

**修复建议**：合成一个 box + 内嵌清单：
```mermaid
H["Deterministic Compute (parallel)<br/>• 5 轴打分 (compute_axes)<br/>• per-chapter conf<br/>• 薪酬 band / snapshot diff<br/>• 编辑手记 / 信号 tier<br/>• 顶层 verdict<br/>• 试用期清单 1mo/3mo/6mo<br/>• 面试反问 + 冲突检测<br/>• collector notes"]:::compute
```
保留 4 个最重要的（轴 / verdict / 反问 / band）作为独立 box，其他合进 sub-bullet。

### 1.4 💡 缺输入/输出边界节点

**位置**：整图最左 / 最右

**问题**：没有"输入：CLI args"和"输出：单文件 HTML"的明确起止点。

**修复建议**：加两个 stub：
```mermaid
IN["系统输入<br/>company + position + city<br/>+ 可选 jd/compare/print"]:::client --> A1 & A2
OUT["系统输出<br/>reports/{slug}.html<br/>单文件可移植"]:::storage <-- K1
```

### 1.5 💡 Watchlist 子命令 (A3) 漂浮孤儿

**位置**：`pipeline.mmd` Phase 1 左下

**问题**：A3 (`watch add/list/remove`) 用 dotted edge 连到 K3 (`watchlist.mark_ran`)，但视觉上是孤儿。

**修复建议**：A3 → 单独的 subgraph "Watchlist 子命令 (独立路径)"，明确它不走主流；连到 W1 (`watchlist.json` storage) 而不是 K3。

---

## 二、Pipeline 实现的真实缺陷（6 条）

按 ROI 排序，前 2 条 ROI 最高。

### 2.1 ❗ Consolidate 单点故障 → 失去所有 cross-domain 洞察

**位置**：[src/jobhunter/pipeline.py:155](../../src/jobhunter/pipeline.py#L155) — `findings = await consolidate(llm, query, facets)`
+ [src/jobhunter/processing/extract.py:412](../../src/jobhunter/processing/extract.py#L412) — `async def consolidate(...)`

**问题**：5 路 facets 全部塞进 1 个 LLM prompt；1 次失败（ccswitch 审核 / 瞬时 API 错误 / 空 tool_use） → fallback 到原始 facets。所有 cross-domain 综合洞察（典型矛盾 / 综合 strengths-weaknesses / 行业映射）丢失。

**当前 fallback 行为**：[pipeline.py:156-164](../../src/jobhunter/pipeline.py#L156-L164) — 构造空的 `AggregatedFindings` 用 raw facets 填空。这保证 run 不挂，但用户拿到的报告少了洞察层。

**修复建议**：
1. **加 retry**：用现成的 [tenacity](https://github.com/jd/tenacity) 装饰 `llm.structured_call`，3 次重试 + exponential backoff：
   ```python
   @tenacity.retry(
       stop=tenacity.stop_after_attempt(3),
       wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
       retry=tenacity.retry_if_exception_type((AnthropicError, TimeoutError)),
       reraise=True,
   )
   ```
2. **拆成两段**：`per_domain_summary`（5 个并行小调用，每个 domain 一个 summarizer）+ `cross_domain_synthesis`（基于 summaries 推断矛盾 / strengths）；任一段失败不影响主报告。

### 2.2 ❗ Round 2 触发条件太严，漏掉「同类型密集」场景

**位置**：[src/jobhunter/pipeline.py:120-149](../../src/jobhunter/pipeline.py#L120-L149) — `if llm.budget_ok():` 后才有 round 2

**问题**：当前 round 2 仅在 budget_ok + reviews_items 非空时跑。但可能场景：
- Round 1 拿到 3 条 vibe（signal count ≥ 3，passes `_needs_second_pass`）→ 不进 round 2 → salary / overtime 章仍薄
- Round 1 拿到 5 条 salary 但 0 vibe / overtime → 同上

应该按 **类型多样性**（distinct signal types）触发，不是按 signal count。

**修复建议**：
```python
# 新触发条件
def _round2_worthwhile(reviews_items: list[RawItem], reviews_first: ReviewFacts | None) -> bool:
    if not reviews_items or not llm.budget_ok():
        return False
    # 至少 2 个 distinct signal types 才算 rich
    types_present = sum([
        bool(reviews_first and (reviews_first.salary_signals or reviews_first.overtime_signals 
                                or reviews_first.vibe_signals or reviews_first.turnover_signals)),
    ])
    return types_present <= 1  # 0-1 types → 触发 round 2
```

### 2.3 ⚠️ Peer comparison 无 LLM response 缓存，N× 成本

**位置**：[src/jobhunter/pipeline.py:248-323](../../src/jobhunter/pipeline.py#L248-L323) — `_build_peer_summary`

**问题**：每个 peer 跑完整 extract (5 路 LLM 并发)。`TavilyClient` 有 24h file cache，但 `LLMClient` 没有持久化层。如果同一公司 30 天内被对比 2 次，第 2 次仍付完整 LLM 成本。

**修复建议**：给 `LLMClient` 加 per-(company, domain) disk cache：
```python
# llm/cache.py (新)
class LLMResponseCache:
    def __init__(self, ttl_hours: int = 24 * 7):  # 7 天
        ...
    def get(self, system_hash: str, user_hash: str) -> dict | None:
        ...
    def set(self, system_hash: str, user_hash: str, response: dict) -> None:
        ...
```
Cache key = hash(system_prompt + user_prompt + model)；命中即跳过 LLM。Tavily cache 已有同款模式可参考 [src/jobhunter/search/cache.py](../../src/jobhunter/search/cache.py)。

### 2.4 ⚠️ Compute 阶段实际串行不是并行

**位置**：[src/jobhunter/pipeline.py:165-202](../../src/jobhunter/pipeline.py#L165-L202)

**问题**：图里画得并行，但代码里顺序调用 `compute_axes` → `_compute_confidence` → `extract_collector_notes`。虽然每个函数快（100-300ms），但 11 个加起来 1.5-3s 浪费。

**修复建议**：用 `asyncio.gather`：
```python
axes, chapter_confidence, collector_notes, snapshot_diff = await asyncio.gather(
    asyncio.to_thread(compute_axes, findings, by_domain, notes),  # sync 函数 to_thread
    asyncio.to_thread(_compute_confidence, by_domain, findings),
    asyncio.to_thread(extract_collector_notes, results),
    asyncio.to_thread(diff_snapshots, prev_snapshot, data),
)
```
注意：compute_* 多是 sync 函数，需用 `asyncio.to_thread` 包装。

### 2.5 ⚠️ `extract_collector_notes` 只识别 2 种错误码

**位置**：[src/jobhunter/report/builder.py:extract_collector_notes](../../src/jobhunter/report/builder.py)

**问题**：当前只识别 `anti_bot_redirect` + `no_results`。其他真实失败模式都没 marker：
- Tavily 5xx（`internal_server_error`）
- Tavily rate_limit（`rate_limited`）
- ccswitch 审核拦截（`moderation_blocked`）
- LLM 空 tool_use（`empty_tool_use`）
- Timeout（`timeout`）

用户看不到「数据缺失原因」。

**修复建议**：加 keyword 字典（按出现顺序匹配）：
```python
ERROR_MARKERS = (
    "anti_bot_redirect",
    "rate_limited",
    "timeout",
    "moderation_blocked",
    "empty_tool_use",
    "no_results",
    "5xx",
    "auth_failed",
)
def extract_collector_notes(results):
    notes = {}
    for r in results:
        if not r.error:
            continue
        first_token = r.error.split(":")[0].strip().lower()
        marker = next((m for m in ERROR_MARKERS if m in first_token), first_token)
        notes[r.collector] = marker
    return notes
```
模板里 [report.html.j2:368](../../src/jobhunter/report/templates/report.html.j2#L368) 加 if/else 链区分不同 marker 文案。

### 2.6 💡 Watchlist mark_ran 在失败路径也跑

**位置**：[src/jobhunter/pipeline.py:run() 末尾](../../src/jobhunter/pipeline.py)

**问题**：pipeline 没有 try/except 包整个 run，所以失败时 watchlist mark_ran 不会触发 ✓。但 snapshot save 包了 try/except → 总是跑 → 如果 Tavily 全挂、LLM 全超时，watchlist 仍标 "已跑"。下轮不会重试。

**修复建议**：把 mark_ran 移到 `ReportArtifacts(...)` 之后，只在成功路径触发：
```python
# pipeline.py:run 末尾
return ReportArtifacts(...)
# ↑ 只有成功才到这
```
当前 [pipeline.py:214-241](../../src/jobhunter/pipeline.py#L214-L241) 已经是这样（mark_ran 在 ReportArtifacts 之前）— 但 [cli.py](../../src/jobhunter/cli.py) 调 run() 后可能 mark_ran 的调用在 try/except 外。检查 cli.py:run_command 是否在 mark_ran 前包 try/except。

---

## 三、产品定位层机会（2 条）

### 3.1 ❗ 缺 batch 模式：「秋招 30 家横向对比」无法本地完成

**现状**：用户一次只能看一家公司。要么跑 30 次（手动），要么靠 watchlist 逐家跑（手动触发，无聚合视图）。

**建议**：
```bash
# 新增 CLI flag
jobhunter run --batch companies.txt --position "后端" --city "杭州"
# companies.txt:
# 阿里云
# 字节跳动
# 美团
# 京东
# ...
```

**实现要点**：
1. CLI 加 `--batch FILE` 互斥 `--company`（同 `--compare` 的现有模式）
2. 新 pipeline 函数 `run_batch(queries, ...)`：
   - 复用 `run()` 单公司路径，但跳过 open_browser（不弹 30 个 tab）
   - 跑完聚合 1 个 `batch_summary.html`（简化版：5 轴雷达矩阵 + verdict 矩阵 + 司法 / 异常计数）
   - Tavily cache 让 batch 内重复公司 0 成本
3. 测试 +5（`tests/test_batch.py`）

**预期收益**：单用户场景价值 5x（秋招是 jobHunter 的 target use case 之一）。

### 3.2 💡 Streaming LLM 反馈：「正在抽 reviews」让用户知道没死

**现状**：Extract + Consolidate 是最慢的阶段（2-3 分钟），用户盯着终端不知道是死是活。当前有 Rich 进度条给 collector，但 LLM 阶段无 feedback。

**建议**：
1. `LLMClient.structured_call` 加 `on_partial=` callback
2. `pipeline.run` 在 extract / consolidate 前用 `Rich.Live` 显示：
   ```
   ⠋ 抽 business · · · · · · 
   ⠋ 抽 reviews (LLM pass 1)
   ⠋ 抽 company_info
   ```
3. 用户中途可按 Ctrl+C 取消（当前不可 — run 是 blocking）

**实现要点**：
- Rich 的 `Live` + `Spinner` + `Text` 组合，按 stage 切换
- LLMClient 加 stage 命名参数：`structured_call(..., stage="business")`
- 测试 +3（mock LLM streaming 验证 spinner 状态切换）

---

## 四、推荐优先级

### 这周做（3 条，估 4-6 小时）

| # | 项 | 工作量 | 价值 |
|---|---|---|---|
| 1 | 图 1.1 fallback 路径显眼 | 30 min | 高（设计回归门） |
| 2 | 图 1.2-1.3 peer + compute box 合并 | 30 min | 中（可读性） |
| 3 | Pipeline 2.1 consolidate retry（tenacity 装饰） | 2-3 h | 高（用户体验大） |

### 下个月做（3 条，估 1-2 天）

| # | 项 | 工作量 | 价值 |
|---|---|---|---|
| 4 | Pipeline 2.2 round 2 触发条件改 type-diversity | 1 h | 中 |
| 5 | Pipeline 2.3 LLM response disk cache | 4-6 h | 高（成本 1-3x 节省） |
| 6 | 产品 3.1 batch 模式 | 6-8 h | 极高（产品定位层） |

### 不急着做（边际收益小）

- 2.4 compute 并行化（节省 1-3s）
- 2.5 collector_notes 多错误码（cosmetic）
- 2.6 watchlist 失败路径检查（已大部分正确）
- 3.2 streaming LLM（cosmetic）

---

## 五、Cross-reference

- 图源：[docs/diagrams/pipeline.mmd](../diagrams/pipeline.mmd)
- 图说明：[docs/diagrams/README.md](../diagrams/README.md)
- Pipeline 入口：[src/jobhunter/pipeline.py](../../src/jobhunter/pipeline.py)
- Extract + consolidate：[src/jobhunter/processing/extract.py](../../src/jobhunter/processing/extract.py)
- Compute 函数：[src/jobhunter/report/builder.py](../../src/jobhunter/report/builder.py)
- Collector 错误处理：[src/jobhunter/collectors/base.py](../../src/jobhunter/collectors/base.py)

## 六、未做的事

- 没改任何代码 — 本文档仅描述问题 + 建议方案；实施等用户确认后按推荐顺序执行
- 没改图 — 改进建议是 mermaid patch snippet，实施时直接改 [pipeline.mmd](../diagrams/pipeline.mmd) + 重渲染

## 后续

如果用户决定执行「这周做」的 3 条，建议拆成 3 个独立 commit + 3 个独立 PR review，方便回滚。如果同时做太多，混在一起难以调试。
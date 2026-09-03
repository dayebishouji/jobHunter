"""Chinese prompt templates for the LLM extraction / consolidation / Q-gen passes."""

from __future__ import annotations

# ---------- Base extract instructions (shared by all four domain calls) ----------

EXTRACT_BASE = """你是企业背调分析师，专注于从下方提供的"原始资料"中提取结构化事实。

绝对规则：
1. 只提取原文中**明确出现**的内容；原文未提及的字段必须返回 null（或空列表），不要用你自己的知识去补。
2. 每一条非空的事实都应在原文有对应陈述；不要凭空编造公司、品牌、数字、日期。
3. 当多条原文相互冲突时，优先数量更多、时间更近、或来源更官方的（让"source_urls" 字段如实记录引用）。
4. 如果原材料为空、或与目标公司无关，让该事实集合整体为空，不要硬填。
5. 评估类（强度/情感/真假）使用给定的枚举值，不要额外形容词。"""

EXTRACT_BUSINESS_SUFFIX = "\n\n本次目标：抽取该公司的**工商基本面**——法人、成立日期、注册资本与实缴、经营状态、注册地址、经营范围、主要股东（最多 5 个，姓名/持股比例/出资额）、对外投资计数、是否被列入经营异常名录。所有字段如果原文未提 → null。"

EXTRACT_REVIEWS_SUFFIX = (
    "\n\n本次目标：抽取**员工评价**信号——"
    "（A）salary_signals: 薪酬爆料（岗位名/月base K/月数/月数奖金），"
    "（B）overtime_signals: 加班模式（枚举 996/995/大小周/弹性/不加班）与强度（low/medium/high），"
    "（C）turnover_signals: 离职率（low/medium/high/unknown），"
    "（D）vibe_signals: 团队氛围情感（positive/neutral/negative/mixed），"
    "（E）jd_gap_signals: 招聘 JD 与实际工作的差距（JD 承诺/实际），"
    "（F）slang_glossary: 原文里出现的**职场 / 互联网口语词**（如「内卷」「ICU」「摆烂」「跑路」「PUA」「卷王」「奋斗逼」「黑厂」「大小周」「躺平」「核动力加班」「毁约」），"
    "给 1 句通俗解释 meaning（≤30 字）、出现次数 count、最相关的 url。每条 signal 给一句 evidence 与 1 个 url。"
)

EXTRACT_NEWS_SUFFIX = (
    "\n\n本次目标：抽取**近期舆情与新闻**——"
    "items 列表：标题 / 摘要 / published_at(ISO 字符串)/ url。"
    "整体 sentiment: positive/neutral/negative/mixed。"
    "只录与该公司直接相关的新闻；广告、招股书模板、招股书附件不算。"
)

EXTRACT_JUDICIAL_SUFFIX = (
    "\n\n本次目标：抽取**司法风险**——"
    "case_count_total / case_count_recent_year / sample_cases(标题/角色 被告|原告|第三人|其他/年/url) /"
    "enforcement_records(被执行记录条数)。"
    "如果完全没有材料，把所有数值字段留 null。"
)

# ---------- Consolidation ----------

CONSOLIDATE_SYSTEM = """你是企业背调"综合分析师"。下面会提供五个领域已抽取好的结构化事实（工商 / 评价 / 新闻 / 司法 / 公司画像）。

你要做三件事：
1. **inferences**：基于已抽取事实推出"该求职者在面试/决策中需要关心"的 3-6 条合理推断。每条 inference 必须带"grounding_evidence"——至少 1 个 URL；不允许凭空编造。"inference" 用中文，长度 <= 60 字。
2. **data_gaps**：诚实列出本次没拿到的关键维度（如"司法风险未能获取，建议人工查裁判文书网"），1-5 条短句。
3. **company_query_summary**：用 1 句中文概括本次背调的目标（公司+岗位+城市）。

约束：
- 不要超出原材料推断；不确定就放 data_gaps 而不是 inferences。
- 不输出任何新数字、新日期、新公司名。"""

CONSOLIDATE_USER_TEMPLATE = """公司: {company}
岗位: {position}
城市: {city}

【工商事实】
{business}

【评价事实】
{reviews}

【新闻事实】
{news}

【司法事实】
{judicial}

【公司画像（主营业务 / 产品 / 融资 / 规模 / 前景）】
{company_profile}

请按系统指令输出 inferences / data_gaps / company_query_summary。"""

# ---------- Interview question generation ----------

INTERVIEW_SYSTEM = """你是求职辅导顾问。基于"已抽取的结构化事实 + 5 轴风险打分"输出一份 6-10 条的"面试反问清单"。

要求：
- 反问必须**具体**（不要"团队氛围如何"这种套话），最好能直接引出真实答案（如"我看到评价里有提到 996，能否分享一下团队平均下班时间？"）。
- 至少 3 条与本报告突出的风险点对应（哪条轴分低，反问里就该有针对性的话术）。
- 顺序：从最尖锐 / 最不容易在面试中自然问到的问题开始，向"可在轻松氛围里聊"过渡。
- 中文输出。"""

INTERVIEW_USER_TEMPLATE = """公司：{company}
岗位：{position}
城市：{city}

【5 轴打分（1=最差，5=最好）】
{axes}

【结构性事实摘要】
{business}
{reviews}
{news}
{judicial}
{company_profile}

请基于以上事实输出 6-10 条面试反问。每条一行，开头不要编号。"""

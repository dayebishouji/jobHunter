"""Anthropic SDK wrapper with `tool_use` structured output and cost guard."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from jobhunter.config import Settings
from jobhunter.llm.cache import LLMResponseCache
from jobhunter.utils.retry import llm_retry as _retry_builder

logger = logging.getLogger(__name__)

# Approximate USD per million tokens for Sonnet 4.5 (Sept 2026).
_PRICE_INPUT_PER_M = 3.0
_PRICE_OUTPUT_PER_M = 15.0

# Schema used by get_company_aliases(). Inline to avoid a separate file.
_ALIASES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "aliases": {
            "type": "array",
            "items": {"type": "string"},
            "description": "常见缩写 / 英文名 / 子品牌（不含全称本身）",
            "maxItems": 3,
        }
    },
    "required": ["aliases"],
}

# Schema used by list_workplace_slang(). Pulls colloquial recall terms.
_SLANG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "slang_queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "打工人口语化搜索词(2-4 字短语,最多 8 个)",
            "maxItems": 8,
        }
    },
    "required": ["slang_queries"],
}

# Schema used by list_company_entities(). Surfaces internal entity names
# (products / sub-brands / departments / founders) so round-2 sub-queries can
# widen recall without drifting off-topic.
_ENTITIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "公司内部实体（产品名 / 子品牌 / 部门 / 创始人 / 业务线）",
            "maxItems": 5,
        }
    },
    "required": ["entities"],
}


class LLMClient:
    """Async Anthropic client with structured-output and budget tracking."""

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self._settings = settings
        kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._tokens_in = 0
        self._tokens_out = 0
        self._budget_blocked = False
        self._retry = _retry_builder(settings)
        # v0.2.2 — disk-backed cache for structured_call responses. Default ON;
        # disable via JOBHUNTER_LLM_CACHE_ENABLED=false in .env.
        self._cache = LLMResponseCache(
            ttl_hours=settings.cache_ttl_hours,
            enabled=settings.llm_cache_enabled,
        )

    # ---------- bookkeeping ----------

    @property
    def tokens_in(self) -> int:
        return self._tokens_in

    @property
    def tokens_out(self) -> int:
        return self._tokens_out

    @property
    def cost_usd(self) -> float:
        return (self._tokens_in / 1_000_000) * _PRICE_INPUT_PER_M + (
            self._tokens_out / 1_000_000
        ) * _PRICE_OUTPUT_PER_M

    def budget_ok(self) -> bool:
        return not self._budget_blocked

    # ---------- primary API ----------

    async def chat(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Plain chat (no tool_use). Used for free-text interview-question generation."""
        if not self.budget_ok():
            return ""
        kwargs = dict(
            model=model or self._settings.model,
            max_tokens=max_tokens or self._settings.max_tokens_per_call,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        async def _do() -> Any:
            return await self._client.messages.create(**kwargs)

        response = await self._retry(_do)
        self._tokens_in += response.usage.input_tokens
        self._tokens_out += response.usage.output_tokens
        if self._tokens_in + self._tokens_out > self._settings.budget_tokens_per_run:
            self._budget_blocked = True
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return ""

    async def structured_call(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        model: str | None = None,
        max_tokens: int | None = None,
        retry_policy: str = "default",
    ) -> dict[str, Any]:
        """Send the user message, force the named tool call, and return the parsed input dict.

        On budget exhaustion: returns `{}` without calling the API.
        On a normal completion: returns the tool's input as a dict.

        `retry_policy`:
          - "default" — uses `llm_retry()` (3 attempts, 1-10s backoff)
          - "strict"  — uses `llm_retry_strict()` (≥3 attempts, 1-20s backoff)
            Use for cross-domain synthesis where fallback can't reproduce the value.
        """
        if not self.budget_ok():
            logger.warning("LLM budget exhausted; returning empty result for %s", tool_name)
            return {}

        # v0.2.2 — cache check BEFORE constructing the LLM kwargs. A hit skips
        # the entire API call (no tokens_in/out charged, no retry). Cache key
        # includes system + user + tool_name so different extraction schemas
        # or models don't collide.
        cached = self._cache.get(system, user, tool_name)
        if cached is not None:
            logger.debug("llm cache hit: %s", tool_name)
            return cached

        kwargs = dict(
            model=model or self._settings.model,
            max_tokens=max_tokens or self._settings.max_tokens_per_call,
            system=system,
            tools=[
                {
                    "name": tool_name,
                    "description": tool_description,
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )

        async def _do_call() -> Any:
            return await self._client.messages.create(**kwargs)

        if retry_policy == "strict":
            from jobhunter.utils.retry import llm_retry_strict as _strict_retry
            retry = _strict_retry(self._settings)
        else:
            retry = self._retry

        # v0.3.2 hotfix — B: retry on "no tool_use block" responses.
        # ccswitch / relay sometimes returns plain text instead of a tool_use
        # block — this isn't an exception so tenacity's exception-based retry
        # doesn't fire. Wrap the call with an explicit retry loop that
        # detects text-only responses and re-prompts. The default policy
        # retries twice; strict retries once (tenacity handles transport
        # retries separately).
        import asyncio as _asyncio
        max_text_retries = 1 if retry_policy == "strict" else 2
        response = None
        for _attempt in range(max_text_retries + 1):
            response = await retry(_do_call)

            # Bookkeeping (counted on every attempt)
            self._tokens_in += response.usage.input_tokens
            self._tokens_out += response.usage.output_tokens
            if self._tokens_in + self._tokens_out > self._settings.budget_tokens_per_run:
                self._budget_blocked = True

            # Did we get a tool_use block?
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    payload = block.input
                    if payload:
                        self._cache.set(system, user, tool_name, payload)
                    return payload

            # No tool_use. Surface what we got and decide whether to retry.
            block_types = [getattr(b, "type", "?") for b in response.content]
            stop_reason = getattr(response, "stop_reason", "?")
            if _attempt < max_text_retries:
                logger.warning(
                    "No tool_use block for %s (got block types=%s, stop_reason=%s); retrying (%d/%d)",
                    tool_name, block_types, stop_reason,
                    _attempt + 1, max_text_retries,
                )
                await _asyncio.sleep(1.5 * (_attempt + 1))  # 1.5s, 3s
                continue
            # Out of retries — log final failure
            logger.warning(
                "No tool_use block for %s (got block types=%s, stop_reason=%s); returning empty after %d attempts",
                tool_name, block_types, stop_reason, max_text_retries + 1,
            )
        return {}


def to_json_schema(model_cls: type) -> dict[str, Any]:
    """Pydantic → JSON Schema for `tool_use.input_schema`."""
    schema = model_cls.model_json_schema()
    # Anthropic requires top-level "type": "object"; some Pydantic versions omit it for primitives.
    schema.setdefault("type", "object")
    return schema


async def list_company_aliases(
    llm: "LLMClient", company_name: str
) -> list[str]:
    """Ask LLM for 1-3 common abbreviations / English names / sub-brands
    that 打工人 might use when referring to this company. Returns [] on failure
    or if the budget is exhausted. Used to expand reviews-domain queries beyond
    strict exact-match quotes."""
    if not company_name.strip():
        return []
    raw = await llm.structured_call(
        system=(
            "你是中文公司别名专家。给定一个中国公司全称，列出最多 3 个打工人日常可能用的"
            "**简称 / 英文名 / 子品牌**（如「阿里巴巴集团」→「阿里」「Alibaba」「淘宝」）。"
            "不要返回公司全称本身。只返回在 UGC 帖子中真正常见的别名；不确定就少给。"
        ),
        user=f"公司全称：{company_name}",
        tool_name="list_company_aliases",
        tool_description="列出常见简称 / 英文名 / 子品牌",
        tool_schema=_ALIASES_SCHEMA,
    )
    if not raw or not isinstance(raw.get("aliases"), list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for a in raw["aliases"]:
        s = str(a).strip()
        if s and s != company_name and s not in seen and len(s) <= 50:
            seen.add(s)
            out.append(s)
    return out[:3]


async def list_workplace_slang(
    llm: "LLMClient", company_name: str, position: str = ""
) -> list[str]:
    """Ask LLM for 5-8 colloquial search terms that 打工人 use in UGC posts
    when reviewing / complaining about a company. These widen reviews-domain
    recall beyond literal terms like '加班' or '薪资'.

    Examples of the kind of term we want: 「内卷」「ICU」「摆烂」「跑路」
    「PUA」「卷王」「毁约」「黑厂」「核动力加班」「奋斗逼」.

    Returns [] on failure or budget exhaustion.
    """
    if not company_name.strip():
        return []
    pos_hint = f"（岗位：{position}）" if position and position.strip() else ""
    raw = await llm.structured_call(
        system=(
            "你是中文职场 UGC 召回词专家。给定一家中国公司，给出 5-8 个打工人讨论该公司"
            "时常用的**口语化 / 网络化短语**，用作搜索引擎查询词提升 UGC 召回。\n\n"
            "硬性要求：\n"
            "1. **每个词 2-6 字**，且**不得包含公司名 / 别名 / 英文名** — 只返回纯 slang。"
            "（如果公司叫「有赞」，返回「内卷」而不是「有赞内卷」。）\n"
            "2. 优先选跟「加班强度 / 薪酬福利 / 团队氛围 / 离职意愿 / 管理风格 / 黑历史」"
            "相关的口语化表达，例如「内卷」「ICU」「摆烂」「跑路」「PUA」「卷王」"
            "「奋斗逼」「黑厂」「毁约」「大小周」「躺平」「核动力加班」「钱少事多」。\n"
            "3. 不要放通用词（不要返回「公司」「工作」「员工」这种无信息量的词）。\n"
            "4. 不确定就少给，宁缺勿滥；最多 8 个。"
        ),
        user=f"公司：{company_name}{pos_hint}",
        tool_name="list_workplace_slang",
        tool_description="列出打工人讨论该公司时常用的口语化 / 网络化短语",
        tool_schema=_SLANG_SCHEMA,
    )
    if not raw or not isinstance(raw.get("slang_queries"), list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for s in raw["slang_queries"]:
        t = str(s).strip()
        if t and t not in seen and 2 <= len(t) <= 12:
            seen.add(t)
            out.append(t)
    return out[:8]


async def list_company_entities(
    llm: "LLMClient",
    company_name: str,
    raw_items: list,
    *,
    max_items: int = 5,
) -> list[str]:
    """Round-2 sub-query seed extraction. Given the first round's raw items
    (typically reviews), ask LLM to surface 3-5 internal entities
    (产品名 / 子品牌 / 部门 / 创始人 / 业务线) strictly belonging to *company_name*.

    These become aliases for a second round of reviews queries — the goal is
    to widen recall for niche teams / products that 打工人 reference by an
    internal name rather than the company name itself (e.g. 「菜鸟」「钉钉」).

    Returns [] on failure or budget exhaustion. The caller is expected to
    further filter against already-known aliases (e.g. remove duplicates).
    """
    from jobhunter.processing.extract import _materialize
    from jobhunter.llm.prompts import ENTITY_EXTRACTION_PROMPT

    if not company_name.strip() or not raw_items:
        return []
    # Use a tight slice — entity extraction only needs the top hits, not
    # the full 50K materialization. 8K is plenty for the LLM to spot names.
    snippet = _materialize(raw_items[:30])[:8000]
    raw = await llm.structured_call(
        system=ENTITY_EXTRACTION_PROMPT.format(company=company_name),
        user=f"原始资料：\n\n{snippet}",
        tool_name="list_company_entities",
        tool_description="从原材料抽取公司内部实体（产品/品牌/部门/创始人）",
        tool_schema=_ENTITIES_SCHEMA,
    )
    # Fallback: ccswitch / Anthropic relay sometimes returns plain text instead
    # of a tool_use block. Try to parse {"entities": [...]} from the text.
    if not raw and isinstance(llm, object):
        try:
            text = await llm.chat(
                system=ENTITY_EXTRACTION_PROMPT.format(company=company_name),
                user=f"原始资料：\n\n{snippet}\n\n只返回 JSON: {{\"entities\": [...]}}",
            )
            import re as _re
            m = _re.search(r"\{.*?\}", text, _re.DOTALL)
            if m:
                raw = json.loads(m.group(0))
        except Exception:  # noqa: BLE001 - best-effort
            pass
    if not raw or not isinstance(raw.get("entities"), list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for e in raw["entities"]:
        t = str(e).strip()
        if t and t not in seen and t != company_name and 2 <= len(t) <= 12:
            seen.add(t)
            out.append(t)
    return out[:max_items]


def safe_dumps(d: dict[str, Any]) -> str:
    """JSON dump with UTF-8, failsafe."""
    return json.dumps(d, ensure_ascii=False, indent=2)

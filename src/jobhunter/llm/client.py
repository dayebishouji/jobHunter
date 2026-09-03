"""Anthropic SDK wrapper with `tool_use` structured output and cost guard."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from jobhunter.config import Settings
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
    ) -> dict[str, Any]:
        """Send the user message, force the named tool call, and return the parsed input dict.

        On budget exhaustion: returns `{}` without calling the API.
        On a normal completion: returns the tool's input as a dict.
        """
        if not self.budget_ok():
            logger.warning("LLM budget exhausted; returning empty result for %s", tool_name)
            return {}

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

        response = await self._retry(_do_call)

        # Bookkeeping
        self._tokens_in += response.usage.input_tokens
        self._tokens_out += response.usage.output_tokens
        if self._tokens_in + self._tokens_out > self._settings.budget_tokens_per_run:
            self._budget_blocked = True

        # Find the tool_use block
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input

        # Some ccswitch / relay responses lose tool_use blocks. Surface what we
        # actually got so the user can diagnose (e.g., relay returned text instead).
        block_types = [getattr(b, "type", "?") for b in response.content]
        stop_reason = getattr(response, "stop_reason", "?")
        logger.warning(
            "No tool_use block for %s (got block types=%s, stop_reason=%s); returning empty",
            tool_name, block_types, stop_reason,
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


def safe_dumps(d: dict[str, Any]) -> str:
    """JSON dump with UTF-8, failsafe."""
    return json.dumps(d, ensure_ascii=False, indent=2)

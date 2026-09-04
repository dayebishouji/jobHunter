"""LLM layer — Anthropic wrapper, Chinese prompts, tool schemas."""

from jobhunter.llm.client import (
    LLMClient,
    list_company_aliases,
    list_company_entities,
    list_workplace_slang,
    safe_dumps,
    to_json_schema,
)
from jobhunter.llm.prompts import (
    CONSOLIDATE_SYSTEM,
    CONSOLIDATE_USER_TEMPLATE,
    ENTITY_EXTRACTION_PROMPT,
    EXTRACT_BASE,
    EXTRACT_BUSINESS_SUFFIX,
    EXTRACT_COMPANY_PROFILE_SUFFIX,
    EXTRACT_JUDICIAL_SUFFIX,
    EXTRACT_NEWS_SUFFIX,
    EXTRACT_REVIEWS_SUFFIX,
    INTERVIEW_SYSTEM,
    INTERVIEW_USER_TEMPLATE,
)
from jobhunter.llm.schemas import extract_tool_spec

__all__ = [
    "CONSOLIDATE_SYSTEM",
    "CONSOLIDATE_USER_TEMPLATE",
    "ENTITY_EXTRACTION_PROMPT",
    "EXTRACT_BASE",
    "EXTRACT_BUSINESS_SUFFIX",
    "EXTRACT_COMPANY_PROFILE_SUFFIX",
    "EXTRACT_JUDICIAL_SUFFIX",
    "EXTRACT_NEWS_SUFFIX",
    "EXTRACT_REVIEWS_SUFFIX",
    "INTERVIEW_SYSTEM",
    "INTERVIEW_USER_TEMPLATE",
    "LLMClient",
    "extract_tool_spec",
    "list_company_aliases",
    "list_company_entities",
    "list_workplace_slang",
    "safe_dumps",
    "to_json_schema",
]

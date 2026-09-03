"""Tool definitions and model→schema helpers for Anthropic `tool_use`."""

from __future__ import annotations

from jobhunter.llm.client import LLMClient, to_json_schema
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CompanyProfile,
    JudicialFacts,
    NewsFacts,
    ReviewFacts,
)

# Each tuple: (model_class, tool_name, description)
_EXTRACT_TOOLS: list[tuple[type, str, str]] = [
    (
        BusinessFacts,
        "record_business_facts",
        "把原材料里关于该公司工商基本面的事实，整理成结构化记录。字段缺失就 null。",
    ),
    (
        ReviewFacts,
        "record_review_facts",
        "把原材料里关于该公司员工评价（薪酬/加班/离职/氛围/JD差距）的信号，整理成结构化记录。",
    ),
    (
        NewsFacts,
        "record_news_facts",
        "把原材料里与该公司直接相关的近期舆情与新闻，整理成结构化记录。",
    ),
    (
        JudicialFacts,
        "record_judicial_facts",
        "把原材料里关于该公司涉诉与被执行的司法数据，整理成结构化记录。",
    ),
    (
        CompanyProfile,
        "record_company_profile",
        "把原材料里关于该公司画像（主营业务 / 产品 / 行业 / 融资阶段 / 规模 / 总部 / 发展前景）的信息，整理成结构化记录。",
    ),
    (
        AggregatedFindings,
        "record_aggregated_findings",
        "把四个领域的事实合并成综合发现，包括 inferences（合理推断）与 data_gaps（数据缺口）。",
    ),
]


def extract_tool_spec(domain: str) -> dict:
    """Return one tool-spec dict for a domain ('business'|'reviews'|'news'|'judicial'|'company_info'|'aggregate')."""
    key_to_idx = {
        "business": 0,
        "reviews": 1,
        "news": 2,
        "judicial": 3,
        "company_info": 4,
        "aggregate": 5,
    }
    idx = key_to_idx[domain]
    _, name, desc = _EXTRACT_TOOLS[idx]
    model = [t[0] for t in _EXTRACT_TOOLS][idx]
    return {
        "name": name,
        "description": desc,
        "input_schema": to_json_schema(model),
    }


__all__ = ["LLMClient", "extract_tool_spec", "to_json_schema"]

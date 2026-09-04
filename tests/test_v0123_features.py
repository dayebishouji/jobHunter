"""v0.1.23 — Loose keyword fallback must run even when LLM extraction fails.

Bug discovered when re-running 美的 / 美团 / 字节跳动 after v0.1.22 hotfix:
the recall phase worked (cache had 100+ workplace URLs per company) but the
final reports章 was empty because `_loose_keyword_reviews()` was gated by
`isinstance(rf, ReviewFacts)` — when the LLM extraction step returned None
(ccswitch moderation, transient API error, or empty tool_use block), `rf`
became None and the fallback was silently skipped. Result: the chapter
rendered "暂无薪酬爆料" even though the raw bucket had dozens of workplace
URLs whose snippets contained 996 / 加班 / 月薪 / 内卷 etc.

The fix removes the isinstance gate; the fallback now runs whenever there
are raw review items, and uses loose-only output when LLM extraction failed
entirely.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.raw import RawItem
from jobhunter.models.facts import ReviewFacts
from jobhunter.processing.extract import extract_all_domains


def _item(url: str, title: str, snippet: str) -> RawItem:
    return RawItem(
        source="tavily:web",
        url=url,
        title=title,
        snippet=snippet,
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
    )


class _NoopLLM:
    """Mock LLM that returns None for every structured_call (simulates
    ccswitch moderation / transient API failure / empty tool_use block)."""

    async def structured_call(self, **kwargs):
        return None


@pytest.mark.asyncio
async def test_loose_keyword_fallback_runs_when_llm_returns_none():
    """v0.1.23 bug fix — even when LLM extraction fails entirely, the local
    keyword scan must synthesize signals from the raw snippets."""
    items = [
        _item("https://www.nowcoder.com/discuss/123", "面试经验",
              "美团后端面试三轮技术 + 一轮HR，996是常态，月薪25k"),
        _item("https://maimai.cn/article/detail?fid=1", "在职体验",
              "团队氛围不错，技术氛围浓厚，弹性工作不加班"),
        _item("https://www.zhihu.com/question/456", "离职感受",
              "部门内卷严重，离职率高，领导PUA"),
    ]
    buckets = {
        "business": [], "judicial": [], "news": [], "company_info": [],
        "reviews": items,
    }

    out = await extract_all_domains(_NoopLLM(), buckets)
    rf = out.get("reviews")

    # LLM returned None, but loose keyword fallback should have populated
    # at least one signal category from the raw snippets.
    assert rf is not None, "reviews facet must not be None when raw items exist"
    assert isinstance(rf, ReviewFacts)
    # Total signals across all categories must be > 0
    total = (
        len(rf.salary_signals) + len(rf.overtime_signals)
        + len(rf.vibe_signals) + len(rf.turnover_signals)
    )
    assert total > 0, (
        "v0.1.23 bug: loose keyword fallback did not run despite raw items"
    )


@pytest.mark.asyncio
async def test_loose_keyword_fallback_augments_thin_llm_result():
    """When LLM returns a valid ReviewFacts but with few signals, the loose
    fallback should add its keyword hits without losing the LLM's output."""
    from jobhunter.models.facts import SalarySignal, VibeSignal

    llm_rf = ReviewFacts(
        salary_signals=[SalarySignal(
            evidence="LLM found this salary datapoint",
            url="https://example.com/llm",
        )],
        vibe_signals=[VibeSignal(sentiment="positive", evidence="LLM vibe")],
    )

    class _StubLLM:
        async def structured_call(self, *, system, user, tool_name, tool_description, tool_schema, **_):
            # Return only when reviews extraction is called; return None for others
            if "record_review_facts" in tool_name or "reviews" in tool_name.lower():
                return llm_rf.model_dump(mode="json")
            return None

    items = [
        _item("https://example.com/keyword", "keyword hit",
              "996加班严重，月薪30k"),
    ]
    buckets = {
        "business": [], "judicial": [], "news": [], "company_info": [],
        "reviews": items,
    }

    out = await extract_all_domains(_StubLLM(), buckets)
    rf = out.get("reviews")
    assert rf is not None
    # LLM's original signals preserved
    assert any("LLM" in s.evidence for s in rf.salary_signals)
    # Loose keyword may add overtime hits (996) — don't lose the existing data
    assert len(rf.vibe_signals) >= 1  # LLM's original


@pytest.mark.asyncio
async def test_no_loose_signals_when_no_keywords_present():
    """When raw snippets contain no workplace keywords, the loose fallback
    produces an empty ReviewFacts — and that empty result should not pollute
    the LLM's output (or, when LLM failed, become a near-empty facet)."""
    items = [
        _item("https://example.com/menu", "Menu navigation",
              "Home About Login"),
        _item("https://example.com/ad", "Ad page",
              "Click here for special offer"),
    ]
    buckets = {
        "business": [], "judicial": [], "news": [], "company_info": [],
        "reviews": items,
    }

    out = await extract_all_domains(_NoopLLM(), buckets)
    rf = out.get("reviews")
    # No keywords → no signals → may still emit empty ReviewFacts (that's OK;
    # builder renders the standard "暂无" message in this case).
    if rf is not None:
        total = (
            len(rf.salary_signals) + len(rf.overtime_signals)
            + len(rf.vibe_signals) + len(rf.turnover_signals)
        )
        assert total == 0

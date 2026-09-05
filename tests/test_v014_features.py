"""Tests for v0.1.14: reviews density boost (two-pass + loose keyword), judicial
chapter negative-finding reframe, fact-driven interview questions, expanded
company_info allowlist."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.facts import (
    BusinessFacts,
    CaseItem,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.pipeline import _fact_driven_interview_questions
from jobhunter.processing.extract import (
    _loose_keyword_reviews,
    _merge_reviews,
    _reviews_signal_count,
    _round2_worthwhile,
    Round2TriggerReason,
)
from jobhunter.report.builder import build_report
from jobhunter.search.query_templates import (
    COMPANY_INFO_DOMAINS,
    company_info_queries,
    domains_for_position,
)


def _item(url: str, snippet: str, title: str = "title") -> RawItem:
    return RawItem(
        source="tavily:web",
        url=url,
        title=title,
        snippet=snippet,
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
        payload={},
    )


def _q() -> CompanyQuery:
    return CompanyQuery(company="TestCo", position="后端", city="杭州")


class TestLooseKeywordReviews:
    """Pure-local synthesis from raw snippets — no LLM call."""

    def test_empty_items_returns_empty_facts(self):
        rf = _loose_keyword_reviews([])
        assert rf.overtime_signals == []
        assert rf.vibe_signals == []
        assert rf.salary_signals == []
        assert rf.turnover_signals == []

    def test_996_keyword_yields_high_overtime(self):
        rf = _loose_keyword_reviews([
            _item("https://maimai.cn/a/1", "工作 996 是日常，加班严重"),
        ])
        assert len(rf.overtime_signals) == 1
        assert rf.overtime_signals[0].intensity == "high"

    def test_vibe_negative_keyword(self):
        rf = _loose_keyword_reviews([
            _item("https://zhihu.com/q/1", "团队内卷严重，氛围PUA，跑路"),
        ])
        assert len(rf.vibe_signals) == 1
        assert rf.vibe_signals[0].sentiment == "negative"

    def test_vibe_positive_keyword(self):
        rf = _loose_keyword_reviews([
            _item("https://zhihu.com/q/2", "团队氛围融洽，同事关系好"),
        ])
        assert len(rf.vibe_signals) == 1
        assert rf.vibe_signals[0].sentiment == "positive"

    def test_salary_keyword_without_number_is_still_flagged(self):
        # We never invent numbers — only flag the keyword presence.
        rf = _loose_keyword_reviews([
            _item("https://zhihu.com/q/3", "月薪 30K，base 28k"),
        ])
        assert len(rf.salary_signals) == 1
        assert rf.salary_signals[0].base_monthly_k is None  # never invent

    def test_caps_per_category(self):
        items = [_item(f"https://x.com/{i}", f"996 加班严重 #{i}") for i in range(10)]
        rf = _loose_keyword_reviews(items)
        assert len(rf.overtime_signals) <= 3  # capped

    def test_no_keyword_yields_no_signals(self):
        rf = _loose_keyword_reviews([
            _item("https://x.com", "今天天气不错"),
        ])
        assert rf.overtime_signals == []
        assert rf.vibe_signals == []
        assert rf.salary_signals == []


class TestRound2Worthwhile:
    """v0.2.2 — strict type-diversity trigger (≤ 1 of 4 core signal types).

    Pre-v0.2.2 used `nonzero_types <= 2 OR total_signals < 3`; v0.2.2
    simplifies to "0 or 1 of the 4 core types have signals → trigger".
    Auxiliary types (jd_gap, slang) do NOT count toward diversity.
    """

    def test_none_returns_no_first_pass(self):
        should, reason = _round2_worthwhile(None)
        assert should is True
        assert reason is Round2TriggerReason.NO_FIRST_PASS

    def test_empty_review_facts_returns_no_first_pass(self):
        # An empty ReviewFacts() is still truthy (it's an instance), so it
        # goes through the type-diversity path — 0 distinct core types → trigger.
        should, reason = _round2_worthwhile(ReviewFacts())
        assert should is True
        assert reason is Round2TriggerReason.SIGNAL_TYPES_LOW

    def test_full_reviews_does_not_need_second_pass(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0)],
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")],
            vibe_signals=[VibeSignal(sentiment="positive")],
            turnover_signals=[],
            jd_gap_signals=[],
        )
        should, reason = _round2_worthwhile(rf)
        assert should is False
        assert reason is Round2TriggerReason.NOT_TRIGGERED

    def test_single_type_only_needs_second_pass(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0)],
        )
        should, reason = _round2_worthwhile(rf)
        assert should is True
        assert reason is Round2TriggerReason.SIGNAL_TYPES_LOW

    def test_two_distinct_core_types_does_not_trigger(self):
        """2 salary + 2 overtime signals but 0 vibe / turnover → NOT triggered.

        v0.2.2 — this used to trigger under the old `nonzero_types <= 2`
        + `total_signals < 3` heuristic (total_signals=4 ≥ 3 but
        nonzero_types=2 ≤ 2, so the OR clause fired). Now it doesn't trigger
        because distinct_core_types = 2, which is healthy.
        """
        rf = ReviewFacts(
            salary_signals=[
                SalarySignal(position="p", base_monthly_k=30.0),
                SalarySignal(position="q", base_monthly_k=35.0),
            ],
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="995", intensity="medium"),
            ],
        )
        should, reason = _round2_worthwhile(rf)
        assert should is False
        assert reason is Round2TriggerReason.NOT_TRIGGERED

    def test_only_auxiliary_types_does_not_trigger(self):
        """Only jd_gap / slang filled → 0 distinct core → SHOULD trigger."""
        rf = ReviewFacts(
            jd_gap_signals=[],
            slang_glossary=[],
        )
        should, reason = _round2_worthwhile(rf)
        assert should is True
        assert reason is Round2TriggerReason.SIGNAL_TYPES_LOW


class TestMergeReviews:
    """Dedup by url when second-pass yields duplicates."""

    def test_dedup_by_url(self):
        first = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0, url="https://x.com/a")],
        )
        # Same url → should not double-count
        second = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=31.0, url="https://x.com/a")],
        )
        merged = _merge_reviews(first, second)
        assert len(merged.salary_signals) == 1

    def test_new_url_appended(self):
        first = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0, url="https://x.com/a")],
        )
        second = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=31.0, url="https://x.com/b")],
        )
        merged = _merge_reviews(first, second)
        assert len(merged.salary_signals) == 2


class TestReviewSignalCount:
    """Sanity for the signal-count helper."""

    def test_counts_all_categories(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=30.0)],
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")],
            vibe_signals=[VibeSignal(sentiment="positive"), VibeSignal(sentiment="negative")],
        )
        c = _reviews_signal_count(rf)
        assert c == {"salary": 1, "overtime": 1, "vibe": 2, "turnover": 0, "jd_gap": 0, "slang": 0}


class TestFactDrivenInterviewQuestions:
    """Deterministic fact-grounded questions."""

    def test_empty_findings_no_questions(self):
        qs = _fact_driven_interview_questions(_q(), None)
        assert qs == []

    def test_judicial_with_cases_yields_question(self):
        j = JudicialFacts(
            case_count_total=3,
            sample_cases=[CaseItem(title="劳动合同", role="被告", year=2024)],
        )
        qs = _fact_driven_interview_questions(_q(), _agg(judicial=j))
        assert any("劳动合同" in q for q in qs)

    def test_salary_spread_yields_question(self):
        rf = ReviewFacts(
            salary_signals=[
                SalarySignal(position="后端", base_monthly_k=10.0),
                SalarySignal(position="后端", base_monthly_k=25.0),
            ]
        )
        qs = _fact_driven_interview_questions(_q(), _agg(reviews=rf))
        assert any("薪酬" in q or "定级" in q for q in qs)

    def test_heavy_overtime_yields_question(self):
        rf = ReviewFacts(
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="996", intensity="high"),
            ]
        )
        qs = _fact_driven_interview_questions(_q(), _agg(reviews=rf))
        assert any("加班" in q or "下班" in q for q in qs)

    def test_anomaly_listed_yields_question(self):
        bf = BusinessFacts.model_validate({
            "legal_rep": "张三",
            "anomaly_listed": True,
        })
        qs = _fact_driven_interview_questions(_q(), _agg(business=bf))
        assert any("经营异常" in q for q in qs)

    def test_funding_stage_yields_question(self):
        from jobhunter.models.facts import CompanyProfile
        cp = CompanyProfile.model_validate({"funding_stage": "B 轮"})
        qs = _fact_driven_interview_questions(_q(), _agg(company_profile=cp))
        assert any("融资" in q for q in qs)

    def test_listed_yields_no_funding_question(self):
        from jobhunter.models.facts import CompanyProfile
        cp = CompanyProfile.model_validate({"funding_stage": "已上市"})
        qs = _fact_driven_interview_questions(_q(), _agg(company_profile=cp))
        # Already public → no funding-round question
        assert not any("下一轮融资" in q for q in qs)

    def test_cap_at_five(self):
        # Construct a findings with all triggers
        from jobhunter.models.facts import AggregatedFindings, CompanyProfile
        j = JudicialFacts(case_count_total=5, sample_cases=[CaseItem(title="劳动争议", role="被告", year=2023)])
        rf = ReviewFacts(
            salary_signals=[SalarySignal(base_monthly_k=10.0), SalarySignal(base_monthly_k=25.0)],
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="996", intensity="high"),
            ],
            vibe_signals=[VibeSignal(sentiment="negative")],
        )
        nf = NewsFacts.model_validate({
            "items": [{"title": "坏新闻", "url": "https://x.com", "published_at": "2026-09-01"}],
            "sentiment": "negative",
        })
        bf = BusinessFacts.model_validate({"anomaly_listed": True})
        cp = CompanyProfile.model_validate({"funding_stage": "B 轮"})
        findings = AggregatedFindings(judicial=j, reviews=rf, news=nf, business=bf, company_profile=cp)
        qs = _fact_driven_interview_questions(_q(), findings)
        assert len(qs) <= 5


def _agg(
    business=None,
    reviews=None,
    news=None,
    judicial=None,
    company_profile=None,
):
    from jobhunter.models.facts import AggregatedFindings
    return AggregatedFindings(
        business=business,
        reviews=reviews,
        news=news,
        judicial=judicial,
        company_profile=company_profile,
    )


class TestJudicialChapterReframe:
    """v0.2.0 — Judicial chapter positive-finding reframe for case_count=0,
    uses broker-blue tinted takeaway + data-table for nonzero."""

    def test_zero_judicial_renders_negative_finding(self):
        from jobhunter.models.report import ReportData
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=JudicialFacts(case_count_total=0, enforcement_records=0),
        )
        html = build_report(data)
        assert "公开记录中未发现诉讼或被执行" in html
        assert "chapter-takeaway-good" in html

    def test_no_judicial_renders_manual_check(self):
        from jobhunter.models.report import ReportData
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=None,
        )
        html = build_report(data)
        assert "裁判文书网" in html

    def test_nonzero_judicial_renders_data_table(self):
        from jobhunter.models.report import ReportData
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=JudicialFacts(case_count_total=10),
        )
        html = build_report(data)
        # v0.2.0 — year buckets rendered in a research-report data-table
        assert "data-table" in html
        assert "诉讼数" in html
        assert "chapter-takeaway-bad" in html  # red-bordered takeaway for nonzero


class TestCompanyInfoAllowlist:
    """v0.1.14 expanded company_info domains."""

    def test_huxiu_in_allowlist(self):
        assert "huxiu.com" in COMPANY_INFO_DOMAINS

    def test_36kr_in_allowlist(self):
        assert "36kr.com" in COMPANY_INFO_DOMAINS

    def test_lieyunwang_in_allowlist(self):
        assert "lieyunwang.com" in COMPANY_INFO_DOMAINS

    def test_queries_include_site_specific(self):
        qs = company_info_queries(_q())
        joined = "\n".join(qs)
        assert "site:36kr.com" in joined
        assert "site:huxiu.com" in joined

    def test_domains_for_position_unchanged(self):
        # Make sure we didn't accidentally regress the cost-control allowlist
        d = domains_for_position("后端")
        # 后端 should map to general + developer; not cross-border or medical
        assert "maimai.cn" in d
        assert "kanzhun.com" in d
        # cross-border is position-keyword gated
        joined = " ".join(d)
        assert "kjxb" not in joined  # 后端 doesn't trigger 跨境
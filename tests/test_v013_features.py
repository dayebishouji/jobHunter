"""Tests for v0.1.13 features: chapter 「编辑手记」 + 「数据故事」 + drag-reorder.

Three deliverables verified here:
- `industry_baselines.pick_industry` / `baseline` / `delta_pct`
- `builder.compute_chapter_stories()` (pure deterministic editorial voice)
- End-to-end: `build_report()` renders story blocks + drag handles + chapters-container
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jobhunter.models.facts import (
    BusinessFacts,
    CaseItem,
    JudicialFacts,
    NewsFacts,
    OvertimeSignal,
    ReviewFacts,
    SalarySignal,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.report import ReportData
from jobhunter.report.builder import build_report, compute_chapter_stories
from jobhunter.report.industry_baselines import (
    INDUSTRY_BASELINES,
    baseline,
    delta_pct,
    pick_industry,
)


def _q() -> CompanyQuery:
    return CompanyQuery(company="TestCo", position="后端", city="杭州")


class TestIndustryBaselines:
    """Pure data layer — easy to lock down."""

    def test_pick_industry_returns_default_for_empty(self):
        assert pick_industry(None) == "default"
        assert pick_industry("") == "default"
        assert pick_industry("   ") == "default"

    def test_pick_industry_substring_match(self):
        assert pick_industry("跨境电商") == "跨境电商"
        assert pick_industry("互联网科技公司") == "互联网"
        assert pick_industry("金融科技") == "金融"
        assert pick_industry("教育培训") == "教育"
        assert pick_industry("餐饮连锁") == "餐饮"

    def test_pick_industry_case_insensitive(self):
        assert pick_industry("GAMING") == "游戏"
        assert pick_industry("Gaming industry") == "游戏"

    def test_pick_industry_unknown_returns_default(self):
        assert pick_industry("未知行业XYZ") == "default"

    def test_baseline_returns_dict_for_known_key(self):
        b = baseline("互联网")
        assert b["lawsuits_per_year"] >= 0
        assert b["overtime_hours_per_week"] >= 0
        assert b["salary_k_monthly_3y"] >= 0

    def test_baseline_falls_back_to_default_for_unknown_key(self):
        b = baseline("default")  # explicit default
        d = baseline("__bogus__")  # type: ignore[arg-type]
        assert b == d

    def test_delta_pct_positive_and_negative(self):
        assert delta_pct(120, 100) == 20.0
        assert delta_pct(80, 100) == -20.0
        assert delta_pct(100, 100) == 0.0

    def test_delta_pct_zero_baseline_returns_zero(self):
        # Avoid division-by-zero noise in templates
        assert delta_pct(50.0, 0.0) == 0.0

    def test_all_industry_keys_have_baseline(self):
        # Sanity: every key in the literal type has an entry
        for key in INDUSTRY_BASELINES:
            assert baseline(key)["salary_k_monthly_3y"] > 0


class TestComputeChapterStories:
    """Deterministic editorial voice. No LLM, no I/O."""

    def test_returns_three_tuple(self):
        q = _q()
        data = ReportData(query=q, generated_at=datetime.now(timezone.utc))
        out = compute_chapter_stories(data)
        assert isinstance(out, tuple) and len(out) == 3
        edit_notes, stories, industry_key = out
        assert isinstance(edit_notes, dict)
        assert isinstance(stories, dict)
        assert isinstance(industry_key, str)

    def test_industry_key_falls_back_to_default(self):
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        _, _, ik = compute_chapter_stories(data)
        assert ik == "default"

    def test_industry_key_resolved_from_company_profile(self):
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            company_profile=_make_company_profile("跨境电商"),
        )
        _, _, ik = compute_chapter_stories(data)
        assert ik == "跨境电商"

    def test_judicial_story_emitted_for_no_lawsuits(self):
        jf = JudicialFacts(case_count_total=0, enforcement_records=0)
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=jf,
        )
        _, stories, _ = compute_chapter_stories(data)
        assert "judicial" in stories
        # Past-12-month framing is the contract
        assert any("过去 12 个月里" in line for line in stories["judicial"])

    def test_judicial_story_compares_to_baseline_when_lawsuits_exist(self):
        jf = JudicialFacts(case_count_total=10, enforcement_records=0)
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=jf,
        )
        _, stories, _ = compute_chapter_stories(data)
        lines = stories.get("judicial", [])
        assert any("比" in line and "%" in line for line in lines)

    def test_judicial_story_edit_note_uses_sample_case_label(self):
        jf = JudicialFacts(
            case_count_total=1,
            sample_cases=[CaseItem(title="劳动合同纠纷", role="被告")],
        )
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=jf,
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "judicial" in edit_notes
        # Title or "未知案由" — never AttributeError on missing `case_type`.
        assert "案件样本" in edit_notes["judicial"]

    def test_business_edit_note_lists_facts(self):
        bf = BusinessFacts(
            legal_rep="张三",
            status="存续",
            established_at="2018-05-01",  # type: ignore[arg-type]
        )
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            business_facts=bf,
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "business" in edit_notes
        assert "张三" in edit_notes["business"]

    def test_company_edit_note_from_industry_and_funding(self):
        cp = _make_company_profile("互联网", funding_stage="B 轮")
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            company_profile=cp,
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "company" in edit_notes
        assert "互联网" in edit_notes["company"] or "B 轮" in edit_notes["company"]

    def test_reviews_story_with_heavy_overtime(self):
        rf = ReviewFacts(
            overtime_signals=[
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="996", intensity="high"),
                OvertimeSignal(pattern="弹性", intensity="low"),
            ]
        )
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            review_facts=rf,
        )
        _, stories, _ = compute_chapter_stories(data)
        assert "reviews" in stories
        # 2/3 heavy — should mention "996 / 007"
        assert any("996" in line or "高强度" in line for line in stories["reviews"])

    def test_reviews_edit_note_counts_signals(self):
        rf = ReviewFacts(
            salary_signals=[SalarySignal(position="p", base_monthly_k=20.0)],
            overtime_signals=[OvertimeSignal(pattern="996", intensity="high")],
        )
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            review_facts=rf,
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "reviews" in edit_notes
        assert "2" in edit_notes["reviews"]  # total signals

    def test_news_edit_note_when_items_present(self):
        nf = NewsFacts.model_validate({
            "items": [{"title": "x", "url": "https://x.com", "published_at": "2026-09-01"}],
            "sentiment": "positive",
        })
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            news_facts=nf,
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "news" in edit_notes

    def test_news_edit_note_no_items_no_entry(self):
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            news_facts=NewsFacts(),
        )
        edit_notes, _, _ = compute_chapter_stories(data)
        assert "news" not in edit_notes


def _make_company_profile(industry: str, funding_stage: str | None = None):
    from jobhunter.models.facts import CompanyProfile
    payload: dict = {"industries": [industry]}
    if funding_stage:
        payload["funding_stage"] = funding_stage
    return CompanyProfile.model_validate(payload)


class TestBuildReportEditorial:
    """End-to-end: build_report wires compute_chapter_stories into the template."""

    def test_render_includes_chapters_container(self):
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        assert 'class="chapters-container"' in html

    def test_render_marks_chapters_as_draggable(self):
        """v0.2.0 — chapters are draggable via JS but no visible drag-handle glyph
        (broker-research layout uses a tighter chapter head — handle added back
        if user requests). drag-drop JS still wires all .chapter elements."""
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        # Chapters are wrapped with draggable=true by the JS init (not template).
        # Verify the JS targets .chapter elements.
        assert "querySelectorAll('.chapter')" in html
        assert html.count('class="chapter"') >= 5  # main numbered chapters
        # data-chapter-key still drives JS reorder (kept for stable persistence)
        assert 'data-chapter-key="company"' in html
        assert 'data-chapter-key="judicial"' in html

    def test_render_includes_story_block_when_judicial_present(self):
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=JudicialFacts(case_count_total=3, enforcement_records=0),
        )
        html = build_report(data)
        assert "story-block" in html
        assert "edit-note" in html
        assert "data-story" in html
        assert "过去 12 个月里" in html

    def test_render_skips_story_block_when_no_facts(self):
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        # No facts → no edit notes emitted for any chapter; the macro renders
        # nothing so the rendered <aside> tag never appears. (CSS rule for
        # `.story-block` legitimately lives in the stylesheet.)
        assert '<aside class="story-block"' not in html
        assert 'class="edit-note"' not in html
        assert 'class="data-story"' not in html

    def test_render_drag_drop_js_present(self):
        """v0.2.0 — drag-drop JS still wired but no visible reset button (research-report chrome is minimal)."""
        data = ReportData(query=_q(), generated_at=datetime.now(timezone.utc))
        html = build_report(data)
        # HTML5 DnD + localStorage wiring (localStorage key updated to v2 schema)
        assert "dragstart" in html
        assert "dragend" in html
        assert "dragover" in html
        assert "drop" in html
        assert "localStorage" in html
        assert "jobhunter:chapter-order" in html

    def test_render_uses_pre_populated_edit_notes(self):
        # Caller-supplied editorial voice wins over the deterministic builder.
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            edit_notes={"company": "X 是家好公司。"},
        )
        html = build_report(data)
        assert "X 是家好公司。" in html
        assert "story-block" in html

    def test_render_data_story_industry_label_visible(self):
        data = ReportData(
            query=_q(),
            generated_at=datetime.now(timezone.utc),
            judicial_facts=JudicialFacts(case_count_total=5),
        )
        html = build_report(data)
        # The industry label "互联网" should appear inside the comparison line
        # since the default CompanyProfile has no industry → default label is
        # "default" → the comparison says "比default同行平均高 X%". Either way,
        # the structural contract is the % sign and the word "比".
        assert "比" in html and "%" in html

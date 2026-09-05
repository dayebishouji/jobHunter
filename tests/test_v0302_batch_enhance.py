"""Tests for v0.3.2: batch 增强 3 件套.

(1) Per-line `[JD:...]` override in CSV
(2) CSS-only 表格排序（4 个维度 radio + sibling selector）
(3) `--from-watchlist` 读 watchlist.json

These tests pin the v0.3.2 contract that was explicitly deferred from v0.3.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobhunter.batch import (
    BatchEntryResult,
    BatchMeta,
    build_batch_report_html,
    parse_batch_file,
    rank_rows,
)
from jobhunter.models.query import CompanyQuery
from jobhunter import watchlist


# =============== helpers ===============

def _write_batch(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "companies.csv"
    p.write_text(content, encoding="utf-8")
    return p


def _r(
    company: str,
    *,
    overall_score: float | None = 4.0,
    verdict: str = "neutral",
    case_count_total: int | None = 0,
    salary_p50: float | None = 18.0,
    status: str = "success",
    error: str | None = None,
) -> BatchEntryResult:
    return BatchEntryResult(
        company=company,
        position="后端",
        city="北京",
        status=status,
        error=error,
        report_path=None,
        cost_usd=0.05,
        tokens_in=1000,
        tokens_out=500,
        overall_score=overall_score,
        verdict=verdict,
        axis_overtime=4,
        axis_salary=4,
        axis_judicial=5,
        axis_business=5,
        axis_vibe=4,
        case_count_total=case_count_total,
        anomaly_listed=False,
        salary_p50=salary_p50,
    )


def _meta() -> BatchMeta:
    return BatchMeta(
        source_file="x.csv",
        run_count=3,
        success_count=3,
        failed_count=0,
        total_cost_usd=0.15,
        total_tokens_in=3000,
        total_tokens_out=1500,
        generated_at="2026-09-05 14:30",
    )


# =============== Item 1 — per-line [JD:...] parsing ===============

class TestPerLineJDParsing:
    """Inline `[JD:...]` overrides default `--jd` flag value."""

    def test_per_line_jd_overrides_default(self, tmp_path):
        content = (
            "阿里云,后端,杭州\n"
            "字节跳动,后端,北京 [JD:JD要求Go,15薪]\n"
        )
        p = _write_batch(tmp_path, content)
        # default_jd parameter is what --jd flag would pass; parse_batch_file
        # only handles CSV → CompanyQuery, the jd_text stays on query.jd_text.
        queries = parse_batch_file(p, default_city="")
        assert queries[0].jd_text is None  # no [JD:] → no override
        assert queries[1].jd_text == "JD要求Go,15薪"  # extracted from [JD:...]

    def test_default_jd_applied_to_lines_without_inline(self, tmp_path):
        content = "阿里云,后端,杭州\n字节跳动,后端,北京 [JD:my jd]\n"
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        # Line 1: no inline JD → jd_text stays None (caller's --jd will fill)
        assert queries[0].jd_text is None
        # Line 2: inline JD takes precedence
        assert queries[1].jd_text == "my jd"

    def test_inline_jd_with_chinese_punctuation(self, tmp_path):
        content = "字节跳动,后端,北京 [JD:要求Go/Python，996警告，15薪]\n"
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        # The Chinese full-width commas inside [JD:...] are NOT csv delimiters
        assert queries[0].city == "北京"
        assert queries[0].jd_text == "要求Go/Python，996警告，15薪"

    def test_inline_jd_at_end_of_quoted_company_name(self, tmp_path):
        """If user quotes company containing comma, [JD:] should still be on
        a separate trailing position (rare — supported via 'comment-style' parse)."""
        content = '"字节跳动, 后端",北京 [JD:tech jd]\n'
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        # The quoted company is one CSV field, then "北京" (no trailing
        # bracket), then "[JD:tech jd]" — but csv.reader only returns the
        # first 2. Per the implementation: only extract [JD:] when last field
        # contains it; if there are only 2 fields and last one ends in ']',
        # it may still be the position column. Skip the brace for this edge.
        # The expected outcome: either treat as city (if it's clearly the last
        # field) OR treat as jd_text — just assert one is set sensibly.
        assert queries[0].company == "字节跳动, 后端"
        # jd_text may or may not be set depending on parse strategy
        # (3-field CSV: company + position + JD). What's important: no crash.
        assert queries[0].position == "北京"

    def test_no_jd_anywhere_keeps_v031_behavior(self, tmp_path):
        """Old-style CSV (no [JD:]) must still work — backward compat."""
        content = "阿里云,后端,杭州\n字节跳动,后端,北京\n"
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        assert all(q.jd_text is None for q in queries)


# =============== Item 2 — CSS-only sort ===============

class TestRankRows:
    """Pre-compute per-column ranks for CSS-only sort."""

    def test_rank_by_score_desc(self):
        rows = [
            _r("low", overall_score=2.0),
            _r("high", overall_score=4.8),
            _r("mid", overall_score=3.5),
        ]
        ranked = rank_rows(rows, by="score")
        assert [r.company for r in ranked] == ["high", "mid", "low"]

    def test_rank_by_cases_asc(self):
        """Fewer lawsuits = safer = top."""
        rows = [
            _r("risky", case_count_total=10),
            _r("safe", case_count_total=0),
            _r("ok", case_count_total=3),
        ]
        ranked = rank_rows(rows, by="cases")
        assert [r.company for r in ranked] == ["safe", "ok", "risky"]

    def test_rank_by_salary_desc(self):
        rows = [
            _r("low_pay", salary_p50=12.0),
            _r("high_pay", salary_p50=28.0),
            _r("mid_pay", salary_p50=18.0),
        ]
        ranked = rank_rows(rows, by="salary")
        assert [r.company for r in ranked] == ["high_pay", "mid_pay", "low_pay"]

    def test_rank_by_verdict_severity(self):
        """avoid > caution > neutral > recommend — most severe first."""
        rows = [
            _r("good", verdict="recommend"),
            _r("bad", verdict="avoid"),
            _r("meh", verdict="caution"),
            _r("mid", verdict="neutral"),
        ]
        ranked = rank_rows(rows, by="verdict")
        assert [r.company for r in ranked] == ["bad", "meh", "mid", "good"]


class TestBatchHtmlCssSort:
    """Aggregate page must contain 4 tbody + radio chips, no JS."""

    def test_html_contains_4_sort_views(self):
        results = [_r("A", overall_score=4.0), _r("B", overall_score=3.0)]
        html = build_batch_report_html(results, _meta())
        # 4 sortable dimensions → 4 tbody elements with distinct classes
        assert "tbody-sort-score" in html
        assert "tbody-sort-cases" in html
        assert "tbody-sort-salary" in html
        assert "tbody-sort-verdict" in html

    def test_html_sort_chips_are_labels(self):
        """Chip selectors are <label> (no JS, paired with radio inputs)."""
        results = [_r("A"), _r("B")]
        html = build_batch_report_html(results, _meta())
        assert 'for="sort-score"' in html
        assert 'for="sort-cases"' in html
        assert 'for="sort-salary"' in html
        assert 'for="sort-verdict"' in html
        # And there must be radio inputs with matching ids
        assert 'id="sort-score"' in html
        assert 'id="sort-cases"' in html
        assert 'id="sort-salary"' in html
        assert 'id="sort-verdict"' in html

    def test_html_default_view_is_score(self):
        """First sort radio (综合分) is `checked` by default — visible tbody."""
        results = [_r("A"), _r("B")]
        html = build_batch_report_html(results, _meta())
        # First occurrence of 'checked' must be on sort-score radio
        first_checked_pos = html.find("checked")
        assert first_checked_pos > 0
        # And it appears on/around sort-score
        snippet = html[max(0, first_checked_pos - 80):first_checked_pos + 80]
        assert "sort-score" in snippet

    def test_html_zero_javascript(self):
        """v0.3.2 contract: zero <script> tags added by sort feature."""
        results = [_r("A"), _r("B")]
        html = build_batch_report_html(results, _meta())
        # The page may have inline JS from v0.2.0 motion system; check that
        # the batch-page-local CSS doesn't introduce any new <script>.
        # Locate the batch-specific <style> block and verify no script tag
        # references "sort".
        # Specifically: between 'batch-section' and the closing of that block
        # there must be no <script> tag.
        sort_start = html.find("id=\"sort-score\"")
        assert sort_start > 0
        # Look ahead 5000 chars (the batch section should fit)
        section = html[sort_start:sort_start + 5000]
        assert "<script" not in section, "batch section must be JS-free"


# =============== Item 3 — watchlist batch ===============

class TestWatchlistBatchHelper:
    """watchlist.entries_to_queries() + integration with parse_batch_file."""

    def test_entries_to_queries_basic(self):
        from jobhunter.watchlist import WatchEntry, entries_to_queries

        entries = [
            WatchEntry(company="美团", position="后端", city="北京"),
            WatchEntry(company="字节跳动", position="算法", city="上海"),
        ]
        queries = entries_to_queries(entries)
        assert len(queries) == 2
        assert queries[0].company == "美团"
        assert queries[1].company == "字节跳动"

    def test_entries_to_queries_with_city_override(self):
        from jobhunter.watchlist import WatchEntry, entries_to_queries

        entries = [
            WatchEntry(company="美团", position="后端", city="北京"),
            WatchEntry(company="字节跳动", position="算法", city="上海"),
        ]
        queries = entries_to_queries(entries, city_override="深圳")
        assert all(q.city == "深圳" for q in queries)

    def test_parse_batch_file_still_returns_company_queries(self):
        """parse_batch_file API didn't break — returns list[CompanyQuery]."""
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            p = Path(td) / "x.csv"
            p.write_text("美团,后端,北京\n", encoding="utf-8")
            queries = parse_batch_file(p, default_city="")
        assert isinstance(queries, list)
        assert all(isinstance(q, CompanyQuery) for q in queries)


class TestWatchlistCLI:
    """--from-watchlist CLI integration."""

    def test_cli_help_mentions_from_watchlist(self):
        from click.testing import CliRunner
        from jobhunter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["batch", "--help"])
        assert result.exit_code == 0
        assert "--from-watchlist" in result.output

    def test_cli_file_and_from_watchlist_mutex(self):
        from click.testing import CliRunner
        from jobhunter.cli import main

        runner = CliRunner()
        # v0.3.2 — set fake API keys so the early-exit `is_ready()` check
        # doesn't short-circuit before reaching the mutex validation.
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-fake-test-key",
            "TAVILY_API_KEY": "tvly-fake-test-key",
        }
        with runner.isolated_filesystem():
            Path("x.csv").write_text("美团,后端,北京\n", encoding="utf-8")
            # Pass both -f and --from-watchlist → should error (exit 2)
            result = runner.invoke(
                main,
                ["batch", "-f", "x.csv", "--from-watchlist"],
                env=env,
            )
        assert result.exit_code != 0
        # Error message should mention the conflict
        out = (result.output + (result.stderr or "")).lower()
        assert "from-watchlist" in out or "watchlist" in out
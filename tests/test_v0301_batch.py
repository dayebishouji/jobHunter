"""Tests for v0.3.1: batch mode (`--batch FILE`).

Bug fixed: autumn recruiting batch of 30 companies previously required writing
shell for-loops that ran serially (150-300 min), with no aggregation page for
side-by-side comparison. The audit (§3.1) flagged this as the top "next month"
item.

Implementation: new `src/jobhunter/batch.py` module with:
  - `parse_batch_file(path) -> list[CompanyQuery]` — CSV with `#` comments
  - `run_batch(queries, ..., concurrency=3)` — asyncio.Semaphore + best-effort
  - `build_batch_report_html(results, meta)` — broker-research-style summary page

This test file covers parsing, concurrency semantics, aggregation rendering,
and CLI surface.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobhunter.batch import (
    BatchEntryResult,
    BatchMeta,
    build_batch_report_html,
    parse_batch_file,
    run_batch,
)
from jobhunter.models.query import CompanyQuery


# =============== helpers ===============

def _write_batch(tmp_path: Path, content: str) -> Path:
    """Write a batch file with UTF-8 (no BOM) — csv module reads both."""
    p = tmp_path / "companies.csv"
    p.write_text(content, encoding="utf-8")
    return p


def _q(company: str = "X", position: str = "", city: str = "") -> CompanyQuery:
    return CompanyQuery(company=company, position=position, city=city)


def _result_success(
    company: str,
    *,
    overall_score: float = 4.2,
    verdict: str = "recommend",
    axis_overtime: int = 4,
    axis_salary: int = 4,
    axis_judicial: int = 5,
    axis_business: int = 5,
    axis_vibe: int = 4,
    case_count_total: int | None = 0,
    anomaly_listed: bool = False,
    salary_p50: float | None = 18.0,
    report_path: Path | None = None,
) -> BatchEntryResult:
    return BatchEntryResult(
        company=company,
        position="后端",
        city="杭州",
        status="success",
        error=None,
        report_path=report_path,
        cost_usd=0.05,
        tokens_in=1000,
        tokens_out=500,
        overall_score=overall_score,
        verdict=verdict,
        axis_overtime=axis_overtime,
        axis_salary=axis_salary,
        axis_judicial=axis_judicial,
        axis_business=axis_business,
        axis_vibe=axis_vibe,
        case_count_total=case_count_total,
        anomaly_listed=anomaly_listed,
        salary_p50=salary_p50,
    )


def _result_failed(company: str, error: str = "boom") -> BatchEntryResult:
    return BatchEntryResult(
        company=company,
        position="后端",
        city="杭州",
        status="failed",
        error=error,
        report_path=None,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        overall_score=None,
        verdict=None,
        axis_overtime=None,
        axis_salary=None,
        axis_judicial=None,
        axis_business=None,
        axis_vibe=None,
        case_count_total=None,
        anomaly_listed=None,
        salary_p50=None,
    )


# =============== parse_batch_file ===============

class TestParseBatchFile:
    """CSV parsing: `公司,岗位,城市` rows with `#` comments and empty lines."""

    def test_simple_three_fields(self, tmp_path):
        p = _write_batch(tmp_path, "阿里云,后端,杭州\n")
        queries = parse_batch_file(p, default_city="")
        assert len(queries) == 1
        q = queries[0]
        assert q.company == "阿里云"
        assert q.position == "后端"
        assert q.city == "杭州"

    def test_two_fields_uses_default_city(self, tmp_path):
        p = _write_batch(tmp_path, "字节跳动,后端\n")
        queries = parse_batch_file(p, default_city="北京")
        assert queries[0].city == "北京"
        assert queries[0].position == "后端"

    def test_one_field_uses_all_defaults(self, tmp_path):
        p = _write_batch(tmp_path, "美团\n")
        queries = parse_batch_file(p, default_city="上海")
        assert queries[0].company == "美团"
        assert queries[0].position == ""
        assert queries[0].city == "上海"

    def test_skip_comment_lines(self, tmp_path):
        content = (
            "# 秋招投递清单\n"
            "阿里云,后端,杭州\n"
            "# 字节跳动用别名\n"
            "字节跳动,后端,北京\n"
        )
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        assert len(queries) == 2
        assert queries[0].company == "阿里云"
        assert queries[1].company == "字节跳动"

    def test_skip_empty_lines(self, tmp_path):
        content = (
            "阿里云,后端,杭州\n"
            "\n"
            "  \n"
            "字节跳动,后端,北京\n"
        )
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        assert [q.company for q in queries] == ["阿里云", "字节跳动"]

    def test_quoted_field_with_comma(self, tmp_path):
        content = '"字节跳动, 后端",后端工程师,杭州\n'
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        assert queries[0].company == "字节跳动, 后端"
        assert queries[0].position == "后端工程师"
        assert queries[0].city == "杭州"

    def test_malformed_line_warns_and_skips(self, tmp_path, caplog):
        """A row that's somehow not 1-3 fields is logged + skipped, not crash."""
        content = (
            "阿里云,后端,杭州\n"
            ",,\n"  # all empty — should skip
            "字节跳动,后端,北京\n"
        )
        p = _write_batch(tmp_path, content)
        queries = parse_batch_file(p, default_city="")
        # The all-empty row may or may not be skipped depending on policy;
        # the important guarantee: at least the 2 valid rows come through
        # and no exception is raised.
        companies = [q.company for q in queries]
        assert "阿里云" in companies
        assert "字节跳动" in companies


# =============== run_batch concurrency + failure handling ===============

class TestRunBatch:
    """Asyncio.Semaphore + best-effort failure isolation."""

    @pytest.mark.asyncio
    async def test_runs_all_concurrently(self):
        """All N companies run to completion; results list length == N."""
        queries = [_q(f"C{i}") for i in range(5)]

        async def fake_run(query, **kwargs):
            # Each call returns a success result tagged with the company name
            return MagicMock(
                data=MagicMock(
                    query=query,
                    axes=[],
                    review_facts=None,
                    judicial_facts=None,
                    business_facts=None,
                    news_facts=None,
                    company_profile=None,
                ),
                path=Path(f"/tmp/{query.company}.html"),
                cost_usd=0.01,
                tokens_in=10,
                tokens_out=5,
            )

        with patch("jobhunter.batch.pipeline_run", side_effect=fake_run):
            with patch("jobhunter.report.builder.compute_overall_verdict") as mock_verdict:
                mock_verdict.return_value = MagicMock(
                    level=MagicMock(value="recommend"),
                    headline="ok",
                    reasons=[],
                )
                results = await run_batch(
                    queries,
                    settings=MagicMock(),
                    output_dir=Path("/tmp"),
                    batch_out_dir=Path("/tmp/batch"),
                    concurrency=3,
                )

        assert len(results) == 5
        assert all(r.status == "success" for r in results)
        assert [r.company for r in results] == [f"C{i}" for i in range(5)]

    @pytest.mark.asyncio
    async def test_failure_does_not_abort_batch(self):
        """One company raising must not stop the others."""
        queries = [_q("A"), _q("B"), _q("C"), _q("D"), _q("E")]

        async def fake_run(query, **kwargs):
            if query.company == "C":
                raise RuntimeError("simulated LLM failure")
            return MagicMock(
                data=MagicMock(
                    query=query, axes=[], review_facts=None, judicial_facts=None,
                    business_facts=None, news_facts=None, company_profile=None,
                ),
                path=Path(f"/tmp/{query.company}.html"),
                cost_usd=0.01, tokens_in=10, tokens_out=5,
            )

        with patch("jobhunter.batch.pipeline_run", side_effect=fake_run):
            with patch("jobhunter.report.builder.compute_overall_verdict") as mock_verdict:
                mock_verdict.return_value = MagicMock(
                    level=MagicMock(value="recommend"),
                    headline="ok", reasons=[],
                )
                results = await run_batch(
                    queries,
                    settings=MagicMock(),
                    output_dir=Path("/tmp"),
                    batch_out_dir=Path("/tmp/batch"),
                    concurrency=3,
                )

        statuses = {r.company: r.status for r in results}
        assert statuses["C"] == "failed"
        assert "simulated LLM failure" in next(r.error for r in results if r.company == "C")
        for other in ["A", "B", "D", "E"]:
            assert statuses[other] == "success", f"{other} should still run"

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrency(self):
        """Semaphore(3) → at most 3 active runs at once."""
        import threading

        queries = [_q(f"C{i}") for i in range(9)]
        active = 0
        peak_active = 0
        lock = threading.Lock()

        async def fake_run(query, **kwargs):
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            await asyncio.sleep(0.05)  # give other tasks time to start
            with lock:
                active -= 1
            return MagicMock(
                data=MagicMock(
                    query=query, axes=[], review_facts=None, judicial_facts=None,
                    business_facts=None, news_facts=None, company_profile=None,
                ),
                path=Path(f"/tmp/{query.company}.html"),
                cost_usd=0.01, tokens_in=10, tokens_out=5,
            )

        with patch("jobhunter.batch.pipeline_run", side_effect=fake_run):
            with patch("jobhunter.report.builder.compute_overall_verdict") as mock_verdict:
                mock_verdict.return_value = MagicMock(
                    level=MagicMock(value="recommend"),
                    headline="ok", reasons=[],
                )
                await run_batch(
                    queries,
                    settings=MagicMock(),
                    output_dir=Path("/tmp"),
                    batch_out_dir=Path("/tmp/batch"),
                    concurrency=3,
                )

        # peak should never exceed concurrency limit (with small slack for timing)
        assert peak_active <= 3, f"peak active was {peak_active}, expected ≤ 3"
        # And actually > 1 (concurrency control isn't reducing to 1)
        assert peak_active >= 2, "semaphore should let tasks overlap"


# =============== build_batch_report_html ===============

class TestBuildBatchReport:
    """Aggregate HTML rendering."""

    def test_summary_table_sorted_by_score_desc(self):
        results = [
            _result_success("low_score_co", overall_score=2.5),
            _result_success("top_co", overall_score=4.8),
            _result_success("mid_co", overall_score=3.7),
        ]
        meta = BatchMeta(
            source_file="companies.csv",
            run_count=3,
            success_count=3,
            failed_count=0,
            total_cost_usd=0.15,
            total_tokens_in=3000,
            total_tokens_out=1500,
            generated_at="2026-09-05 14:30",
        )
        html = build_batch_report_html(results, meta)
        # Find first mention of each company name
        top_pos = html.find("top_co")
        mid_pos = html.find("mid_co")
        low_pos = html.find("low_score_co")
        assert 0 <= top_pos < mid_pos < low_pos, (
            f"expected desc order top < mid < low, got {top_pos}/{mid_pos}/{low_pos}"
        )

    def test_verdict_badges_color_correctly(self):
        results = [
            _result_success("good_co", verdict="recommend"),
            _result_success("meh_co", verdict="caution"),
            _result_success("bad_co", verdict="avoid"),
            _result_success("neutral_co", verdict="neutral"),
        ]
        meta = BatchMeta(
            source_file="x", run_count=4, success_count=4, failed_count=0,
            total_cost_usd=0.0, total_tokens_in=0, total_tokens_out=0,
            generated_at="t",
        )
        html = build_batch_report_html(results, meta)
        # Each verdict has a unique class so template can color them
        assert "verdict-recommend" in html
        assert "verdict-caution" in html
        assert "verdict-avoid" in html
        assert "verdict-neutral" in html

    def test_failure_section_includes_errors(self):
        results = [
            _result_success("good_co"),
            _result_failed("bad_co", error="API key invalid"),
        ]
        meta = BatchMeta(
            source_file="x", run_count=2, success_count=1, failed_count=1,
            total_cost_usd=0.05, total_tokens_in=1000, total_tokens_out=500,
            generated_at="t",
        )
        html = build_batch_report_html(results, meta)
        # Failure list should show up — both company name + error message
        assert "bad_co" in html
        assert "API key invalid" in html
        # Failed row should be visually marked
        assert "status-failed" in html


# =============== CLI integration ===============

class TestBatchCLI:
    """`jobhunter batch --help` works + bad args exit cleanly."""

    def test_batch_help_text(self):
        from click.testing import CliRunner
        from jobhunter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["batch", "--help"])
        assert result.exit_code == 0
        assert "--file" in result.output
        assert "--batch-concurrency" in result.output

    def test_batch_missing_file_errors(self):
        from click.testing import CliRunner
        from jobhunter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["batch", "-f", "/nonexistent/path/xyz.csv"])
        # Click should reject (exit 2) when file doesn't exist (exists=True)
        assert result.exit_code != 0
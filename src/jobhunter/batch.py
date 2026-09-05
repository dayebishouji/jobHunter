"""v0.3.1 — Batch mode: run N companies with bounded concurrency + aggregate HTML.

Parses a CSV file (one row per company with `#` comments), runs each entry
through the full pipeline with `asyncio.Semaphore(N)`, and writes:

  1. per-company HTML reports to `output_dir/` (same as `run` command)
  2. an aggregate `index.html` in `batch_out_dir/` with a sortable summary
     table for side-by-side comparison.

Failure isolation: each entry runs inside its own try/except; a single failure
does NOT abort the batch (best-effort by default; `--strict` makes it CI-friendly).
Cache reuse: v0.2.2 LLM cache + Tavily cache mean duplicate companies within 24h
are zero-cost.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from jobhunter.config import Settings
from jobhunter.models.query import CompanyQuery
from jobhunter.pipeline import ReportArtifacts, run as pipeline_run

logger = logging.getLogger(__name__)


# =============== public dataclasses ===============

@dataclass
class BatchEntryResult:
    """One row of the aggregate summary table.

    Populated by `run_batch()` from the corresponding `ReportArtifacts`.
    Failed entries carry `status="failed"` + an `error` message instead of
    scoring data.
    """
    company: str
    position: str
    city: str
    status: Literal["success", "failed"]
    error: str | None = None
    report_path: Path | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    overall_score: float | None = None
    verdict: str | None = None  # recommend / caution / avoid / neutral
    axis_overtime: int | None = None
    axis_salary: int | None = None
    axis_judicial: int | None = None
    axis_business: int | None = None
    axis_vibe: int | None = None
    case_count_total: int | None = None
    anomaly_listed: bool | None = None
    salary_p50: float | None = None


@dataclass
class BatchMeta:
    """Aggregate KPI strip at the top of the report page."""
    source_file: str
    run_count: int
    success_count: int
    failed_count: int
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    generated_at: str  # human-readable timestamp


# =============== file parsing ===============

def parse_batch_file(path: Path, default_city: str = "") -> list[CompanyQuery]:
    """Read CSV: each row is `公司,岗位,城市` (1–3 fields).

    Skip rules:
      - Lines whose first non-whitespace char is `#`
      - Empty / whitespace-only lines
      - Rows with >3 fields or <1 non-empty field (logged + skipped)
    """
    queries: list[CompanyQuery] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for line_no, row in enumerate(reader, start=1):
            # Strip whitespace from each field
            fields = [c.strip() for c in row]
            # Detect comment lines (whole line starts with #, possibly indented)
            non_empty = [c for c in fields if c]
            if not non_empty:
                continue
            if non_empty[0].startswith("#"):
                continue
            if not fields[0]:
                # First field empty → not a valid row
                logger.warning(
                    "batch file %s line %d: empty company name, skipped",
                    path, line_no,
                )
                continue
            company = fields[0]
            position = fields[1] if len(fields) > 1 else ""
            city = fields[2] if len(fields) > 2 and fields[2] else default_city
            queries.append(CompanyQuery(company=company, position=position, city=city))
    return queries


# =============== batch runner ===============

async def run_batch(
    queries: list[CompanyQuery],
    *,
    settings: Settings,
    output_dir: Path,
    batch_out_dir: Path,
    concurrency: int = 3,
    include_judicial: bool = True,
    include_news: bool = True,
    jd_text: str | None = None,
) -> list[BatchEntryResult]:
    """Run each company through `pipeline.run()` with bounded concurrency.

    Returns a list of `BatchEntryResult` in the SAME order as `queries` so the
    caller can correlate. Failed entries are returned with `status="failed"`
    rather than raising — the batch continues end-to-end.
    """
    # Lazy import to avoid a circular reference: pipeline imports batch? No.
    # Pipeline doesn't import batch, but `run` is the right entry point.
    from jobhunter.report.builder import compute_overall_verdict

    sem = asyncio.Semaphore(concurrency)

    async def _one(q: CompanyQuery) -> BatchEntryResult:
        async with sem:
            # Inject defaults from caller (--no-judicial etc.)
            q = q.model_copy(update={
                "include_judicial": include_judicial,
                "include_news": include_news,
                "jd_text": jd_text if jd_text else q.jd_text,
            })
            try:
                artifacts: ReportArtifacts = await pipeline_run(
                    q,
                    settings=settings,
                    output_dir=output_dir,
                    open_browser=False,
                )
            except Exception as e:  # noqa: BLE001 — best-effort batch
                logger.warning("batch entry %s failed: %s", q.company, e)
                return BatchEntryResult(
                    company=q.company,
                    position=q.position,
                    city=q.city,
                    status="failed",
                    error=str(e),
                )

            # Extract summary from the ReportData
            data = artifacts.data
            axes = {a.axis.value: a.stars for a in (data.axes or []) if a.stars is not None}

            # Try the v0.1.16 overall verdict; if it can't be computed (missing
            # data), fall back to None.
            try:
                verdict_obj = compute_overall_verdict(data)
                verdict = verdict_obj.level.value
            except Exception:  # noqa: BLE001
                verdict = None

            # Salary P50 from review_facts (linear interpolation like P25/P75
            # but we just need the median; use simple sorted median for speed).
            p50 = _salary_median(data.review_facts)

            # Average axis score for sort key
            avg = (
                round(sum(axes.values()) / len(axes), 2)
                if axes else None
            )

            return BatchEntryResult(
                company=q.company,
                position=q.position,
                city=q.city,
                status="success",
                report_path=artifacts.path,
                cost_usd=artifacts.cost_usd,
                tokens_in=artifacts.tokens_in,
                tokens_out=artifacts.tokens_out,
                overall_score=avg,
                verdict=verdict,
                axis_overtime=axes.get("overtime"),
                axis_salary=axes.get("salary"),
                axis_judicial=axes.get("judicial"),
                axis_business=axes.get("business"),
                axis_vibe=axes.get("vibe"),
                case_count_total=(
                    data.judicial_facts.case_count_total
                    if data.judicial_facts else None
                ),
                anomaly_listed=(
                    data.business_facts.anomaly_listed
                    if data.business_facts else None
                ),
                salary_p50=p50,
            )

    return list(await asyncio.gather(*(_one(q) for q in queries)))


def _salary_median(review_facts) -> float | None:
    """Compute simple median of base_monthly_k across salary signals.

    Returns None when fewer than 1 datapoint exists. Used for the batch summary
    table; for the per-company report, the full `compute_salary_band()` P25/P50/
    P75 calculation is reused.
    """
    if not review_facts or not review_facts.salary_signals:
        return None
    vals: list[float] = []
    for s in review_facts.salary_signals:
        if s.salary_range_min_k is not None and s.salary_range_max_k is not None:
            vals.append((s.salary_range_min_k + s.salary_range_max_k) / 2)
        elif s.base_monthly_k is not None:
            vals.append(float(s.base_monthly_k))
    if not vals:
        return None
    vals.sort()
    return round(vals[len(vals) // 2], 1)


# =============== aggregate HTML ===============

_TEMPLATE_NAME = "batch.html.j2"
_TEMPLATE_DIR = Path(__file__).parent / "report" / "templates"


def build_batch_report_html(results: list[BatchEntryResult], meta: BatchMeta) -> str:
    """Render the aggregate summary page.

    Table is sorted by overall_score desc, with failed entries pushed to the
    bottom (status-failed class for visual distinction).
    """
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_NAME)

    successes = [r for r in results if r.status == "success"]
    failures = [r for r in results if r.status == "failed"]

    # Sort successes by overall_score desc; failures by company name asc
    successes_sorted = sorted(
        successes,
        key=lambda r: (r.overall_score is None, -(r.overall_score or 0)),
    )
    failures_sorted = sorted(failures, key=lambda r: r.company)

    rows = successes_sorted + failures_sorted

    return template.render(rows=rows, meta=meta, css=_load_css())


def _load_css() -> str:
    """Inline report.css into the batch page so the file stays single-file portable."""
    css_path = _TEMPLATE_DIR.parent / "static" / "report.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""
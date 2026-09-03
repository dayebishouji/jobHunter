"""Report layer — heuristic scoring + HTML rendering."""

from jobhunter.report.builder import build_report
from jobhunter.report.scoring import compute_axes

__all__ = ["build_report", "compute_axes"]

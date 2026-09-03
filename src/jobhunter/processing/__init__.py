"""Processing layer — normalize / extract / cross-check."""

from jobhunter.processing.crosscheck import (
    all_notes,
    detect_overtime_consensus,
    detect_salary_conflicts,
    sentiment_majority,
)
from jobhunter.processing.extract import (
    consolidate,
    extract_all_domains,
    parse_interview_lines,
)
from jobhunter.processing.normalize import normalize

__all__ = [
    "all_notes",
    "consolidate",
    "detect_overtime_consensus",
    "detect_salary_conflicts",
    "extract_all_domains",
    "normalize",
    "parse_interview_lines",
    "sentiment_majority",
]

"""Filename-safe slug generation. v0.1 uses ASCII fall-back (timestamp)."""

from __future__ import annotations

import re

from jobhunter.models.query import CompanyQuery


def _safe(s: str) -> str:
    """ASCII-safe fallback for non-ASCII company/position names."""
    s = s.strip()
    if not s:
        return ""
    # Keep alnum + common separators; collapse to '-'
    out = re.sub(r"[^\w一-鿿\-]+", "-", s, flags=re.UNICODE)
    out = re.sub(r"-+", "-", out).strip("-")
    return out


def make_slug(query: CompanyQuery, ts: str) -> str:
    """Return `{company}-{position?}-{ts}`. Timestamp ensures uniqueness on same input."""
    parts = [_safe(query.company)]
    if query.position:
        p = _safe(query.position)
        if p:
            parts.append(p)
    parts.append(ts)
    return "-".join(parts)


def batch_dir_slug(file_path: str | Path, ts: str) -> str:
    """Return the directory name for a batch run: `{file_stem}-{ts}`.

    `file_stem` is the basename without extension; non-ASCII characters are
    passed through so the directory name remains human-readable (e.g.
    `companies-20260905-1430` or `秋招清单-20260905-1430`).
    """
    stem = Path(file_path).stem
    return f"{stem}-{ts}"

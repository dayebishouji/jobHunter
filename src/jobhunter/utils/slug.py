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

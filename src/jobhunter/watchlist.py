"""v0.1.17 — Persistent company watchlist (JSON in platformdirs cache).

Design choice — keep this dead simple, no SQLite, no migrations:
    ~/.cache/jobhunter/watchlist.json

Schema:
    {
      "version": 1,
      "entries": [
        {"company": "...", "position": "...", "city": "...",
         "added_at": "ISO timestamp", "last_run_at": null | "ISO"}
      ]
    }

This is enough to power `jobhunter watch add/list/remove` and as a hook for
future batch-run commands (`jobhunter watch run` — not in this release).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_cache_dir


_PATH = Path(user_cache_dir("jobhunter", "dayebishouji")) / "watchlist.json"


@dataclass
class WatchEntry:
    company: str
    position: str = ""
    city: str = ""
    added_at: str = ""
    last_run_at: str | None = None

    def display(self) -> str:
        parts = [self.company]
        if self.position:
            parts.append(self.position)
        if self.city:
            parts.append(self.city)
        return " · ".join(parts)


def _read() -> dict:
    if not _PATH.exists():
        return {"version": 1, "entries": []}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": 1, "entries": []}


def _write(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_entries() -> list[WatchEntry]:
    data = _read()
    return [WatchEntry(**e) for e in data.get("entries", [])]


def add(company: str, position: str = "", city: str = "") -> WatchEntry:
    """Add a company to the watchlist. Idempotent on (company, position, city)
    triple — adding twice with identical fields is a no-op."""
    company = company.strip()
    if not company:
        raise ValueError("company 不能为空")
    position = position.strip()
    city = city.strip()
    entries = list_entries()
    for e in entries:
        if e.company == company and e.position == position and e.city == city:
            return e  # already there
    entry = WatchEntry(
        company=company,
        position=position,
        city=city,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    entries.append(entry)
    _write({"version": 1, "entries": [asdict(e) for e in entries]})
    return entry


def remove(company: str) -> bool:
    """Remove a company by exact name match. Returns True if anything was removed."""
    company = company.strip()
    if not company:
        return False
    entries = list_entries()
    new_entries = [e for e in entries if e.company != company]
    if len(new_entries) == len(entries):
        return False
    _write({"version": 1, "entries": [asdict(e) for e in new_entries]})
    return True


def mark_ran(company: str) -> None:
    """Update last_run_at for a watched entry. No-op if not in list."""
    now = datetime.now(timezone.utc).isoformat()
    entries = list_entries()
    touched = False
    for e in entries:
        if e.company == company:
            e.last_run_at = now
            touched = True
    if touched:
        _write({"version": 1, "entries": [asdict(e) for e in entries]})


def path_for_display() -> Path:
    """Return the watchlist JSON path (used by `jobhunter watch list --path`)."""
    return _PATH


def entries_to_queries(
    entries: list[WatchEntry],
    *,
    city_override: str = "",
) -> list:
    """v0.3.2 — Convert watchlist entries into `CompanyQuery` for batch mode.

    `city_override` lets `--city` from the CLI take precedence over each
    entry's stored city (useful for users who keep the watchlist city empty
    or stale). Empty `city_override` means keep each entry's stored city.

    Each WatchEntry has no JD field (out of scope for v0.3.2), so all
    resulting queries get `jd_text=None`. Use `--jd TEXT` on the batch
    command if a default JD applies to all watched companies.
    """
    # Local import to avoid a hard dependency from this module to models.
    from jobhunter.models.query import CompanyQuery

    out: list[CompanyQuery] = []
    for e in entries:
        out.append(
            CompanyQuery(
                company=e.company,
                position=e.position,
                city=city_override or e.city,
            )
        )
    return out
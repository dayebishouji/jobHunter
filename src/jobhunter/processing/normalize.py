"""Cross-collector normalization: flatten, URL-dedup, fuzzy-dedup, date-sort, bucket."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

from jobhunter.models.raw import CollectorResult, RawItem


def _title_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def normalize(results: Iterable[CollectorResult]) -> dict[str, list[RawItem]]:
    """Take all (successful) CollectorResults and return items bucketed by domain.

    Steps:
        1. filter out errored collectors
        2. URL-dedup (keep first seen)
        3. title-fuzzy-dedup (SequenceMatcher ratio >= 0.85)
        4. sort each bucket by published_at desc (None goes last)
    """
    by_domain: dict[str, list[RawItem]] = {
        "business": [], "judicial": [], "reviews": [], "news": [], "company_info": []
    }
    for r in results:
        if r.error:
            continue
        by_domain[r.domain].extend(r.items)

    out: dict[str, list[RawItem]] = {}
    for domain, items in by_domain.items():
        seen_url: set[str] = set()
        uniq_url: list[RawItem] = []
        for it in items:
            u = str(it.url)
            if u in seen_url:
                continue
            seen_url.add(u)
            uniq_url.append(it)

        uniq_title: list[RawItem] = []
        for it in uniq_url:
            if any(_title_similar(it.title, j.title) for j in uniq_title):
                continue
            uniq_title.append(it)

        uniq_title.sort(
            key=lambda x: (
                x.published_at is None,
                -(x.published_at.timestamp() if x.published_at else 0),
            )
        )
        out[domain] = uniq_title
    return out

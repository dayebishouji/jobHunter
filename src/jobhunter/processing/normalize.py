"""Cross-collector normalization: flatten, URL-dedup, fuzzy-dedup, date-sort, bucket."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import urlparse

from jobhunter.models.raw import CollectorResult, RawItem


def _title_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


# v0.1.22 — Per-host URL-path filters for the reviews bucket.
#
# Background: Tavily name-only queries on consumer brands (e.g. 美的) returned
# 80%+ product reviews / consumer shopping pages from 知乎 / 一亩三分地 / 看准
# etc. — the LLM extraction step then correctly throws them away because
# "三明治机评测" is not an employer review, leaving the reviews chapter empty.
#
# The fix is cheaper than a smarter query: drop URL hits whose path clearly
# indicates non-employer content (product page / shop page / login / ad
# landing) BEFORE the LLM extraction step. The host → list-of-required-
# substrings map below is the allowlist — keep URLs that match ANY of the
# substrings for their host, drop the rest.
#
# Hosts NOT in this map (豆瓣 / 大众点评 / B站 / etc.) are passed through
# unchanged — their signal is sparse but legitimate when it does land, and
# the LLM extraction step already filters most consumer noise.
REVIEW_URL_PATTERNS: dict[str, list[str]] = {
    "www.1point3acres.com": ["/bbs/thread-", "/bbs/forum", "/interview/thread"],
    "1point3acres.com": ["/bbs/thread-", "/bbs/forum", "/interview/thread"],
    "www.zhihu.com": ["/question/", "zhuanlan.zhihu.com/p"],
    "zhuanlan.zhihu.com": ["/p/"],
    "www.nowcoder.com": ["/discuss/", "/interview/", "/feed/"],
    "www.36dianping.com": ["/dianping/", "/interview/", "/salary/", "/firm/", "/company-"],
    "36dianping.com": ["/dianping/", "/interview/", "/salary/", "/firm/", "/company-"],
    "maimai.cn": ["/article/", "/profile/"],
}


def _keep_in_reviews(url: str) -> bool:
    """Return True if the URL should stay in the reviews bucket.

    Hosts without a filter rule pass through (return True). Hosts with a rule
    are kept only if their URL contains at least one of the required substrings.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return True
    patterns = REVIEW_URL_PATTERNS.get(host)
    if not patterns:
        return True
    return any(pat in url for pat in patterns)


def normalize(results: Iterable[CollectorResult]) -> dict[str, list[RawItem]]:
    """Take all (successful) CollectorResults and return items bucketed by domain.

    Steps:
        1. filter out errored collectors
        2. URL-dedup (keep first seen)
        3. title-fuzzy-dedup (SequenceMatcher ratio >= 0.85)
        4. v0.1.22 — reviews URL-pattern filter (drop employer-irrelevant URLs)
        5. sort each bucket by published_at desc (None goes last)
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

        # v0.1.22 — Reviews bucket: drop URLs that don't match an employer-review
        # path pattern for their host. Consumer brands (e.g. 美的) used to flood
        # the LLM extraction step with product / shop / login URLs; this filter
        # removes the worst offenders BEFORE the LLM sees them.
        if domain == "reviews":
            uniq_title = [it for it in uniq_title if _keep_in_reviews(str(it.url))]

        uniq_title.sort(
            key=lambda x: (
                x.published_at is None,
                -(x.published_at.timestamp() if x.published_at else 0),
            )
        )
        out[domain] = uniq_title
    return out

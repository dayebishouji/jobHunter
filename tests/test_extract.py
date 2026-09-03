"""Tests for the extract stage — materialization + score ordering + chars cap."""

from __future__ import annotations

from datetime import datetime, timezone

from jobhunter.models.raw import RawItem
from jobhunter.processing.extract import CHARS_CAP, _materialize


def _item(url: str, title: str, snippet: str, score: float | None = None) -> RawItem:
    payload: dict = {}
    if score is not None:
        payload["score"] = score
    return RawItem(
        source="tavily:web",
        url=url,
        title=title,
        snippet=snippet,
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
        payload=payload,
    )


def test_chars_cap_is_50k():
    """CHARS_CAP must be ≥ 25K (the previous default) so high-quality items
    survive the slice. The new default is 50K to give the LLM more recall."""
    assert CHARS_CAP >= 25_000


def test_materialize_orders_high_score_first():
    """Higher Tavily scores must come first so they survive CHARS_CAP."""
    items = [
        _item("https://low.com/1", "low", "low score body", 0.1),
        _item("https://high.com/1", "high", "high score body", 0.9),
        _item("https://mid.com/1", "mid", "mid score body", 0.5),
    ]
    out = _materialize(items)
    pos_high = out.find("high score body")
    pos_mid = out.find("mid score body")
    pos_low = out.find("low score body")
    assert 0 <= pos_high < pos_mid < pos_low


def test_materialize_treats_missing_score_as_zero():
    """Items without a payload.score should be pushed to the tail, not the head."""
    items = [
        _item("https://no.com/1", "no score", "no score body"),  # no payload.score
        _item("https://high.com/1", "high", "high score body", 0.9),
    ]
    out = _materialize(items)
    pos_high = out.find("high score body")
    pos_no = out.find("no score body")
    assert 0 <= pos_high < pos_no
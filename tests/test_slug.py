"""Slug generation tests."""

from __future__ import annotations

from jobhunter.models.query import CompanyQuery
from jobhunter.utils.slug import _safe, make_slug


def test_safe_handles_chinese():
    s = _safe("阿里云")
    assert "阿里云" in s


def test_safe_replaces_special_chars():
    s = _safe("AC/ME 公司?")
    assert "/" not in s
    assert "?" not in s


def test_make_slug_includes_timestamp():
    q = CompanyQuery(company="阿里", position="后端", city="杭州")
    slug = make_slug(q, "20260903-1830")
    assert "20260903-1830" in slug
    assert "阿里" in slug


def test_make_slug_handles_empty_position():
    q = CompanyQuery(company="AC", position="", city="")
    slug = make_slug(q, "20260903-1830")
    # Should not have empty segments
    assert "--" not in slug

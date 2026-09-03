"""Tests for query template generation (alias expansion + dedup)."""

from __future__ import annotations

from jobhunter.models.query import CompanyQuery
from jobhunter.search.query_templates import (
    _all_names,
    business_queries,
    judicial_queries,
    news_queries,
    review_queries,
)


def _q(company: str = "AC", position: str = "", city: str = "", **kw) -> CompanyQuery:
    return CompanyQuery(company=company, position=position, city=city, **kw)


class TestAllNames:
    def test_company_only(self):
        assert _all_names(_q("阿里巴巴集团")) == ["阿里巴巴集团"]

    def test_dedup_aliases(self):
        names = _all_names(_q("阿里", aliases=["ali", "ali"]))
        assert names == ["阿里", "ali"]

    def test_aliases_capped(self):
        names = _all_names(_q("X", aliases=["a", "b", "c", "d", "e"]), max_n=3)
        assert len(names) == 3

    def test_empty_aliases_skipped(self):
        names = _all_names(_q("X", aliases=["", " ", "real"]))
        assert names == ["X", "real"]

    def test_long_alias_dropped(self):
        # Anything > 50 chars is suspicious; skip
        long = "x" * 60
        names = _all_names(_q("X", aliases=[long]))
        assert names == ["X"]


class TestReviewQueriesExpansion:
    def test_no_aliases(self):
        q = review_queries(_q("阿里巴巴集团"))
        assert all('"阿里巴巴集团"' in s for s in q)
        # 6 base queries
        assert len(q) == 6

    def test_with_aliases_doubles_queries(self):
        q = review_queries(_q("阿里巴巴集团", aliases=["阿里"]))
        # 6 base × 2 names = 12
        assert len(q) == 12
        assert any('"阿里"' in s for s in q)
        assert any('"阿里巴巴集团"' in s for s in q)

    def test_with_aliases_and_position(self):
        q = review_queries(_q("阿里巴巴集团", position="后端", aliases=["阿里"]))
        # 6 base × 2 + 2 position × 2 = 16
        assert len(q) == 16

    def test_aliases_capped_at_4_total(self):
        q = review_queries(_q("X", aliases=["a", "b", "c", "d", "e", "f"]))
        # 6 base × 4 names = 24
        assert len(q) == 24

    def test_position_escape_with_city(self):
        q = review_queries(_q("X", position="P", city="杭州"))
        assert any("杭州 避雷" in s for s in q)


class TestReviewSlangExpansion:
    """Slang queries (LLM-generated colloquial recall terms) get appended
    as plain query strings and as company-anchored variants."""

    def test_no_slang_means_no_extras(self):
        q = review_queries(_q("阿里巴巴集团"))
        # 6 base queries, no slang
        assert len(q) == 6

    def test_with_slang_appends_company_anchored_and_bare(self):
        slang = ["内卷", "ICU", "摆烂"]
        q = review_queries(_q("阿里巴巴集团", slang_queries=slang))
        # 6 base + 3 × 2 (anchored + bare) = 12
        assert len(q) == 12
        assert any("阿里巴巴集团 内卷" in s for s in q)
        assert any("阿里巴巴集团 ICU" in s for s in q)
        assert any(s == "摆烂" for s in q)

    def test_slang_capped_at_8(self):
        slang = [f"词{i}" for i in range(20)]
        q = review_queries(_q("X", slang_queries=slang))
        # 6 base + 8 × 2 = 22
        assert len(q) == 22

    def test_slang_dedup(self):
        slang = ["内卷", "内卷", "ICU"]
        q = review_queries(_q("X", slang_queries=slang))
        # 6 + (2 unique) × 2 = 10
        assert len(q) == 10

    def test_empty_slang_ignored(self):
        slang = ["", "  ", "内卷"]
        q = review_queries(_q("X", slang_queries=slang))
        # 6 + 1 × 2 = 8
        assert len(q) == 8


class TestOtherDomainsNoAliases:
    """business / judicial / news should NOT use aliases — aggregator data
    is keyed by official name, not casual abbreviation."""

    def test_news_uses_full_name(self):
        q = news_queries(_q("阿里巴巴集团", aliases=["阿里"]))
        assert all('"阿里巴巴集团"' in s for s in q)
        assert not any('"阿里"' in s for s in q)

    def test_business_uses_full_name(self):
        q = business_queries(_q("阿里巴巴集团", aliases=["阿里"]))
        assert all('"阿里巴巴集团"' in s for s in q)

    def test_judicial_uses_full_name(self):
        q = judicial_queries(_q("阿里巴巴集团", aliases=["阿里"]))
        assert all('"阿里巴巴集团"' in s for s in q)
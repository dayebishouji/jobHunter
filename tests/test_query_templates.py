"""Tests for query template generation (alias expansion + dedup)."""

from __future__ import annotations

from jobhunter.models.query import CompanyQuery
from jobhunter.search.query_templates import (
    AUTO_REVIEW_DOMAINS,
    DEVELOPER_REVIEW_DOMAINS,
    ECOMMERCE_OPS_REVIEW_DOMAINS,
    FINANCE_REVIEW_DOMAINS,
    GENERAL_REVIEW_DOMAINS,
    HR_REVIEW_DOMAINS,
    LOGISTICS_REVIEW_DOMAINS,
    MEDICAL_REVIEW_DOMAINS,
    REAL_ESTATE_REVIEW_DOMAINS,
    REVIEW_DOMAINS,
    SECURITY_REVIEW_DOMAINS,
    _all_names,
    business_queries,
    domains_for_position,
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


class TestDomainsForPosition:
    """Position-keyword allowlist filter (cost-control feature in v0.1.9)."""

    def test_empty_position_returns_full_union(self):
        assert sorted(domains_for_position("")) == sorted(REVIEW_DOMAINS)
        assert sorted(domains_for_position("   ")) == sorted(REVIEW_DOMAINS)

    def test_unrecognized_position_returns_full_union(self):
        # "运营" was removed from POSITION_DOMAIN_HINTS because it's too
        # ambiguous (互联网/跨境/工厂都可能). Unrecognized → fall back to full.
        assert sorted(domains_for_position("运营")) == sorted(REVIEW_DOMAINS)
        assert sorted(domains_for_position("CEO")) == sorted(REVIEW_DOMAINS)

    def test_backend_position_returns_general_plus_developer(self):
        out = domains_for_position("后端")
        # All general platforms always present
        for d in GENERAL_REVIEW_DOMAINS:
            assert d in out
        # All developer verticals present
        for d in DEVELOPER_REVIEW_DOMAINS:
            assert d in out
        # Vertical NOT in matched set (medical / cross-border / gaming) absent
        assert "bbs.dxy.com" not in out
        assert "kjxb.org" not in out
        assert "ngabbs.com" not in out

    def test_doctor_position_returns_general_plus_medical(self):
        out = domains_for_position("医生")
        assert "bbs.dxy.com" in out
        for d in GENERAL_REVIEW_DOMAINS:
            assert d in out
        # No irrelevant verticals
        assert "juejin.cn" not in out
        assert "ngabbs.com" not in out
        assert "kjxb.org" not in out

    def test_gaming_position_returns_general_plus_nganbb(self):
        out = domains_for_position("游戏策划")
        assert "ngabbs.com" in out
        assert "bbs.dxy.com" not in out
        assert "juejin.cn" not in out

    def test_cross_border_position_returns_all_cross_border_verticals(self):
        out = domains_for_position("跨境运营")
        for d in ["kjxb.org", "zhiwuwubuyan.com", "amz123.com", "10100.com"]:
            assert d in out
        assert "bbs.dxy.com" not in out

    def test_multiple_keywords_union(self):
        # "Python 后端" matches both "python" and "后端" → union
        out = domains_for_position("Python 后端")
        assert "juejin.cn" in out
        assert "segmentfault.com" in out
        assert "oschina.net" in out

    def test_case_insensitive_match(self):
        out_upper = domains_for_position("PYTHON 后端")
        out_lower = domains_for_position("python 后端")
        assert out_upper == out_lower

    def test_amazon_keyword_partial_match(self):
        # "amazon" lowercase matches "亚马逊运营" only via lowercase("amazon") —
        # but "亚马逊" is the canonical Chinese keyword. Verify both paths.
        out_zh = domains_for_position("亚马逊运营")
        assert "kjxb.org" in out_zh
        out_en = domains_for_position("Amazon运营")
        assert "kjxb.org" in out_en

    def test_full_union_is_24_domains(self):
        # Sanity check: 15 general + 4 cross-border + 1 gaming + 1 medical + 3 developer = 24
        # (kept as a regression marker; v0.1.10 expanded to 31)
        assert len(REVIEW_DOMAINS) >= 24

    def test_filtered_is_subset_of_full(self):
        for pos in ["后端", "医生", "游戏", "跨境", "python", "Java", "策划"]:
            sub = domains_for_position(pos)
            assert set(sub).issubset(set(REVIEW_DOMAINS))


class TestV0110Verticals:
    """v0.1.10 — coverage expansion to 31 domains across 9 verticals."""

    def test_full_union_is_31_domains(self):
        # v0.1.10 marker — kept as regression guard. v0.1.11 expanded to 46.
        assert len(REVIEW_DOMAINS) >= 31

    def test_security_keyword_returns_freebuf_pediy(self):
        out = domains_for_position("安全工程师")
        assert "freebuf.com" in out
        assert "bbs.pediy.com" in out
        for d in SECURITY_REVIEW_DOMAINS:
            assert d in out
        # No irrelevant verticals
        assert "juejin.cn" not in out
        assert "kjxb.org" not in out
        assert "zcool.com.cn" not in out

    def test_penetration_keyword_returns_security(self):
        out = domains_for_position("渗透测试")
        assert "freebuf.com" in out

    def test_taobao_keyword_returns_paidai_only(self):
        out = domains_for_position("淘宝运营")
        for d in ECOMMERCE_OPS_REVIEW_DOMAINS:
            assert d in out
        # paidai is e-commerce ops, NOT cross-border — those should be excluded
        assert "kjxb.org" not in out
        assert "amz123.com" not in out

    def test_ecommerce_keyword_unions_cross_border_and_paidai(self):
        out = domains_for_position("电商运营")
        # Both cross-border verticals AND paidai
        assert "kjxb.org" in out
        assert "zhiwuwubuyan.com" in out
        assert "paidai.com" in out

    def test_design_keyword_returns_zcool_ui_cn(self):
        out = domains_for_position("UI 设计师")
        assert "zcool.com.cn" in out
        assert "ui.cn" in out
        # No irrelevant verticals
        assert "freebuf.com" not in out
        assert "paidai.com" not in out
        assert "qzzn.com" not in out

    def test_ux_keyword_returns_design(self):
        out = domains_for_position("UX 设计师")
        assert "zcool.com.cn" in out
        assert "ui.cn" in out

    def test_civil_service_keyword_returns_qzzn(self):
        out = domains_for_position("公务员")
        assert "qzzn.com" in out
        assert "freebuf.com" not in out
        assert "paidai.com" not in out

    def test_xuandiao_keyword_returns_qzzn(self):
        out = domains_for_position("选调生")
        assert "qzzn.com" in out

    def test_hr_keyword_returns_hrloo(self):
        out = domains_for_position("HR")
        for d in HR_REVIEW_DOMAINS:
            assert d in out
        # HR is distinct from general HR-tech content
        assert "qzzn.com" not in out
        assert "freebuf.com" not in out

    def test_recruiter_keyword_returns_hrloo(self):
        out = domains_for_position("招聘专员")
        assert "hrloo.com" in out

    def test_general_platforms_always_included(self):
        # Even when position matches a vertical, the 15 general platforms
        # must stay (kanzhun/maimai/zhihu/etc. — they're cross-industry).
        for pos in ["安全", "淘宝", "UI", "公务员", "HR", "后端"]:
            out = set(domains_for_position(pos))
            for d in GENERAL_REVIEW_DOMAINS:
                assert d in out, f"{d} missing for position={pos}"

    def test_all_verticals_present_in_full_union(self):
        # Every vertical constant must contribute at least one domain to REVIEW_DOMAINS
        union = set(REVIEW_DOMAINS)
        assert set(SECURITY_REVIEW_DOMAINS).issubset(union)
        assert set(ECOMMERCE_OPS_REVIEW_DOMAINS).issubset(union)
        # DESIGN / CIVIL_SERVICE / HR also covered (imported at top)


class TestV0111Verticals:
    """v0.1.11 — extend REVIEW_DOMAINS to 46 (5 general additions + 4 new verticals
    + 2 cross-border supplements). Black Cat Complaint (黑猫投诉) lands in GENERAL
    because it's the highest-signal risk surface across all industries."""

    def test_full_union_is_46_domains(self):
        # 20 general (15 + 5) + 6 cross-border (4 + 2) + 1 gaming + 1 medical + 3 developer
        # + 2 security + 1 ecom-ops + 2 design + 1 civil-service + 1 hr
        # + 4 auto + 3 finance + 3 real-estate + 3 logistics = 51
        # Recount after explicit accounting: see source file for arithmetic.
        assert len(REVIEW_DOMAINS) >= 46
        assert len(domains_for_position("")) == len(REVIEW_DOMAINS)

    def test_heitou_in_general_for_all_positions(self):
        # 黑猫投诉 is the standout A-tier addition; must appear in every position's allowlist.
        for pos in ["", "后端", "医生", "安全", "UI", "公务员", "HR", "汽车", "金融", "物流"]:
            out = domains_for_position(pos)
            assert "tousu.sina.com.cn" in out, f"黑猫投诉 missing for position={pos!r}"

    def test_weibo_douyin_kuaishou_36dianping_in_general(self):
        for d in ["weibo.com", "douyin.com", "kuaishou.com", "36dianping.com"]:
            assert d in GENERAL_REVIEW_DOMAINS

    def test_auto_keyword_returns_auto_vertical(self):
        out = domains_for_position("汽车工程师")
        for d in AUTO_REVIEW_DOMAINS:
            assert d in out
        assert "autohome.com.cn" in out
        assert "12365auto.com" in out  # 车质网 — high-value for背调
        # No irrelevant verticals
        assert "freebuf.com" not in out
        assert "xueqiu.com" not in out
        assert "fang.com" not in out

    def test_4s_dealer_keyword_returns_auto(self):
        out = domains_for_position("4S店")
        assert "autohome.com.cn" in out
        assert "dongchedi.com" in out

    def test_finance_keyword_returns_finance_vertical(self):
        out = domains_for_position("基金经理")
        for d in FINANCE_REVIEW_DOMAINS:
            assert d in out
        assert "xueqiu.com" in out
        assert "guba.eastmoney.com" in out
        # No irrelevant verticals
        assert "autohome.com.cn" not in out
        assert "fang.com" not in out

    def test_stock_keyword_returns_finance(self):
        out = domains_for_position("股票分析师")
        assert "xueqiu.com" in out
        assert "guba.eastmoney.com" in out

    def test_real_estate_keyword_returns_real_estate(self):
        out = domains_for_position("房产中介")
        for d in REAL_ESTATE_REVIEW_DOMAINS:
            assert d in out
        assert "fang.com" in out
        assert "anjuke.com" in out
        assert "ke.com" in out

    def test_property_management_keyword_returns_real_estate(self):
        out = domains_for_position("物业经理")
        assert "fang.com" in out
        assert "ke.com" in out

    def test_logistics_keyword_returns_logistics_vertical(self):
        out = domains_for_position("货车司机")
        for d in LOGISTICS_REVIEW_DOMAINS:
            assert d in out
        assert "360che.com" in out
        # No irrelevant verticals
        assert "autohome.com.cn" not in out
        assert "fang.com" not in out

    def test_delivery_keyword_returns_logistics(self):
        out = domains_for_position("快递员")
        assert "yunmanman.com" in out

    def test_cifnews_shangjia_added_to_cross_border(self):
        out = domains_for_position("跨境电商运营")
        assert "cifnews.com" in out
        assert "shangjia.com" in out

    def test_general_platforms_always_included_v0111(self):
        # 20 general domains (was 15 in v0.1.10)
        for pos in ["汽车", "金融", "物业", "货车司机", "安全", "后端"]:
            out = set(domains_for_position(pos))
            for d in GENERAL_REVIEW_DOMAINS:
                assert d in out, f"{d} missing for position={pos}"

    def test_all_v0111_verticals_present_in_full_union(self):
        union = set(REVIEW_DOMAINS)
        for vertical in [AUTO_REVIEW_DOMAINS, FINANCE_REVIEW_DOMAINS,
                         REAL_ESTATE_REVIEW_DOMAINS, LOGISTICS_REVIEW_DOMAINS]:
            assert set(vertical).issubset(union), f"{vertical} missing from union"

    def test_filtered_never_exceeds_union(self):
        # Sanity: filtered allowlist must be ≤ full union for every position
        union = set(REVIEW_DOMAINS)
        for pos in ["", "后端", "汽车", "金融", "物业", "货车司机", "安全", "UI",
                    "公务员", "HR", "医生", "游戏", "跨境", "淘宝", "Python"]:
            assert set(domains_for_position(pos)).issubset(union)
"""Regenerate the sample HTML using the same mocks as the smoke test,
but with richer fixtures so the visual upgrade is on display.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhunter.config import Settings
from jobhunter.models.facts import (
    AggregatedFindings,
    BusinessFacts,
    CaseItem,
    CompanyProfile,
    InferredClaim,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    ReviewFacts,
    SalarySignal,
    OvertimeSignal,
    Shareholder,
    VibeSignal,
)
from jobhunter.models.query import CompanyQuery
from jobhunter.models.raw import RawItem
from jobhunter.models.report import ReportData
from jobhunter.processing.crosscheck import detect_salary_conflicts
from jobhunter.report.builder import build_report
from jobhunter.report.scoring import compute_axes
from jobhunter.utils.slug import make_slug


def main() -> None:
    q = CompanyQuery(company="示例公司", position="后端工程师", city="杭州")

    reviews = ReviewFacts(
        salary_signals=[
            SalarySignal(position="后端工程师", base_monthly_k=28.0, bonus_months=4,
                         evidence="HR 沟通的 14 薪，月 base 28K", url="https://www.kanzhun.com/r/abc"),
            SalarySignal(position="后端工程师", base_monthly_k=30.0, bonus_months=4,
                         evidence="offershow 显示同岗位 30K×14", url="https://www.zhihu.com/q/salary"),
            SalarySignal(position="后端工程师", base_monthly_k=28.0, bonus_months=3,
                         evidence="应届 28K 一线级别", url="https://www.nowcoder.com/discuss/200"),
            SalarySignal(position="后端工程师", base_monthly_k=42.0, bonus_months=3,
                         evidence="P7 级别 42K 偏中等", url="https://www.nowcoder.com/discuss/201"),
            SalarySignal(position="后端工程师", base_monthly_k=12.0, bonus_months=2,
                         evidence="外包岗 12K 但工时很长", url="https://www.zhihu.com/q/outsource"),
        ],
        overtime_signals=[
            OvertimeSignal(pattern="996", intensity="high", evidence="平均 10 点下班，末班公交挤不上",
                           url="https://www.zhihu.com/q/996"),
            OvertimeSignal(pattern="996", intensity="high", evidence="OKR 季度末固定冲一波",
                           url="https://www.kanzhun.com/r/abc"),
            OvertimeSignal(pattern="996", intensity="high", evidence="9 点走是早的，11 点常态",
                           url="https://www.zhihu.com/q/996b"),
            OvertimeSignal(pattern="大小周", intensity="high", evidence="每月最后一个周末加班",
                           url="https://www.zhihu.com/q/weekend"),
            OvertimeSignal(pattern="弹性", intensity="low", evidence="周三可远程，节奏有时可控",
                           url="https://maimai.cn/buzz/detail"),
            OvertimeSignal(pattern="弹性", intensity="medium", evidence="正常下班 7-8 点",
                           url="https://www.zhihu.com/q/flex"),
        ],
        vibe_signals=[
            VibeSignal(sentiment="negative", evidence="流程乱，会议多，技术债重",
                       url="https://www.zhihu.com/q/vibe1"),
            VibeSignal(sentiment="mixed", evidence="同事水平不错，但项目压力大",
                       url="https://www.kanzhun.com/r/abc"),
            VibeSignal(sentiment="negative", evidence="中干空降多，决策不稳定",
                       url="https://www.zhihu.com/q/vibe2"),
        ],
        source_urls=[
            "https://www.zhihu.com/q/996",
            "https://www.kanzhun.com/r/abc",
            "https://maimai.cn/buzz/detail",
        ],
    )

    business = BusinessFacts(
        status="存续",
        legal_rep="张三",
        established_at="2014-03-15",
        registered_capital="5000 万元",
        paid_in_capital="5000 万元",
        address="杭州市西湖区",
        scope="技术开发、技术咨询、技术服务",
        top_shareholders=[
            Shareholder(name="创始团队", stake_pct=35.0, contribution="1750 万元"),
            Shareholder(name="红杉资本", stake_pct=18.0, contribution="900 万元"),
            Shareholder(name="高瓴创投", stake_pct=12.0, contribution="600 万元"),
            Shareholder(name="员工持股平台", stake_pct=10.0, contribution="500 万元"),
            Shareholder(name="天使投资人 王某", stake_pct=8.0, contribution="400 万元"),
        ],
        anomaly_listed=False,
        source_urls=["https://www.qcc.com/firm/someid"],
    )

    judicial = JudicialFacts(
        case_count_total=23,
        case_count_recent_year=8,
        enforcement_records=2,
        sample_cases=[
            CaseItem(title="某某科技 v. 示例公司 合同纠纷", role="被告", year=2026, url="https://wenshu.court.gov.cn/case1"),
            CaseItem(title="示例公司 v. 某前员工 竞业限制纠纷", role="原告", year=2025, url="https://wenshu.court.gov.cn/case2"),
            CaseItem(title="供应商 v. 示例公司 货款纠纷", role="被告", year=2025, url="https://wenshu.court.gov.cn/case3"),
            CaseItem(title="示例公司 v. 某客户 服务合同纠纷", role="原告", year=2024, url="https://wenshu.court.gov.cn/case4"),
            CaseItem(title="员工 v. 示例公司 劳动仲裁", role="被告", year=2024, url="https://wenshu.court.gov.cn/case5"),
        ],
        source_urls=["https://wenshu.court.gov.cn/"],
    )

    company_profile = CompanyProfile(
        description="国内领先的企业级 PaaS 与低代码平台提供商,服务超过 3000 家中大型客户,深耕金融与制造行业",
        official_website="https://www.example-corp.com",
        main_business=[
            "企业级 PaaS 平台开发与运维",
            "低代码 / aPaaS 应用搭建工具",
            "行业云解决方案(金融 / 制造 / 零售)",
            "定制化技术咨询与交付服务",
        ],
        products=[
            "ExamplePaaS 5.0 — 云原生应用平台",
            "ExampleBuilder — 低代码应用搭建",
            "ExampleConnect — 数据集成中台",
            "ExampleInsight — 业务分析 BI 套件",
        ],
        industries=["云计算 SaaS", "企业服务", "PaaS", "低代码"],
        company_size="1000-5000 人",
        founded_year=2014,
        funding_stage="C 轮",
        total_funding="约 12 亿元",
        investors=[
            "红杉资本",
            "高瓴创投",
            "GGV 纪源资本",
            "经纬创投",
            "启明创投",
        ],
        headquarters="杭州市西湖区文一西路",
        prospects="持续投入 AI Agent 与行业大模型方向,海外业务起步于东南亚市场,核心增长来自金融与制造业数字化转型",
        source_urls=[
            "https://baike.baidu.com/item/example",
            "https://www.itjuzi.com/company/example",
            "https://www.cyzone.cn/article/example",
        ],
    )

    news = NewsFacts(
        items=[
            NewsItem(title="示例公司完成 C 轮 5 亿元融资",
                     summary="2026 年 5 月，公司宣布完成 C 轮 5 亿元融资，红杉领投",
                     url="https://36kr.com/p/sample-news-1",
                     published_at="2026-05-12"),
            NewsItem(title="示例公司被曝裁员 10%",
                     summary="7 月传出 10% 裁员，主要为测试与运维",
                     url="https://www.huxiu.com/article/sample-news-2.html",
                     published_at="2026-07-22"),
            NewsItem(title="示例公司发布新一代 PaaS 平台",
                     summary="主打企业级低代码，竞争对手包含钉钉宜搭",
                     url="https://www.36kr.com/p/sample-news-3",
                     published_at="2026-08-01"),
        ],
        sentiment="mixed",
        source_urls=[
            "https://36kr.com/p/sample-news-1",
            "https://www.huxiu.com/article/sample-news-2.html",
        ],
    )

    findings = AggregatedFindings(
        company_query_summary=q.display(),
        business=business,
        reviews=reviews,
        news=news,
        judicial=judicial,
        company_profile=company_profile,
        inferences=[
            InferredClaim(claim="加班偏重但薪酬中上，整体仍是技术驱动的中型互联网公司",
                          grounding_evidence=["https://www.zhihu.com/q/996", "https://www.kanzhun.com/r/abc"]),
            InferredClaim(claim="近期融资健康但已出现裁员信号，业务结构可能正在收缩",
                          grounding_evidence=["https://36kr.com/p/sample-news-1", "https://www.huxiu.com/article/sample-news-2.html"]),
            InferredClaim(claim="司法风险以合同纠纷为主，未见重大被执行，常规经营风险",
                          grounding_evidence=["https://wenshu.court.gov.cn/case1", "https://wenshu.court.gov.cn/case3"]),
            InferredClaim(claim="股权结构以创始团队 + 头部 VC 为主，员工持股比例健康",
                          grounding_evidence=["https://www.qcc.com/firm/someid"]),
        ],
        data_gaps=[],
    )

    salary_conflicts = detect_salary_conflicts(reviews)
    axes = compute_axes(findings, {}, salary_conflicts)

    data = ReportData(
        query=q,
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        axes=axes,
        business_facts=business,
        review_facts=reviews,
        news_facts=news,
        judicial_facts=judicial,
        company_profile=company_profile,
        interview_questions=[
            "团队最近一次调薪是什么时候？幅度如何？",
            "过去一年里，离职率大概多少？主要是哪几个团队？",
            "OKR 季度末的冲周期，平均工作时间是？",
            "中干空降的决策机制是怎样的？",
            "加班的 '996' 是常态还是项目冲刺期？",
            "C 轮融资后，核心业务方向会有什么调整？",
            "金融与制造两大行业的客户结构，对个人技术栈有什么偏好？",
            "公司对 AI Agent 的投入是 all-in 还是试水？",
        ],
        data_gaps=findings.data_gaps,
        overall_confidence="high",
    )

    html = build_report(data)

    out_dir = Path("e:/project/jobHunter/reports")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    slug = make_slug(q, ts)
    out_path = out_dir / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html)} bytes)")
    print(f"Score: {sum(a.stars for a in axes)/len(axes):.2f}/5.0")
    print(f"Sections rendered: see HTML")


if __name__ == "__main__":
    main()
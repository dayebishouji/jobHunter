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
    InferredClaim,
    JudicialFacts,
    NewsFacts,
    NewsItem,
    ReviewFacts,
    SalarySignal,
    OvertimeSignal,
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
        top_shareholders=[],
        anomaly_listed=False,
        source_urls=["https://www.qcc.com/firm/someid"],
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
        inferences=[
            InferredClaim(claim="加班偏重但薪酬中上，整体仍是技术驱动的中型互联网公司",
                          grounding_evidence=["https://www.zhihu.com/q/996", "https://www.kanzhun.com/r/abc"]),
            InferredClaim(claim="近期融资健康但已出现裁员信号，业务结构可能正在收缩",
                          grounding_evidence=["https://36kr.com/p/sample-news-1", "https://www.huxiu.com/article/sample-news-2.html"]),
        ],
        data_gaps=["司法数据未能获取（本机 gsxt 不可达，建议人工到 wenshu.court.gov.cn 核查）"],
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
        judicial_facts=None,
        interview_questions=[
            "团队最近一次调薪是什么时候？幅度如何？",
            "过去一年里，离职率大概多少？主要是哪几个团队？",
            "OKR 季度末的冲周期，平均工作时间是？",
            "中干空降的决策机制是怎样的？",
            "加班的 '996' 是常态还是项目冲刺期？",
            "C 轮融资后，核心业务方向会有什么调整？",
        ],
        data_gaps=findings.data_gaps,
        overall_confidence="medium",
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
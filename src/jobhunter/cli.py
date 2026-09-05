"""jobHunter CLI — Click entrypoint with InquirerPy interactive prompts."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from InquirerPy import inquirer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from jobhunter import __version__
from jobhunter.config import load_settings
from jobhunter.models.query import CompanyQuery
from jobhunter.pipeline import ReportArtifacts, run
from jobhunter import watchlist


def _force_utf8_stdio() -> None:
    """Chinese Windows defaults to GBK codec which crashes on Rich's spinner
    Unicode chars (U+2834 braille pattern, etc.). Reconfigure stdout/stderr to
    UTF-8 with 'replace' fallback before any Rich object is constructed.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError, ValueError):
            pass


_force_utf8_stdio()

# legacy_windows=False keeps Rich from using the GBK-failing Windows console renderer
console = Console(legacy_windows=False)
err_console = Console(stderr=True, legacy_windows=False)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


# ---------- interactive prompt helpers ----------

def _ask_query_interactive() -> CompanyQuery | None:
    """Run InquirerPy prompt sequence. None on Ctrl-C / abort."""
    try:
        company = inquirer.text(
            message="公司名（必填）:",
            validate=lambda s: len(s.strip()) > 0 or "公司名不能为空",
        ).execute()
        if not company:
            return None
        position = inquirer.text(message="岗位（可回车跳过）:").execute() or ""
        city = inquirer.text(message="城市（可回车跳过）:").execute() or ""
        include_judicial = inquirer.confirm(
            message="包含司法风险（耗时稍长）?", default=True
        ).execute()
        include_news = inquirer.confirm(
            message="包含近期舆情?", default=True
        ).execute()
        confirm = inquirer.confirm(
            message=f"即将对『{company}』进行背调，是否继续?",
            default=True,
        ).execute()
    except KeyboardInterrupt:
        return None
    if not confirm:
        return None
    return CompanyQuery(
        company=company.strip(),
        position=position.strip(),
        city=city.strip(),
        include_judicial=include_judicial,
        include_news=include_news,
    )


def _ask_open_browser(path: Path) -> bool:
    try:
        return bool(
            inquirer.confirm(
                message=f"报告已写入 {path}，是否立即在浏览器中打开?",
                default=True,
            ).execute()
        )
    except KeyboardInterrupt:
        return False


# ---------- main flow ----------

async def _execute(
    query: CompanyQuery,
    *,
    output_dir: Path | None,
    open_browser: bool,
    progress_cb,
) -> ReportArtifacts:
    """Wrap pipeline.run() with progress reporting."""
    return await run(query, output_dir=output_dir, open_browser=False)  # we open manually below


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__, prog_name="jobhunter")
def main(ctx: click.Context) -> None:
    """jobHunter — 公司反向背调 CLI。"""
    _setup_logging()
    if ctx.invoked_subcommand is not None:
        return
    # Default: interactive flow
    asyncio.run(_interactive_flow())


async def _interactive_flow() -> None:
    settings = load_settings()
    ok, missing = settings.is_ready()
    if not ok:
        err_console.print(
            f"[red]缺少 API key：[/red]{', '.join(missing)}\\n"
            "请在 .env 中配置（参考 .env.example），或 export ANTHROPIC_API_KEY / TAVILY_API_KEY。"
        )
        raise click.exceptions.Exit(code=2)

    # InquirerPy → prompt_toolkit's Application.run() internally calls asyncio.run(),
    # which is illegal to nest inside our own running loop (Python 3.14 enforces this).
    # Run prompts in a worker thread so they get their own fresh loop.
    loop = asyncio.get_running_loop()
    query = await loop.run_in_executor(None, _ask_query_interactive)
    if query is None:
        raise click.exceptions.Exit(code=0)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("启动...", total=5)
        try:
            progress.update(task, description="[1/5] 工商信息 + 司法", total=5, completed=1)
            progress.update(task, description="[2/5] 评价（看准/脉脉/知乎）", completed=2)
            progress.update(task, description="[3/5] 舆情（36氪/虎嗅/微博）", completed=3)
            progress.update(task, description="[4/5] LLM 抽取与综合", completed=4)
            progress.update(task, description="[5/5] 生成报告", completed=4)
            artifacts = await run(query)
        except Exception as e:  # noqa: BLE001
            progress.update(task, description="[red]失败")
            err_console.print(f"[red]失败：[/red]{e}")
            raise click.exceptions.Exit(code=1)
        progress.update(task, description="完成", completed=5)

    console.print(f"[green]✓[/green] 报告生成：{artifacts.path}")
    console.print(f"  耗时成本：约 ${artifacts.cost_usd:.4f}（输入 {artifacts.tokens_in} / 输出 {artifacts.tokens_out} tokens）")
    if query.aliases:
        console.print(f"  reviews 域额外搜索别名：{', '.join(query.aliases)}")

    if await loop.run_in_executor(None, _ask_open_browser, artifacts.path):
        from jobhunter.utils.browser import open_in_browser
        open_in_browser(artifacts.path)


@main.command()
@click.option("--company", "-c", required=True, help="公司名（必填）")
@click.option("--position", "-p", default="", help="岗位")
@click.option("--city", "-y", default="", help="城市")
@click.option("--no-judicial", is_flag=True, default=False, help="跳过司法")
@click.option("--no-news", is_flag=True, default=False, help="跳过新闻")
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path), help="输出目录")
@click.option("--no-open", is_flag=True, default=False, help="不自动打开浏览器")
@click.option("--compare", default="", help="同行业对比公司（逗号分隔，如「美团,京东」）；每多 1 家 ≈ 多 1 次轻量级 pipeline")
@click.option("--jd", "jd_text", default=None, help="JD 文本（可选）。提供后报告会自动与公司真实数据交叉验证")
@click.option("--jd-file", "jd_file", default=None, type=click.Path(exists=True, path_type=Path), help="JD 文件路径（与 --jd 二选一）")
@click.option("--print", "print_pdf", is_flag=True, default=False, help="生成后自动打开浏览器并触发打印对话框（用户可保存为 PDF / 实际打印）")
def run_cmd(
    company: str,
    position: str,
    city: str,
    no_judicial: bool,
    no_news: bool,
    output: Path | None,
    no_open: bool,
    compare: str,
    jd_text: str | None,
    jd_file: Path | None,
    print_pdf: bool,
) -> None:
    """非交互模式（脚本友好）。"""
    _setup_logging()
    settings = load_settings()
    ok, missing = settings.is_ready()
    if not ok:
        err_console.print(f"[red]缺少 API key：[/red]{', '.join(missing)}")
        raise click.exceptions.Exit(code=2)

    if jd_text and jd_file:
        err_console.print("[red]--jd 与 --jd-file 二选一[/red]")
        raise click.exceptions.Exit(code=2)
    if jd_file:
        jd_text = jd_file.read_text(encoding="utf-8").strip() or None

    q = CompanyQuery(
        company=company,
        position=position,
        city=city,
        include_judicial=not no_judicial,
        include_news=not no_news,
        jd_text=jd_text,
    )
    peer_names = [n.strip() for n in compare.split(",") if n.strip()] if compare else []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("运行中...", total=None)
        try:
            artifacts = asyncio.run(
                run(q, output_dir=output, open_browser=False, peer_names=peer_names)
            )
        except Exception as e:  # noqa: BLE001
            # Rich's Windows legacy renderer can UnicodeEncodeError on GBK consoles
            # when flushing buffered error text. Fall back to plain print so the
            # user always sees what went wrong.
            msg = f"失败：{e}"
            try:
                err_console.print(f"[red]{msg}[/red]")
            except (UnicodeEncodeError, UnicodeError):  # noqa: PERF203
                print(msg, file=sys.stderr)
            raise click.exceptions.Exit(code=1)
        progress.update(task, description="完成")

    console.print(f"[green]✓[/green] {artifacts.path}")
    if q.aliases:
        console.print(f"  reviews 域额外搜索别名：{', '.join(q.aliases)}")
    if not no_open or print_pdf:
        from jobhunter.utils.browser import open_in_browser
        open_in_browser(artifacts.path)

    if print_pdf:
        # v0.1.17 — append ?print=1 to URL; the inline JS picks it up and calls
        # window.print() once the page is ready. User then Ctrl+Enter or clicks
        # "Save as PDF" in the resulting dialog. Zero external deps.
        try:
            import webbrowser
            webbrowser.open(artifacts.path.as_uri() + "?print=1", new=2)
        except Exception as e:  # noqa: BLE001
            err_console.print(f"[yellow]?print=1 触发失败：[/yellow]{e}")

    # v0.1.17 — touch watchlist entry if present (best-effort).
    try:
        watchlist.mark_ran(q.company)
    except Exception:  # noqa: BLE001
        pass


# Subcommand alias: both `jobhunter run` and `jobhunter check` work
main.add_command(run_cmd, name="run")
main.add_command(run_cmd, name="check")


# ---------- v0.3.1 — batch mode ----------

from jobhunter.batch import build_batch_report_html, parse_batch_file, run_batch  # noqa: E402
from jobhunter.batch import BatchMeta  # noqa: E402
from jobhunter.utils.slug import batch_dir_slug  # noqa: E402


@main.command(name="batch")
@click.option("--file", "-f", required=True, type=click.Path(exists=True, path_type=Path), help="CSV 文件路径（一行一公司：`公司,岗位,城市`，# 开头为注释）")
@click.option("--city", "-y", default="", help="默认城市（行内未填 city 时使用）")
@click.option("--no-judicial", is_flag=True, default=False, help="跳过司法")
@click.option("--no-news", is_flag=True, default=False, help="跳过新闻")
@click.option("--jd", "jd_text", default=None, help="JD 文本（可选，所有公司共用）")
@click.option("--jd-file", "jd_file", default=None, type=click.Path(exists=True, path_type=Path), help="JD 文件路径")
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path), help="per-company 报告输出目录（默认 reports/）")
@click.option("--batch-out", "-O", default=None, type=click.Path(path_type=Path), help="聚合页输出目录（默认 reports/batch/{file_stem}-{ts}/）")
@click.option("--batch-concurrency", default=3, type=int, help="并发上限（asyncio.Semaphore，默认 3）")
@click.option("--strict", is_flag=True, default=False, help="fail-fast：任一公司失败立即 abort（默认 best-effort）")
@click.option("--no-open", is_flag=True, default=False, help="不自动打开聚合页")
@click.option("--print", "print_pdf", is_flag=True, default=False, help="生成后触发 ?print=1")
def batch_cmd(
    file: Path,
    city: str,
    no_judicial: bool,
    no_news: bool,
    jd_text: str | None,
    jd_file: Path | None,
    output: Path | None,
    batch_out: Path | None,
    batch_concurrency: int,
    strict: bool,
    no_open: bool,
    print_pdf: bool,
) -> None:
    """批量跑多家公司（CSV 文件输入），生成 per-company 报告 + 横向对比聚合页。

    文件格式：`公司,岗位,城市` 一行一个；# 开头为注释；空行跳过。
    并发上限默认 3（asyncio.Semaphore）；失败默认 best-effort（--strict 改 fail-fast）。
    """
    _setup_logging()
    settings = load_settings()
    ok, missing = settings.is_ready()
    if not ok:
        err_console.print(f"[red]缺少 API key：[/red]{', '.join(missing)}")
        raise click.exceptions.Exit(code=2)

    if jd_text and jd_file:
        err_console.print("[red]--jd 与 --jd-file 二选一[/red]")
        raise click.exceptions.Exit(code=2)
    if jd_file:
        jd_text = jd_file.read_text(encoding="utf-8").strip() or None

    # Parse batch file → list of queries
    try:
        queries = parse_batch_file(file, default_city=city)
    except Exception as e:  # noqa: BLE001
        err_console.print(f"[red]无法解析 batch 文件 {file}：[/red]{e}")
        raise click.exceptions.Exit(code=2)

    if not queries:
        err_console.print(f"[red]batch 文件 {file} 没有有效公司行[/red]")
        raise click.exceptions.Exit(code=2)

    console.print(f"[bold]batch 模式[/bold] · 共 {len(queries)} 家公司 · 并发 {batch_concurrency} · 源文件 {file.name}")
    for q in queries:
        console.print(f"  • {q.company} · {q.position or '—'} · {q.city or '—'}")

    # Compute output dirs
    per_company_dir = output or settings.output_dir
    per_company_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d-%H%M")
    batch_dir_name = batch_dir_slug(file, ts)
    batch_dir = batch_out or (per_company_dir / "batch" / batch_dir_name)
    batch_dir.mkdir(parents=True, exist_ok=True)

    # Run with progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"并发 {batch_concurrency} 路跑 {len(queries)} 家公司...", total=len(queries))
        try:
            results = asyncio.run(
                run_batch(
                    queries,
                    settings=settings,
                    output_dir=per_company_dir,
                    batch_out_dir=batch_dir,
                    concurrency=batch_concurrency,
                    include_judicial=not no_judicial,
                    include_news=not no_news,
                    jd_text=jd_text,
                )
            )
            # Update progress as results come in (best-effort: just mark all done)
            for _ in results:
                progress.update(task, advance=1)
        except Exception as e:  # noqa: BLE001
            progress.update(task, description="[red]失败")
            err_console.print(f"[red]batch run 失败：[/red]{e}")
            raise click.exceptions.Exit(code=1)

    # Strict mode: any failure → exit 1
    if strict and any(r.status == "failed" for r in results):
        failed_names = [r.company for r in results if r.status == "failed"]
        err_console.print(f"[red]--strict 模式下失败：[/red]{', '.join(failed_names)}")
        raise click.exceptions.Exit(code=1)

    # Build aggregate HTML
    successes = [r for r in results if r.status == "success"]
    failures = [r for r in results if r.status == "failed"]
    meta = BatchMeta(
        source_file=file.name,
        run_count=len(results),
        success_count=len(successes),
        failed_count=len(failures),
        total_cost_usd=round(sum(r.cost_usd for r in results), 4),
        total_tokens_in=sum(r.tokens_in for r in results),
        total_tokens_out=sum(r.tokens_out for r in results),
        generated_at=ts,
    )
    html = build_batch_report_html(results, meta)
    index_path = batch_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    # Summary
    console.print(f"[green]✓[/green] 完成 · 成功 {len(successes)} / 失败 {len(failures)}")
    console.print(f"  聚合页：{index_path}")
    console.print(f"  总成本：约 ${meta.total_cost_usd:.4f}（输入 {meta.total_tokens_in} / 输出 {meta.total_tokens_out} tokens）")
    if not no_open or print_pdf:
        from jobhunter.utils.browser import open_in_browser
        open_in_browser(index_path)

    if print_pdf:
        try:
            import webbrowser
            webbrowser.open(index_path.as_uri() + "?print=1", new=2)
        except Exception as e:  # noqa: BLE001
            err_console.print(f"[yellow]?print=1 触发失败：[/yellow]{e}")


# ---------- v0.1.17 — watchlist subcommands ----------

@click.group()
def watch_group() -> None:
    """管理 watchlist（持久化的关注公司列表）。"""


@watch_group.command(name="add")
@click.option("--company", "-c", required=True, help="公司名")
@click.option("--position", "-p", default="", help="岗位")
@click.option("--city", "-y", default="", help="城市")
def watch_add(company: str, position: str, city: str) -> None:
    """把公司加入 watchlist（持久化在 user cache 目录）。"""
    try:
        entry = watchlist.add(company, position, city)
    except ValueError as e:
        err_console.print(f"[red]{e}[/red]")
        raise click.exceptions.Exit(code=2)
    console.print(f"[green]✓[/green] 已加入 watchlist：{entry.display()}")
    console.print(f"  列表文件：{watchlist.path_for_display()}")


@watch_group.command(name="list")
def watch_list() -> None:
    """列出 watchlist 中所有公司。"""
    entries = watchlist.list_entries()
    if not entries:
        console.print("[yellow]watchlist 为空[/yellow] — `jobhunter watch add -c <公司名>` 加入第一项")
        return
    console.print(f"[bold]{len(entries)} 家公司：[/bold]")
    for e in entries:
        last = f" · 上次跑：{e.last_run_at[:10]}" if e.last_run_at else " · 未跑过"
        console.print(f"  • {e.display()}{last}")


@watch_group.command(name="remove")
@click.option("--company", "-c", required=True, help="公司名（精确匹配）")
def watch_remove(company: str) -> None:
    """从 watchlist 中移除公司。"""
    if watchlist.remove(company):
        console.print(f"[green]✓[/green] 已移除 {company}")
    else:
        console.print(f"[yellow]{company} 不在 watchlist 中[/yellow]")


main.add_command(watch_group)


if __name__ == "__main__":
    main()

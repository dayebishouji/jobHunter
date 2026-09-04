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
def run_cmd(
    company: str,
    position: str,
    city: str,
    no_judicial: bool,
    no_news: bool,
    output: Path | None,
    no_open: bool,
    compare: str,
) -> None:
    """非交互模式（脚本友好）。"""
    _setup_logging()
    settings = load_settings()
    ok, missing = settings.is_ready()
    if not ok:
        err_console.print(f"[red]缺少 API key：[/red]{', '.join(missing)}")
        raise click.exceptions.Exit(code=2)

    q = CompanyQuery(
        company=company,
        position=position,
        city=city,
        include_judicial=not no_judicial,
        include_news=not no_news,
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
    if not no_open:
        from jobhunter.utils.browser import open_in_browser
        open_in_browser(artifacts.path)


# Subcommand alias: both `jobhunter run` and `jobhunter check` work
main.add_command(run_cmd, name="run")
main.add_command(run_cmd, name="check")


if __name__ == "__main__":
    main()

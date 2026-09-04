"""CLI smoke tests — catches import-time regressions.

v0.1.17 had a bug where `@watch_group.command(...)` ran at import time before
`watch_group` itself was defined, raising NameError before any test even ran.
This file imports the CLI module end-to-end and verifies the watch group
has all 3 subcommands attached.
"""

from __future__ import annotations

import pytest


def test_cli_module_imports_cleanly():
    """Importing jobhunter.cli must not raise — guards against decorator-order bugs."""
    import jobhunter.cli  # noqa: F401


def test_main_has_watch_group_with_three_subcommands():
    from jobhunter.cli import main

    # main is a click.Group
    assert hasattr(main, "commands")
    assert "watch" in main.commands
    watch = main.commands["watch"]
    # watch is a click.Group with add/list/remove attached
    cmd_names = set(watch.commands.keys())
    assert cmd_names == {"add", "list", "remove"}


def test_version_string_matches_pyproject():
    """`jobhunter --version` must report the same version as pyproject.toml.
    v0.1.17 shipped with __init__.py stuck at 0.1.4 — this catches that drift."""
    import tomllib
    from jobhunter.cli import main
    from click.testing import CliRunner

    pyproject = tomllib.loads(open("pyproject.toml", encoding="utf-8").read())
    expected = pyproject["project"]["version"]

    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert expected in result.output, f"--version output '{result.output}' missing '{expected}'"
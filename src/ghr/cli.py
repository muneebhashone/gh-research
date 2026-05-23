"""The `ghr` CLI root: global flags, lazy context, and command-group wiring."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import typer

from ghr import __version__
from ghr.commands import auth as auth_cmd
from ghr.commands import cache as cache_cmd
from ghr.commands import discussions as discussions_cmd
from ghr.commands import issues as issues_cmd
from ghr.commands import repos as repos_cmd
from ghr.commands import research as research_cmd
from ghr.commands._common import CliState, app_context, finish

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    help="GitHub Issues & Discussions research for AI agents. JSON output by default.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


@app.callback()
def main(
    ctx: typer.Context,
    token: str = typer.Option(None, "--token", help="GitHub token (overrides env / gh CLI)."),
    token_source: str = typer.Option(
        None, "--token-source", help="Force token origin: none (unauth) | auto (default)."
    ),
    json_output: bool = typer.Option(None, "--json/--no-json", help="Force JSON or human output."),
    jq: str = typer.Option(None, "--jq", help="Filter JSON output with a jq program."),
    quiet_meta: bool = typer.Option(
        False, "--quiet-meta", help="Drop the meta block to save tokens."
    ),
    full: bool = typer.Option(False, "--full", help="Do not trim item bodies."),
    limit: int = typer.Option(None, "--limit", help="Default result count for lists/searches."),
    body_chars: int = typer.Option(None, "--body-chars", help="Body trim length (default 500)."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the local cache."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-refresh cached entries."),
    max_requests: int = typer.Option(None, "--max-requests", help="Per-command request budget."),
    time_budget_ms: int = typer.Option(
        None, "--time-budget-ms", help="Per-command time budget (ms)."
    ),
    config: Path = typer.Option(None, "--config", help="Path to a config.toml."),
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Build the (lazy) application context from global flags."""
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    cli = {
        "token": token,
        "token_source": token_source,
        "json": json_output,
        "jq": jq,
        "quiet_meta": quiet_meta,
        "full": full,
        "no_cache": no_cache,
        "refresh": refresh,
        "default_limit": limit,
        "body_char_cap": body_chars,
        "max_requests": max_requests,
        "time_budget_ms": time_budget_ms,
    }
    ctx.obj = CliState(cli=cli, config_path=config)


@app.command("rate")
def rate(ctx: typer.Context) -> None:
    """Show per-resource rate-limit budgets (GET /rate_limit)."""
    actx = app_context(ctx)
    finish(
        actx,
        command="rate",
        params={},
        resource=None,
        work=lambda: (actx.client.get_json("/rate_limit", resource="core", ttl=0).data, {}),
    )


app.add_typer(research_cmd.app, name="research")
app.add_typer(repos_cmd.app, name="repo")
app.add_typer(issues_cmd.app, name="issues")
app.add_typer(discussions_cmd.app, name="discussions")
app.add_typer(auth_cmd.app, name="auth")
app.add_typer(cache_cmd.app, name="cache")

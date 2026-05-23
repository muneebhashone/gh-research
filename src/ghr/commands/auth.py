"""`ghr auth …` — token status and storage. Never prints the raw token."""

from __future__ import annotations

import sys
from typing import Any

import typer

from ghr.auth.resolver import mask
from ghr.auth.store import (
    delete_config_token,
    keyring_delete,
    keyring_set,
    write_config_token,
)
from ghr.commands._common import app_context, finish
from ghr.github.errors import GhrError, UsageError

app = typer.Typer(no_args_is_help=True, help="Authentication status & token storage.")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Report whether a token is available, its source, and a masked hint."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        data: dict[str, Any] = {
            "authenticated": actx.has_token,
            "source": actx.token.source.value,
            "token_hint": mask(actx.token.token),
        }
        if actx.has_token:
            try:
                actx.client.get_json("/rate_limit", resource="core", ttl=0)
                data["connectivity_ok"] = True
            except GhrError as exc:
                data["connectivity_ok"] = False
                data["connectivity_error"] = exc.code
        return data, {}

    finish(actx, command="auth status", params={}, resource="core", work=work)


@app.command("login")
def login(
    ctx: typer.Context,
    token: str = typer.Option(None, "--token", help="Token value; omit to read stdin / prompt."),
    use_keyring: bool = typer.Option(True, "--keyring/--no-keyring"),
) -> None:
    """Store a token (OS keyring if available, else the config file)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        value = token
        if not value:
            value = (
                typer.prompt("GitHub token", hide_input=True)
                if sys.stdin.isatty()
                else sys.stdin.readline().strip()
            )
        if not value:
            raise UsageError("No token provided.", suggestion="Pass --token or pipe it on stdin.")
        if use_keyring and keyring_set(value):
            location = "keyring"
        else:
            write_config_token(actx.config_path, value)
            location = str(actx.config_path)
        return {"stored": True, "location": location, "token_hint": mask(value)}, {}

    finish(actx, command="auth login", params={}, resource=None, work=work)


@app.command("logout")
def logout(ctx: typer.Context) -> None:
    """Remove any stored token from the config file and keyring."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        return {
            "removed_config": delete_config_token(actx.config_path),
            "removed_keyring": keyring_delete(),
        }, {}

    finish(actx, command="auth logout", params={}, resource=None, work=work)

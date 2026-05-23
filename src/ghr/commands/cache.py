"""`ghr cache …` — inspect and manage the local SQLite response cache."""

from __future__ import annotations

from typing import Any

import typer

from ghr.cache.store import CacheStore
from ghr.commands._common import app_context, finish

app = typer.Typer(no_args_is_help=True, help="Local response cache control.")


@app.command("stats")
def stats(ctx: typer.Context) -> None:
    """Show cache entry counts, size, and location."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        store = CacheStore(actx.cache_path)
        try:
            return store.stats(), {}
        finally:
            store.close()

    finish(actx, command="cache stats", params={}, resource=None, work=work)


@app.command("clear")
def clear(
    ctx: typer.Context,
    resource: str = typer.Option(None, "--resource", help="Only clear one resource bucket."),
) -> None:
    """Delete cached entries (all, or one resource bucket)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        store = CacheStore(actx.cache_path)
        try:
            return {"cleared": store.clear(resource)}, {}
        finally:
            store.close()

    finish(actx, command="cache clear", params={"resource": resource}, resource=None, work=work)


@app.command("path")
def path(ctx: typer.Context) -> None:
    """Print the resolved cache database path."""
    actx = app_context(ctx)
    finish(
        actx,
        command="cache path",
        params={},
        resource=None,
        work=lambda: ({"path": str(actx.cache_path)}, {}),
    )

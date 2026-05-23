"""`ghr repo …` — repository discovery and health (Tier 2)."""

from __future__ import annotations

from typing import Any

import typer

from ghr.commands._common import app_context, finish, split_repo
from ghr.constants import ttl_for
from ghr.models import normalize_repo

app = typer.Typer(no_args_is_help=True, help="Repository discovery & health.")


def build_repo_query(
    query: str | None,
    *,
    language: str | None,
    topics: list[str],
    min_stars: int | None,
    created: str | None,
    pushed: str | None,
    archived: bool | None,
) -> str:
    parts: list[str] = []
    if query:
        parts.append(query)
    if language:
        parts.append(f"language:{language}")
    parts.extend(f"topic:{topic}" for topic in topics)
    if min_stars is not None:
        parts.append(f"stars:>={min_stars}")
    if created:
        parts.append(f"created:{created}")
    if pushed:
        parts.append(f"pushed:{pushed}")
    if archived is not None:
        parts.append(f"archived:{str(archived).lower()}")
    return " ".join(parts)


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument("", help="Raw query terms (combined with the qualifier flags)."),
    language: str = typer.Option(None, "--language", "-l"),
    topic: list[str] = typer.Option([], "--topic", "-t", help="Repeatable topic qualifier."),
    min_stars: int = typer.Option(None, "--min-stars"),
    created: str = typer.Option(None, "--created", help="e.g. '>2026-01-01'"),
    pushed: str = typer.Option(None, "--pushed", help="e.g. '>2026-05-01'"),
    archived: bool = typer.Option(None, "--archived/--no-archived"),
    sort: str = typer.Option("stars", "--sort", help="stars|forks|updated|help-wanted-issues"),
    order: str = typer.Option("desc", "--order"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """Search repositories (official Search API)."""
    actx = app_context(ctx)
    count = limit or actx.settings.default_limit
    q = build_repo_query(
        query,
        language=language,
        topics=topic,
        min_stars=min_stars,
        created=created,
        pushed=pushed,
        archived=archived,
    )

    def work() -> tuple[Any, dict[str, Any]]:
        page = actx.client.paginate_search(
            "/search/repositories",
            params={"q": q, "sort": sort, "order": order},
            resource="search",
            ttl=ttl_for("search"),
            limit=count,
        )
        repos = [normalize_repo(item, now=actx.now) for item in page.items]
        data = {"query": q, "total_count": page.total_count, "repos": repos}
        extra = {"truncated": page.truncated} if page.truncated else {}
        return data, extra

    finish(
        actx,
        command="repo search",
        params={"q": q, "sort": sort, "limit": count},
        resource="search",
        work=work,
    )


@app.command("view")
def view(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
) -> None:
    """Repository health fields + derived velocity metrics."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        owner, name = split_repo(repo)
        res = actx.client.get_json(f"/repos/{owner}/{name}", resource="repo", ttl=ttl_for("repo"))
        return normalize_repo(res.data, now=actx.now), {}

    finish(actx, command="repo view", params={"repo": repo}, resource="core", work=work)


@app.command("topics")
def topics(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
) -> None:
    """List a repository's topics (discovery helper)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        owner, name = split_repo(repo)
        res = actx.client.get_json(f"/repos/{owner}/{name}", resource="repo", ttl=ttl_for("repo"))
        return {"full_name": res.data.get("full_name"), "topics": res.data.get("topics", [])}, {}

    finish(actx, command="repo topics", params={"repo": repo}, resource="core", work=work)

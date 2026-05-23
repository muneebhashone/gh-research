"""`ghr issues …` — search, list, view, and analyze issues (Tier 2)."""

from __future__ import annotations

from typing import Any

import typer

from ghr.analysis.labels import label_frequency
from ghr.analysis.rank import rank_items
from ghr.commands._common import app_context, finish, split_repo, with_trimmed_body
from ghr.constants import ttl_for
from ghr.context import AppContext
from ghr.github.client import PageResult
from ghr.github.errors import UsageError
from ghr.models import is_pull_request, normalize_issue

app = typer.Typer(no_args_is_help=True, help="Search, list, view, and analyze issues.")

#: Issue-search relevance modes. ``None`` (the default) is GitHub's classic
#: lexical search; ``semantic``/``hybrid`` use the semantic index and carry a
#: stricter 10 req/min, auth-only rate limit (GA April 2026).
SEARCH_TYPES: tuple[str, ...] = ("semantic", "hybrid")


def validate_search_type(value: str | None) -> str | None:
    """Return a normalized search type or raise a usage error for unknown values."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in SEARCH_TYPES:
        raise UsageError(
            f"Invalid --search-type {value!r}.",
            suggestion=f"Use one of: {', '.join(SEARCH_TYPES)} (omit for lexical search).",
        )
    return normalized


def build_issue_query(
    query: str,
    *,
    repo: str | None = None,
    org: str | None = None,
    author: str | None = None,
    labels: list[str] | None = None,
    language: str | None = None,
    state: str | None = None,
    in_: str | None = None,
    created: str | None = None,
    updated: str | None = None,
    min_comments: int | None = None,
    min_reactions: int | None = None,
) -> str:
    """Compose a /search/issues query, always constrained to ``is:issue`` (no PRs)."""
    parts = ["is:issue"]
    if query:
        parts.append(query)
    if repo:
        parts.append(f"repo:{repo}")
    if org:
        parts.append(f"org:{org}")
    if author:
        parts.append(f"author:{author}")
    parts.extend(f'label:"{label}"' for label in labels or [])
    if language:
        parts.append(f"language:{language}")
    if state:
        parts.append(f"state:{state}")
    if in_:
        parts.append(f"in:{in_}")
    if created:
        parts.append(f"created:{created}")
    if updated:
        parts.append(f"updated:{updated}")
    if min_comments is not None:
        parts.append(f"comments:>={min_comments}")
    if min_reactions is not None:
        parts.append(f"reactions:>={min_reactions}")
    return " ".join(parts)


def search_issues(
    actx: AppContext,
    *,
    q: str,
    sort: str | None,
    order: str,
    limit: int,
    search_type: str | None = None,
) -> tuple[list[dict[str, Any]], PageResult]:
    """Run an issue search and return (normalized non-PR issues, raw page).

    ``search_type`` (``semantic``/``hybrid``) opts into GitHub's semantic index;
    when omitted, the classic lexical search runs. Semantic/hybrid results live in
    their own cache bucket since the same ``q`` yields a different result set.
    """
    params: dict[str, Any] = {"q": q, "order": order}
    if sort:
        params["sort"] = sort
    if search_type:
        params["search_type"] = search_type
    resource = "search_semantic" if search_type else "search"
    page = actx.client.paginate_search(
        "/search/issues", params=params, resource=resource, ttl=ttl_for(resource), limit=limit
    )
    items = [normalize_issue(it) for it in page.items if not is_pull_request(it)]
    return items, page


def list_repo_issues(
    actx: AppContext,
    owner: str,
    name: str,
    *,
    state: str,
    labels: str | None,
    sort: str,
    direction: str,
    since: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], PageResult]:
    """List a repo's issues via REST (cheaper than search; PRs filtered out)."""
    params: dict[str, Any] = {"state": state, "sort": sort, "direction": direction}
    if labels:
        params["labels"] = labels
    if since:
        params["since"] = since
    page = actx.client.paginate_list(
        f"/repos/{owner}/{name}/issues",
        params=params,
        resource="issue_list",
        ttl=ttl_for("issue_list"),
        limit=limit,
    )
    items = [normalize_issue(it) for it in page.items if not is_pull_request(it)]
    return items, page


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument("", help="Raw query terms combined with the qualifier flags."),
    repo: str = typer.Option(None, "--repo"),
    org: str = typer.Option(None, "--org"),
    author: str = typer.Option(None, "--author"),
    label: list[str] = typer.Option([], "--label", help="Repeatable."),
    language: str = typer.Option(None, "--language"),
    state: str = typer.Option(None, "--state", help="open|closed"),
    in_: str = typer.Option(None, "--in", help="title|body|comments"),
    created: str = typer.Option(None, "--created"),
    updated: str = typer.Option(None, "--updated"),
    min_comments: int = typer.Option(None, "--min-comments"),
    min_reactions: int = typer.Option(None, "--min-reactions"),
    sort: str = typer.Option(
        None, "--sort", help="comments|reactions|interactions|created|updated"
    ),
    order: str = typer.Option("desc", "--order"),
    search_type: str = typer.Option(
        None,
        "--search-type",
        help="semantic|hybrid (semantic index, auth-only, 10 req/min); omit for lexical.",
    ),
    with_body: bool = typer.Option(False, "--with-body"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """Search issues across GitHub (Search API; is:issue enforced)."""
    actx = app_context(ctx)
    count = limit or actx.settings.default_limit
    q = build_issue_query(
        query,
        repo=repo,
        org=org,
        author=author,
        labels=label,
        language=language,
        state=state,
        in_=in_,
        created=created,
        updated=updated,
        min_comments=min_comments,
        min_reactions=min_reactions,
    )

    def work() -> tuple[Any, dict[str, Any]]:
        mode = validate_search_type(search_type)  # raises UsageError → exit 2 envelope
        items, page = search_issues(
            actx, q=q, sort=sort, order=order, limit=count, search_type=mode
        )
        out = [with_trimmed_body(i, actx, include_body=with_body) for i in items]
        data: dict[str, Any] = {"query": q, "total_count": page.total_count, "issues": out}
        if mode:
            data["search_type"] = mode
        return data, ({"truncated": page.truncated} if page.truncated else {})

    finish(
        actx,
        command="issues search",
        params={"q": q, "sort": sort, "limit": count, "search_type": search_type},
        resource="search",
        work=work,
    )


@app.command("list")
def list_(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    state: str = typer.Option("open", "--state", help="open|closed|all"),
    labels: str = typer.Option(None, "--labels", help="comma-separated label names"),
    sort: str = typer.Option("updated", "--sort", help="created|updated|comments"),
    direction: str = typer.Option("desc", "--direction"),
    since: str = typer.Option(None, "--since", help="ISO timestamp"),
    with_body: bool = typer.Option(False, "--with-body"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """List a repository's issues via REST (cheap; avoids the search rate bucket)."""
    actx = app_context(ctx)
    count = limit or actx.settings.default_limit

    def work() -> tuple[Any, dict[str, Any]]:
        owner, name = split_repo(repo)
        items, page = list_repo_issues(
            actx,
            owner,
            name,
            state=state,
            labels=labels,
            sort=sort,
            direction=direction,
            since=since,
            limit=count,
        )
        out = [with_trimmed_body(i, actx, include_body=with_body) for i in items]
        return {"repo": repo, "issues": out}, (
            {"truncated": page.truncated} if page.truncated else {}
        )

    finish(
        actx,
        command="issues list",
        params={"repo": repo, "state": state, "limit": count},
        resource="core",
        work=work,
    )


@app.command("view")
def view(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    number: int = typer.Argument(...),
    comments: int = typer.Option(0, "--comments", help="Include up to N comments."),
) -> None:
    """View one issue, optionally with its top comments."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        owner, name = split_repo(repo)
        res = actx.client.get_json(
            f"/repos/{owner}/{name}/issues/{number}", resource="issue", ttl=ttl_for("issue")
        )
        item = with_trimmed_body(normalize_issue(res.data), actx, include_body=True)
        if comments > 0:
            page = actx.client.paginate_list(
                f"/repos/{owner}/{name}/issues/{number}/comments",
                params={},
                resource="issue",
                ttl=ttl_for("issue"),
                limit=comments,
            )
            item["comments_list"] = [
                {
                    "user": (c.get("user") or {}).get("login"),
                    "created_at": c.get("created_at"),
                    "body": with_trimmed_body({"body": c.get("body")}, actx, include_body=True)[
                        "body"
                    ],
                }
                for c in page.items
            ]
        return item, {}

    finish(
        actx,
        command="issues view",
        params={"repo": repo, "number": number},
        resource="core",
        work=work,
    )


@app.command("analyze")
def analyze(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    what: str = typer.Option("hot,labels", "--what", help="comma list: hot,labels"),
    state: str = typer.Option("open", "--state"),
    label: list[str] = typer.Option([], "--label"),
    window: int = typer.Option(200, "--window", help="Issues sampled for analysis."),
    top: int = typer.Option(10, "--top"),
) -> None:
    """Aggregate analytics (hot ranking, label frequency) over an issue set."""
    actx = app_context(ctx)
    wanted = {w.strip() for w in what.split(",") if w.strip()}
    q = build_issue_query("", repo=repo, labels=label, state=state)

    def work() -> tuple[Any, dict[str, Any]]:
        items, page = search_issues(actx, q=q, sort="reactions", order="desc", limit=window)
        data: dict[str, Any] = {"repo": repo, "set_size": len(items)}
        if "hot" in wanted:
            ranked = rank_items(items, now=actx.now, weights=actx.settings.weights, top=top)
            data["hot"] = [with_trimmed_body(i, actx, include_body=False) for i in ranked]
        if "labels" in wanted:
            data["labels"] = label_frequency(items)
        extra: dict[str, Any] = {"scoring": {"weights": actx.settings.weights}}
        if page.truncated:
            extra["truncated"] = page.truncated
        return data, extra

    finish(
        actx,
        command="issues analyze",
        params={"repo": repo, "what": what},
        resource="search",
        work=work,
    )

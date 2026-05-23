"""`ghr research …` — opinionated, one-shot Tier-1 commands composing the primitives."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import typer

from ghr.analysis.activity import compute_activity
from ghr.analysis.labels import label_frequency
from ghr.analysis.rank import rank_items
from ghr.commands._common import app_context, finish, require_token, split_repo, with_trimmed_body
from ghr.commands.discussions import fetch_discussions
from ghr.commands.issues import build_issue_query, search_issues
from ghr.commands.repos import build_repo_query
from ghr.constants import CROSS_REPO_REPOS_MAX, ttl_for
from ghr.context import AppContext
from ghr.github.errors import GhrError, UsageError
from ghr.github.ratelimit import BudgetExceeded
from ghr.models import normalize_repo

app = typer.Typer(no_args_is_help=True, help="One-shot research bundles (start here).")

_BUCKET_DAYS = {"day": 1, "week": 7, "month": 30}
_PAIN_LABELS = "bug,crash,regression,defect"


def _compact(items: list[dict[str, Any]], actx: AppContext) -> list[dict[str, Any]]:
    return [with_trimmed_body(i, actx, include_body=False) for i in items]


def _count_issues(actx: AppContext, q: str) -> int:
    res = actx.client.get_json(
        "/search/issues", params={"q": q, "per_page": 1}, resource="search", ttl=ttl_for("search")
    )
    return int(res.data.get("total_count", 0))


def _repo_activity(actx: AppContext, repo: str, *, bucket: str, windows: int) -> dict[str, Any]:
    days = _BUCKET_DAYS.get(bucket, 7)
    delta = timedelta(days=days)
    buckets: list[dict[str, Any]] = []
    for i in range(windows, 0, -1):
        hi = actx.now - delta * (i - 1)
        lo = actx.now - delta * i
        lo_s, hi_s = lo.date().isoformat(), hi.date().isoformat()
        opened = _count_issues(actx, f"repo:{repo} is:issue created:{lo_s}..{hi_s}")
        closed = _count_issues(actx, f"repo:{repo} is:issue closed:{lo_s}..{hi_s}")
        buckets.append({"start": lo_s, "opened": opened, "closed": closed})
    return compute_activity(buckets)


@app.command("trending")
def trending(
    ctx: typer.Context,
    language: str = typer.Option(None, "--language", "-l"),
    topic: list[str] = typer.Option([], "--topic", "-t"),
    days: int = typer.Option(30, "--days", help="Created within the last N days."),
    min_stars: int = typer.Option(50, "--min-stars"),
    sort: str = typer.Option("stars", "--sort"),
    velocity: bool = typer.Option(True, "--velocity/--no-velocity", help="Re-rank by stars/day."),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Discover recently-popular repos (Search API approximation, not github.com/trending)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        created = f">{(actx.now - timedelta(days=days)).date().isoformat()}"
        q = build_repo_query(
            None,
            language=language,
            topics=topic,
            min_stars=min_stars,
            created=created,
            pushed=None,
            archived=False,
        )
        page = actx.client.paginate_search(
            "/search/repositories",
            params={"q": q, "sort": sort, "order": "desc"},
            resource="search",
            ttl=ttl_for("search"),
            limit=limit,
        )
        repos = [normalize_repo(it, now=actx.now) for it in page.items]
        if velocity:
            repos.sort(key=lambda r: (-r["stars_per_day"], r["full_name"]))
        data = {
            "query": q,
            "repos": repos,
            "note": "Approximation via Search API (stars/day); not github.com/trending velocity.",
        }
        return data, ({"truncated": page.truncated} if page.truncated else {})

    finish(
        actx,
        command="research trending",
        params={"language": language, "days": days},
        resource="search",
        work=work,
    )


@app.command("pain-points")
def pain_points(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    labels: str = typer.Option(_PAIN_LABELS, "--labels", help="Comma list; '' to disable."),
    state: str = typer.Option("open", "--state"),
    min_reactions: int = typer.Option(1, "--min-reactions"),
    top: int = typer.Option(15, "--top"),
) -> None:
    """Top-reacted (open) issues — where users are hurting."""
    actx = app_context(ctx)
    label_list = [s for s in labels.split(",") if s]

    def work() -> tuple[Any, dict[str, Any]]:
        q = build_issue_query(
            "", repo=repo, labels=label_list, state=state, min_reactions=min_reactions
        )
        window = min(100, max(top * 3, 50))
        items, page = search_issues(actx, q=q, sort="reactions", order="desc", limit=window)
        # pain persists regardless of freshness → damp the recency term
        weights = {**actx.settings.weights, "recency": 0.5}
        ranked = rank_items(items, now=actx.now, weights=weights, top=top)
        data = {
            "repo": repo,
            "pain_points": _compact(ranked, actx),
            "label_summary": label_frequency(items),
        }
        extra: dict[str, Any] = {"scoring": {"weights": weights}}
        if page.truncated:
            extra["truncated"] = page.truncated
        return data, extra

    finish(
        actx,
        command="research pain-points",
        params={"repo": repo, "labels": labels},
        resource="search",
        work=work,
    )


@app.command("hot-discussions")
def hot_discussions(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    window: int = typer.Option(100, "--window"),
    order: str = typer.Option("UPDATED_AT", "--order"),
    top: int = typer.Option(10, "--top"),
) -> None:
    """Client-side hottest discussions (GraphQL has no popularity ordering)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        owner, name = split_repo(repo)
        items = fetch_discussions(actx, owner, name, limit=window, order=order)
        ranked = rank_items(items, now=actx.now, weights=actx.settings.weights, top=top)
        data = {"repo": repo, "window": len(items), "hot_discussions": _compact(ranked, actx)}
        return data, {"scoring": {"weights": actx.settings.weights}}

    finish(
        actx,
        command="research hot-discussions",
        params={"repo": repo, "top": top},
        resource="graphql",
        work=work,
    )


@app.command("activity")
def activity(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    bucket: str = typer.Option("week", "--bucket", help="day|week|month"),
    windows: int = typer.Option(12, "--windows"),
) -> None:
    """Booming-vs-dying: opened/closed per bucket, momentum, and a verdict (issues only)."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        result = _repo_activity(actx, repo, bucket=bucket, windows=windows)
        result["note"] = "Issue activity only; discussions not counted in v1."
        return result, {}

    finish(
        actx,
        command="research activity",
        params={"repo": repo, "bucket": bucket},
        resource="search",
        work=work,
    )


@app.command("digest")
def digest(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    issues_window: int = typer.Option(200, "--issues-window"),
    discussions_window: int = typer.Option(100, "--discussions-window"),
    top: int = typer.Option(8, "--top"),
    bucket: str = typer.Option("week", "--bucket"),
    windows: int = typer.Option(8, "--windows"),
) -> None:
    """One-call repo overview: health + top issues + hot discussions + labels + activity."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        owner, name = split_repo(repo)
        warnings: list[dict[str, Any]] = []

        health = normalize_repo(
            actx.client.get_json(
                f"/repos/{owner}/{name}", resource="repo", ttl=ttl_for("repo")
            ).data,
            now=actx.now,
        )

        issue_items, _ = search_issues(
            actx,
            q=build_issue_query("", repo=repo),
            sort="reactions",
            order="desc",
            limit=issues_window,
        )
        top_issues = rank_items(issue_items, now=actx.now, weights=actx.settings.weights, top=top)
        common_labels = label_frequency(issue_items)

        top_discussions: list[dict[str, Any]] | None = None
        if not actx.has_token:
            warnings.append(
                {
                    "code": "discussions_skipped_unauth",
                    "message": "No token; discussions omitted. Set GH_TOKEN to include them.",
                }
            )
        elif health.get("has_discussions"):
            try:
                disc_items = fetch_discussions(
                    actx, owner, name, limit=discussions_window, order="UPDATED_AT"
                )
                ranked = rank_items(
                    disc_items, now=actx.now, weights=actx.settings.weights, top=top
                )
                top_discussions = _compact(ranked, actx)
            except GhrError as exc:
                warnings.append({"code": "discussions_error", "message": exc.message})

        activity_result = _repo_activity(actx, repo, bucket=bucket, windows=windows)

        data = {
            "repo": health,
            "headline_metrics": {
                "stars": health.get("stars"),
                "open_issues": health.get("open_issues"),
                "verdict": activity_result.get("verdict"),
                "top_issue_hot_score": top_issues[0]["hot_score"] if top_issues else None,
            },
            "top_issues": _compact(top_issues, actx),
            "top_discussions": top_discussions,
            "common_labels": common_labels,
            "activity": activity_result,
        }
        extra: dict[str, Any] = {"scoring": {"weights": actx.settings.weights}}
        if warnings:
            extra["warnings"] = warnings
        return data, extra

    finish(actx, command="research digest", params={"repo": repo}, resource="search", work=work)


@app.command("common-issues")
def common_issues(
    ctx: typer.Context,
    topic: list[str] = typer.Option([], "--topic", "-t"),
    language: str = typer.Option(None, "--language", "-l"),
    repos: int = typer.Option(8, "--repos"),
    issues_per_repo: int = typer.Option(30, "--issues-per-repo"),
    repo_sort: str = typer.Option("stars", "--repo-sort"),
) -> None:
    """Cross-repo: sample issues across <type> projects and aggregate common labels."""
    actx = app_context(ctx)
    repo_count = min(repos, CROSS_REPO_REPOS_MAX)

    def work() -> tuple[Any, dict[str, Any]]:
        if not topic and not language:
            raise UsageError("Provide --topic and/or --language to scope the ecosystem.")
        repo_q = build_repo_query(
            None,
            language=language,
            topics=topic,
            min_stars=None,
            created=None,
            pushed=None,
            archived=False,
        )
        repo_page = actx.client.paginate_search(
            "/search/repositories",
            params={"q": repo_q, "sort": repo_sort, "order": "desc"},
            resource="search",
            ttl=ttl_for("search"),
            limit=repo_count,
        )
        sampled: list[dict[str, Any]] = []
        all_issues: list[dict[str, Any]] = []
        truncated: dict[str, Any] | None = None
        for repo_obj in repo_page.items:
            full = repo_obj.get("full_name")
            try:
                items, _ = search_issues(
                    actx,
                    q=build_issue_query("", repo=full, state="open"),
                    sort="reactions",
                    order="desc",
                    limit=issues_per_repo,
                )
            except BudgetExceeded as exc:
                truncated = {"reason": exc.reason, "sampled": len(sampled)}
                break
            all_issues.extend(items)
            hottest = rank_items(items, now=actx.now, weights=actx.settings.weights, top=1)
            sampled.append(
                {
                    "repo": full,
                    "stars": repo_obj.get("stargazers_count"),
                    "hottest_issue": _compact(hottest, actx)[0] if hottest else None,
                }
            )
        data = {
            "query": {"topics": topic, "language": language},
            "repos_sampled": sampled,
            "aggregate_labels": label_frequency(all_issues),
            "themes_note": "Label aggregates, not semantic clusters — synthesize themes yourself.",
        }
        return data, ({"truncated": truncated} if truncated else {})

    finish(
        actx,
        command="research common-issues",
        params={"topics": topic, "language": language, "repos": repo_count},
        resource="search",
        work=work,
    )

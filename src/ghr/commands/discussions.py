"""`ghr discussions …` — GraphQL-backed (Tier 2). All commands require a token."""

from __future__ import annotations

from typing import Any

import typer

from ghr.analysis.rank import rank_items
from ghr.commands._common import app_context, finish, require_token, split_repo, with_trimmed_body
from ghr.constants import ttl_for
from ghr.context import AppContext
from ghr.github.errors import NotFoundError
from ghr.models import normalize_discussion

app = typer.Typer(no_args_is_help=True, help="Search, list, view discussions (requires auth).")

_NODE_FIELDS = """
  number title bodyText url createdAt updatedAt isAnswered closed
  category { name isAnswerable }
  comments { totalCount }
  labels(first: 10) { nodes { name } }
  reactionGroups { content reactors { totalCount } }
"""


def _inject_nodes(template: str) -> str:
    return template.replace("@@NODES@@", _NODE_FIELDS)


_LIST_QUERY = _inject_nodes("""
query($owner:String!,$name:String!,$first:Int!,$after:String,$orderField:DiscussionOrderField!){
  repository(owner:$owner,name:$name){
    discussions(first:$first, after:$after, orderBy:{field:$orderField, direction:DESC}){
      pageInfo { hasNextPage endCursor }
      nodes { @@NODES@@ }
    }
  }
  rateLimit { limit cost remaining resetAt }
}
""")

_VIEW_QUERY = _inject_nodes("""
query($owner:String!,$name:String!,$number:Int!,$comments:Int!){
  repository(owner:$owner,name:$name){
    discussion(number:$number){
      @@NODES@@
      answer { bodyText author { login } }
      comments(first:$comments){
        totalCount
        nodes {
          bodyText isAnswer createdAt author { login }
          reactionGroups { content reactors { totalCount } }
          replies(first:5){ nodes { bodyText createdAt author { login } } }
        }
      }
    }
  }
  rateLimit { limit cost remaining resetAt }
}
""")

_CATEGORIES_QUERY = """
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    discussionCategories(first:25){ nodes { name emoji description isAnswerable } }
  }
  rateLimit { limit cost remaining resetAt }
}
"""

_SEARCH_QUERY = _inject_nodes("""
query($q:String!,$first:Int!){
  search(query:$q, type:DISCUSSION, first:$first){
    discussionCount
    nodes { ... on Discussion { @@NODES@@ repository { nameWithOwner } } }
  }
  rateLimit { limit cost remaining resetAt }
}
""")


def fetch_discussions(
    actx: AppContext, owner: str, name: str, *, limit: int, order: str
) -> list[dict[str, Any]]:
    """Cursor-paginate a repo's discussions and return normalized items."""
    collected: list[dict[str, Any]] = []
    after: str | None = None
    while len(collected) < limit:
        first = min(100, limit - len(collected))
        data = actx.client.graphql(
            _LIST_QUERY,
            variables={
                "owner": owner,
                "name": name,
                "first": first,
                "after": after,
                "orderField": order,
            },
            ttl=ttl_for("discussion"),
        )
        conn = ((data.get("repository") or {}).get("discussions")) or {}
        collected.extend(normalize_discussion(n) for n in conn.get("nodes") or [])
        page_info = conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
    return collected[:limit]


@app.command("list")
def list_(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    order: str = typer.Option("UPDATED_AT", "--order", help="UPDATED_AT|CREATED_AT"),
    with_body: bool = typer.Option(False, "--with-body"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """List a repository's discussions (newest first by default)."""
    actx = app_context(ctx)
    count = limit or actx.settings.default_limit

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        owner, name = split_repo(repo)
        items = fetch_discussions(actx, owner, name, limit=count, order=order)
        out = [with_trimmed_body(i, actx, include_body=with_body) for i in items]
        return {"repo": repo, "discussions": out}, {}

    finish(
        actx,
        command="discussions list",
        params={"repo": repo, "limit": count},
        resource="graphql",
        work=work,
    )


@app.command("view")
def view(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    number: int = typer.Argument(...),
    comments: int = typer.Option(10, "--comments"),
) -> None:
    """View one discussion with its answer and top comments."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        owner, name = split_repo(repo)
        data = actx.client.graphql(
            _VIEW_QUERY,
            variables={"owner": owner, "name": name, "number": number, "comments": comments},
            ttl=ttl_for("discussion"),
        )
        node = (data.get("repository") or {}).get("discussion")
        if node is None:
            raise NotFoundError(f"Discussion #{number} not found in {repo}.")
        item = with_trimmed_body(normalize_discussion(node), actx, include_body=True)
        answer = node.get("answer")
        item["answer"] = (
            {"author": (answer.get("author") or {}).get("login"), "body": answer.get("bodyText")}
            if answer
            else None
        )
        item["comments_list"] = [
            {
                "author": (c.get("author") or {}).get("login"),
                "is_answer": c.get("isAnswer"),
                "created_at": c.get("createdAt"),
                "body": with_trimmed_body({"body": c.get("bodyText")}, actx, include_body=True)[
                    "body"
                ],
            }
            for c in ((node.get("comments") or {}).get("nodes") or [])
        ]
        return item, {}

    finish(
        actx,
        command="discussions view",
        params={"repo": repo, "number": number},
        resource="graphql",
        work=work,
    )


@app.command("categories")
def categories(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
) -> None:
    """List a repository's discussion categories."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        owner, name = split_repo(repo)
        data = actx.client.graphql(
            _CATEGORIES_QUERY,
            variables={"owner": owner, "name": name},
            ttl=ttl_for("discussion"),
        )
        nodes = ((data.get("repository") or {}).get("discussionCategories") or {}).get(
            "nodes"
        ) or []
        return {"repo": repo, "categories": nodes}, {}

    finish(
        actx, command="discussions categories", params={"repo": repo}, resource="graphql", work=work
    )


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query (GitHub discussion qualifiers allowed)."),
    with_body: bool = typer.Option(False, "--with-body"),
    limit: int = typer.Option(None, "--limit"),
) -> None:
    """Search discussions across GitHub (GraphQL search)."""
    actx = app_context(ctx)
    count = min(limit or actx.settings.default_limit, 100)

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        data = actx.client.graphql(
            _SEARCH_QUERY, variables={"q": query, "first": count}, ttl=ttl_for("search")
        )
        search_data = data.get("search") or {}
        items = []
        for node in search_data.get("nodes") or []:
            item = with_trimmed_body(normalize_discussion(node), actx, include_body=with_body)
            item["repo"] = (node.get("repository") or {}).get("nameWithOwner")
            items.append(item)
        return {
            "query": query,
            "total_count": search_data.get("discussionCount"),
            "discussions": items,
        }, {}

    finish(
        actx,
        command="discussions search",
        params={"q": query, "limit": count},
        resource="graphql",
        work=work,
    )


@app.command("analyze")
def analyze(
    ctx: typer.Context,
    repo: str = typer.Argument(..., metavar="OWNER/REPO"),
    order: str = typer.Option("UPDATED_AT", "--order"),
    window: int = typer.Option(100, "--window"),
    top: int = typer.Option(10, "--top"),
) -> None:
    """Client-side hot ranking + answered stats over a discussion window."""
    actx = app_context(ctx)

    def work() -> tuple[Any, dict[str, Any]]:
        require_token(actx)
        owner, name = split_repo(repo)
        items = fetch_discussions(actx, owner, name, limit=window, order=order)
        ranked = rank_items(items, now=actx.now, weights=actx.settings.weights, top=top)
        answered = sum(1 for i in items if i.get("is_answered"))
        data = {
            "repo": repo,
            "window": len(items),
            "answered": answered,
            "unanswered": len(items) - answered,
            "hot": [with_trimmed_body(i, actx, include_body=False) for i in ranked],
        }
        return data, {"scoring": {"weights": actx.settings.weights}}

    finish(
        actx,
        command="discussions analyze",
        params={"repo": repo, "window": window},
        resource="graphql",
        work=work,
    )

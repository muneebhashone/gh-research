"""End-to-end CLI tests for issues, discussions, and research command groups."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from ghr.cli import app

runner = CliRunner()


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    base = {
        "GHR_CACHE_PATH": str(tmp_path / "cache.sqlite"),
        "GHR_CONFIG_PATH": str(tmp_path / "c.toml"),
    }
    base.update(extra)
    return base


def _issue(number: int, reactions: int = 3, comments: int = 2) -> dict:
    return {
        "number": number,
        "title": f"issue {number}",
        "state": "open",
        "html_url": f"https://github.com/o/r/issues/{number}",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-10T00:00:00Z",
        "comments": comments,
        "labels": [{"name": "bug"}],
        "reactions": {"+1": reactions, "total_count": reactions},
        "body": "x" * 800,
    }


SEARCH_HEADERS = {"x-ratelimit-remaining": "29", "x-ratelimit-resource": "search"}
CORE_HEADERS = {"x-ratelimit-remaining": "4999", "x-ratelimit-resource": "core"}

GQL_DISCUSSIONS = {
    "data": {
        "repository": {
            "discussions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "number": 1,
                        "title": "How?",
                        "bodyText": "body",
                        "url": "u",
                        "createdAt": "2026-05-01T00:00:00Z",
                        "updatedAt": "2026-05-10T00:00:00Z",
                        "isAnswered": True,
                        "closed": False,
                        "category": {"name": "Q&A", "isAnswerable": True},
                        "comments": {"totalCount": 4},
                        "labels": {"nodes": [{"name": "question"}]},
                        "reactionGroups": [{"content": "THUMBS_UP", "reactors": {"totalCount": 7}}],
                    }
                ],
            },
            "rateLimit": {
                "limit": 5000,
                "remaining": 4999,
                "resetAt": "2026-05-23T18:00:00Z",
                "cost": 1,
            },
        }
    }
}


@respx.mock
def test_issues_search_enforces_is_issue(tmp_path: Path) -> None:
    captured = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        return httpx.Response(
            200, json={"total_count": 1, "items": [_issue(1)]}, headers=SEARCH_HEADERS
        )

    respx.get("https://api.github.com/search/issues").mock(side_effect=responder)
    result = runner.invoke(
        app,
        ["--token-source", "none", "issues", "search", "--repo", "o/r", "--label", "bug"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert len(data["issues"]) == 1
    assert "is:issue" in captured["q"]
    assert 'label:"bug"' in captured["q"]
    # body omitted by default in list/search output
    assert "body" not in data["issues"][0]


def test_discussions_list_without_token_exits_4(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--token-source", "none", "discussions", "list", "o/r"], env=_env(tmp_path)
    )
    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"]["code"] == "auth_required"


@respx.mock
def test_discussions_list_with_token(tmp_path: Path) -> None:
    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=GQL_DISCUSSIONS)
    )
    result = runner.invoke(
        app, ["discussions", "list", "o/r"], env=_env(tmp_path, GH_TOKEN="testtoken")
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert len(data["discussions"]) == 1
    assert data["discussions"][0]["is_answered"] is True
    assert data["discussions"][0]["reactions"]["+1"] == 7


@respx.mock
def test_research_trending_sorts_by_velocity(tmp_path: Path) -> None:
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 2,
                "items": [
                    {
                        "full_name": "o/slow",
                        "stargazers_count": 365,
                        "created_at": "2025-05-23T00:00:00Z",
                        "pushed_at": "2026-05-01T00:00:00Z",
                    },
                    {
                        "full_name": "o/fast",
                        "stargazers_count": 300,
                        "created_at": "2026-05-13T00:00:00Z",
                        "pushed_at": "2026-05-22T00:00:00Z",
                    },
                ],
            },
            headers=SEARCH_HEADERS,
        )
    )
    result = runner.invoke(
        app,
        ["--token-source", "none", "research", "trending", "--language", "go"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    repos = json.loads(result.output)["data"]["repos"]
    # o/fast: 300 stars over ~10 days >> o/slow: 365 over ~365 days
    assert repos[0]["full_name"] == "o/fast"


@respx.mock
def test_research_activity_returns_verdict(tmp_path: Path) -> None:
    respx.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(
            200, json={"total_count": 5, "items": []}, headers=SEARCH_HEADERS
        )
    )
    result = runner.invoke(
        app,
        ["--token-source", "none", "research", "activity", "o/r", "--windows", "4"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["verdict"] in {"booming", "dying", "steady"}
    assert len(data["buckets"]) == 4


@respx.mock
def test_research_digest_composes_sections(tmp_path: Path) -> None:
    respx.get("https://api.github.com/repos/cli/cli").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_name": "cli/cli",
                "stargazers_count": 1000,
                "open_issues_count": 10,
                "created_at": "2024-05-23T00:00:00Z",
                "pushed_at": "2026-05-20T00:00:00Z",
                "has_discussions": True,
                "topics": [],
            },
            headers=CORE_HEADERS,
        )
    )
    respx.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(
            200, json={"total_count": 3, "items": [_issue(1), _issue(2, 9)]}, headers=SEARCH_HEADERS
        )
    )
    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json=GQL_DISCUSSIONS)
    )
    result = runner.invoke(
        app,
        ["research", "digest", "cli/cli", "--windows", "2"],
        env=_env(tmp_path, GH_TOKEN="testtoken"),
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["repo"]["full_name"] == "cli/cli"
    assert "headline_metrics" in data
    assert len(data["top_issues"]) >= 1
    assert data["top_discussions"] is not None
    assert "verdict" in data["activity"]


def test_research_digest_unauth_skips_discussions(tmp_path: Path) -> None:
    with respx.mock:
        respx.get("https://api.github.com/repos/cli/cli").mock(
            return_value=httpx.Response(
                200,
                json={
                    "full_name": "cli/cli",
                    "stargazers_count": 1000,
                    "open_issues_count": 10,
                    "created_at": "2024-05-23T00:00:00Z",
                    "pushed_at": "2026-05-20T00:00:00Z",
                    "has_discussions": True,
                    "topics": [],
                },
                headers=CORE_HEADERS,
            )
        )
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200, json={"total_count": 1, "items": [_issue(1)]}, headers=SEARCH_HEADERS
            )
        )
        result = runner.invoke(
            app,
            ["--token-source", "none", "research", "digest", "cli/cli", "--windows", "2"],
            env=_env(tmp_path),
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["top_discussions"] is None
    assert any(w["code"] == "discussions_skipped_unauth" for w in payload["meta"]["warnings"])

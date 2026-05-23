"""End-to-end CLI tests for the repo/ops vertical slice (runner + respx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from ghr.cli import app

runner = CliRunner()


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "GHR_CACHE_PATH": str(tmp_path / "cache.sqlite"),
        "GHR_CONFIG_PATH": str(tmp_path / "c.toml"),
    }


REPO_JSON = {
    "full_name": "cli/cli",
    "stargazers_count": 1000,
    "forks_count": 50,
    "open_issues_count": 42,
    "subscribers_count": 10,
    "pushed_at": "2026-05-20T00:00:00Z",
    "created_at": "2024-05-23T00:00:00Z",
    "archived": False,
    "license": {"spdx_id": "MIT"},
    "topics": ["cli"],
    "has_discussions": True,
    "html_url": "https://github.com/cli/cli",
}


@respx.mock
def test_repo_view(tmp_path: Path) -> None:
    respx.get("https://api.github.com/repos/cli/cli").mock(
        return_value=httpx.Response(
            200,
            json=REPO_JSON,
            headers={"x-ratelimit-remaining": "4999", "x-ratelimit-resource": "core"},
        )
    )
    result = runner.invoke(
        app, ["--token-source", "none", "repo", "view", "cli/cli"], env=_env(tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["full_name"] == "cli/cli"
    assert payload["data"]["stars"] == 1000
    assert payload["meta"]["command"] == "repo view"
    assert payload["meta"]["rate_limit"]["remaining"] == 4999


@respx.mock
def test_repo_search_builds_query(tmp_path: Path) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert "language:go" in request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "total_count": 2,
                "items": [
                    {
                        "full_name": "o/a",
                        "stargazers_count": 100,
                        "created_at": "2025-01-01T00:00:00Z",
                        "pushed_at": "2026-05-01T00:00:00Z",
                    },
                    {
                        "full_name": "o/b",
                        "stargazers_count": 50,
                        "created_at": "2025-01-01T00:00:00Z",
                        "pushed_at": "2026-05-01T00:00:00Z",
                    },
                ],
            },
            headers={"x-ratelimit-remaining": "29", "x-ratelimit-resource": "search"},
        )

    respx.get("https://api.github.com/search/repositories").mock(side_effect=responder)
    result = runner.invoke(
        app,
        ["--token-source", "none", "repo", "search", "--language", "go", "--limit", "5"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert len(data["repos"]) == 2
    assert "language:go" in data["query"]


@respx.mock
def test_rate_command(tmp_path: Path) -> None:
    respx.get("https://api.github.com/rate_limit").mock(
        return_value=httpx.Response(
            200,
            json={"resources": {"core": {"limit": 5000, "remaining": 4999}}},
            headers={"x-ratelimit-remaining": "4999", "x-ratelimit-resource": "core"},
        )
    )
    result = runner.invoke(app, ["--token-source", "none", "rate"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["resources"]["core"]["remaining"] == 4999


def test_cache_path_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--token-source", "none", "cache", "path"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["path"].endswith("cache.sqlite")


def test_bad_repo_slug_is_usage_error_envelope(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--token-source", "none", "repo", "view", "noslash"], env=_env(tmp_path)
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"]["code"] == "usage_error"

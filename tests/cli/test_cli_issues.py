"""End-to-end CLI tests for `ghr issues search`, incl. semantic/hybrid search."""

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


ISSUE_ITEM = {
    "number": 7,
    "title": "auth fails on mobile",
    "state": "open",
    "html_url": "https://github.com/o/r/issues/7",
    "created_at": "2026-05-01T00:00:00Z",
    "updated_at": "2026-05-10T00:00:00Z",
    "comments": 3,
    "reactions": {"total_count": 5, "+1": 5},
    "labels": [{"name": "bug"}],
    "body": "it breaks",
}


def _search_response(request: httpx.Request, captured: dict[str, str]) -> httpx.Response:
    captured["q"] = request.url.params.get("q", "")
    captured["search_type"] = request.url.params.get("search_type", "")
    return httpx.Response(
        200,
        json={"total_count": 1, "items": [ISSUE_ITEM]},
        headers={"x-ratelimit-remaining": "9", "x-ratelimit-resource": "search"},
    )


@respx.mock
def test_semantic_search_sends_search_type_and_echoes_it(tmp_path: Path) -> None:
    captured: dict[str, str] = {}
    respx.get("https://api.github.com/search/issues").mock(
        side_effect=lambda req: _search_response(req, captured)
    )
    result = runner.invoke(
        app,
        [
            "--token-source",
            "none",
            "issues",
            "search",
            "authentication failing on mobile",
            "--search-type",
            "semantic",
            "--limit",
            "5",
        ],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    assert captured["search_type"] == "semantic"
    data = json.loads(result.output)["data"]
    assert data["search_type"] == "semantic"
    assert data["issues"][0]["number"] == 7


@respx.mock
def test_hybrid_search_sends_search_type(tmp_path: Path) -> None:
    captured: dict[str, str] = {}
    respx.get("https://api.github.com/search/issues").mock(
        side_effect=lambda req: _search_response(req, captured)
    )
    result = runner.invoke(
        app,
        ["--token-source", "none", "issues", "search", "flaky timeline", "--search-type", "hybrid"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    assert captured["search_type"] == "hybrid"


@respx.mock
def test_lexical_search_omits_search_type_param(tmp_path: Path) -> None:
    captured: dict[str, str] = {}
    respx.get("https://api.github.com/search/issues").mock(
        side_effect=lambda req: _search_response(req, captured)
    )
    result = runner.invoke(
        app,
        ["--token-source", "none", "issues", "search", "boom", "--repo", "o/r"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 0, result.output
    assert captured["search_type"] == ""  # not sent → lexical default
    data = json.loads(result.output)["data"]
    assert "search_type" not in data


def test_invalid_search_type_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--token-source", "none", "issues", "search", "x", "--search-type", "fuzzy"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"]["code"] == "usage_error"

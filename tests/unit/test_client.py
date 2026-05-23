"""Tests for the GitHubClient request pipeline (cache, retry, rate, pagination)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from ghr.cache.store import CacheStore
from ghr.config import Settings
from ghr.github.client import GitHubClient
from ghr.github.errors import NotFoundError, UpstreamError
from ghr.github.ratelimit import BudgetGuard, RateLimitState
from ghr.github.session import build_session

BASE = "https://api.github.com"


def _make(tmp_path: Path, **kw: Any) -> GitHubClient:
    session = build_session(kw.get("token"), base_url=BASE)
    cache = CacheStore(tmp_path / "cache.sqlite", clock=lambda: 1000.0)
    return GitHubClient(
        session=session,
        cache=cache,
        budget=BudgetGuard(max_requests=50, time_budget_ms=60_000, clock=lambda: 0.0),
        state=RateLimitState(),
        settings=Settings(),
        token=kw.get("token"),
        sleeper=kw.get("sleeper", lambda d: None),
        now=lambda: 1000.0,
        refresh=kw.get("refresh", False),
        use_cache=kw.get("use_cache", True),
    )


def _rest_headers(remaining: str = "4999", resource: str = "core") -> dict[str, str]:
    return {"x-ratelimit-remaining": remaining, "x-ratelimit-resource": resource, "etag": '"v1"'}


@respx.mock
def test_get_json_fetches_then_serves_from_cache(tmp_path: Path) -> None:
    route = respx.get(f"{BASE}/repos/o/r").mock(
        return_value=httpx.Response(200, json={"x": 1}, headers=_rest_headers())
    )
    client = _make(tmp_path)
    try:
        first = client.get_json("/repos/o/r", resource="repo", ttl=3600)
        second = client.get_json("/repos/o/r", resource="repo", ttl=3600)
        assert first.data == {"x": 1}
        assert first.from_cache is False
        assert second.from_cache is True
        assert route.call_count == 1
        assert client.state.remaining("core") == 4999
    finally:
        client.close()


@respx.mock
def test_conditional_request_304_serves_cached_body(tmp_path: Path) -> None:
    respx.get(f"{BASE}/repos/o/r").mock(
        return_value=httpx.Response(200, json={"x": 1}, headers=_rest_headers())
    )
    client = _make(tmp_path)
    client.get_json("/repos/o/r", resource="repo", ttl=3600)
    client.close()

    # New client forced to refresh → sends If-None-Match → server replies 304.
    route = respx.get(f"{BASE}/repos/o/r").mock(return_value=httpx.Response(304))
    client2 = _make(tmp_path, refresh=True)
    try:
        result = client2.get_json("/repos/o/r", resource="repo", ttl=3600)
        assert result.data == {"x": 1}
        assert result.from_cache is True
        assert route.calls.last.request.headers["if-none-match"] == '"v1"'
    finally:
        client2.close()


@respx.mock
def test_retries_on_503_then_succeeds(tmp_path: Path) -> None:
    route = respx.get(f"{BASE}/repos/o/r").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": 1}, headers=_rest_headers()),
        ]
    )
    sleeps: list[float] = []
    client = _make(tmp_path, sleeper=sleeps.append)
    try:
        result = client.get_json("/repos/o/r", resource="repo", ttl=10)
        assert result.data == {"ok": 1}
        assert route.call_count == 2
        assert len(sleeps) == 1
    finally:
        client.close()


@respx.mock
def test_404_raises_not_found(tmp_path: Path) -> None:
    respx.get(f"{BASE}/repos/o/missing").mock(return_value=httpx.Response(404))
    client = _make(tmp_path)
    try:
        with pytest.raises(NotFoundError):
            client.get_json("/repos/o/missing", resource="repo", ttl=10)
    finally:
        client.close()


@respx.mock
def test_paginate_search_aggregates_and_respects_1000_cap(tmp_path: Path) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        per = int(request.url.params["per_page"])
        items = [{"number": (page - 1) * per + i} for i in range(per)]
        return httpx.Response(
            200,
            json={"total_count": 5000, "incomplete_results": False, "items": items},
            headers=_rest_headers(remaining="29", resource="search"),
        )

    respx.get(f"{BASE}/search/issues").mock(side_effect=responder)
    client = _make(tmp_path)
    try:
        result = client.paginate_search("/search/issues", params={"q": "x"}, ttl=300, limit=5000)
        assert len(result.items) == 1000
        assert result.total_count == 5000
        assert result.truncated is not None
        assert result.truncated["reason"] == "search_cap"
    finally:
        client.close()


@respx.mock
def test_paginate_search_clamps_per_page_to_max_limit(tmp_path: Path) -> None:
    route = respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(
            200,
            json={"total_count": 3, "items": [{"number": 1}]},
            headers=_rest_headers(resource="search"),
        )
    )
    client = _make(tmp_path)
    try:
        client.paginate_search("/search/issues", params={"q": "x"}, ttl=300, limit=500)
        assert route.calls.last.request.url.params["per_page"] == "100"
    finally:
        client.close()


@respx.mock
def test_graphql_returns_data_and_tracks_rate(tmp_path: Path) -> None:
    respx.post(f"{BASE}/graphql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "repository": {"x": 1},
                    "rateLimit": {
                        "limit": 5000,
                        "remaining": 4990,
                        "resetAt": "2026-05-23T18:00:00Z",
                        "cost": 1,
                    },
                }
            },
        )
    )
    client = _make(tmp_path, token="t")
    try:
        data = client.graphql("query { x }", variables={"a": 1}, ttl=900)
        assert data == {"repository": {"x": 1}}  # rateLimit stripped out
        assert client.state.remaining("graphql") == 4990
    finally:
        client.close()


@respx.mock
def test_graphql_errors_raise_upstream(tmp_path: Path) -> None:
    respx.post(f"{BASE}/graphql").mock(
        return_value=httpx.Response(
            200, json={"data": None, "errors": [{"message": "Bad", "type": "X"}]}
        )
    )
    client = _make(tmp_path, token="t")
    try:
        with pytest.raises(UpstreamError):
            client.graphql("query { x }", ttl=900)
    finally:
        client.close()


@respx.mock
def test_graphql_not_found_error_maps_to_not_found(tmp_path: Path) -> None:
    respx.post(f"{BASE}/graphql").mock(
        return_value=httpx.Response(
            200, json={"data": None, "errors": [{"type": "NOT_FOUND", "message": "missing"}]}
        )
    )
    client = _make(tmp_path, token="t")
    try:
        with pytest.raises(NotFoundError):
            client.graphql("query { x }", ttl=900)
    finally:
        client.close()

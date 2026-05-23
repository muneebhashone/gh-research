"""The GitHubClient: one request pipeline shared by REST and GraphQL.

Pipeline per request:
    budget.check -> cache lookup (fresh? return; stale+etag? conditional)
                 -> send -> track rate limit
                 -> 200 (store + return) | 304 (serve cached) | retryable (backoff) | raise
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ghr.cache.store import CacheStore, auth_scope_bucket, make_key
from ghr.config import Settings
from ghr.constants import SEARCH_RESULT_CAP
from ghr.github.backoff import next_delay
from ghr.github.errors import NotFoundError, UpstreamError, classify_http_error
from ghr.github.ratelimit import BudgetGuard, RateLimitState


@dataclass
class JsonResult:
    data: Any
    from_cache: bool


@dataclass
class PageResult:
    items: list[dict[str, Any]]
    total_count: int | None
    truncated: dict[str, Any] | None


class GitHubClient:
    def __init__(
        self,
        *,
        session: httpx.Client,
        cache: CacheStore | None,
        budget: BudgetGuard,
        state: RateLimitState,
        settings: Settings,
        token: str | None,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        max_retries: int = 4,
        refresh: bool = False,
        use_cache: bool = True,
    ) -> None:
        self._session = session
        self._cache = cache
        self._budget = budget
        self.state = state
        self._settings = settings
        self._auth_scope = auth_scope_bucket(token)
        self._sleeper = sleeper
        self._now = now
        self._max_retries = max_retries
        self._refresh = refresh
        self._use_cache = use_cache
        self.cache_hits = 0
        self.cache_misses = 0

    def close(self) -> None:
        self._session.close()
        if self._cache is not None:
            self._cache.close()

    # -- public API ---------------------------------------------------------

    def get_json(
        self, path: str, *, params: Mapping[str, Any] | None = None, resource: str, ttl: int
    ) -> JsonResult:
        return self._request(
            "GET", path, params=params, json_body=None, resource=resource, ttl=ttl, transport="rest"
        )

    def graphql(self, query: str, *, variables: Mapping[str, Any] | None = None, ttl: int) -> Any:
        body = {"query": query, "variables": dict(variables or {})}
        result = self._request(
            "POST",
            "/graphql",
            params=None,
            json_body=body,
            resource="graphql",
            ttl=ttl,
            transport="graphql",
        )
        return result.data

    def paginate_search(
        self,
        path: str,
        *,
        params: Mapping[str, Any],
        resource: str = "search",
        ttl: int,
        limit: int,
    ) -> PageResult:
        per_page = max(1, min(limit, self._settings.max_limit, 100))
        items: list[dict[str, Any]] = []
        total: int | None = None
        truncated: dict[str, Any] | None = None
        page = 1
        while True:
            body = self._request(
                "GET",
                path,
                params={**params, "per_page": per_page, "page": page},
                json_body=None,
                resource=resource,
                ttl=ttl,
                transport="rest",
            ).data
            data = body if isinstance(body, dict) else {}
            total = data.get("total_count", total)
            page_items = data.get("items") or []
            items.extend(page_items)
            if len(items) >= limit:
                items = items[:limit]
                break
            if not page_items or len(page_items) < per_page:
                break
            if page * per_page >= SEARCH_RESULT_CAP:
                truncated = {"reason": "search_cap", "cap": SEARCH_RESULT_CAP, "total_count": total}
                break
            if page >= self._settings.max_pages:
                truncated = {
                    "reason": "max_pages",
                    "max_pages": self._settings.max_pages,
                    "total_count": total,
                }
                break
            page += 1
        return PageResult(items=items, total_count=total, truncated=truncated)

    def paginate_list(
        self, path: str, *, params: Mapping[str, Any], resource: str, ttl: int, limit: int
    ) -> PageResult:
        per_page = max(1, min(limit, self._settings.max_limit, 100))
        items: list[dict[str, Any]] = []
        truncated: dict[str, Any] | None = None
        page = 1
        while True:
            body = self._request(
                "GET",
                path,
                params={**params, "per_page": per_page, "page": page},
                json_body=None,
                resource=resource,
                ttl=ttl,
                transport="rest",
            ).data
            page_items = body if isinstance(body, list) else []
            items.extend(page_items)
            if len(items) >= limit:
                items = items[:limit]
                break
            if len(page_items) < per_page:
                break
            if page >= self._settings.max_pages:
                truncated = {"reason": "max_pages", "max_pages": self._settings.max_pages}
                break
            page += 1
        return PageResult(items=items, total_count=None, truncated=truncated)

    # -- pipeline -----------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Mapping[str, Any] | None,
        resource: str,
        ttl: int,
        transport: str,
    ) -> JsonResult:
        key = make_key(
            method=method,
            url=url,
            params=params,
            gql_query=json_body.get("query") if (transport == "graphql" and json_body) else None,
            gql_vars=json_body.get("variables") if (transport == "graphql" and json_body) else None,
            auth_scope=self._auth_scope,
        )
        entry = self._cache.get(key) if (self._cache is not None and self._use_cache) else None
        if (
            entry is not None
            and not self._refresh
            and self._cache is not None
            and self._cache.is_fresh(entry)
        ):
            self.cache_hits += 1
            return JsonResult(json.loads(entry.body), True)

        headers: dict[str, str] = {}
        if entry is not None and entry.etag and transport == "rest":
            headers["If-None-Match"] = entry.etag

        attempt = 0
        while True:
            self._budget.check()
            response = self._session.request(
                method, url, params=params, json=json_body, headers=headers or None
            )
            self._budget.record()
            if transport == "rest":
                self.state.update_from_rest_headers(response.headers)

            if response.status_code == 304 and entry is not None:
                if self._cache is not None:
                    self._cache.touch(key)
                self.cache_hits += 1
                return JsonResult(json.loads(entry.body), True)

            if response.status_code == 200:
                return self._handle_200(
                    response, key=key, resource=resource, ttl=ttl, transport=transport
                )

            delay = next_delay(
                attempt=attempt,
                status=response.status_code,
                headers=response.headers,
                now=self._now(),
            )
            if delay is None or attempt >= self._max_retries:
                raise classify_http_error(response)
            self._sleeper(delay)
            attempt += 1

    def _handle_200(
        self, response: httpx.Response, *, key: str, resource: str, ttl: int, transport: str
    ) -> JsonResult:
        parsed = response.json()
        if transport == "graphql":
            payload = parsed if isinstance(parsed, dict) else {}
            data = payload.get("data") or {}
            if isinstance(data, dict) and "rateLimit" in data:
                self.state.update_from_graphql(data.pop("rateLimit"))
            if payload.get("errors"):
                _raise_for_graphql_errors(payload["errors"])
            body_bytes = json.dumps(data).encode("utf-8")
            parsed = data
        else:
            body_bytes = response.content

        if self._cache is not None and self._use_cache:
            self._cache.set(
                key,
                resource=resource,
                transport=transport,
                body=body_bytes,
                etag=response.headers.get("etag"),
                status=200,
                ttl=ttl,
                auth_scope=self._auth_scope,
            )
        self.cache_misses += 1
        return JsonResult(parsed, False)


def _raise_for_graphql_errors(errors: list[dict[str, Any]]) -> None:
    message = errors[0].get("message", "GraphQL error")
    if any(err.get("type") == "NOT_FOUND" for err in errors):
        raise NotFoundError(message)
    raise UpstreamError(f"GraphQL error: {message}")

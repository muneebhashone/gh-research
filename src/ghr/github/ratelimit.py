"""Per-resource rate-limit tracking and a per-command request/time budget guard."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ResourceBudget:
    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None
    used: int | None = None


class RateLimitState:
    """Tracks remaining budget per GitHub resource (``core``/``search``/``graphql``)."""

    def __init__(self) -> None:
        self.resources: dict[str, ResourceBudget] = {}

    def update_from_rest_headers(self, headers: Mapping[str, str]) -> None:
        if "x-ratelimit-remaining" not in headers:
            return
        resource = headers.get("x-ratelimit-resource", "core")
        self.resources[resource] = ResourceBudget(
            limit=_to_int(headers.get("x-ratelimit-limit")),
            remaining=_to_int(headers.get("x-ratelimit-remaining")),
            reset=_to_int(headers.get("x-ratelimit-reset")),
            used=_to_int(headers.get("x-ratelimit-used")),
        )

    def update_from_graphql(self, rate_limit: Mapping[str, Any] | None) -> None:
        if not rate_limit:
            return
        self.resources["graphql"] = ResourceBudget(
            limit=_to_int(rate_limit.get("limit")),
            remaining=_to_int(rate_limit.get("remaining")),
            reset=_iso_to_epoch(rate_limit.get("resetAt")),
            used=_to_int(rate_limit.get("used")),
        )

    def remaining(self, resource: str) -> int | None:
        budget = self.resources.get(resource)
        return budget.remaining if budget else None

    def snapshot(self, resource: str) -> dict[str, Any] | None:
        budget = self.resources.get(resource)
        if budget is None:
            return None
        return {
            "resource": resource,
            "remaining": budget.remaining,
            "limit": budget.limit,
            "reset": budget.reset,
        }


class BudgetExceeded(Exception):
    """Raised when a command would exceed its request or time budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BudgetGuard:
    """Caps total requests and wall-clock time for a single command invocation."""

    def __init__(
        self,
        *,
        max_requests: int,
        time_budget_ms: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.time_budget_s = time_budget_ms / 1000.0
        self._clock = clock
        self._start = clock()
        self._requests = 0

    def check(self) -> None:
        """Raise :class:`BudgetExceeded` if issuing another request would breach a cap."""
        if self._requests >= self.max_requests:
            raise BudgetExceeded("max_requests")
        if self._clock() - self._start >= self.time_budget_s:
            raise BudgetExceeded("time_budget")

    def record(self, n: int = 1) -> None:
        self._requests += n

    @property
    def requests_made(self) -> int:
        return self._requests

    def elapsed_ms(self) -> int:
        return int((self._clock() - self._start) * 1000)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_to_epoch(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp())
    except ValueError:
        return None

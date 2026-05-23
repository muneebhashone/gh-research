"""Pure retry/backoff decisions. The actual sleeping happens in the client loop.

``next_delay`` returns the seconds to wait before retrying, or ``None`` when the
status is not retryable. Keeping it pure (taking ``now`` and a ``jitter`` hook)
makes the retry policy fully unit-testable without a clock or randomness.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from email.utils import parsedate_to_datetime

RETRYABLE_SERVER_STATUSES = frozenset({500, 502, 503, 504})


def is_rate_limited(status: int, headers: Mapping[str, str]) -> bool:
    """A 403 is rate-limiting only when the primary budget is exhausted."""
    return status == 429 or (status == 403 and headers.get("x-ratelimit-remaining") == "0")


def _parse_retry_after(value: str, *, now: float) -> float:
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - now)
    except (TypeError, ValueError):
        return 0.0


def _expo(attempt: int, base: float, cap: float, jitter: Callable[[float], float]) -> float:
    return jitter(min(cap, base * 2**attempt))


def next_delay(
    *,
    attempt: int,
    status: int,
    headers: Mapping[str, str],
    now: float,
    base: float = 0.5,
    cap: float = 30.0,
    jitter: Callable[[float], float] | None = None,
) -> float | None:
    """Seconds to wait before retry, or ``None`` if the status is not retryable.

    Rate limits prefer ``Retry-After`` then ``x-ratelimit-reset``; everything
    else (and server 5xx) uses capped exponential backoff with full jitter.
    """
    jit = jitter if jitter is not None else (lambda d: random.uniform(0.0, d))
    if is_rate_limited(status, headers):
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            return _parse_retry_after(retry_after, now=now)
        reset = headers.get("x-ratelimit-reset")
        if reset is not None:
            try:
                return max(0.0, float(reset) - now)
            except ValueError:
                pass
        return _expo(attempt, base, cap, jit)
    if status in RETRYABLE_SERVER_STATUSES:
        return _expo(attempt, base, cap, jit)
    return None

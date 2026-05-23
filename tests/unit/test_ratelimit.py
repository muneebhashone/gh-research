"""Tests for rate-limit tracking and the per-command budget guard."""

import pytest

from ghr.github.ratelimit import BudgetExceeded, BudgetGuard, RateLimitState


def test_rest_headers_parsed_by_resource() -> None:
    st = RateLimitState()
    st.update_from_rest_headers(
        {
            "x-ratelimit-limit": "5000",
            "x-ratelimit-remaining": "4990",
            "x-ratelimit-reset": "1769200000",
            "x-ratelimit-used": "10",
            "x-ratelimit-resource": "core",
        }
    )
    assert st.snapshot("core") == {
        "resource": "core",
        "remaining": 4990,
        "limit": 5000,
        "reset": 1769200000,
    }
    assert st.remaining("core") == 4990
    assert st.snapshot("search") is None
    assert st.last_rest_resource == "core"


def test_last_rest_resource_tracks_most_recent_rest_response() -> None:
    st = RateLimitState()
    assert st.last_rest_resource is None
    st.update_from_rest_headers({"x-ratelimit-remaining": "9", "x-ratelimit-resource": "search"})
    assert st.last_rest_resource == "search"
    # A response without rate-limit headers must not clobber the last-seen resource.
    st.update_from_rest_headers({})
    assert st.last_rest_resource == "search"


def test_graphql_body_parsed_with_reset_epoch() -> None:
    st = RateLimitState()
    st.update_from_graphql(
        {"limit": 5000, "remaining": 4997, "used": 3, "resetAt": "2026-05-23T18:00:00Z", "cost": 3}
    )
    snap = st.snapshot("graphql")
    assert snap is not None
    assert snap["remaining"] == 4997
    assert snap["limit"] == 5000
    assert isinstance(snap["reset"], int)


def test_budget_guard_trips_on_max_requests() -> None:
    g = BudgetGuard(max_requests=2, time_budget_ms=100_000, clock=lambda: 0.0)
    g.check()
    g.record()
    g.check()
    g.record()
    with pytest.raises(BudgetExceeded) as ei:
        g.check()
    assert ei.value.reason == "max_requests"


def test_budget_guard_trips_on_time_budget() -> None:
    clock = {"t": 0.0}
    g = BudgetGuard(max_requests=100, time_budget_ms=1000, clock=lambda: clock["t"])
    g.check()  # fine at t=0
    clock["t"] = 2.0
    with pytest.raises(BudgetExceeded) as ei:
        g.check()
    assert ei.value.reason == "time_budget"


def test_budget_guard_tracks_requests_and_elapsed() -> None:
    clock = {"t": 0.0}
    g = BudgetGuard(max_requests=10, time_budget_ms=5000, clock=lambda: clock["t"])
    g.record()
    g.record()
    assert g.requests_made == 2
    clock["t"] = 1.5
    assert g.elapsed_ms() == 1500

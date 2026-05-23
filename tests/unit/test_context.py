"""Tests for meta assembly and context construction."""

from pathlib import Path

from ghr.auth.resolver import TokenSource
from ghr.context import build_context, build_meta
from ghr.github.ratelimit import BudgetGuard, RateLimitState


def test_build_meta_assembles_expected_fields() -> None:
    state = RateLimitState()
    state.update_from_rest_headers(
        {
            "x-ratelimit-remaining": "29",
            "x-ratelimit-limit": "30",
            "x-ratelimit-reset": "100",
            "x-ratelimit-resource": "search",
        }
    )
    budget = BudgetGuard(max_requests=50, time_budget_ms=20_000, clock=lambda: 0.0)
    budget.record()
    budget.record()
    meta = build_meta(
        command="issues search",
        params={"q": "x"},
        state=state,
        cache_hits=1,
        cache_misses=2,
        budget=budget,
        resource="search",
        truncated={"reason": "search_cap"},
    )
    assert meta["command"] == "issues search"
    assert meta["params"] == {"q": "x"}
    assert meta["rate_limit"] == {"resource": "search", "remaining": 29, "limit": 30, "reset": 100}
    assert meta["cache"] == {"hits": 1, "misses": 2}
    assert meta["requests_made"] == 2
    assert meta["elapsed_ms"] == 0
    assert meta["truncated"] == {"reason": "search_cap"}
    assert "tool_version" in meta


def test_build_meta_omits_optional_blocks_when_absent() -> None:
    meta = build_meta(command="rate", params={})
    assert "truncated" not in meta
    assert "rate_limit" not in meta
    assert meta["command"] == "rate"


def test_build_context_without_token_resolves_none(tmp_path: Path) -> None:
    ctx = build_context(
        cli={},
        env={},
        config_path=tmp_path / "config.toml",
        cache_path=tmp_path / "cache.sqlite",
        gh_token_getter=lambda: None,
        config_token_getter=lambda: None,
    )
    try:
        assert ctx.token.source is TokenSource.NONE
        assert ctx.settings.default_limit == 30
        assert ctx.has_token is False
    finally:
        ctx.close()


def test_build_context_uses_env_token(tmp_path: Path) -> None:
    ctx = build_context(
        cli={},
        env={"GH_TOKEN": "abc"},
        config_path=tmp_path / "config.toml",
        cache_path=tmp_path / "cache.sqlite",
    )
    try:
        assert ctx.token.source is TokenSource.ENV_GH_TOKEN
        assert ctx.has_token is True
    finally:
        ctx.close()

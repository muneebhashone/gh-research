"""Tests for the GhrError hierarchy and HTTP-status classification."""

import httpx

from ghr.github.errors import (
    AuthRequiredError,
    GhrError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
    UsageError,
    classify_http_error,
)


def _resp(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.github.com/x"),
    )


def test_error_codes_and_exit_codes() -> None:
    assert (GhrError("x").code, GhrError("x").exit_code) == ("internal_error", 1)
    assert (UsageError("x").code, UsageError("x").exit_code) == ("usage_error", 2)
    assert (NotFoundError("x").code, NotFoundError("x").exit_code) == ("not_found", 3)
    assert (AuthRequiredError("x").code, AuthRequiredError("x").exit_code) == ("auth_required", 4)
    assert (RateLimitedError("x").code, RateLimitedError("x").exit_code) == ("rate_limited", 5)
    assert (UpstreamError("x").code, UpstreamError("x").exit_code) == ("upstream_error", 6)


def test_to_error_dict_uniform_shape_with_suggestion() -> None:
    e = AuthRequiredError("need token", suggestion="run gh auth login")
    assert e.to_error_dict() == {
        "code": "auth_required",
        "message": "need token",
        "suggestion": "run gh auth login",
    }


def test_to_error_dict_includes_null_suggestion_when_absent() -> None:
    assert NotFoundError("nope").to_error_dict() == {
        "code": "not_found",
        "message": "nope",
        "suggestion": None,
    }


def test_classify_404_is_not_found() -> None:
    assert isinstance(classify_http_error(_resp(404)), NotFoundError)


def test_classify_401_is_auth_required() -> None:
    assert isinstance(classify_http_error(_resp(401)), AuthRequiredError)


def test_classify_429_is_rate_limited() -> None:
    assert isinstance(classify_http_error(_resp(429)), RateLimitedError)


def test_classify_403_with_zero_remaining_is_rate_limited() -> None:
    r = _resp(403, {"x-ratelimit-remaining": "0"})
    assert isinstance(classify_http_error(r), RateLimitedError)


def test_classify_403_without_rate_signal_is_auth_required() -> None:
    assert isinstance(classify_http_error(_resp(403)), AuthRequiredError)


def test_classify_503_is_upstream() -> None:
    assert isinstance(classify_http_error(_resp(503)), UpstreamError)

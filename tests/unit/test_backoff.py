"""Tests for retry/backoff delay decisions (pure, no sleeping)."""

from ghr.github.backoff import is_rate_limited, next_delay

# jitter disabled → deterministic exponential values
NO_JITTER = lambda d: d  # noqa: E731


def test_non_retryable_statuses_return_none() -> None:
    for status in (200, 400, 401, 404, 422):
        assert next_delay(attempt=0, status=status, headers={}, now=0.0) is None


def test_is_rate_limited() -> None:
    assert is_rate_limited(429, {}) is True
    assert is_rate_limited(403, {"x-ratelimit-remaining": "0"}) is True
    assert is_rate_limited(403, {"x-ratelimit-remaining": "5"}) is False
    assert is_rate_limited(403, {}) is False


def test_retry_after_seconds_is_honored() -> None:
    d = next_delay(attempt=0, status=429, headers={"retry-after": "5"}, now=1000.0)
    assert d == 5.0


def test_rate_limit_reset_is_used_when_no_retry_after() -> None:
    d = next_delay(
        attempt=0,
        status=403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1010"},
        now=1000.0,
    )
    assert d == 10.0


def test_exponential_backoff_for_server_errors() -> None:
    assert next_delay(attempt=0, status=503, headers={}, now=0.0, base=0.5, jitter=NO_JITTER) == 0.5
    assert next_delay(attempt=2, status=503, headers={}, now=0.0, base=0.5, jitter=NO_JITTER) == 2.0


def test_exponential_backoff_for_rate_limit_without_headers() -> None:
    d = next_delay(attempt=1, status=429, headers={}, now=0.0, base=0.5, jitter=NO_JITTER)
    assert d == 1.0


def test_backoff_is_capped() -> None:
    d = next_delay(
        attempt=10, status=503, headers={}, now=0.0, base=0.5, cap=30.0, jitter=NO_JITTER
    )
    assert d == 30.0


def test_default_jitter_stays_within_bounds() -> None:
    for _ in range(50):
        d = next_delay(attempt=3, status=503, headers={}, now=0.0, base=0.5)
        assert d is not None
        assert 0.0 <= d <= 4.0  # base * 2**3 == 4.0

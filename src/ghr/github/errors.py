"""Error hierarchy mapping failures to structured output + deterministic exit codes.

Exit codes (mirrored in the CLI and SKILL.md):
    0 ok · 1 internal · 2 usage · 3 not-found · 4 auth-required ·
    5 rate-limited · 6 upstream · 7 partial/timeout (set on the result, not raised)
"""

from __future__ import annotations

import httpx


class GhrError(Exception):
    """Base error. Subclasses set a machine ``code`` and process ``exit_code``."""

    code: str = "internal_error"
    exit_code: int = 1

    def __init__(self, message: str, *, suggestion: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion

    def to_error_dict(self) -> dict[str, str | None]:
        """Render the uniform ``error`` block of the output envelope."""
        return {"code": self.code, "message": self.message, "suggestion": self.suggestion}


class UsageError(GhrError):
    code = "usage_error"
    exit_code = 2


class NotFoundError(GhrError):
    code = "not_found"
    exit_code = 3


class AuthRequiredError(GhrError):
    code = "auth_required"
    exit_code = 4


class RateLimitedError(GhrError):
    code = "rate_limited"
    exit_code = 5


class UpstreamError(GhrError):
    code = "upstream_error"
    exit_code = 6


def classify_http_error(response: httpx.Response) -> GhrError:
    """Map an unsuccessful HTTP response to the appropriate :class:`GhrError`.

    A 403 is rate-limiting only when the primary budget is exhausted
    (``x-ratelimit-remaining: 0``); otherwise it is treated as an auth/scope
    problem the caller can fix with a better token.
    """
    status = response.status_code
    if status == 404:
        return NotFoundError(
            "Resource not found (HTTP 404).",
            suggestion="Check the owner/repo spelling or the item number.",
        )
    if status == 429 or (status == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
        return RateLimitedError(
            f"GitHub rate limit exceeded (HTTP {status}).",
            suggestion="Wait for the reset window, or authenticate for a higher limit.",
        )
    if status in (401, 403):
        return AuthRequiredError(
            f"Authentication required or insufficient (HTTP {status}).",
            suggestion="Set GH_TOKEN / GITHUB_TOKEN or run `gh auth login` with the needed scope.",
        )
    return UpstreamError(f"GitHub upstream error (HTTP {status}).")

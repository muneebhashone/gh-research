"""Tests for the {ok, data, error, meta} output envelope."""

from ghr.github.errors import AuthRequiredError, NotFoundError
from ghr.output.envelope import build_envelope, error_envelope


def test_build_envelope_success() -> None:
    env = build_envelope({"x": 1}, meta={"command": "rate"})
    assert env == {"ok": True, "data": {"x": 1}, "error": None, "meta": {"command": "rate"}}


def test_error_envelope_sets_ok_false_and_null_data() -> None:
    env = error_envelope(NotFoundError("nope"), meta={"command": "repo view"})
    assert env["ok"] is False
    assert env["data"] is None
    assert env["error"] == {"code": "not_found", "message": "nope", "suggestion": None}
    assert env["meta"] == {"command": "repo view"}


def test_error_envelope_preserves_suggestion() -> None:
    env = error_envelope(AuthRequiredError("need", suggestion="do x"), meta={})
    assert env["error"]["suggestion"] == "do x"

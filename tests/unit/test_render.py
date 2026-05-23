"""Tests for the output/render layer: JSON emit, exit-code mapping, human tables."""

from __future__ import annotations

import importlib.util
import io
import json
from typing import Any

from ghr.output.render import EXIT_CODES, emit, exit_code_for

_JQ_AVAILABLE = importlib.util.find_spec("jq") is not None


def _ok_env(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "meta": meta if meta is not None else {}}


def _err_env(code: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": f"{code} happened", "suggestion": "fix it"},
        "meta": meta if meta is not None else {},
    }


# --------------------------------------------------------------------------- emit: JSON


def test_emit_json_mode_writes_one_line_that_round_trips() -> None:
    env = _ok_env({"x": 1, "items": [1, 2, 3]}, meta={"command": "rate", "result_count": 3})
    out = io.StringIO()
    emit(env, json_mode=True, stdout=out)
    text = out.getvalue()
    assert text.endswith("\n")
    assert text.count("\n") == 1  # exactly one line
    assert json.loads(text) == env


def test_emit_json_is_compact_no_spaces() -> None:
    env = _ok_env({"a": 1})
    out = io.StringIO()
    emit(env, json_mode=True, stdout=out)
    # compact separators: no ", " or ": "
    assert ", " not in out.getvalue()
    assert ": " not in out.getvalue()


def test_emit_json_preserves_non_ascii() -> None:
    env = _ok_env({"title": "héllo — 世界"})
    out = io.StringIO()
    emit(env, json_mode=True, stdout=out)
    assert "héllo — 世界" in out.getvalue()
    assert json.loads(out.getvalue()) == env


def test_emit_quiet_meta_drops_meta_but_keeps_ok_data_error() -> None:
    env = _ok_env({"x": 1}, meta={"command": "rate", "secret": "noisy"})
    out = io.StringIO()
    emit(env, json_mode=True, quiet_meta=True, stdout=out)
    obj = json.loads(out.getvalue())
    assert "meta" not in obj
    assert obj["ok"] is True
    assert obj["data"] == {"x": 1}
    assert obj["error"] is None


def test_emit_quiet_meta_does_not_mutate_input_envelope() -> None:
    env = _ok_env({"x": 1}, meta={"command": "rate"})
    out = io.StringIO()
    emit(env, json_mode=True, quiet_meta=True, stdout=out)
    assert "meta" in env  # original untouched


def test_emit_default_mode_with_stringio_is_json() -> None:
    # StringIO.isatty() is False -> agent/pipe path -> JSON
    env = _ok_env({"x": 1}, meta={"command": "rate"})
    out = io.StringIO()
    emit(env, stdout=out)
    assert json.loads(out.getvalue()) == env


# --------------------------------------------------------------------------- emit: human


def test_emit_json_false_uses_human_renderer_dict_data() -> None:
    env = _ok_env({"stars": 42, "name": "cli/cli"}, meta={"command": "repo view"})
    out = io.StringIO()
    emit(env, json_mode=False, stdout=out)
    text = out.getvalue()
    assert text  # wrote something
    # not a single compact JSON object line
    try:
        json.loads(text)
        is_json = True
    except (ValueError, json.JSONDecodeError):
        is_json = False
    assert not is_json
    assert "stars" in text


def test_emit_json_false_uses_human_renderer_list_of_dicts() -> None:
    env = _ok_env(
        [{"number": 1, "title": "a"}, {"number": 2, "title": "b"}],
        meta={"command": "issues list"},
    )
    out = io.StringIO()
    emit(env, json_mode=False, stdout=out)
    text = out.getvalue()
    assert text
    assert "1" in text and "2" in text


def test_emit_json_false_shows_error_code_and_message() -> None:
    env = _err_env("not_found")
    out = io.StringIO()
    emit(env, json_mode=False, stdout=out)
    text = out.getvalue()
    assert "not_found" in text
    assert "not_found happened" in text


# --------------------------------------------------------------------------- emit: jq


def test_emit_jq_expr() -> None:
    env = _ok_env({"x": 99}, meta={"command": "rate"})
    out = io.StringIO()
    emit(env, jq_expr=".data.x", stdout=out)
    text = out.getvalue()
    if _JQ_AVAILABLE:
        # jq applied: each result on its own line as compact JSON
        assert [json.loads(line) for line in text.splitlines() if line] == [99]
    else:
        obj = json.loads(text)
        assert obj["ok"] is False
        assert obj["error"]["code"] == "jq_unavailable"
        assert obj["data"] is None
        assert obj["meta"] == {}


def test_emit_jq_unavailable_never_raises_and_is_an_error_envelope() -> None:
    # Regardless of availability this must not raise and must emit valid JSON.
    env = _ok_env({"x": 1})
    out = io.StringIO()
    emit(env, jq_expr=".data", stdout=out)
    # every line is valid JSON
    for line in out.getvalue().splitlines():
        if line:
            json.loads(line)


# --------------------------------------------------------------------------- exit_code_for


def test_exit_code_ok_is_zero() -> None:
    assert exit_code_for(_ok_env({"x": 1})) == 0


def test_exit_code_truncated_dict_is_seven() -> None:
    env = _ok_env({"x": 1}, meta={"truncated": {"reason": "search_cap"}})
    assert exit_code_for(env) == 7


def test_exit_code_truncated_true_is_seven() -> None:
    env = _ok_env({"x": 1}, meta={"truncated": True})
    assert exit_code_for(env) == 7


def test_exit_code_truncated_false_is_zero() -> None:
    env = _ok_env({"x": 1}, meta={"truncated": False})
    assert exit_code_for(env) == 0


def test_exit_code_truncated_empty_dict_is_zero() -> None:
    # empty dict is falsy -> not truncated
    env = _ok_env({"x": 1}, meta={"truncated": {}})
    assert exit_code_for(env) == 0


def test_exit_code_missing_meta_is_zero() -> None:
    assert exit_code_for({"ok": True, "data": {}, "error": None}) == 0


def test_exit_code_for_each_error_code() -> None:
    assert exit_code_for(_err_env("internal_error")) == 1
    assert exit_code_for(_err_env("usage_error")) == 2
    assert exit_code_for(_err_env("not_found")) == 3
    assert exit_code_for(_err_env("auth_required")) == 4
    assert exit_code_for(_err_env("rate_limited")) == 5
    assert exit_code_for(_err_env("upstream_error")) == 6


def test_exit_code_unknown_error_code_defaults_to_one() -> None:
    assert exit_code_for(_err_env("totally_made_up")) == 1


def test_error_takes_precedence_over_truncated() -> None:
    env = _err_env("not_found", meta={"truncated": True})
    assert exit_code_for(env) == 3


def test_exit_codes_mapping_matches_canonical_contract() -> None:
    assert EXIT_CODES == {
        "internal_error": 1,
        "usage_error": 2,
        "not_found": 3,
        "auth_required": 4,
        "rate_limited": 5,
        "upstream_error": 6,
    }

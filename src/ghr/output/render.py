"""Render the output envelope: JSON emit, ``--jq`` filtering, exit-code mapping.

Agents pipe stdout (non-TTY) and get compact JSON; humans at a TTY get a
minimal table via :mod:`ghr.output.tables`. The exception-to-exit-code map
mirrors :mod:`ghr.github.errors`; exit ``7`` signals partial/capped results.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from ghr.output import tables

# Canonical error-code -> process-exit-code map (see ghr.github.errors).
EXIT_CODES: dict[str, int] = {
    "internal_error": 1,
    "usage_error": 2,
    "not_found": 3,
    "auth_required": 4,
    "rate_limited": 5,
    "upstream_error": 6,
}


def exit_code_for(envelope: Mapping[str, Any]) -> int:
    """Map a finished envelope to its process exit code.

    Failure -> the error's mapped code (unknown codes -> ``1``); a truthy
    ``meta.truncated`` (non-empty dict or ``True``) on success -> ``7``;
    otherwise ``0``.
    """
    if envelope.get("ok") is False:
        error = envelope.get("error") or {}
        code = error.get("code")
        return EXIT_CODES.get(code, 1) if isinstance(code, str) else 1
    if envelope.get("meta", {}).get("truncated"):
        return 7
    return 0


def _want_json(json_mode: bool | None, jq_expr: str | None, stdout: TextIO) -> bool:
    """Decide JSON vs human output. ``--jq`` always implies JSON."""
    if json_mode is not None:
        return json_mode
    if jq_expr is not None:
        return True
    return not stdout.isatty()


def _strip_meta(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Shallow copy of ``envelope`` without the ``meta`` key."""
    return {k: v for k, v in envelope.items() if k != "meta"}


def _dump(obj: Any) -> str:
    """Compact JSON for a single object/value."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _emit_jq(obj: Mapping[str, Any], jq_expr: str, stdout: TextIO) -> None:
    """Apply a jq program if ``jq`` is importable; otherwise emit an error envelope.

    ``jq`` is an optional, undeclared dependency, so a missing import is a
    normal (non-fatal) outcome reported as a ``jq_unavailable`` error envelope.
    """
    try:
        import jq  # type: ignore[import-not-found, import-untyped, unused-ignore]
    except ImportError:
        unavailable: dict[str, Any] = {
            "ok": False,
            "data": None,
            "error": {
                "code": "jq_unavailable",
                "message": (
                    "The --jq option requires the optional 'jq' package, which is not installed."
                ),
                "suggestion": (
                    "Install jq (e.g. `uv pip install jq`) or omit --jq and "
                    "parse the JSON yourself."
                ),
            },
            "meta": {},
        }
        stdout.write(_dump(unavailable) + "\n")
        return

    for result in jq.compile(jq_expr).input_value(obj).all():
        stdout.write(_dump(result) + "\n")


def emit(
    envelope: Mapping[str, Any],
    *,
    json_mode: bool | None = None,
    jq_expr: str | None = None,
    quiet_meta: bool = False,
    stdout: TextIO = sys.stdout,
) -> None:
    """Render ``envelope`` to ``stdout`` as JSON, a jq stream, or a human table.

    Output mode: ``json_mode`` wins if given; else ``--jq`` forces JSON; else
    JSON when stdout is not a TTY (agents pipe), tables otherwise. With
    ``quiet_meta`` the emitted object drops ``meta`` (keeping ok/data/error).
    """
    obj: Mapping[str, Any] = _strip_meta(envelope) if quiet_meta else envelope

    if not _want_json(json_mode, jq_expr, stdout):
        tables.render(obj, stdout)
        return

    if jq_expr is not None:
        _emit_jq(obj, jq_expr, stdout)
        return

    stdout.write(_dump(obj) + "\n")

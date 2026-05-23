"""Minimal, robust human-readable rendering of the output envelope.

The agent-facing path is JSON; this exists only so a human at a TTY sees
something legible. It must never raise on arbitrary JSON-able ``data`` and
uses no external dependencies — just ``stdout.write``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TextIO

_MAX_ROWS = 30
_MAX_CELL = 80


def _scalar(value: Any) -> str:
    """Render a single value to a short, single-line string."""
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) > _MAX_CELL:
        text = text[: _MAX_CELL - 1] + "…"
    return text


def _render_dict(data: Mapping[str, Any], stdout: TextIO) -> None:
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            stdout.write(f"{key}: ({type(value).__name__}, {len(value)} items)\n")
        else:
            stdout.write(f"{key}: {_scalar(value)}\n")


def _render_list(data: list[Any], stdout: TextIO) -> None:
    stdout.write(f"{len(data)} item(s)\n")
    for index, item in enumerate(data[:_MAX_ROWS]):
        if isinstance(item, Mapping):
            cells = "  ".join(f"{k}={_scalar(v)}" for k, v in item.items())
            stdout.write(f"  [{index}] {cells}\n")
        else:
            stdout.write(f"  [{index}] {_scalar(item)}\n")
    if len(data) > _MAX_ROWS:
        stdout.write(f"  ... and {len(data) - _MAX_ROWS} more\n")


def render(envelope: Mapping[str, Any], stdout: TextIO) -> None:
    """Write a compact human summary of ``envelope`` to ``stdout``.

    Prints an ``ok``/error header, then a key/value (dict) or row (list)
    listing of ``data``. Tolerates any JSON-able shape without raising.
    """
    ok = bool(envelope.get("ok"))
    error = envelope.get("error")
    if not ok and isinstance(error, Mapping):
        code = _scalar(error.get("code"))
        message = _scalar(error.get("message"))
        stdout.write(f"ERROR [{code}]: {message}\n")
        suggestion = error.get("suggestion")
        if suggestion:
            stdout.write(f"  suggestion: {_scalar(suggestion)}\n")
        return

    stdout.write("ok\n")
    data = envelope.get("data")
    if isinstance(data, Mapping):
        _render_dict(data, stdout)
    elif isinstance(data, list):
        _render_list(data, stdout)
    elif data is not None:
        stdout.write(f"{_scalar(data)}\n")

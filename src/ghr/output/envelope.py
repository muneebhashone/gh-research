"""The single output contract every command emits: ``{ok, data, error, meta}``."""

from __future__ import annotations

from typing import Any

from ghr.github.errors import GhrError


def build_envelope(data: Any, *, meta: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful result. ``error`` is always ``None`` on success."""
    return {"ok": True, "data": data, "error": None, "meta": meta}


def error_envelope(err: GhrError, *, meta: dict[str, Any]) -> dict[str, Any]:
    """Wrap a failure. ``data`` is always ``None``; ``error`` is the uniform block."""
    return {"ok": False, "data": None, "error": err.to_error_dict(), "meta": meta}

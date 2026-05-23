"""Token-efficient text helpers for the agent-facing output."""

from __future__ import annotations


def trim_text(text: str | None, max_chars: int) -> tuple[str | None, bool]:
    """Trim ``text`` to ``max_chars``.

    Returns ``(trimmed, was_truncated)``. ``None`` passes through untouched.
    """
    if text is None:
        return None, False
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True

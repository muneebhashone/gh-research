"""Tests for token-efficient body trimming."""

from ghr.analysis.text import trim_text


def test_trim_none_returns_none_untruncated() -> None:
    assert trim_text(None, 500) == (None, False)


def test_trim_short_text_unchanged() -> None:
    assert trim_text("hello", 500) == ("hello", False)


def test_trim_long_text_is_cut_and_flagged() -> None:
    text = "x" * 600
    trimmed, truncated = trim_text(text, 500)
    assert truncated is True
    assert trimmed == "x" * 500
    assert trimmed is not None
    assert len(trimmed) == 500


def test_trim_exact_length_not_truncated() -> None:
    assert trim_text("abc", 3) == ("abc", False)

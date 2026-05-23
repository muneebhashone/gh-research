"""Tests for the layered auth/token resolver and the TOML/keyring store.

The resolver is dependency-injected so token precedence is fully exercised
without touching the real environment, ``gh`` subprocess, or config file.
"""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest

from ghr.auth import resolver as resolver_mod
from ghr.auth import store as store_mod
from ghr.auth.resolver import (
    ResolvedToken,
    TokenSource,
    gh_cli_token,
    has_token,
    mask,
    resolve_token,
)
from ghr.auth.store import (
    delete_config_token,
    read_config_token,
    write_config_token,
)


def _no_gh() -> str | None:
    """A gh-cli getter that must never be consulted in these cases."""
    raise AssertionError("gh_token_getter should not be called")


def _no_config() -> str | None:
    raise AssertionError("config_token_getter should not be called")


def _empty_env() -> Mapping[str, str]:
    return {}


# --- precedence ---------------------------------------------------------


def test_token_source_member_values() -> None:
    assert TokenSource.FLAG.value == "flag"
    assert TokenSource.ENV_GH_TOKEN.value == "env:GH_TOKEN"
    assert TokenSource.ENV_GITHUB_TOKEN.value == "env:GITHUB_TOKEN"
    assert TokenSource.GH_CLI.value == "gh-cli"
    assert TokenSource.CONFIG.value == "config-file"
    assert TokenSource.NONE.value == "none"


def test_explicit_cli_token_wins_and_reports_flag() -> None:
    result = resolve_token(
        "flagtok",
        env={"GH_TOKEN": "envtok", "GITHUB_TOKEN": "envtok2"},
        gh_token_getter=_no_gh,
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("flagtok", TokenSource.FLAG)


def test_gh_token_env_beats_github_token_and_below() -> None:
    result = resolve_token(
        None,
        env={"GH_TOKEN": "ghtok", "GITHUB_TOKEN": "ghubtok"},
        gh_token_getter=_no_gh,
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("ghtok", TokenSource.ENV_GH_TOKEN)


def test_github_token_env_beats_gh_cli_and_config() -> None:
    result = resolve_token(
        None,
        env={"GITHUB_TOKEN": "ghubtok"},
        gh_token_getter=_no_gh,
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("ghubtok", TokenSource.ENV_GITHUB_TOKEN)


def test_gh_cli_beats_config() -> None:
    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: "clitok",
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("clitok", TokenSource.GH_CLI)


def test_config_used_when_nothing_above_resolves() -> None:
    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: None,
        config_token_getter=lambda: "cfgtok",
    )
    assert result == ResolvedToken("cfgtok", TokenSource.CONFIG)


def test_none_when_nothing_resolves() -> None:
    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: None,
        config_token_getter=lambda: None,
    )
    assert result == ResolvedToken(None, TokenSource.NONE)


# --- empty / whitespace handling ---------------------------------------


def test_empty_string_cli_token_is_skipped() -> None:
    result = resolve_token(
        "   ",
        env={"GH_TOKEN": "ghtok"},
        gh_token_getter=_no_gh,
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("ghtok", TokenSource.ENV_GH_TOKEN)


def test_empty_env_values_are_skipped() -> None:
    result = resolve_token(
        None,
        env={"GH_TOKEN": "", "GITHUB_TOKEN": "   "},
        gh_token_getter=lambda: "clitok",
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("clitok", TokenSource.GH_CLI)


def test_whitespace_is_stripped_from_winning_token() -> None:
    result = resolve_token(
        "  spacedtok  ",
        env=_empty_env(),
        gh_token_getter=_no_config,
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("spacedtok", TokenSource.FLAG)


# --- failure tolerance --------------------------------------------------


def test_gh_getter_that_raises_does_not_propagate() -> None:
    def boom() -> str | None:
        raise RuntimeError("subprocess blew up")

    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=boom,
        config_token_getter=lambda: "cfgtok",
    )
    assert result == ResolvedToken("cfgtok", TokenSource.CONFIG)


def test_config_getter_that_raises_falls_through_to_none() -> None:
    def boom() -> str | None:
        raise RuntimeError("config read blew up")

    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: None,
        config_token_getter=boom,
    )
    assert result == ResolvedToken(None, TokenSource.NONE)


# --- has_token ----------------------------------------------------------


def test_has_token_true_when_resolved() -> None:
    assert has_token(
        "flagtok",
        env=_empty_env(),
        gh_token_getter=_no_gh,
        config_token_getter=_no_config,
    )


def test_has_token_false_when_nothing_resolves() -> None:
    assert not has_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: None,
        config_token_getter=lambda: None,
    )


# --- gh_cli_token (the real subprocess seam) ----------------------------


class _FakeProc:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_gh_cli_token_returns_stripped_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resolver_mod.subprocess,
        "run",
        lambda *a, **k: _FakeProc(0, "  tok-from-gh\n"),
    )
    assert gh_cli_token() == "tok-from-gh"


def test_gh_cli_token_none_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resolver_mod.subprocess, "run", lambda *a, **k: _FakeProc(1, "not logged in")
    )
    assert gh_cli_token() is None


def test_gh_cli_token_none_on_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver_mod.subprocess, "run", lambda *a, **k: _FakeProc(0, "   \n"))
    assert gh_cli_token() is None


def test_gh_cli_token_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> _FakeProc:
        raise FileNotFoundError("gh not installed")

    monkeypatch.setattr(resolver_mod.subprocess, "run", boom)
    assert gh_cli_token() is None

    def timeout(*a: object, **k: object) -> _FakeProc:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=5)

    monkeypatch.setattr(resolver_mod.subprocess, "run", timeout)
    assert gh_cli_token() is None


def test_injected_getters_never_invoke_real_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Security invariant: with getters injected, the real `gh` shell-out is
    # never reached, so subprocess.run must not be called at all.
    def fail(*a: object, **k: object) -> object:
        raise AssertionError("real subprocess.run must not be called")

    monkeypatch.setattr(resolver_mod.subprocess, "run", fail)
    result = resolve_token(
        None,
        env=_empty_env(),
        gh_token_getter=lambda: "clitok",
        config_token_getter=_no_config,
    )
    assert result == ResolvedToken("clitok", TokenSource.GH_CLI)


# --- mask ---------------------------------------------------------------


def test_mask_none_returns_placeholder() -> None:
    assert mask(None) == "<none>"


def test_mask_long_token_shows_only_last_four() -> None:
    masked = mask("ghp_supersecretvalue1234")
    assert masked == "***1234"
    assert "supersecret" not in masked


def test_mask_short_token_is_fully_hidden() -> None:
    # 4 chars or fewer must never leak any character.
    assert mask("abcd") == "****"
    assert mask("ab") == "****"
    assert mask("") == "****"


# === store.py ===========================================================


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    write_config_token(cfg, "round-trip-token")
    assert read_config_token(cfg) == "round-trip-token"


def test_read_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_config_token(tmp_path / "does-not-exist.toml") is None


def test_read_file_without_auth_section_returns_none(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[defaults]\nlimit = 30\n", encoding="utf-8")
    assert read_config_token(cfg) is None


def test_write_creates_parent_directory(tmp_path: Path) -> None:
    cfg = tmp_path / "nested" / "deeper" / "config.toml"
    write_config_token(cfg, "tok")
    assert cfg.exists()
    assert read_config_token(cfg) == "tok"


def test_write_preserves_pre_existing_unrelated_table(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[defaults]\nlimit = 30\nlanguage = "python"\n', encoding="utf-8")
    write_config_token(cfg, "new-token")

    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["auth"]["token"] == "new-token"
    assert data["defaults"] == {"limit": 30, "language": "python"}


def test_write_updates_existing_token(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    write_config_token(cfg, "old")
    write_config_token(cfg, "new")
    assert read_config_token(cfg) == "new"


def test_delete_removes_token_and_reports_true(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    write_config_token(cfg, "tok")
    assert delete_config_token(cfg) is True
    assert read_config_token(cfg) is None


def test_delete_preserves_other_tables(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[defaults]\nlimit = 30\n", encoding="utf-8")
    write_config_token(cfg, "tok")
    assert delete_config_token(cfg) is True

    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert "token" not in data.get("auth", {})
    assert data["defaults"] == {"limit": 30}


def test_delete_missing_file_returns_false(tmp_path: Path) -> None:
    assert delete_config_token(tmp_path / "nope.toml") is False


def test_delete_when_no_token_key_returns_false(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[defaults]\nlimit = 30\n", encoding="utf-8")
    assert delete_config_token(cfg) is False


# --- keyring backend (import-guarded) -----------------------------------


def test_keyring_get_returns_none_when_backend_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate `import keyring` failing.
    monkeypatch.setattr(store_mod, "_import_keyring", lambda: None)
    assert store_mod.keyring_get() is None


def test_keyring_set_and_delete_return_false_when_backend_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_mod, "_import_keyring", lambda: None)
    assert store_mod.keyring_set("tok") is False
    assert store_mod.keyring_delete() is False


def test_keyring_round_trip_with_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeKeyring:
        def __init__(self) -> None:
            self.store: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, user: str) -> str | None:
            return self.store.get((service, user))

        def set_password(self, service: str, user: str, password: str) -> None:
            self.store[(service, user)] = password

        def delete_password(self, service: str, user: str) -> None:
            del self.store[(service, user)]

    fake = _FakeKeyring()
    monkeypatch.setattr(store_mod, "_import_keyring", lambda: fake)

    assert store_mod.keyring_get() is None
    assert store_mod.keyring_set("kr-token") is True
    assert store_mod.keyring_get() == "kr-token"
    assert store_mod.keyring_delete() is True
    assert store_mod.keyring_get() is None


def test_keyring_calls_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenKeyring:
        def get_password(self, service: str, user: str) -> str | None:
            raise RuntimeError("no backend available")

        def set_password(self, service: str, user: str, password: str) -> None:
            raise RuntimeError("locked")

        def delete_password(self, service: str, user: str) -> None:
            raise RuntimeError("locked")

    monkeypatch.setattr(store_mod, "_import_keyring", lambda: _BrokenKeyring())
    assert store_mod.keyring_get() is None
    assert store_mod.keyring_set("tok") is False
    assert store_mod.keyring_delete() is False

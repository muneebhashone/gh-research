"""Layered token resolution with explicit, fully unit-testable precedence.

Precedence (first non-empty wins):
    explicit ``--token`` flag  → ``FLAG``
    ``GH_TOKEN`` env           → ``ENV_GH_TOKEN``
    ``GITHUB_TOKEN`` env       → ``ENV_GITHUB_TOKEN``
    ``gh auth token``          → ``GH_CLI``
    config-file / keyring      → ``CONFIG``
    nothing                    → ``NONE``

Every external source is injectable so precedence can be tested without
touching the real environment, the ``gh`` subprocess, or the config file.
The raw token is never logged or printed; :func:`mask` is the only display
path.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum


class TokenSource(str, Enum):  # noqa: UP042 - explicit (str, Enum) is part of the public contract
    """The provenance of a resolved token (reported by ``auth status``)."""

    FLAG = "flag"
    ENV_GH_TOKEN = "env:GH_TOKEN"
    ENV_GITHUB_TOKEN = "env:GITHUB_TOKEN"
    GH_CLI = "gh-cli"
    CONFIG = "config-file"
    NONE = "none"


@dataclass(frozen=True)
class ResolvedToken:
    """A token and where it came from. ``token`` is ``None`` only for ``NONE``."""

    token: str | None
    source: TokenSource


def _clean(value: str | None) -> str | None:
    """Return the stripped value, or ``None`` for empty/whitespace-only input."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _safe_get(getter: Callable[[], str | None]) -> str | None:
    """Invoke a token getter, swallowing any exception (never propagate)."""
    try:
        return _clean(getter())
    except Exception:
        return None


def gh_cli_token() -> str | None:
    """Default ``GH_CLI`` getter: shell out to ``gh auth token``.

    Returns the stripped token, or ``None`` on any failure (missing ``gh``,
    non-zero exit, timeout, empty output). Never raises.
    """
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return _clean(proc.stdout)


def _config_none() -> str | None:
    """Default ``CONFIG`` getter hook: resolves nothing unless wired up."""
    return None


def resolve_token(
    cli_token: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    gh_token_getter: Callable[[], str | None] | None = None,
    config_token_getter: Callable[[], str | None] | None = None,
) -> ResolvedToken:
    """Resolve a token by precedence (first non-empty wins).

    ``cli_token`` (→FLAG) > ``GH_TOKEN`` (→ENV_GH_TOKEN) >
    ``GITHUB_TOKEN`` (→ENV_GITHUB_TOKEN) > ``gh_token_getter`` (→GH_CLI) >
    ``config_token_getter`` (→CONFIG) > ``ResolvedToken(None, NONE)``.

    Empty/whitespace-only values are treated as absent. ``env`` defaults to
    :data:`os.environ`; the getters default to a real ``gh auth token``
    shell-out and a no-op config hook. Getters that raise are tolerated and
    treated as resolving nothing.
    """
    flag = _clean(cli_token)
    if flag is not None:
        return ResolvedToken(flag, TokenSource.FLAG)

    environ = env if env is not None else os.environ
    gh_env = _clean(environ.get("GH_TOKEN"))
    if gh_env is not None:
        return ResolvedToken(gh_env, TokenSource.ENV_GH_TOKEN)
    github_env = _clean(environ.get("GITHUB_TOKEN"))
    if github_env is not None:
        return ResolvedToken(github_env, TokenSource.ENV_GITHUB_TOKEN)

    gh_getter = gh_token_getter if gh_token_getter is not None else gh_cli_token
    cli = _safe_get(gh_getter)
    if cli is not None:
        return ResolvedToken(cli, TokenSource.GH_CLI)

    cfg_getter = config_token_getter if config_token_getter is not None else _config_none
    cfg = _safe_get(cfg_getter)
    if cfg is not None:
        return ResolvedToken(cfg, TokenSource.CONFIG)

    return ResolvedToken(None, TokenSource.NONE)


def has_token(
    cli_token: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    gh_token_getter: Callable[[], str | None] | None = None,
    config_token_getter: Callable[[], str | None] | None = None,
) -> bool:
    """``True`` iff a token resolves (used for graceful Discussions degradation)."""
    return bool(
        resolve_token(
            cli_token,
            env=env,
            gh_token_getter=gh_token_getter,
            config_token_getter=config_token_getter,
        ).token
    )


def mask(token: str | None) -> str:
    """Render a token safe for display, never revealing the full value.

    ``None`` becomes ``"<none>"``; tokens longer than four characters show
    only a ``"***" + last four`` hint; anything shorter is fully hidden.
    """
    if token is None:
        return "<none>"
    if len(token) > 4:
        return "***" + token[-4:]
    return "****"

"""Application context: resolves config + token and builds the GitHub client.

Built once per invocation (in the CLI callback) and passed to commands. Also
houses the pure ``build_meta`` helper that assembles the envelope ``meta`` block.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

from ghr import __version__
from ghr.auth.resolver import ResolvedToken, TokenSource, resolve_token
from ghr.auth.store import keyring_get, read_config_token
from ghr.cache.store import CacheStore
from ghr.config import Settings, load_settings
from ghr.github.client import GitHubClient
from ghr.github.ratelimit import BudgetGuard, RateLimitState
from ghr.github.session import build_session

APP_NAME = "gh-research"


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def default_cache_path() -> Path:
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)) / "cache.sqlite3"


def _env_path(env: Mapping[str, str], key: str) -> Path | None:
    value = env.get(key)
    return Path(value) if value else None


def load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def build_meta(
    *,
    command: str,
    params: Mapping[str, Any],
    state: RateLimitState | None = None,
    cache_hits: int = 0,
    cache_misses: int = 0,
    budget: BudgetGuard | None = None,
    resource: str | None = None,
    truncated: Mapping[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    scoring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the envelope ``meta`` block (pure)."""
    meta: dict[str, Any] = {
        "command": command,
        "params": dict(params),
        "tool_version": __version__,
        "cache": {"hits": cache_hits, "misses": cache_misses},
    }
    if resource and state is not None:
        snapshot = state.snapshot(resource)
        if snapshot is not None:
            meta["rate_limit"] = snapshot
    if budget is not None:
        meta["requests_made"] = budget.requests_made
        meta["elapsed_ms"] = budget.elapsed_ms()
    if truncated:
        meta["truncated"] = dict(truncated)
    if warnings:
        meta["warnings"] = warnings
    if scoring:
        meta["scoring"] = dict(scoring)
    return meta


@dataclass
class AppContext:
    settings: Settings
    token: ResolvedToken
    client: GitHubClient
    budget: BudgetGuard
    now: datetime
    config_path: Path
    cache_path: Path
    output_json: bool | None = None
    jq: str | None = None
    quiet_meta: bool = False
    full: bool = False

    @property
    def has_token(self) -> bool:
        return bool(self.token.token)

    def meta(
        self, command: str, params: Mapping[str, Any], *, resource: str | None = None, **extra: Any
    ) -> dict[str, Any]:
        return build_meta(
            command=command,
            params=params,
            state=self.client.state,
            cache_hits=self.client.cache_hits,
            cache_misses=self.client.cache_misses,
            budget=self.budget,
            resource=resource,
            **extra,
        )

    def close(self) -> None:
        self.client.close()


def build_context(
    *,
    cli: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
    cache_path: Path | None = None,
    gh_token_getter: Callable[[], str | None] | None = None,
    config_token_getter: Callable[[], str | None] | None = None,
) -> AppContext:
    """Resolve settings + token from the precedence chain and build the client.

    ``gh_token_getter``/``config_token_getter`` are injectable for testing; in
    normal use the gh-CLI shell-out and config-file/keyring lookups are used.
    """
    env = env if env is not None else dict(os.environ)
    config_path = config_path or _env_path(env, "GHR_CONFIG_PATH") or default_config_path()
    cache_path = cache_path or _env_path(env, "GHR_CACHE_PATH") or default_cache_path()

    file_data = load_config_file(config_path)
    settings_config = file_data.get("defaults", {})
    settings = load_settings(cli=cli, env=env, config=settings_config)

    if cli.get("token_source") == "none":
        token = ResolvedToken(None, TokenSource.NONE)
    else:
        if config_token_getter is None:

            def config_token_getter() -> str | None:
                return read_config_token(config_path) or keyring_get()

        token = resolve_token(
            cli.get("token"),
            env=env,
            gh_token_getter=gh_token_getter,
            config_token_getter=config_token_getter,
        )

    use_cache = settings.cache_enabled and not cli.get("no_cache", False)
    cache = CacheStore(cache_path) if use_cache else None
    budget = BudgetGuard(max_requests=settings.max_requests, time_budget_ms=settings.time_budget_ms)
    state = RateLimitState()
    client = GitHubClient(
        session=build_session(token.token),
        cache=cache,
        budget=budget,
        state=state,
        settings=settings,
        token=token.token,
        refresh=cli.get("refresh", False),
        use_cache=use_cache,
    )
    return AppContext(
        settings=settings,
        token=token,
        client=client,
        budget=budget,
        now=datetime.now(UTC),
        config_path=config_path,
        cache_path=cache_path,
        output_json=cli.get("json"),
        jq=cli.get("jq"),
        quiet_meta=cli.get("quiet_meta", False),
        full=cli.get("full", False),
    )

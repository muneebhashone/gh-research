"""Settings with layered precedence: flag > env (GHR_*) > config file > default."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ghr import constants

ENV_PREFIX = "GHR_"
_TRUE = {"1", "true", "yes", "on"}


@dataclasses.dataclass(frozen=True)
class Settings:
    default_limit: int = constants.DEFAULT_LIMIT
    max_limit: int = constants.MAX_LIMIT
    max_pages: int = constants.MAX_PAGES
    graphql_node_budget: int = constants.GRAPHQL_NODE_BUDGET
    max_requests: int = constants.MAX_REQUESTS
    time_budget_ms: int = constants.TIME_BUDGET_MS
    body_char_cap: int = constants.BODY_CHAR_CAP
    cache_enabled: bool = True
    half_life_days: float = 30.0
    w_reactions: float = 1.0
    w_comments: float = 0.7
    w_recency: float = 1.5
    config_path: Path | None = None
    cache_path: Path | None = None

    @property
    def weights(self) -> dict[str, float]:
        return {
            "reactions": self.w_reactions,
            "comments": self.w_comments,
            "recency": self.w_recency,
        }


def _coerce(raw: Any, default: Any) -> Any:
    """Coerce a string/loose value to the type implied by the field's default."""
    if isinstance(default, bool):
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in _TRUE
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def load_settings(
    *,
    cli: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> Settings:
    """Resolve every setting through the precedence chain into a frozen ``Settings``."""
    cli = cli or {}
    env = env or {}
    config = config or {}

    values: dict[str, Any] = {}
    for field in dataclasses.fields(Settings):
        name, default = field.name, field.default
        env_key = ENV_PREFIX + name.upper()
        if cli.get(name) is not None:
            values[name] = cli[name]
        elif env.get(env_key, "") != "":
            values[name] = _coerce(env[env_key], default)
        elif config.get(name) is not None:
            values[name] = _coerce(config[name], default)
        else:
            values[name] = default
    return Settings(**values)

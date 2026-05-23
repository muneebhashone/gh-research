"""Shared plumbing for command modules: context access, the emit/exit flow, helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

from ghr.analysis.text import trim_text
from ghr.context import AppContext, build_context
from ghr.github.errors import AuthRequiredError, GhrError, UsageError
from ghr.github.ratelimit import BudgetExceeded
from ghr.output.envelope import build_envelope, error_envelope
from ghr.output.render import emit, exit_code_for

#: Result of a command's work: (data, extra_meta) where extra_meta only carries
#: keys ``build_meta`` accepts (truncated/warnings/scoring).
Work = Callable[[], tuple[Any, dict[str, Any]]]


@dataclass
class CliState:
    """Holds parsed global flags; builds the AppContext lazily on first use."""

    cli: dict[str, Any]
    config_path: Path | None = None
    _ctx: AppContext | None = field(default=None, repr=False)

    def context(self) -> AppContext:
        if self._ctx is None:
            self._ctx = build_context(cli=self.cli, config_path=self.config_path)
        return self._ctx


def app_context(ctx: typer.Context) -> AppContext:
    state: CliState = ctx.obj
    return state.context()


def split_repo(slug: str) -> tuple[str, str]:
    """Parse ``owner/repo`` → ``(owner, repo)`` or raise a usage error.

    Raises :class:`UsageError` (a GhrError) so it surfaces as a JSON error
    envelope with exit 2 rather than Typer's human-only error.
    """
    parts = slug.split("/")
    if len(parts) != 2 or not all(parts):
        raise UsageError(f"Expected OWNER/REPO, got {slug!r}.", suggestion="e.g. cli/cli")
    return parts[0], parts[1]


def require_token(actx: AppContext) -> None:
    """Fail fast (exit 4) before a doomed GraphQL call when no token is available."""
    if not actx.has_token:
        raise AuthRequiredError(
            "GitHub Discussions require an authenticated token (GraphQL is auth-only).",
            suggestion="Set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`, then retry.",
        )


def with_trimmed_body(
    item: Mapping[str, Any], actx: AppContext, *, include_body: bool
) -> dict[str, Any]:
    """Drop the body (lists/searches) or trim it to the cap (views), per --full."""
    out = {k: v for k, v in item.items() if k != "body"}
    if not include_body:
        return out
    body = item.get("body")
    if actx.full or body is None:
        out["body"] = body
        out["body_truncated"] = False
    else:
        trimmed, was_truncated = trim_text(body, actx.settings.body_char_cap)
        out["body"] = trimmed
        out["body_truncated"] = was_truncated
    return out


def finish(
    actx: AppContext,
    *,
    command: str,
    params: Mapping[str, Any],
    resource: str | None,
    work: Work,
) -> None:
    """Run a command's work, build + emit the envelope, set the exit code, clean up."""
    try:
        try:
            data, extra = work()
            meta = actx.meta(command, params, resource=resource, **extra)
            envelope = build_envelope(data, meta=meta)
        except GhrError as exc:
            envelope = error_envelope(exc, meta=actx.meta(command, params, resource=resource))
        except BudgetExceeded as exc:
            meta = actx.meta(command, params, resource=resource, truncated={"reason": exc.reason})
            envelope = build_envelope(None, meta=meta)
        emit(
            envelope,
            json_mode=actx.output_json,
            jq_expr=actx.jq,
            quiet_meta=actx.quiet_meta,
            stdout=sys.stdout,
        )
        raise typer.Exit(exit_code_for(envelope))
    finally:
        actx.close()

"""Engagement ('hot') scoring for issues and discussions.

The score blends positive reactions, comment volume, and recency:

    hot = w_react * log1p(positive_reactions)
        + w_comments * log1p(comments)
        + w_recency * recency_factor(age)

``log1p`` damps mega-threads (diminishing returns); the exponential recency
factor makes "hot" mean *currently* hot rather than all-time popular.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

DEFAULT_WEIGHTS: dict[str, float] = {"reactions": 1.0, "comments": 0.7, "recency": 1.5}
DEFAULT_HALF_LIFE_DAYS: float = 30.0

#: Reaction emojis that count as positive signal.
POSITIVE_REACTIONS: tuple[str, ...] = ("+1", "laugh", "hooray", "heart", "rocket")
#: All GitHub reaction emojis (REST naming).
ALL_REACTIONS: tuple[str, ...] = (
    "+1",
    "-1",
    "laugh",
    "hooray",
    "confused",
    "heart",
    "rocket",
    "eyes",
)


def recency_factor(age_days: float, *, half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Exponential decay: 1.0 at age 0, 0.5 at one half-life, 0.25 at two."""
    return math.exp(-math.log(2) * age_days / half_life_days)


def hot_score(
    *,
    positive_reactions: int,
    comments: int,
    recency: float,
    weights: Mapping[str, float] | None = None,
    ndigits: int = 4,
) -> float:
    """Deterministic engagement score, rounded for byte-stable output."""
    w = weights if weights is not None else DEFAULT_WEIGHTS
    raw = (
        w["reactions"] * math.log1p(positive_reactions)
        + w["comments"] * math.log1p(comments)
        + w["recency"] * recency
    )
    return round(raw, ndigits)


def positive_reactions(reactions: Mapping[str, int]) -> int:
    """Sum the positive-signal reaction emojis, tolerating missing keys."""
    return sum(int(reactions.get(k, 0)) for k in POSITIVE_REACTIONS)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def age_in_days(updated_at: str, *, now: datetime) -> float:
    """Age in (fractional) days between ``updated_at`` and ``now``."""
    return (now - _parse_ts(updated_at)).total_seconds() / 86400.0


def rank_items(
    items: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    weights: Mapping[str, float] | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Attach ``hot_score`` to each item and return a new sorted list.

    Order: ``hot_score`` desc, then most-recently-updated, then lowest number.
    Does not mutate the input items.
    """
    scored: list[dict[str, Any]] = []
    for item in items:
        reactions = item.get("reactions") or {}
        rec = recency_factor(
            age_in_days(item["updated_at"], now=now), half_life_days=half_life_days
        )
        score = hot_score(
            positive_reactions=positive_reactions(reactions),
            comments=int(item.get("comments", 0)),
            recency=rec,
            weights=weights,
        )
        enriched = dict(item)
        enriched["hot_score"] = score
        scored.append(enriched)

    scored.sort(
        key=lambda i: (-i["hot_score"], -_parse_ts(i["updated_at"]).timestamp(), i["number"])
    )
    return scored[:top] if top is not None else scored

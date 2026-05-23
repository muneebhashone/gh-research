"""Activity-trend primitive: is a project 'booming' or 'dying'?

Consumes per-bucket opened/closed counts (the command layer fetches these via
cheap ``/search/issues`` total_count queries) and derives momentum + a
deterministic, thresholded verdict — no LLM judgement.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

BOOM_THRESHOLD = 0.25
DIE_THRESHOLD = -0.25
RATIO_THRESHOLD = 1.2


def compute_activity(buckets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return per-bucket stats plus an overall momentum and verdict.

    ``momentum`` compares opened volume in the most recent half of the window
    against the preceding half: ``(recent - prior) / max(prior, 1)``.
    """
    rows = list(buckets)
    enriched: list[dict[str, Any]] = []
    for b in rows:
        opened = int(b["opened"])
        closed = int(b["closed"])
        enriched.append(
            {
                "start": b["start"],
                "opened": opened,
                "closed": closed,
                "net": opened - closed,
                "ratio": round(opened / max(closed, 1), 4),
            }
        )

    half = len(enriched) // 2
    momentum = 0.0
    verdict = "steady"
    if half >= 1:
        recent = sum(b["opened"] for b in enriched[-half:])
        prior = sum(b["opened"] for b in enriched[-2 * half : -half])
        momentum = round((recent - prior) / max(prior, 1), 4)
        recent_ratio = recent / max(prior, 1)
        if momentum >= BOOM_THRESHOLD and recent_ratio >= RATIO_THRESHOLD:
            verdict = "booming"
        elif momentum <= DIE_THRESHOLD:
            verdict = "dying"

    return {
        "buckets": enriched,
        "momentum": momentum,
        "verdict": verdict,
        "thresholds": {"boom": BOOM_THRESHOLD, "die": DIE_THRESHOLD, "ratio": RATIO_THRESHOLD},
    }

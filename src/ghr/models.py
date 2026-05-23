"""Normalize GitHub REST/GraphQL payloads into uniform, analysis-ready items.

A normalized issue/discussion item has a stable shape so the (pure) analysis
functions and the output layer never branch on transport details:

    {kind, number, title, state, url, created_at, updated_at, comments,
     reactions: {<emoji>: int, total: int}, labels: [str], is_answered, body, ...}
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

#: REST reaction emoji keys, in canonical order.
REACTION_KEYS: tuple[str, ...] = (
    "+1",
    "-1",
    "laugh",
    "hooray",
    "confused",
    "heart",
    "rocket",
    "eyes",
)

#: GraphQL reactionGroup ``content`` enum → REST emoji key.
_GQL_REACTION_MAP: dict[str, str] = {
    "THUMBS_UP": "+1",
    "THUMBS_DOWN": "-1",
    "LAUGH": "laugh",
    "HOORAY": "hooray",
    "CONFUSED": "confused",
    "HEART": "heart",
    "ROCKET": "rocket",
    "EYES": "eyes",
}


def _reactions_from_rest(raw: Mapping[str, Any] | None) -> dict[str, int]:
    raw = raw or {}
    counts = {key: int(raw.get(key, 0)) for key in REACTION_KEYS}
    counts["total"] = int(raw.get("total_count", sum(counts.values())))
    return counts


def _reactions_from_groups(groups: Any) -> dict[str, int]:
    counts = {key: 0 for key in REACTION_KEYS}
    for group in groups or []:
        key = _GQL_REACTION_MAP.get(group.get("content"))
        if key is None:
            continue
        reactors = group.get("reactors") or {}
        counts[key] = int(reactors.get("totalCount", 0))
    counts["total"] = sum(counts.values())
    return counts


def is_pull_request(raw: Mapping[str, Any]) -> bool:
    """The REST issues endpoint also returns PRs; they carry a ``pull_request`` key."""
    return "pull_request" in raw


def normalize_issue(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Map a REST issue object to the uniform item shape."""
    labels = [
        label["name"] if isinstance(label, Mapping) else str(label)
        for label in raw.get("labels", [])
    ]
    return {
        "kind": "issue",
        "number": int(raw["number"]),
        "title": raw.get("title", ""),
        "state": raw.get("state", "open"),
        "url": raw.get("html_url", ""),
        "created_at": raw.get("created_at", ""),
        "updated_at": raw.get("updated_at", ""),
        "comments": int(raw.get("comments", 0)),
        "reactions": _reactions_from_rest(raw.get("reactions")),
        "labels": labels,
        "is_answered": None,
        "body": raw.get("body"),
    }


def normalize_discussion(node: Mapping[str, Any]) -> dict[str, Any]:
    """Map a GraphQL discussion node to the uniform item shape."""
    category = node.get("category") or {}
    label_nodes = (node.get("labels") or {}).get("nodes") or []
    return {
        "kind": "discussion",
        "number": int(node["number"]),
        "title": node.get("title", ""),
        "state": "closed" if node.get("closed") else "open",
        "url": node.get("url", ""),
        "created_at": node.get("createdAt", ""),
        "updated_at": node.get("updatedAt", ""),
        "comments": int((node.get("comments") or {}).get("totalCount", 0)),
        "reactions": _reactions_from_groups(node.get("reactionGroups")),
        "labels": [lbl.get("name") for lbl in label_nodes],
        "is_answered": node.get("isAnswered"),
        "category": category.get("name"),
        "body": node.get("bodyText"),
    }


def normalize_repo(raw: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Map a REST repository object to health fields + derived velocity metrics."""
    created = datetime.fromisoformat(raw["created_at"])
    pushed = datetime.fromisoformat(raw["pushed_at"])
    age_days = (now - created).total_seconds() / 86400.0
    stars = int(raw.get("stargazers_count", 0))
    license_obj = raw.get("license") or {}
    return {
        "full_name": raw.get("full_name", ""),
        "description": raw.get("description"),
        "url": raw.get("html_url", ""),
        "stars": stars,
        "forks": int(raw.get("forks_count", 0)),
        "open_issues": int(raw.get("open_issues_count", 0)),
        "watchers": int(raw.get("subscribers_count", 0)),
        "pushed_at": raw.get("pushed_at"),
        "created_at": raw.get("created_at"),
        "archived": bool(raw.get("archived", False)),
        "disabled": bool(raw.get("disabled", False)),
        "license": license_obj.get("spdx_id") if license_obj else None,
        "default_branch": raw.get("default_branch"),
        "topics": list(raw.get("topics", [])),
        "has_discussions": bool(raw.get("has_discussions", False)),
        "days_since_push": int((now - pushed).total_seconds() // 86400),
        "stars_per_day": round(stars / max(age_days, 1.0), 4),
    }

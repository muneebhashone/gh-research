"""Tests for normalizing GitHub REST/GraphQL payloads into uniform items."""

from datetime import UTC, datetime

from ghr.models import (
    is_pull_request,
    normalize_discussion,
    normalize_issue,
    normalize_repo,
)

NOW = datetime(2026, 5, 23, tzinfo=UTC)

REST_ISSUE = {
    "number": 5,
    "title": "Crash on save",
    "state": "open",
    "html_url": "https://github.com/o/r/issues/5",
    "created_at": "2026-05-01T00:00:00Z",
    "updated_at": "2026-05-10T00:00:00Z",
    "comments": 3,
    "body": "repro steps...",
    "labels": [{"name": "bug"}, {"name": "crash"}],
    "reactions": {
        "+1": 4,
        "-1": 0,
        "laugh": 0,
        "hooray": 1,
        "confused": 2,
        "heart": 0,
        "rocket": 0,
        "eyes": 0,
        "total_count": 7,
    },
}


def test_normalize_issue_shape() -> None:
    item = normalize_issue(REST_ISSUE)
    assert item == {
        "kind": "issue",
        "number": 5,
        "title": "Crash on save",
        "state": "open",
        "url": "https://github.com/o/r/issues/5",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-10T00:00:00Z",
        "comments": 3,
        "reactions": {
            "+1": 4,
            "-1": 0,
            "laugh": 0,
            "hooray": 1,
            "confused": 2,
            "heart": 0,
            "rocket": 0,
            "eyes": 0,
            "total": 7,
        },
        "labels": ["bug", "crash"],
        "is_answered": None,
        "body": "repro steps...",
    }


def test_is_pull_request_detects_pr_key() -> None:
    assert is_pull_request({"pull_request": {"url": "..."}}) is True
    assert is_pull_request(REST_ISSUE) is False


REST_DISCUSSION = {
    "number": 12,
    "title": "How to configure X?",
    "bodyText": "body text",
    "url": "https://github.com/o/r/discussions/12",
    "createdAt": "2026-05-01T00:00:00Z",
    "updatedAt": "2026-05-09T00:00:00Z",
    "isAnswered": True,
    "closed": False,
    "category": {"name": "Q&A", "isAnswerable": True},
    "comments": {"totalCount": 8},
    "labels": {"nodes": [{"name": "question"}]},
    "reactionGroups": [
        {"content": "THUMBS_UP", "reactors": {"totalCount": 5}},
        {"content": "HEART", "reactors": {"totalCount": 2}},
    ],
}


def test_normalize_discussion_maps_reaction_groups_and_fields() -> None:
    item = normalize_discussion(REST_DISCUSSION)
    assert item["kind"] == "discussion"
    assert item["number"] == 12
    assert item["state"] == "open"
    assert item["comments"] == 8
    assert item["labels"] == ["question"]
    assert item["is_answered"] is True
    assert item["category"] == "Q&A"
    assert item["body"] == "body text"
    assert item["reactions"] == {
        "+1": 5,
        "-1": 0,
        "laugh": 0,
        "hooray": 0,
        "confused": 0,
        "heart": 2,
        "rocket": 0,
        "eyes": 0,
        "total": 7,
    }


REST_REPO = {
    "full_name": "o/r",
    "description": "a tool",
    "html_url": "https://github.com/o/r",
    "stargazers_count": 1000,
    "forks_count": 50,
    "open_issues_count": 42,
    "subscribers_count": 10,
    "pushed_at": "2026-05-20T00:00:00Z",
    "created_at": "2024-05-23T00:00:00Z",
    "archived": False,
    "disabled": False,
    "license": {"spdx_id": "MIT"},
    "default_branch": "main",
    "topics": ["cli", "tool"],
    "has_discussions": True,
}


def test_normalize_repo_health_and_derived_metrics() -> None:
    repo = normalize_repo(REST_REPO, now=NOW)
    assert repo["full_name"] == "o/r"
    assert repo["stars"] == 1000
    assert repo["forks"] == 50
    assert repo["open_issues"] == 42
    assert repo["license"] == "MIT"
    assert repo["topics"] == ["cli", "tool"]
    assert repo["has_discussions"] is True
    assert repo["archived"] is False
    assert repo["days_since_push"] == 3
    # created 2024-05-23 → now 2026-05-23 = 730 days; 1000/730
    assert repo["stars_per_day"] == round(1000 / 730, 4)

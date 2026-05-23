"""Tests for reaction tallying and item ranking orchestration."""

from datetime import UTC, datetime

from ghr.analysis.rank import positive_reactions, rank_items

NOW = datetime(2026, 5, 23, tzinfo=UTC)


def test_positive_reactions_sums_only_positive_emojis() -> None:
    r = {
        "+1": 3,
        "-1": 5,
        "laugh": 1,
        "hooray": 2,
        "confused": 9,
        "heart": 4,
        "rocket": 1,
        "eyes": 7,
    }
    # positive = +1 + laugh + hooray + heart + rocket = 3 + 1 + 2 + 4 + 1 = 11
    assert positive_reactions(r) == 11


def test_positive_reactions_tolerates_missing_keys() -> None:
    assert positive_reactions({"+1": 2}) == 2
    assert positive_reactions({}) == 0


def test_rank_items_orders_by_hot_score_desc() -> None:
    items = [
        {"number": 1, "updated_at": "2026-05-23T00:00:00Z", "comments": 0, "reactions": {"+1": 0}},
        {"number": 2, "updated_at": "2026-05-23T00:00:00Z", "comments": 0, "reactions": {"+1": 9}},
    ]
    ranked = rank_items(items, now=NOW)
    assert [i["number"] for i in ranked] == [2, 1]
    assert ranked[0]["hot_score"] >= ranked[1]["hot_score"]


def test_rank_items_tiebreaks_recent_first_then_lower_number() -> None:
    # identical engagement → newer updated_at wins; if equal, lower number wins
    items = [
        {"number": 5, "updated_at": "2026-05-01T00:00:00Z", "comments": 0, "reactions": {}},
        {"number": 9, "updated_at": "2026-05-20T00:00:00Z", "comments": 0, "reactions": {}},
        {"number": 3, "updated_at": "2026-05-20T00:00:00Z", "comments": 0, "reactions": {}},
    ]
    ranked = rank_items(items, now=NOW)
    assert [i["number"] for i in ranked] == [3, 9, 5]


def test_rank_items_honours_top_limit() -> None:
    items = [
        {"number": n, "updated_at": "2026-05-23T00:00:00Z", "comments": n, "reactions": {}}
        for n in range(1, 6)
    ]
    ranked = rank_items(items, now=NOW, top=2)
    assert len(ranked) == 2
    assert ranked[0]["number"] == 5  # most comments → highest score


def test_rank_items_does_not_mutate_input() -> None:
    items = [{"number": 1, "updated_at": "2026-05-23T00:00:00Z", "comments": 0, "reactions": {}}]
    rank_items(items, now=NOW)
    assert "hot_score" not in items[0]

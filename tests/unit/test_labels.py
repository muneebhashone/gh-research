"""Tests for label-frequency / 'common problems' aggregation."""

from ghr.analysis.labels import label_frequency

ISSUES = [
    {"labels": ["bug", "ui"]},
    {"labels": ["bug"]},
    {"labels": ["bug", "needs-repro"]},
    {"labels": []},
    {"labels": ["ui", "bug"]},
]


def test_label_counts_and_shares_sorted_desc() -> None:
    result = label_frequency(ISSUES)
    assert result["set_size"] == 5
    assert result["labels"] == [
        {"label": "bug", "count": 4, "share": 0.8},
        {"label": "ui", "count": 2, "share": 0.4},
        {"label": "needs-repro", "count": 1, "share": 0.2},
    ]


def test_co_occurrence_pairs_sorted_desc() -> None:
    result = label_frequency(ISSUES)
    assert result["co_occurrence"] == [
        {"a": "bug", "b": "ui", "count": 2},
        {"a": "bug", "b": "needs-repro", "count": 1},
    ]


def test_unlabeled_count() -> None:
    assert label_frequency(ISSUES)["unlabeled"] == 1


def test_empty_input() -> None:
    assert label_frequency([]) == {
        "set_size": 0,
        "labels": [],
        "co_occurrence": [],
        "unlabeled": 0,
    }


def test_duplicate_label_within_issue_counted_once() -> None:
    result = label_frequency([{"labels": ["bug", "bug"]}])
    assert result["labels"] == [{"label": "bug", "count": 1, "share": 1.0}]

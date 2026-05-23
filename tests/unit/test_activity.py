"""Tests for the activity-trend ('booming vs dying') primitive."""

from ghr.analysis.activity import compute_activity


def _b(start: str, opened: int, closed: int) -> dict[str, object]:
    return {"start": start, "opened": opened, "closed": closed}


def test_booming_when_recent_opened_surges() -> None:
    buckets = [
        _b("2026-04-01", 10, 8),
        _b("2026-04-08", 10, 8),
        _b("2026-04-15", 30, 10),
        _b("2026-04-22", 30, 10),
    ]
    r = compute_activity(buckets)
    assert r["momentum"] == 2.0  # (60-20)/20
    assert r["verdict"] == "booming"
    assert r["buckets"][0] == {
        "start": "2026-04-01",
        "opened": 10,
        "closed": 8,
        "net": 2,
        "ratio": 1.25,
    }
    assert r["thresholds"] == {"boom": 0.25, "die": -0.25, "ratio": 1.2}


def test_dying_when_recent_opened_collapses() -> None:
    buckets = [
        _b("w0", 30, 5),
        _b("w1", 30, 5),
        _b("w2", 10, 20),
        _b("w3", 10, 20),
    ]
    r = compute_activity(buckets)
    assert r["momentum"] == round((20 - 60) / 60, 4)
    assert r["verdict"] == "dying"


def test_steady_when_flat() -> None:
    buckets = [_b(f"w{i}", 10, 10) for i in range(4)]
    r = compute_activity(buckets)
    assert r["momentum"] == 0.0
    assert r["verdict"] == "steady"


def test_ratio_handles_zero_closed() -> None:
    r = compute_activity([_b("w0", 5, 0)])
    assert r["buckets"][0]["ratio"] == 5.0
    assert r["verdict"] == "steady"  # too few buckets for momentum


def test_empty_input() -> None:
    r = compute_activity([])
    assert r["buckets"] == []
    assert r["momentum"] == 0.0
    assert r["verdict"] == "steady"

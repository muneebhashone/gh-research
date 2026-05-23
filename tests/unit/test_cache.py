"""Tests for the SQLite TTL cache layer (key derivation + store)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from ghr.cache.store import CacheStore, auth_scope_bucket, make_key


class FakeClock:
    """A mutable monotonic-ish clock for deterministic TTL tests."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path: Path, clock: FakeClock) -> Iterator[CacheStore]:
    db_path = tmp_path / "cache" / "ghr.sqlite3"
    s = CacheStore(db_path, clock=clock)
    try:
        yield s
    finally:
        s.close()  # CRITICAL on Windows: release the file lock before cleanup.


def test_auth_scope_bucket_anon_when_no_token() -> None:
    assert auth_scope_bucket(None) == "anon"
    assert auth_scope_bucket("") == "anon"


def test_auth_scope_bucket_hashes_token_without_leaking_it() -> None:
    token = "ghp_supersecrettoken123"  # not a real secret; test fixture only
    bucket = auth_scope_bucket(token)
    expected = "auth:" + hashlib.sha256(token.encode()).hexdigest()[:12]
    assert bucket == expected
    # The raw token must never appear in the bucket string.
    assert token not in bucket


def test_make_key_is_stable_regardless_of_dict_ordering() -> None:
    k1 = make_key(
        method="get",
        url="https://API.github.com/search/issues",
        params={"q": "bug", "sort": "reactions", "order": "desc"},
        gql_query=None,
        gql_vars=None,
        auth_scope="anon",
    )
    k2 = make_key(
        method="get",
        url="https://API.github.com/search/issues",
        params={"order": "desc", "sort": "reactions", "q": "bug"},
        gql_query=None,
        gql_vars=None,
        auth_scope="anon",
    )
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex digest


def test_make_key_differs_when_auth_scope_differs() -> None:
    base = {
        "method": "get",
        "url": "https://api.github.com/repos/cli/cli",
        "params": None,
        "gql_query": None,
        "gql_vars": None,
    }
    anon = make_key(**base, auth_scope="anon")
    authed = make_key(**base, auth_scope="auth:abc123def456")
    assert anon != authed


def test_make_key_never_contains_a_raw_token() -> None:
    token = "ghp_supersecrettoken123"  # not a real secret; test fixture only
    key = make_key(
        method="get",
        url=f"https://api.github.com/x?access_token={token}",
        params={"access_token": token, "token": token},
        gql_query=None,
        gql_vars={"token": token},
        auth_scope=auth_scope_bucket(token),
    )
    assert token not in key


# --- CacheStore behaviour ----------------------------------------------------


def test_get_returns_none_for_absent_key(store: CacheStore) -> None:
    assert store.get("missing") is None


def test_set_then_get_round_trips_body_etag_status(store: CacheStore, clock: FakeClock) -> None:
    body = "hello — café 🦊".encode()  # non-ascii to prove BLOB round-trips
    store.set(
        "k1",
        resource="repo",
        transport="rest",
        body=body,
        etag='W/"abc"',
        status=200,
        ttl=3600,
        auth_scope="anon",
    )
    entry = store.get("k1")
    assert entry is not None
    assert entry.key == "k1"
    assert entry.resource == "repo"
    assert entry.transport == "rest"
    assert entry.body == body
    assert entry.etag == 'W/"abc"'
    assert entry.status == 200
    assert entry.ttl == 3600
    assert entry.auth_scope == "anon"
    assert entry.fetched_at == clock.now
    assert entry.size_bytes == len(body)


def test_set_with_null_etag_round_trips(store: CacheStore) -> None:
    store.set(
        "k1",
        resource="list",
        transport="rest",
        body=b"x",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    entry = store.get("k1")
    assert entry is not None
    assert entry.etag is None


def test_set_upserts_existing_key(store: CacheStore) -> None:
    common = {
        "resource": "repo",
        "transport": "rest",
        "etag": None,
        "status": 200,
        "ttl": 300,
        "auth_scope": "anon",
    }
    store.set("k1", body=b"first", **common)
    store.set("k1", body=b"second-longer", **common)
    entry = store.get("k1")
    assert entry is not None
    assert entry.body == b"second-longer"
    assert entry.size_bytes == len(b"second-longer")
    assert store.stats()["count"] == 1


def test_is_fresh_true_before_ttl_false_after(store: CacheStore, clock: FakeClock) -> None:
    store.set(
        "k1",
        resource="list",
        transport="rest",
        body=b"x",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    entry = store.get("k1")
    assert entry is not None
    assert store.is_fresh(entry) is True
    clock.advance(299)
    assert store.is_fresh(entry) is True
    clock.advance(2)  # now 301s elapsed, past the 300s ttl
    assert store.is_fresh(entry) is False


def test_stale_entry_is_still_returned_by_get(store: CacheStore, clock: FakeClock) -> None:
    store.set(
        "k1",
        resource="list",
        transport="rest",
        body=b"stale",
        etag=None,
        status=200,
        ttl=10,
        auth_scope="anon",
    )
    clock.advance(1000)
    entry = store.get("k1")
    assert entry is not None  # get returns stale entries; caller decides freshness
    assert entry.body == b"stale"
    assert store.is_fresh(entry) is False


def test_touch_refreshes_freshness(store: CacheStore, clock: FakeClock) -> None:
    store.set(
        "k1",
        resource="issue",
        transport="rest",
        body=b"x",
        etag='W/"e"',
        status=200,
        ttl=100,
        auth_scope="anon",
    )
    clock.advance(150)  # now stale
    stale = store.get("k1")
    assert stale is not None
    assert store.is_fresh(stale) is False

    store.touch("k1")  # simulate a 304 revalidation
    refreshed = store.get("k1")
    assert refreshed is not None
    assert refreshed.fetched_at == clock.now
    assert store.is_fresh(refreshed) is True


def test_touch_missing_key_is_a_noop(store: CacheStore) -> None:
    store.touch("nope")  # must not raise
    assert store.get("nope") is None


def test_clear_all_returns_deleted_count_and_empties(store: CacheStore) -> None:
    for i in range(3):
        store.set(
            f"k{i}",
            resource="list",
            transport="rest",
            body=b"x",
            etag=None,
            status=200,
            ttl=300,
            auth_scope="anon",
        )
    deleted = store.clear()
    assert deleted == 3
    assert store.stats()["count"] == 0
    assert store.get("k0") is None


def test_clear_by_resource_removes_only_that_resource(store: CacheStore) -> None:
    store.set(
        "a",
        resource="repo",
        transport="rest",
        body=b"x",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    store.set(
        "b",
        resource="list",
        transport="rest",
        body=b"y",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    store.set(
        "c",
        resource="list",
        transport="rest",
        body=b"z",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    deleted = store.clear(resource="list")
    assert deleted == 2
    assert store.get("a") is not None
    assert store.get("b") is None
    assert store.get("c") is None


def test_clear_empty_returns_zero(store: CacheStore) -> None:
    assert store.clear() == 0
    assert store.clear(resource="list") == 0


def test_stats_shape_and_counts(store: CacheStore, clock: FakeClock, tmp_path: Path) -> None:
    store.set(
        "a",
        resource="repo",
        transport="rest",
        body=b"xxxx",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    first_fetched = clock.now
    clock.advance(50)
    store.set(
        "b",
        resource="list",
        transport="rest",
        body=b"yy",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    store.set(
        "c",
        resource="list",
        transport="rest",
        body=b"z",
        etag=None,
        status=200,
        ttl=300,
        auth_scope="anon",
    )
    stats = store.stats()
    assert set(stats) == {"count", "total_size_bytes", "oldest_fetched_at", "by_resource", "path"}
    assert stats["count"] == 3
    assert stats["total_size_bytes"] == len(b"xxxx") + len(b"yy") + len(b"z")
    assert stats["oldest_fetched_at"] == first_fetched
    assert stats["by_resource"] == {"repo": 1, "list": 2}
    assert isinstance(stats["path"], str)


def test_stats_empty_store(store: CacheStore) -> None:
    stats = store.stats()
    assert stats["count"] == 0
    assert stats["total_size_bytes"] == 0
    assert stats["oldest_fetched_at"] is None
    assert stats["by_resource"] == {}


def test_path_returns_db_path(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "sub" / "ghr.sqlite3"
    s = CacheStore(db_path, clock=clock)
    try:
        assert s.path() == db_path
        assert s.path().exists()  # parent dirs created, file opened
    finally:
        s.close()


def test_close_then_reopen_same_path_reads_data(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "ghr.sqlite3"
    s1 = CacheStore(db_path, clock=clock)
    s1.set(
        "k1",
        resource="repo",
        transport="rest",
        body=b"persisted",
        etag='W/"v1"',
        status=200,
        ttl=3600,
        auth_scope="anon",
    )
    s1.close()

    s2 = CacheStore(db_path, clock=clock)
    try:
        entry = s2.get("k1")
        assert entry is not None
        assert entry.body == b"persisted"
        assert entry.etag == 'W/"v1"'
    finally:
        s2.close()

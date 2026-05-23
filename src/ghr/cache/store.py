"""Cache key derivation and the :class:`CacheStore` SQLite TTL store.

The cache key is a sha256 digest over a *canonical* JSON encoding of the
normalized request identity. Normalization makes the key invariant to
incidental ordering (dict iteration order, query-string order) so logically
identical requests collapse to one cache entry. Any ``access_token`` / ``token``
query parameter is stripped before hashing, and only the non-secret
``auth_scope`` bucket participates — the raw credential never reaches the key
or the database.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from ghr.cache.db import SCHEMA, connect

_WHITESPACE_RUN = re.compile(r"\s+")
#: Query/variable names that may carry a credential and must never be hashed.
_SECRET_PARAM_NAMES = frozenset({"access_token", "token"})


@dataclass(frozen=True)
class CacheEntry:
    """An immutable cached response row."""

    key: str
    resource: str
    transport: str
    body: bytes
    etag: str | None
    status: int
    fetched_at: float
    ttl: int
    auth_scope: str
    size_bytes: int


def auth_scope_bucket(token: str | None) -> str:
    """Map a token to a non-secret scope bucket.

    ``"anon"`` for a missing/empty token, otherwise ``"auth:" + sha256(token)``
    truncated to 12 hex chars. The bucket is one-way: the raw token can never be
    recovered from it, and it never contains the token verbatim.
    """
    if not token:
        return "anon"
    return "auth:" + hashlib.sha256(token.encode()).hexdigest()[:12]


def _normalize_url(url: str) -> str:
    """Lowercase the host and sort/strip the query of a URL."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = host.lower()
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    query_pairs = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _SECRET_PARAM_NAMES
    )
    query = "&".join(f"{k}={v}" for k, v in query_pairs)
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, query, ""))


def _normalize_params(params: Mapping[str, Any] | None) -> list[list[Any]] | None:
    """Sort params by key and drop any credential-bearing keys."""
    if params is None:
        return None
    return [[k, params[k]] for k in sorted(params) if k not in _SECRET_PARAM_NAMES]


def _collapse_whitespace(text: str | None) -> str | None:
    """Collapse runs of whitespace to a single space and strip the ends."""
    if text is None:
        return None
    return _WHITESPACE_RUN.sub(" ", text).strip()


def _normalize_vars(gql_vars: Mapping[str, Any] | None) -> list[list[Any]] | None:
    """Sort GraphQL variables by key and drop credential-bearing keys."""
    if gql_vars is None:
        return None
    return [[k, gql_vars[k]] for k in sorted(gql_vars) if k not in _SECRET_PARAM_NAMES]


def make_key(
    *,
    method: str,
    url: str,
    params: Mapping[str, Any] | None,
    gql_query: str | None,
    gql_vars: Mapping[str, Any] | None,
    auth_scope: str,
) -> str:
    """Return a stable sha256 hex digest of the normalized request identity.

    Stability guarantees: identical requests differing only in dict/query
    ordering produce the same key; differing ``auth_scope`` produces a different
    key; no raw credential is ever folded into the digest.
    """
    identity: dict[str, Any] = {
        "method": method.upper(),
        "url": _normalize_url(url),
        "params": _normalize_params(params),
        "gql_query": _collapse_whitespace(gql_query),
        "gql_vars": _normalize_vars(gql_vars),
        "auth_scope": auth_scope,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class CacheStore:
    """A SQLite-backed TTL cache of HTTP/GraphQL responses.

    ``get`` returns entries regardless of freshness; the caller checks
    :meth:`is_fresh` and either serves the cached body or revalidates (and then
    :meth:`touch`-es on a 304). Time comes from an injectable ``clock`` so TTL
    behaviour is deterministic in tests. The connection must be :meth:`close`-d
    before the backing file can be removed on Windows.
    """

    def __init__(self, db_path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._path = db_path
        self._clock = clock
        self._conn = connect(db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def path(self) -> Path:
        """The filesystem path of the backing database."""
        return self._path

    def get(self, key: str) -> CacheEntry | None:
        """Return the entry for ``key`` (even if stale), or ``None`` if absent."""
        row = self._conn.execute(
            "SELECT key, resource, transport, body, etag, status, "
            "fetched_at, ttl, auth_scope, size_bytes FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return CacheEntry(
            key=row["key"],
            resource=row["resource"],
            transport=row["transport"],
            body=bytes(row["body"]),
            etag=row["etag"],
            status=row["status"],
            fetched_at=row["fetched_at"],
            ttl=row["ttl"],
            auth_scope=row["auth_scope"],
            size_bytes=row["size_bytes"],
        )

    def is_fresh(self, entry: CacheEntry) -> bool:
        """``True`` while the entry is within its TTL relative to ``clock()``."""
        return self._clock() < entry.fetched_at + entry.ttl

    def set(
        self,
        key: str,
        *,
        resource: str,
        transport: str,
        body: bytes,
        etag: str | None,
        status: int,
        ttl: int,
        auth_scope: str,
    ) -> None:
        """Insert or replace ``key``; stamps ``fetched_at`` and ``size_bytes``."""
        self._conn.execute(
            "INSERT OR REPLACE INTO cache "
            "(key, resource, transport, body, etag, status, "
            "fetched_at, ttl, auth_scope, size_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                resource,
                transport,
                body,
                etag,
                status,
                self._clock(),
                ttl,
                auth_scope,
                len(body),
            ),
        )
        self._conn.commit()

    def touch(self, key: str) -> None:
        """Reset ``fetched_at`` to ``clock()`` (after a 304 revalidation)."""
        self._conn.execute(
            "UPDATE cache SET fetched_at = ? WHERE key = ?",
            (self._clock(), key),
        )
        self._conn.commit()

    def clear(self, resource: str | None = None) -> int:
        """Delete all rows, or only those for ``resource``; return rows deleted."""
        if resource is None:
            cur = self._conn.execute("DELETE FROM cache")
        else:
            cur = self._conn.execute("DELETE FROM cache WHERE resource = ?", (resource,))
        self._conn.commit()
        return cur.rowcount

    def stats(self) -> dict[str, Any]:
        """Summary counters: total count/size, oldest entry, and per-resource counts."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS count, "
            "COALESCE(SUM(size_bytes), 0) AS total_size_bytes, "
            "MIN(fetched_at) AS oldest_fetched_at FROM cache"
        ).fetchone()
        by_resource = {
            r["resource"]: r["n"]
            for r in self._conn.execute(
                "SELECT resource, COUNT(*) AS n FROM cache GROUP BY resource"
            ).fetchall()
        }
        return {
            "count": row["count"],
            "total_size_bytes": row["total_size_bytes"],
            "oldest_fetched_at": row["oldest_fetched_at"],
            "by_resource": by_resource,
            "path": str(self._path),
        }

    def close(self) -> None:
        """Close the SQLite connection (required before removing the file on Windows)."""
        self._conn.close()

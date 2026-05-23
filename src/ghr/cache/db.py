"""Low-level SQLite plumbing: schema DDL and a configured connection factory.

WAL journaling plus a busy timeout keeps the cache usable under the occasional
concurrent ``ghr`` invocation, and a :class:`sqlite3.Row` factory lets the store
read columns by name. :mod:`ghr.cache.store` is the only consumer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Milliseconds to wait on a locked database before raising ``OperationalError``.
BUSY_TIMEOUT_MS = 5_000

#: Schema for the single ``cache`` table plus its fetched-at index. Idempotent.
SCHEMA: str = """
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    resource   TEXT,
    transport  TEXT,
    body       BLOB,
    etag       TEXT,
    status     INTEGER,
    fetched_at REAL,
    ttl        INTEGER,
    auth_scope TEXT,
    size_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cache_fetched ON cache(fetched_at);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` with WAL, a busy timeout, and a row-by-name factory.

    The parent directory is created if missing. The returned connection has not
    yet had the schema applied — callers run :data:`SCHEMA` (see
    :class:`ghr.cache.store.CacheStore`).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn

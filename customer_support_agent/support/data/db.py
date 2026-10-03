"""Database connection for the store.

The data lives in Supabase Postgres, reached with psycopg. The schema is plain
SQL in schema.sql, applied by `python -m support.data.seed`.

Set LOCAL_SQLITE=1 in .env (or the environment) to use a local SQLite file
instead. That keeps the tests runnable offline and avoids spending Supabase
connections on them. Queries are written once, in Postgres style, and a small
shim adapts them for SQLite.
"""

import atexit
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

# A FIXED "today". Orders are generated with dates relative to this constant, so
# an order that is 10 days old stays 10 days old however long the project runs.
# Without it, every accuracy measurement would drift from one day to the next.
TODAY = date(2026, 10, 1)

SQLITE_PATH = Path(__file__).parent / "store.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DatabaseNotConfigured(RuntimeError):
    pass


def database_url() -> str:
    """The pooled Supabase URL (port 6543)."""
    return os.getenv("DATABASE_URL", "").strip()


def use_sqlite() -> bool:
    """Whether to use the local file instead of Postgres.

    Read at call time rather than import time, so a test or a script can flip
    LOCAL_SQLITE and have it take effect without reimporting the module.
    """
    if os.getenv("LOCAL_SQLITE", "0") == "1":
        return True
    return not database_url()


def backend() -> str:
    return "sqlite" if use_sqlite() else "postgres"


class _SqliteShim:
    """Lets SQLite run the Postgres-style queries the app is written in.

    Only the placeholder differs (%s vs ?) and SQLite has no SERIAL, so a small
    translation is far cheaper than maintaining two copies of every statement,
    which would drift apart within a day.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, params=()):
        return self._conn.execute(sql.replace("%s", "?"), params)

    def executemany(self, sql: str, seq):
        return self._conn.executemany(sql.replace("%s", "?"), seq)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _PostgresShim:
    """Gives a psycopg connection the same surface as the SQLite one.

    psycopg3 puts `execute` on the connection as a convenience but keeps
    `executemany` on the cursor only. Wrapping both here means callers use one
    interface and never have to know which backend they are talking to.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        # A fresh cursor per statement. Sharing one would mean a second query
        # silently discarded the first one's unread rows -- the kind of bug that
        # only shows up later, when someone adds a query in the wrong place.
        # Returning the cursor keeps .fetchone()/.fetchall() working the way
        # sqlite3's execute() does.
        cur = self._conn.cursor()
        cur.execute(sql, params or None)
        return cur

    def executemany(self, sql: str, seq):
        cur = self._conn.cursor()
        cur.executemany(sql, list(seq))
        return cur

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _sqlite_schema() -> str:
    """Translate the Postgres schema well enough for SQLite."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    return (
        sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        .replace("DOUBLE PRECISION", "REAL")
        .replace("BOOLEAN", "INTEGER")
        .replace("FALSE", "0")
        .replace(" CASCADE", "")
    )


# A pool of open Postgres connections, created on first use.
#
# This matters more than it looks. Opening a fresh connection to Supabase costs
# roughly a second -- TCP, then TLS, then authentication -- and a single support
# conversation makes around seven tool calls. Without pooling that is seven
# seconds of pure handshake per conversation. Reusing connections drops it to
# one network round trip each.
_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "15"))
        try:
            _POOL = ConnectionPool(
                database_url(),
                min_size=1,
                # Supabase's free tier pooler is not generous; a handful of
                # connections is plenty for one app process.
                max_size=int(os.getenv("DB_POOL_SIZE", "5")),
                timeout=timeout,
                kwargs={"row_factory": dict_row, "connect_timeout": timeout},
                open=True,
            )
            # Fail here, with a useful message, rather than on the first query.
            _POOL.wait(timeout=timeout)
            # Without this the pool's worker threads outlive the program and
            # print "couldn't stop thread" warnings on every exit.
            atexit.register(close_pool)
        except Exception as exc:  # noqa: BLE001
            _POOL = None
            raise DatabaseNotConfigured(
                "Could not connect to Postgres.\n"
                f"  Check DATABASE_URL in {ENV_PATH} -- it should be the POOLED\n"
                "  Supabase URL, on port 6543.\n"
                "  To work offline instead, set LOCAL_SQLITE=1\n"
                f"  Error: {exc}"
            ) from exc
    return _POOL


def close_pool() -> None:
    """Shut the pool down. Used when a process exits or a test changes backend."""
    global _POOL
    if _POOL is not None:
        pool, _POOL = _POOL, None
        try:
            pool.close()
        except Exception:  # noqa: BLE001 - never let cleanup break a shutdown
            pass


@contextmanager
def connect():
    """Borrow a connection to the store.

    Always use `with connect() as conn:`. On Postgres the connection returns to
    the pool at the end of the block; holding one open would exhaust the pool
    and make the app hang.
    """
    if use_sqlite():
        conn = sqlite3.connect(str(SQLITE_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield _SqliteShim(conn)
            conn.commit()
        finally:
            conn.close()
        return

    with _pool().connection() as conn:
        # The pool commits on a clean exit and rolls back if the block raises.
        yield _PostgresShim(conn)


def create_schema() -> None:
    """Drop and recreate every table."""
    if use_sqlite():
        if SQLITE_PATH.exists():
            SQLITE_PATH.unlink()
        conn = sqlite3.connect(str(SQLITE_PATH))
        try:
            conn.executescript(_sqlite_schema())
            conn.commit()
        finally:
            conn.close()
        return

    with connect() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def rows(conn, sql: str, params=()) -> list[dict]:
    """Run a query, return plain dicts, whichever backend is in use."""
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql: str, params=()) -> dict | None:
    """Run a query, return the first row as a dict, or None."""
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None

"""Tests for the database layer.

The SQLite path is exercised by every other test in the suite. These tests cover
the Postgres path, which otherwise only gets tried against a live Supabase.

The fake below copies psycopg3's interface precisely where it differs from
sqlite3 -- in particular, a psycopg *connection* has `execute` but NOT
`executemany`; that lives on the cursor. Calling the wrong one raises
AttributeError at runtime, which is exactly the bug this guards against.
"""

import pytest

from support.data import db as db_module
from support.data.db import _PostgresShim


class FakeCursor:
    def __init__(self, log, rows=None):
        self.log = log
        self._rows = rows if rows is not None else []

    def execute(self, sql, params=None):
        self.log.append(("execute", sql, params))
        return self

    def executemany(self, sql, seq):
        self.log.append(("executemany", sql, list(seq)))
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    """Mimics psycopg3: has execute(), deliberately has NO executemany()."""

    def __init__(self, rows=None):
        self.log = []
        self.rows = rows
        self.committed = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self.log, self.rows)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_executemany_goes_through_a_cursor():
    """The connection has no executemany; the shim must not call it."""
    conn = FakeConnection()

    # Proves the fake is faithful to psycopg -- if this ever passes, the test
    # below stops being meaningful.
    assert not hasattr(conn, "executemany")

    shim = _PostgresShim(conn)
    shim.executemany("INSERT INTO t VALUES (%s)", [("a",), ("b",)])

    assert conn.log == [("executemany", "INSERT INTO t VALUES (%s)", [("a",), ("b",)])]


def test_execute_returns_something_fetchable():
    conn = FakeConnection(rows=[{"order_id": "ORD-0001"}])
    shim = _PostgresShim(conn)

    result = shim.execute("SELECT * FROM orders WHERE order_id = %s", ("ORD-0001",))

    assert result.fetchone() == {"order_id": "ORD-0001"}


def test_each_query_gets_its_own_cursor():
    """Sharing one cursor would discard the first query's unread rows."""
    conn = FakeConnection(rows=[{"n": 1}])
    shim = _PostgresShim(conn)

    first = shim.execute("SELECT 1")
    second = shim.execute("SELECT 2")

    assert first is not second


def test_empty_params_become_none():
    """psycopg only allows multi-statement SQL when params is None."""
    conn = FakeConnection()
    _PostgresShim(conn).execute("CREATE TABLE a (); CREATE TABLE b ();")

    _, _, params = conn.log[0]
    assert params is None


def test_unknown_attributes_fall_through_to_the_connection():
    conn = FakeConnection()
    _PostgresShim(conn).commit()
    assert conn.committed


# --- backend selection -----------------------------------------------------


def test_blank_database_url_falls_back_to_sqlite(monkeypatch):
    monkeypatch.setenv("LOCAL_SQLITE", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    assert db_module.use_sqlite() is True
    assert db_module.backend() == "sqlite"


def test_local_sqlite_flag_overrides_a_set_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:6543/postgres")
    monkeypatch.setenv("LOCAL_SQLITE", "1")
    assert db_module.use_sqlite() is True


def test_url_without_the_flag_selects_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:6543/postgres")
    monkeypatch.setenv("LOCAL_SQLITE", "0")
    assert db_module.use_sqlite() is False
    assert db_module.backend() == "postgres"


def test_a_bad_url_explains_itself(monkeypatch):
    """A connection failure should say what to check, not leak a driver trace."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nope@127.0.0.1:1/none")
    monkeypatch.setenv("LOCAL_SQLITE", "0")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "2")  # keep the suite quick

    with pytest.raises(db_module.DatabaseNotConfigured) as caught:
        with db_module.connect():
            pass

    message = str(caught.value)
    assert "DATABASE_URL" in message
    assert "6543" in message
    assert "LOCAL_SQLITE" in message


# --- schema translation ----------------------------------------------------


def test_sqlite_schema_translation():
    """The Postgres schema has to be rewritten to run on SQLite."""
    sql = db_module._sqlite_schema()

    assert "SERIAL" not in sql
    assert "DOUBLE PRECISION" not in sql
    assert "BOOLEAN" not in sql
    assert "CASCADE" not in sql
    assert "INTEGER PRIMARY KEY AUTOINCREMENT" in sql
    # The tables themselves must survive the translation.
    for table in ("customers", "orders", "stock", "payments", "actions"):
        assert f"CREATE TABLE {table}" in sql

"""Test configuration.

Tests always run against the local SQLite file, never Supabase. Three reasons:

- Speed. A hosted round trip per query turns a half-second suite into a minute.
- Isolation. Tests write to the store; doing that to a shared hosted database
  would corrupt whatever a teammate was demoing.
- Offline. The suite should pass on a train.

The handful of tests that need Postgres behaviour fake the driver instead; see
support/data/test_db.py.
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def use_local_database():
    """Force the SQLite backend for the whole test session."""
    previous = os.environ.get("LOCAL_SQLITE")
    os.environ["LOCAL_SQLITE"] = "1"
    yield
    if previous is None:
        os.environ.pop("LOCAL_SQLITE", None)
    else:
        os.environ["LOCAL_SQLITE"] = previous


@pytest.fixture(scope="session", autouse=True)
def seeded_store(use_local_database):
    """Make sure the local store exists and holds the expected rows.

    Tests assert against specific orders (ORD-0050 and friends), so the data has
    to be there. Seeding is deterministic, so this is cheap and repeatable.
    """
    from support.data.db import SQLITE_PATH, connect, one
    from support.data.seed import seed_database

    needs_seed = not SQLITE_PATH.exists()
    if not needs_seed:
        try:
            with connect() as conn:
                needs_seed = one(conn, "SELECT COUNT(*) AS n FROM orders")["n"] == 0
        except Exception:  # noqa: BLE001 - missing or damaged file
            needs_seed = True

    if needs_seed:
        seed_database()

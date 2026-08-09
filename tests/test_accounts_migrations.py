import sqlite3
from pathlib import Path

import pytest

from thesisound.accounts import AccountStore


def test_account_schema_initialization_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "accounts.sqlite3"

    AccountStore(database)
    AccountStore(database)

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert version == ("1",)
    assert {"schema_meta", "users", "project_members"} <= tables
    assert "idx_project_members_user" in indexes


def test_newer_account_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "accounts.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '99')"
        )

    with pytest.raises(RuntimeError, match="newer than this build"):
        AccountStore(database)

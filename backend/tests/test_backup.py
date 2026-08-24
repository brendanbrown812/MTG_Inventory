from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.backup import backup_database, restore_database, verify_database


def _create_database(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (value) VALUES (?)", (value,))
        conn.commit()


def _read_value(path: Path) -> str:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT value FROM sample").fetchone()[0]


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    destination = tmp_path / "destination.db"
    _create_database(source, "original")
    _create_database(destination, "replacement")

    backup_database(source, backup)
    verify_database(backup)
    assert _read_value(backup) == "original"

    with pytest.raises(ValueError, match="--yes"):
        restore_database(backup, destination, confirmed=False)

    restore_database(backup, destination, confirmed=True)
    assert _read_value(destination) == "original"

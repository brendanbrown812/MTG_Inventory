"""Safe SQLite backup, verification, and explicit restore commands."""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def verify_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path}: {result}")


def _sqlite_copy(source: Path, destination: Path, *, overwrite: bool) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("Source and destination must be different files")
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as source_db:
            with closing(sqlite3.connect(temporary)) as destination_db:
                source_db.backup(destination_db)
        verify_database(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(source: Path, destination: Path, *, overwrite: bool = False) -> None:
    _sqlite_copy(source, destination, overwrite=overwrite)


def restore_database(backup: Path, destination: Path, *, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("Restore requires --yes because it replaces the destination database")
    verify_database(backup)
    _sqlite_copy(backup, destination, overwrite=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup_cmd = commands.add_parser("backup", help="Create and verify a consistent SQLite backup")
    backup_cmd.add_argument("source", type=Path)
    backup_cmd.add_argument("destination", type=Path)
    backup_cmd.add_argument("--overwrite", action="store_true")

    verify_cmd = commands.add_parser("verify", help="Run SQLite integrity_check against a database")
    verify_cmd.add_argument("database", type=Path)

    restore_cmd = commands.add_parser("restore", help="Verify a backup and replace a stopped database")
    restore_cmd.add_argument("backup", type=Path)
    restore_cmd.add_argument("destination", type=Path)
    restore_cmd.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    if args.command == "backup":
        backup_database(args.source, args.destination, overwrite=args.overwrite)
        print(f"Backup created and verified: {args.destination}")
    elif args.command == "verify":
        verify_database(args.database)
        print(f"Database integrity check passed: {args.database}")
    else:
        restore_database(args.backup, args.destination, confirmed=args.yes)
        print(f"Database restored and verified: {args.destination}")


if __name__ == "__main__":
    main()

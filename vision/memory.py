"""Durable memory backed by SQLite.

Vision 1.2 rewrote ``memory.json`` on every update.  Two writers (the command
loop and an async LLM reply) could interleave and corrupt the file, and a crash
during ``json.dump`` truncated it.  SQLite in WAL mode gives us atomic
transactions, concurrent readers and a well-defined schema.

Legacy ``memory.json`` files are imported once and renamed to
``memory.json.migrated`` so no user data is lost.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging_setup import get_logger

logger = get_logger("memory")

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_text      TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_created
    ON conversations(created_at);
"""


class MemoryStoreError(RuntimeError):
    """Raised when the memory database cannot be opened or written."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _legacy_time(value: Any) -> str:
    """Convert ``%Y-%m-%d %H:%M:%S`` (local) or ISO strings to ISO-8601."""
    if not value:
        return utc_now()
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return utc_now()


class MemoryStore:
    """Thread-safe facade over the SQLite memory database."""

    def __init__(self, path: str | Path, migrate_from: str | Path | None = None) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(
                str(path),
                check_same_thread=False,
                timeout=10.0,
            )
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"cannot open memory database {path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            try:
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            except sqlite3.Error as exc:  # e.g. network share without WAL support
                logger.warning("SQLite WAL unavailable, using default journal: %s", exc)
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute("PRAGMA user_version = 1")
            self._conn.commit()
        if migrate_from:
            self.migrate_legacy_json(migrate_from)

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        with self._lock:
            with suppress(sqlite3.Error):
                self._conn.commit()
            self._conn.close()

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except sqlite3.Error as exc:
                self._conn.rollback()
                raise MemoryStoreError(f"memory database error: {exc}") from exc

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return list(self._conn.execute(sql, params).fetchall())
            except sqlite3.Error as exc:
                raise MemoryStoreError(f"memory database error: {exc}") from exc

    # ----------------------------------------------------------------- profile
    def get_name(self) -> str:
        rows = self._query("SELECT value FROM profile WHERE key = 'name'")
        return rows[0]["value"] if rows else ""

    def set_name(self, name: str) -> None:
        value = str(name).strip()
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO profile(key, value) VALUES('name', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (value,),
            )

    def get_profile(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self._query("SELECT key, value FROM profile")}

    # -------------------------------------------------------------------- notes
    def add_note(self, note: str) -> int:
        text = str(note).strip()
        if not text:
            raise ValueError("note cannot be empty")
        with self._transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO notes(text, created_at) VALUES(?, ?)",
                (text, utc_now()),
            )
            return int(cursor.lastrowid or 0)

    def list_notes(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id, text, created_at FROM notes ORDER BY id ASC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql = (
                "SELECT id, text, created_at FROM ("
                "  SELECT id, text, created_at FROM notes ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC"
            )
            params = (max(0, int(limit)),)
        return [dict(row) for row in self._query(sql, params)]

    def get_notes(self) -> list[str]:
        return [row["text"] for row in self.list_notes()]

    def clear_notes(self) -> int:
        with self._transaction() as conn:
            cursor = conn.execute("DELETE FROM notes")
            return int(cursor.rowcount)

    # ------------------------------------------------------------ conversations
    def add_conversation(self, user_text: str, assistant_text: str) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations(user_text, assistant_text, created_at) "
                "VALUES(?, ?, ?)",
                (str(user_text), str(assistant_text), utc_now()),
            )
            return int(cursor.lastrowid or 0)

    def recent_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        count = max(0, int(limit))
        rows = self._query(
            "SELECT id, user_text, assistant_text, created_at FROM ("
            "  SELECT id, user_text, assistant_text, created_at "
            "  FROM conversations ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (count,),
        )
        return [dict(row) for row in rows]

    def clear_conversations(self) -> int:
        with self._transaction() as conn:
            cursor = conn.execute("DELETE FROM conversations")
            return int(cursor.rowcount)

    # ------------------------------------------------------------------- admin
    def clear_all(self) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM notes")
            conn.execute("DELETE FROM profile")

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.get_name(),
            "notes": self.get_notes(),
            "last_conversation": self.recent_conversations(10),
        }

    # --------------------------------------------------------------- migration
    def migrate_legacy_json(self, path: str | Path) -> bool:
        """Import Vision 1.2 ``memory.json`` once. Returns True if imported."""
        source = Path(path)
        if not source.is_file():
            return False
        if self.get_profile() or self.list_notes(limit=1) or self.recent_conversations(1):
            logger.info("Memory database is not empty; skipping import of %s", source)
            return False
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not read legacy memory file %s: %s", source, exc)
            return False
        if not isinstance(data, dict):
            logger.warning("Legacy memory file is not an object; skipping import.")
            return False

        try:
            with self._transaction() as conn:
                name = str(data.get("name", "")).strip()
                if name:
                    conn.execute("INSERT INTO profile(key, value) VALUES('name', ?)", (name,))
                for note in data.get("notes", []) or []:
                    text = str(note).strip()
                    if text:
                        conn.execute(
                            "INSERT INTO notes(text, created_at) VALUES(?, ?)",
                            (text, utc_now()),
                        )
                for item in data.get("last_conversation", []) or []:
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        "INSERT INTO conversations(user_text, assistant_text, created_at) "
                        "VALUES(?, ?, ?)",
                        (
                            str(item.get("user", "")),
                            str(item.get("vision", "")),
                            _legacy_time(item.get("time")),
                        ),
                    )
        except MemoryStoreError as exc:
            logger.warning("Legacy memory import failed: %s", exc)
            return False

        backup = source.with_suffix(source.suffix + ".migrated")
        try:
            source.replace(backup)
        except OSError as exc:
            logger.warning("Imported legacy memory but could not rename it: %s", exc)
        logger.info("Imported legacy memory from %s", source)
        return True

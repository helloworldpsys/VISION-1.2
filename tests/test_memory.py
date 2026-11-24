"""SQLite memory tests, including the Vision 1.2 JSON migration."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from vision.memory import MemoryStore


@pytest.fixture()
def store(tmp_path: Path):
    db = MemoryStore(tmp_path / "memory.db")
    yield db
    db.close()


def test_defaults(store: MemoryStore) -> None:
    assert store.get_name() == ""
    assert store.get_notes() == []
    assert store.recent_conversations() == []


def test_profile_roundtrip(store: MemoryStore) -> None:
    store.set_name("Alex")
    assert store.get_name() == "Alex"
    store.set_name("Sam")
    assert store.get_name() == "Sam"


def test_notes(store: MemoryStore) -> None:
    first = store.add_note("buy milk")
    second = store.add_note("exam on Friday")
    assert (first, second) == (1, 2)
    assert store.get_notes() == ["buy milk", "exam on Friday"]
    assert store.clear_notes() == 2
    assert store.get_notes() == []


def test_empty_note_rejected(store: MemoryStore) -> None:
    with pytest.raises(ValueError):
        store.add_note("   ")


def test_conversations_are_ordered_and_limited(store: MemoryStore) -> None:
    for index in range(15):
        store.add_conversation(f"question {index}", f"answer {index}")
    recent = store.recent_conversations(10)
    assert len(recent) == 10
    assert recent[0]["user_text"] == "question 5"
    assert recent[-1]["user_text"] == "question 14"


def test_snapshot_and_clear(store: MemoryStore) -> None:
    store.set_name("Alex")
    store.add_note("note")
    store.add_conversation("hi", "hello")
    snapshot = store.snapshot()
    assert snapshot["name"] == "Alex"
    assert snapshot["notes"] == ["note"]
    assert snapshot["last_conversation"][0]["user_text"] == "hi"
    store.clear_all()
    assert store.snapshot() == {"name": "", "notes": [], "last_conversation": []}


def test_persistence(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    with MemoryStore(path) as store:
        store.set_name("Alex")
        store.add_note("persisted")
    with MemoryStore(path) as reopened:
        assert reopened.get_name() == "Alex"
        assert reopened.get_notes() == ["persisted"]


def test_legacy_migration(tmp_path: Path) -> None:
    legacy = tmp_path / "memory.json"
    legacy.write_text(
        json.dumps(
            {
                "name": "Taha",
                "notes": ["note one", "note two"],
                "last_conversation": [
                    {"time": "2024-05-01 10:00:00", "user": "hi", "vision": "hello"}
                ],
            }
        ),
        encoding="utf-8",
    )
    db = MemoryStore(tmp_path / "memory.db", migrate_from=legacy)
    try:
        assert db.get_name() == "Taha"
        assert db.get_notes() == ["note one", "note two"]
        conversation = db.recent_conversations(1)[0]
        assert conversation["user_text"] == "hi"
        assert conversation["assistant_text"] == "hello"
        assert not legacy.exists()
        assert (tmp_path / "memory.json.migrated").exists()
    finally:
        db.close()


def test_migration_does_not_overwrite_existing_data(tmp_path: Path) -> None:
    legacy = tmp_path / "memory.json"
    legacy.write_text(json.dumps({"name": "Old", "notes": ["old note"]}), encoding="utf-8")
    db = MemoryStore(tmp_path / "memory.db")
    try:
        db.set_name("Current")
        assert db.migrate_legacy_json(legacy) is False
        assert db.get_name() == "Current"
        assert legacy.exists()
    finally:
        db.close()


def test_concurrent_writes(tmp_path: Path) -> None:
    db = MemoryStore(tmp_path / "memory.db")
    errors: list[Exception] = []

    def worker(start: int) -> None:
        try:
            for index in range(start, start + 20):
                db.add_note(f"note {index}")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 20,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    try:
        assert errors == []
        assert len(db.get_notes()) == 100
    finally:
        db.close()

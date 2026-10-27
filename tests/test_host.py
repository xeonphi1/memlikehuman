import pytest

from memlikehuman.host import ingest
from memlikehuman.models import Scope
from memlikehuman.store import Store


def event(session="chat", ident="one", text="我现在住杭州"):
    return dict(
        event_id=ident,
        session_id=session,
        text=text,
        role="user",
        source="host",
        occurred_at="2026-01-01T00:00:00Z",
    )


def test_resume_delete_and_archive_cursor(tmp_path):
    scope = Scope()
    data = tmp_path / "data"
    result = ingest(
        data, scope, dict(session_id="chat", start=0, end=3, events=[event()], checkpoint=True)
    )
    assert result["offset"] == 3 and result["checkpoint_id"]
    assert Store(data).event(scope, "one")["state"] == "pending"
    Store(data).forget(scope, "one")
    assert ingest(data, scope, dict(session_id="chat"))["offset"] == 3
    with pytest.raises(ValueError, match="cursor changed"):
        ingest(data, scope, dict(session_id="chat", start=0, end=3, events=[event()]))
    restored = Store(tmp_path / "restored")
    restored.import_archive(Store(data).export())
    assert ingest(tmp_path / "restored", scope, dict(session_id="chat"))["offset"] == 3
    assert ingest(data, Scope(project_id="other"), dict(session_id="chat"))["offset"] == 0


def test_failed_batch_retries_raw_and_checkpoint(tmp_path, monkeypatch):
    scope = Scope()
    payload = dict(session_id="chat", start=0, end=2, events=[event()], checkpoint=True)
    original = Store.checkpoint

    def fail(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(Store, "checkpoint", fail)
    with pytest.raises(OSError):
        ingest(tmp_path, scope, payload)
    assert Store(tmp_path).event(scope, "one")["text"] == "我现在住杭州"
    assert ingest(tmp_path, scope, dict(session_id="chat"))["offset"] == 0
    monkeypatch.setattr(Store, "checkpoint", original)
    ingest(tmp_path, scope, payload)
    assert len(Store(tmp_path).export()["tables"]["events"]) == 1


def test_summary_is_reference_and_checkpoint_retry_is_idempotent(tmp_path):
    scope = Scope()
    summary = {
        **event(ident="summary", text="待办：整理照片"),
        "role": "assistant",
        "category": "reference",
    }
    payload = dict(
        session_id="chat",
        start=0,
        end=0,
        events=[summary],
        checkpoint=True,
        summary_event_id="summary",
    )
    first = ingest(tmp_path, scope, payload)
    second = ingest(tmp_path, scope, payload)
    assert first["checkpoint_id"] == second["checkpoint_id"]
    assert Store(tmp_path).event(scope, "summary")["role"] == "assistant"
    assert "summary" in Store(tmp_path).latest_checkpoint(scope)["state"]["next_step"]


def test_invalid_batch_no_partial_write(tmp_path):
    with pytest.raises(ValueError):
        ingest(
            tmp_path,
            Scope(),
            dict(session_id="chat", start=0, end=1, events=[event(), event(session="other")]),
        )
    assert not (tmp_path / "memory.sqlite3").exists()


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_sqlite_restore_preserves_events(tmp_path, version):
    import sqlite3

    from memlikehuman.archive import load_archive
    from memlikehuman.store import MIGRATION_2, SCHEMA

    legacy = tmp_path / "old.sqlite3"
    with sqlite3.connect(legacy) as db:
        db.executescript(SCHEMA)
        if version == 2:
            db.executescript(MIGRATION_2)
    archive = load_archive(legacy)
    store = Store(tmp_path / "new")
    store.import_archive(archive)
    assert store.doctor()["schema_version"] == 3
    assert store.export()["tables"]["host_cursors"] == []


def test_cursor_export_jsonl_and_backup_roundtrip(tmp_path):
    from memlikehuman.archive import load_archive, write_archive

    source = tmp_path / "source"
    ingest(source, Scope(), dict(session_id="chat", start=0, end=1, events=[event()]))
    for suffix in ("jsonl", "sqlite3"):
        path = tmp_path / ("backup." + suffix)
        if suffix == "jsonl":
            write_archive(path, Store(source).export())
        else:
            Store(source).backup(path)
        target = tmp_path / suffix
        Store(target).import_archive(load_archive(path))
        assert ingest(target, Scope(), dict(session_id="chat"))["offset"] == 1

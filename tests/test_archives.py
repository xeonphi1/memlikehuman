import copy
import json

import pytest
from conftest import remember

from memlikehuman.archive import load_archive, write_archive
from memlikehuman.engine import Engine
from memlikehuman.models import TaskState


@pytest.mark.parametrize("suffix", [".json", ".jsonl", ".sqlite3"])
def test_lossless_portable_restore(engine, scope, tmp_path, suffix):
    mid = remember(engine, scope, subject="user", fact_key="home")
    engine.checkpoint(scope, "default", "e1", TaskState(goal="保存进度", next_step="继续测试"))
    path = tmp_path / ("archive" + suffix)
    if suffix == ".sqlite3":
        engine.store.backup(path)
    else:
        write_archive(path, engine.store.export())
    fresh = Engine(tmp_path / "restored")
    fresh.store.import_archive(load_archive(path))
    assert fresh.store.export()["tables"] == engine.store.export()["tables"]
    assert fresh.recall(scope, "上海")["memories"][0]["id"] == mid
    assert fresh.store.doctor()["integrity"] == "ok"
    with pytest.raises(ValueError, match="empty"):
        fresh.store.import_archive(load_archive(path))


def test_import_failure_rolls_back_all_tables(engine, scope, tmp_path):
    remember(engine, scope)
    archive = engine.store.export()
    archive["tables"]["memories"][0]["project_id"] = "other"
    fresh = Engine(tmp_path / "bad")
    with pytest.raises(ValueError, match="provenance"):
        fresh.store.import_archive(archive)
    assert all(n == 0 for n in fresh.store.doctor()["counts"].values())


def test_corrupt_archive_and_future_version_rejected(engine, scope, tmp_path):
    remember(engine, scope)
    original = engine.store.export()
    for change in ("version", "column", "quote"):
        archive = copy.deepcopy(original)
        if change == "version":
            archive["version"] = 999
        elif change == "column":
            archive["tables"]["events"][0]["arbitrary_sql"] = "oops"
        else:
            archive["tables"]["memories"][0]["source_quote"] = "捏造"
        fresh = Engine(tmp_path / change)
        with pytest.raises(ValueError):
            fresh.store.import_archive(archive)
        assert fresh.store.doctor()["counts"]["events"] == 0


def test_config_and_environment_keys_not_exported(engine, scope, monkeypatch):
    monkeypatch.setenv("MEMLIKEHUMAN_API_KEY", "secret-should-not-leak")
    remember(engine, scope)
    output = json.dumps(engine.store.export())
    assert "secret-should-not-leak" not in output
    assert "config" not in engine.store.export()["tables"]


def test_archive_and_backup_refuse_overwrite(engine, tmp_path):
    target = tmp_path / "existing"
    target.write_text("keep me")
    with pytest.raises(FileExistsError):
        engine.store.backup(target)
    with pytest.raises(FileExistsError):
        write_archive(target, engine.store.export())
    assert target.read_text() == "keep me"


def test_import_does_not_bypass_live_role_validation(engine, scope, tmp_path):
    remember(engine, scope)
    archive = engine.store.export()
    archive["tables"]["events"][0]["role"] = "assistant"
    destination = Engine(tmp_path / "forged")
    with pytest.raises(ValueError, match="Only user"):
        destination.store.import_archive(archive)
    assert destination.store.doctor()["counts"]["events"] == 0

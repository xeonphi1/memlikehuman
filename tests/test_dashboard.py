from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import remember

from memlikehuman.archive import write_archive
from memlikehuman.dashboard import Dashboard
from memlikehuman.models import EventInput, Scope
from memlikehuman.store import Store


def test_layer_edit_preserves_basis_source_and_history(engine, scope, tmp_path):
    mid = remember(
        engine,
        scope,
        role="assistant",
        basis="inference",
        kind="observation",
        text="可能喜欢咖啡",
        confidence=0.2,
    )
    panel = Dashboard(engine.store.data_dir)
    edited = panel.mutate(
        "main",
        scope,
        "memory",
        {"id": mid, "edits": {"content": "咖啡偏好尚未确认", "gist": "待确认"}},
    )
    row = panel.detail("main", scope, "observation", edited["id"])
    assert row["basis"] == "inference" and row["confidence"] == 0.2
    assert row["source_quote"] == "可能喜欢咖啡"
    assert row["source"]["text"] == "可能喜欢咖啡"
    assert panel.detail("main", scope, "observation", mid)["status"] == "revoked"
    assert panel.browse("main", scope, "observation")["total"] == 1
    Store(tmp_path / "roundtrip").import_archive(engine.store.export())
    with pytest.raises(ValueError):
        panel.mutate(
            "main",
            Scope(project_id="other"),
            "memory",
            {"id": edited["id"], "edits": {"content": "串区"}},
        )
    with pytest.raises(ValueError):
        panel.mutate(
            "main", scope, "memory", {"id": edited["id"], "edits": {"basis": "user_statement"}}
        )
    panel.mutate("main", scope, "forget", {"id": edited["id"]})
    assert not engine.store.export()["tables"]["memories"]


def test_emotion_edit_does_not_change_persona(engine, scope):
    mid = remember(
        engine,
        scope,
        role="assistant",
        basis="assistant_expression",
        kind="emotion",
        text="我表达轻松",
        valence=0.6,
        arousal=0.3,
    )
    panel = Dashboard(engine.store.data_dir)
    before = engine.store.persona(scope.persona_id)
    result = panel.mutate(
        "main", scope, "memory", {"id": mid, "edits": {"valence": 0.2, "arousal": 0.1}}
    )
    assert panel.detail("main", scope, "emotion", result["id"])["valence"] == 0.2
    assert before == engine.store.persona(scope.persona_id)


@pytest.mark.parametrize("suffix", ["json", "jsonl", "sqlite3"])
def test_import_isolated_library_and_invalid_file_atomic(engine, scope, tmp_path, suffix):
    remember(engine, scope)
    package = tmp_path / ("archive." + suffix)
    if suffix == "sqlite3":
        engine.store.backup(package)
    else:
        write_archive(package, engine.store.export())
    panel = Dashboard(tmp_path / "dashboard")
    result = panel.import_file(package.read_bytes(), "测试记忆")
    assert panel.browse(result["library"], scope, "fact")["total"] == 1
    assert panel.browse("main", scope, "fact")["total"] == 0
    before = panel.libraries()
    with pytest.raises((ValueError, KeyError, TypeError)):
        panel.import_file(b'{"fake":true}', "损坏文件")
    assert panel.libraries() == before
    with pytest.raises(ValueError):
        panel.directory("../../other")


def test_persona_rollback_checkpoint_and_raw_revision(engine, scope):
    remember(engine, scope)
    panel = Dashboard(engine.store.data_dir)
    original = engine.store.persona(scope.persona_id)
    content = {**original["content"], "name": "新的名字"}
    panel.mutate("main", scope, "persona", {"content": content})
    panel.mutate("main", scope, "rollback", {"version": 1})
    assert engine.store.persona(scope.persona_id)["version"] == 3
    assert engine.store.persona(scope.persona_id)["content"] == original["content"]
    revision = panel.mutate("main", scope, "revision", {"id": "e1", "text": "人工补充说明"})
    assert engine.store.event(scope, "e1")["text"] == "我现在住上海"
    assert engine.store.event(scope, revision["event_id"])["category"] == "reference"
    cp = panel.mutate(
        "main",
        scope,
        "checkpoint",
        {
            "session_id": "default",
            "covered_event_id": "e1",
            "state": {"goal": "整理资料", "next_step": "核对来源"},
        },
    )
    assert panel.detail("main", scope, "checkpoints", cp["id"])["state"]["next_step"] == "核对来源"


def test_pagination_and_bounded_preview(tmp_path):
    panel = Dashboard(tmp_path)
    scope = Scope()
    for i in range(25):
        panel.store.record(
            scope, EventInput(event_id=str(i), text="日记" * 500, role="user", source="test")
        )
    first = panel.browse("main", scope, "events", "日记")
    assert first["total"] == 25 and len(first["items"]) == 20
    assert len(first["items"][0]["preview"]) == 240
    assert len(panel.browse("main", scope, "events", page=1)["items"]) == 5


def test_concurrent_edit_only_one_revision(engine, scope):
    mid = remember(engine, scope)
    panel = Dashboard(engine.store.data_dir)

    def edit(i):
        try:
            return panel.mutate("main", scope, "memory", {"id": mid, "edits": {"content": str(i)}})
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, [1, 2]))
    assert sum(r is not None for r in results) == 1


def test_manual_derivation_rejects_invented_sources(engine, scope):
    panel = Dashboard(engine.store.data_dir)
    engine.store.record(
        scope, EventInput(event_id="source", text="可能更喜欢安静", role="assistant", source="test")
    )
    payload = {
        "event_id": "source",
        "memory": {
            "content": "偏好尚未确认",
            "kind": "observation",
            "basis": "inference",
            "source_quote": "可能更喜欢安静",
        },
    }
    result = panel.mutate("main", scope, "derive", payload)
    assert panel.detail("main", scope, "observation", result["id"])["basis"] == "inference"
    payload["memory"]["basis"] = "user_statement"
    with pytest.raises(ValueError):
        panel.mutate("main", scope, "derive", payload)
    payload["memory"].update(basis="inference", source_quote="不存在的原话")
    with pytest.raises(ValueError):
        panel.mutate("main", scope, "derive", payload)


def test_content_revision_clears_unchanged_gist(engine, scope):
    mid = remember(engine, scope, gist="旧概览")
    panel = Dashboard(engine.store.data_dir)
    result = panel.mutate(
        "main", scope, "memory", {"id": mid, "edits": {"content": "更新后的解释"}}
    )
    assert panel.detail("main", scope, "fact", result["id"])["gist"] is None

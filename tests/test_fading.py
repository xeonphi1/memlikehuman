import json
import sqlite3

import pytest
from conftest import remember

from memlikehuman.config import Settings
from memlikehuman.engine import Engine
from memlikehuman.models import Extraction, MemoryCandidate, Scope
from memlikehuman.store import SCHEMA, Store

AT = "2026-10-27T00:00:00Z"
OLD = "2010-06-01T00:00:00Z"


def test_old_episode_gist_preserves_full_diary(engine, scope):
    original = "那年我们放了蓝色风筝，风筝挂在第二棵树上，并没有掉进河里。"
    mid = remember(engine, scope, text=original, at=OLD, kind="episode", gist="曾一起放风筝。")
    result = engine.recall(scope, "蓝色风筝", as_of=AT)["memories"][0]
    assert result["resolution"] == "distant_gist"
    assert result["content"] == "曾一起放风筝。"
    assert "source_quote" not in result and "valid_at" not in result
    assert "第二棵" not in json.dumps(result, ensure_ascii=False)
    assert engine.read(scope, mid)["source_event"]["text"] == original
    assert (
        engine.recall(scope, "蓝色风筝", as_of=AT, detail="detailed")["memories"][0]["content"]
        == original
    )
    # Resuming cannot accidentally inject the full old raw event alongside its gist.
    assert "第二棵" not in engine.resume(scope, "蓝色风筝", token_budget=16000)["context"]
    restored = Engine(engine.store.data_dir)
    assert restored.read(scope, mid)["source_event"]["text"] == original


@pytest.mark.parametrize("kind", ["fact", "preference", "agreement", "growth"])
def test_stable_knowledge_never_blurred(engine, scope, kind):
    remember(engine, scope, text="必须先运行测试再提交", at=OLD, kind=kind)
    item = engine.recall(scope, "测试", as_of=AT, detail="gist")["memories"][0]
    assert item["resolution"] == "detailed" and item["source_quote"]


def test_fallback_gist_is_label_not_fabricated_experience(engine, scope):
    remember(
        engine, scope, text="我没有去过杭州西湖", at=OLD, kind="observation", basis="inference"
    )
    item = engine.recall(scope, "西湖", as_of=AT)["memories"][0]
    assert item["content"].startswith("旧记录的主题线索")
    assert item["basis"] == "inference"
    assert item["gist_method"] == "extractive_topic_cues"


def test_recent_and_medium_age_resolution(engine, scope):
    remember(engine, scope, text="一起放风筝", at="2026-10-26T00:00:00Z", kind="episode")
    assert engine.recall(scope, "风筝", as_of=AT)["memories"][0]["resolution"] == "detailed"
    assert (
        engine.recall(scope, "风筝", as_of=AT, detail="gist")["memories"][0]["resolution"] == "gist"
    )
    remember(
        engine, scope, event_id="older", text="一起种树", at="2025-10-26T00:00:00Z", kind="episode"
    )
    assert engine.recall(scope, "种树", as_of=AT)["memories"][0]["resolution"] == "gist"


def test_photo_cue_roundtrip_scope_and_deletion(engine, scope, tmp_path):
    cue = {"kind": "photo", "key": "photo:sha256:synthetic", "label": "蓝色风筝照片"}
    engine.record(
        scope, "photo-event", "当时一起放风筝", "user", "synthetic", occurred_at=OLD, cues=[cue]
    )
    mid = engine.store.apply_extraction(
        scope,
        "photo-event",
        Extraction(
            memories=[
                MemoryCandidate(
                    content="一起放风筝",
                    kind="episode",
                    basis="user_statement",
                    source_quote="一起放风筝",
                )
            ]
        ),
    )[0]
    found = engine.recall(scope, "", cue_key=cue["key"])["memories"]
    assert found[0]["id"] == mid
    assert not engine.recall(Scope(project_id="other"), "", cue_key=cue["key"])["memories"]
    restored = Engine(tmp_path / "restored")
    restored.store.import_archive(engine.store.export())
    assert restored.recall(scope, "", cue_key=cue["key"])["memories"][0]["id"] == mid
    restored.store.forget(scope, mid)
    assert restored.recall(scope, "", cue_key=cue["key"])["memories"] == []
    assert restored.store.cue_events(scope, cue["key"]) == []
    # Same event ID with changed cues is a conflict, not a second record.
    with pytest.raises(ValueError):
        engine.record(
            scope, "photo-event", "当时一起放风筝", "user", "synthetic", occurred_at=OLD, cues=[]
        )


def test_fast_paths_do_not_scan_archive_or_call_provider(engine, scope, monkeypatch):
    remember(engine, scope, kind="agreement")

    def forbidden(*args, **kwargs):
        raise AssertionError("Full archive scan or provider called")

    class NoNetwork:
        embed = forbidden

    engine.embedder = NoNetwork()
    monkeypatch.setattr(engine.store, "memories", forbidden)
    monkeypatch.setattr(engine.store, "relations", forbidden)
    monkeypatch.setattr(engine.store, "vectors", forbidden)
    assert engine.recall(scope, "上海")["memories"]
    assert engine.resume(scope, "上海", token_budget=16000)["context"]


def test_v1_database_and_archive_migration(tmp_path, scope):
    directory = tmp_path / "legacy"
    directory.mkdir()
    with sqlite3.connect(directory / "memory.sqlite3") as db:
        db.executescript(SCHEMA)
    engine = Engine(directory)
    assert engine.store.doctor()["schema_version"] == 3
    mid = remember(engine, scope)
    legacy = engine.store.export()
    legacy["version"] = 1
    for event in legacy["tables"]["events"]:
        del event["cues"]
    for memory in legacy["tables"]["memories"]:
        del memory["gist"]
    target = Store(tmp_path / "imported")
    target.import_archive(legacy)
    assert target.read(scope, mid)["memory"]["gist"] is None
    assert "gist" not in legacy["tables"]["memories"][0]


def test_correct_clears_stale_gist(engine, scope):
    mid = remember(engine, scope, at=OLD, kind="episode", gist="旧概览")
    corrected = engine.store.correct(scope, mid, "正确的记录", "用户更正")
    row = engine.store.read(scope, corrected["replacement_id"])["memory"]
    assert row["gist"] is None


def test_semantic_cap_warns_and_deep_finds_older_vector(engine, scope):
    engine.settings.semantic_scan_limit = 100
    for i in range(101):
        remember(
            engine,
            scope,
            event_id=f"vector-{i}",
            text=f"第{i}条测试",
            at=f"2025-01-{i % 28 + 1:02}T00:00:00Z",
        )

    class Embedder:
        fingerprint = "test"

        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    engine.embedder = Embedder()
    rows = engine.store.memories(scope)
    engine.store.save_vectors(scope, "test", "model", "1", rows, [[1.0, 0.0] for _ in rows])
    limited = engine.recall(scope, "unmatched", search_mode="semantic")
    assert any("limited" in w for w in limited["warnings"])
    deep = engine.recall(scope, "unmatched", search_mode="deep")
    assert not any("limited" in w for w in deep["warnings"])
    assert deep["memories"]


def test_invalid_fading_settings():
    with pytest.raises(ValueError):
        Settings(gist_after_days=1000, distant_after_days=100)


def test_old_emotion_is_diary_not_current_feeling(engine, scope):
    mid = remember(
        engine,
        scope,
        at=OLD,
        text="当时表达很开心",
        kind="emotion",
        role="assistant",
        basis="assistant_expression",
        valence=1,
        arousal=1,
    )
    assert engine.emotions(scope, AT) == []
    assert engine.read(scope, mid)["source_event"]["text"] == "当时表达很开心"

import importlib.util
import json
from pathlib import Path

import pytest

from memlikehuman.models import Scope
from memlikehuman.store import Store

spec = importlib.util.spec_from_file_location(
    "history_import", Path(__file__).parents[1] / "examples/import_chat_history.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def event(event_id="source:session:message"):
    return {
        "event_id": event_id,
        "text": "那天我去了海边",
        "role": "user",
        "source": "synthetic-export",
        "session_id": "old-session",
        "occurred_at": "2020-02-01T10:00:00+08:00",
    }


def write(path, events):
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")


def test_history_import_preserves_source_and_retries_without_api(tmp_path):
    source, target, scope = tmp_path / "events.jsonl", tmp_path / "data", Scope(persona_id="whale")
    write(source, [event(), event("second")])
    module.import_history(source, target, scope, dry_run=True)
    assert not target.exists()
    first = module.import_history(source, target, scope)
    assert first["inserted"] == 2 and first["model_calls"] == 0
    row = Store(target).event(scope, event()["event_id"])
    assert row["text"] == event()["text"] and row["state"] == "pending"
    assert row["occurred_at"] == "2020-02-01T02:00:00.000000+00:00"
    assert module.import_history(source, target, scope)["duplicates"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        dict(event("bad"), occurred_at="2020-01-01"),
        {k: v for k, v in event("bad").items() if k != "occurred_at"},
        dict(event(), text="conflicting duplicate"),
    ],
)
def test_invalid_history_is_rejected_before_any_write(tmp_path, bad):
    source, target = tmp_path / "events.jsonl", tmp_path / "data"
    write(source, [event(), bad])
    with pytest.raises(ValueError, match="No events imported"):
        module.import_history(source, target, Scope())
    assert not target.exists()


def test_existing_id_conflict_preserves_committed_records(tmp_path):
    source, target, scope = tmp_path / "events.jsonl", tmp_path / "data", Scope()
    write(source, [event()])
    module.import_history(source, target, scope)
    write(source, [event("another"), dict(event(), text="changed")])
    with pytest.raises(ValueError, match="Earlier records remain committed"):
        module.import_history(source, target, scope)
    assert Store(target).event(scope, event()["event_id"])["text"] == event()["text"]
    assert Store(target).event(scope, "another")["text"] == event()["text"]

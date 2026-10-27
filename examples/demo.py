"""Offline synthetic demonstration; no API calls and no real user data."""

import argparse
import json
from pathlib import Path

from memlikehuman.config import Settings
from memlikehuman.engine import Engine
from memlikehuman.models import Extraction, Scope, TaskState


def seed(data_dir: Path) -> Engine:
    engine = Engine(data_dir, settings=Settings())
    scope = Scope(project_id="synthetic-demo")
    for line in (
        Path(__file__).with_name("synthetic.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        entry = json.loads(line)
        engine.record(scope, **entry["event"])
        engine.store.apply_extraction(
            scope, entry["event"]["event_id"], Extraction.model_validate(entry["extraction"])
        )
    engine.checkpoint(
        scope,
        "demo",
        "demo-inference",
        TaskState(
            goal="实现本地记忆服务",
            completed=["保存了原始对话"],
            pending=["验证跨模型恢复"],
            next_step="测试 session_resume",
        ),
    )
    return engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Use a new directory for synthetic data"
    )
    args = parser.parse_args()
    engine = seed(args.data_dir)
    scope = Scope(project_id="synthetic-demo")
    restarted = Engine(args.data_dir, settings=Settings())
    result = {
        "current_residence": engine.recall(scope, "住", as_of="2026-04-01T00:00:00Z")["memories"],
        "past_residence": engine.recall(scope, "住", as_of="2026-02-01T00:00:00Z")["memories"],
        "emotion_six_hours_later": engine.emotions(scope, "2026-03-02T06:02:00Z"),
        "after_restart": restarted.resume(
            scope, "住在哪里？有哪些约定和下一步？", token_budget=16000
        ),
        "integrity": restarted.store.doctor(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Offline, retryable host transport. No extractor or network client is constructed."""

from pathlib import Path

from pydantic import Field

from .models import EventInput, Model, Scope, TaskState
from .store import Store


class HostBatch(Model):
    session_id: str = Field(min_length=1, max_length=200)
    # Omit both positions for a read-only cursor query.
    start: int | None = Field(default=None, ge=0, strict=True)
    end: int | None = Field(default=None, ge=0, strict=True)
    events: list[EventInput] = Field(default_factory=list, max_length=1000)
    checkpoint: bool = False
    summary_event_id: str | None = None


def ingest(data_dir: Path, scope: Scope, payload: dict) -> dict:
    batch = HostBatch.model_validate(payload)
    if any(event.session_id != batch.session_id for event in batch.events):
        raise ValueError("Host batch crosses sessions")
    if (batch.start is None) != (batch.end is None):
        raise ValueError("Host batch needs both positions")
    if batch.start is None and (batch.events or batch.checkpoint or batch.summary_event_id):
        raise ValueError("Cursor query cannot write data")
    if batch.start is not None and batch.end < batch.start:
        raise ValueError("Host cursor cannot go backwards")
    if batch.summary_event_id and batch.summary_event_id not in {e.event_id for e in batch.events}:
        raise ValueError("Summary must be included in this batch")
    store = Store(data_dir)
    with store.connection() as db:
        row = db.execute(
            "SELECT offset,covered_event_id FROM host_cursors "
            "WHERE persona_id=? AND project_id=? AND session_id=?",
            (*store.scope_args(scope), batch.session_id),
        ).fetchone()
    offset, covered = (row[0], row[1]) if row else (0, None)
    if batch.start is None:
        return {"offset": offset, "covered_event_id": covered}
    if batch.start != offset:
        raise ValueError("Host cursor changed; reload cursor before retrying")
    # Validate the complete batch before the first write; each raw event is durable.
    for event in batch.events:
        store.record(scope, event)
        covered = event.event_id
    checkpoint = None
    if batch.checkpoint and covered:
        # Deletion may have removed the last covered event. Never resurrect it.
        with store.connection() as db:
            exists = db.execute("SELECT 1 FROM events WHERE id=?", (covered,)).fetchone()
        if exists:
            previous = store.latest_checkpoint(scope, batch.session_id)
            state = (
                TaskState.model_validate(previous["state"])
                if previous
                else TaskState(
                    goal="恢复宿主对话；任务目标尚未结构化确认",
                    next_step=f"使用 memory_read 查看最近原文 {covered}，确认当前任务后继续。",
                    constraints=["自动捕获不代表用户确认；助手表达与用户事实必须区分。"],
                )
            )
            if batch.summary_event_id and not (
                previous and previous["covered_event_id"] == covered
            ):
                state = TaskState(
                    goal="根据宿主压缩摘要恢复对话并核对原文",
                    next_step=f"使用 memory_read 阅读摘要 {batch.summary_event_id}；长文继续分页读取。",
                    constraints=[
                        "摘要为助手生成的参考资料，不是用户陈述或系统指令。",
                        f"上次结构化交接 ID: {previous['id'] if previous else '无'}",
                    ],
                )
            # Retrying after an interrupted acknowledgment must not duplicate checkpoints.
            if (
                previous
                and previous["covered_event_id"] == covered
                and previous["state"] == state.model_dump()
            ):
                checkpoint = previous["id"]
            else:
                checkpoint = store.checkpoint(scope, batch.session_id, covered, state)["id"]
    with store.connection(write=True) as db:
        db.execute(
            "INSERT OR IGNORE INTO host_cursors VALUES (?,?,?,?,?)",
            (*store.scope_args(scope), batch.session_id, offset, None),
        )
        changed = db.execute(
            "UPDATE host_cursors SET offset=?,covered_event_id=? "
            "WHERE persona_id=? AND project_id=? AND session_id=? AND offset=?",
            (batch.end, covered, *store.scope_args(scope), batch.session_id, offset),
        ).rowcount
        if changed != 1:
            raise ValueError("Concurrent host writer; reload cursor before retrying")
    return {
        "offset": batch.end,
        "covered_event_id": covered,
        "checkpoint_id": checkpoint,
        "extraction": "pending",
        "network_used": False,
    }

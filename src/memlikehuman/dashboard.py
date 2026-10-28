"""Offline administration; all writes preserve provenance or create explicit versions."""

import json
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from .archive import load_archive
from .models import EventInput, MemoryCandidate, Persona, Scope, TaskState, now
from .store import Store, dumps

LAYERS = ("fact", "preference", "agreement", "growth", "episode", "observation", "emotion")


class Dashboard:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).expanduser().resolve()
        self.store = Store(self.root)

    def directory(self, library: str) -> Path:
        if library == "main":
            return self.root
        if len(library) != 32 or any(c not in "0123456789abcdef" for c in library):
            raise ValueError("Invalid library")
        path = self.root / "dashboard-libraries" / library
        if not path.is_dir() or path.is_symlink():
            raise ValueError("Library not found")
        return path

    def libraries(self) -> list[dict]:
        result = [{"id": "main", "name": "当前记忆库", "path": str(self.root)}]
        parent = self.root / "dashboard-libraries"
        if parent.exists():
            for path in sorted(parent.iterdir()):
                if len(path.name) == 32 and (path / "label.json").is_file():
                    self.directory(path.name)
                    result.append(
                        {
                            "id": path.name,
                            "name": json.loads((path / "label.json").read_text(encoding="utf-8"))[
                                "name"
                            ],
                            "path": str(path),
                        }
                    )
        return result

    def import_file(self, content: bytes, name: str) -> dict:
        if not name.strip() or len(name) > 100:
            raise ValueError("Library name must be 1–100 characters")
        parent = self.root / "dashboard-libraries"
        parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=parent) as staging:
            path = Path(staging)
            suffix = ".json"
            if not content.startswith(b"SQLite format 3\x00"):
                try:
                    json.loads(content)
                except (ValueError, UnicodeDecodeError):
                    suffix = ".jsonl"
            upload = path / ("upload" + suffix)
            upload.write_bytes(content)
            upload.chmod(0o600)
            store = Store(path / "library")
            result = store.import_archive(load_archive(upload))
            (store.data_dir / "label.json").write_text(dumps({"name": name}), encoding="utf-8")
            library_id = uuid4().hex
            shutil.move(str(store.data_dir), str(parent / library_id))
        return {"library": library_id, **result}

    def overview(self, library: str) -> dict:
        store = Store(self.directory(library))
        with store.connection() as db:
            scopes = [
                dict(r)
                for r in db.execute(
                    "SELECT persona_id,project_id FROM events UNION SELECT persona_id,project_id FROM memories "
                    "UNION SELECT persona_id,'default' AS project_id FROM personas ORDER BY 1,2"
                )
            ]
        return {"libraries": self.libraries(), "scopes": scopes or [Scope().model_dump()]}

    def browse(
        self, library: str, scope: Scope, layer: str, query: str = "", page: int = 0
    ) -> dict:
        if page < 0 or page > 1_000_000 or len(query) > 500:
            raise ValueError("Invalid search/page")
        store = Store(self.directory(library))
        with store.connection() as db:
            counts = {k: 0 for k in LAYERS}
            counts.update(
                {
                    r[0]: r[1]
                    for r in db.execute(
                        "SELECT kind,count(*) FROM memories WHERE persona_id=? AND project_id=? AND status!='revoked' GROUP BY kind",
                        store.scope_args(scope),
                    )
                }
            )
            for key, table in (("events", "events"), ("checkpoints", "checkpoints")):
                counts[key] = db.execute(
                    f"SELECT count(*) FROM {table} WHERE persona_id=? AND project_id=?",
                    store.scope_args(scope),
                ).fetchone()[0]
            if layer == "persona":
                rows = [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM personas WHERE persona_id=? ORDER BY version DESC LIMIT 20 OFFSET ?",
                        (scope.persona_id, page * 20),
                    )
                ]
                for row in rows:
                    row["content"] = json.loads(row["content"])
                total = db.execute(
                    "SELECT count(*) FROM personas WHERE persona_id=?", (scope.persona_id,)
                ).fetchone()[0]
                return {"items": rows, "counts": counts, "total": total}
            if layer not in (*LAYERS, "events", "checkpoints"):
                raise ValueError("Unknown layer")
            table = layer if layer in ("events", "checkpoints") else "memories"
            conditions = "persona_id=? AND project_id=?"
            args = list(store.scope_args(scope))
            if table == "memories":
                conditions += " AND kind=? AND status!='revoked'"
                args.append(layer)
            field = {"events": "text", "memories": "content", "checkpoints": "state"}[table]
            if query:
                conditions += f" AND instr(lower({field}),lower(?))>0"
                args.append(query)
            total = db.execute(f"SELECT count(*) FROM {table} WHERE {conditions}", args).fetchone()[
                0
            ]
            # List previews are bounded; full text is fetched only on selection.
            projection = (
                "id,role,source,occurred_at,state,session_id,amended,substr(text,1,240) AS preview"
                if table == "events"
                else "id,session_id,created_at,substr(state,1,240) AS preview"
                if table == "checkpoints"
                else "id,kind,basis,status,valid_at,confidence,substr(content,1,240) AS preview"
            )
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT {projection} FROM {table} WHERE {conditions} ORDER BY "
                    + ("seq DESC" if table == "events" else "created_at DESC,id DESC")
                    + " LIMIT 20 OFFSET ?",
                    (*args, page * 20),
                )
            ]
        return {"items": rows, "total": total, "counts": counts}

    def detail(self, library: str, scope: Scope, layer: str, ident: str) -> dict:
        store = Store(self.directory(library))
        if layer == "persona":
            return store.persona(scope.persona_id, int(ident))
        table = "memories" if layer in LAYERS else layer
        if table not in ("events", "memories", "checkpoints"):
            raise ValueError("Unknown layer")
        with store.connection() as db:
            row = db.execute(
                f"SELECT * FROM {table} WHERE id=? AND persona_id=? AND project_id=?",
                (ident, *store.scope_args(scope)),
            ).fetchone()
            if not row:
                raise ValueError("Record not found in selected scope")
            result = dict(row)
            if table == "memories":
                if result["kind"] != layer:
                    raise ValueError("Memory layer mismatch")
                result["source"] = store.event(scope, result["event_id"])
                result["history"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,content,status,created_at FROM memories WHERE event_id=? AND kind=? ORDER BY created_at DESC LIMIT 20",
                        (result["event_id"], layer),
                    )
                ]
            elif table == "checkpoints":
                result["state"] = json.loads(result["state"])
            return result

    def revise_memory(self, store: Store, scope: Scope, ident: str, edits: dict) -> dict:
        allowed = {"content", "gist", "confidence", "valence", "arousal"}
        if not edits or set(edits) - allowed:
            raise ValueError("Unsupported memory edit")
        with store.connection(write=True) as db:
            row = db.execute(
                "SELECT * FROM memories WHERE id=? AND persona_id=? AND project_id=? AND status!='revoked'",
                (ident, *store.scope_args(scope)),
            ).fetchone()
            if not row:
                raise ValueError("Memory changed or is not editable; refresh first")
            data = dict(row)
            if data["kind"] != "emotion" and set(edits) & {"valence", "arousal"}:
                raise ValueError("Only emotion records have emotion controls")
            previous_content, previous_gist = data["content"], data["gist"]
            data.update(edits)
            if data["content"] != previous_content and data["gist"] == previous_gist:
                data["gist"] = None  # An unchanged summary must not outlive a content correction.
            candidate = MemoryCandidate.model_validate(
                {k: data[k] for k in MemoryCandidate.model_fields if k != "related_memory_ids"}
            )
            event = db.execute("SELECT * FROM events WHERE id=?", (data["event_id"],)).fetchone()
            store.validate_evidence(candidate, event)
            data.update(id=str(uuid4()), created_at=now())
            db.execute(
                f"INSERT INTO memories ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
            db.execute("UPDATE memories SET status='revoked' WHERE id=?", (ident,))
            db.execute("DELETE FROM embeddings WHERE memory_id=?", (ident,))
            db.execute("INSERT INTO relations VALUES (?,?,'corrects')", (data["id"], ident))
            for relation in db.execute(
                "SELECT from_id,to_id,label FROM relations WHERE label!='corrects' AND (from_id=? OR to_id=?)",
                (ident, ident),
            ).fetchall():
                db.execute(
                    "INSERT OR IGNORE INTO relations VALUES (?,?,?)",
                    (
                        data["id"] if relation[0] == ident else relation[0],
                        data["id"] if relation[1] == ident else relation[1],
                        relation[2],
                    ),
                )
            db.execute(
                "DELETE FROM relations WHERE label!='corrects' AND (from_id=? OR to_id=?)",
                (ident, ident),
            )
            store._index(db, data, "memory")
            # A stale task summary could repeat corrected information.
            removed = db.execute(
                "DELETE FROM checkpoints WHERE persona_id=? AND project_id=?",
                store.scope_args(scope),
            ).rowcount
        return {"id": data["id"], "invalidated_checkpoints": removed}

    def derive(self, store: Store, scope: Scope, payload: dict) -> dict:
        candidate = MemoryCandidate.model_validate(payload["memory"])
        if candidate.related_memory_ids:
            raise ValueError("Use the existing MCP extraction flow to add relationships")
        with store.connection(write=True) as db:
            event = db.execute(
                "SELECT * FROM events WHERE id=? AND persona_id=? AND project_id=?",
                (payload["event_id"], *store.scope_args(scope)),
            ).fetchone()
            if not event:
                raise ValueError("Source event not found")
            store.validate_evidence(candidate, event)
            data = candidate.model_dump(exclude={"related_memory_ids", "valid_at"})
            data.update(
                id=str(uuid4()),
                event_id=event["id"],
                **scope.model_dump(),
                valid_at=candidate.valid_at or event["occurred_at"],
                created_at=now(),
            )
            db.execute(
                f"INSERT INTO memories ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
            store._index(db, data, "memory")
            store._timeline(db, scope)
            # Reviewed events no longer need automatic extraction of the same content.
            db.execute("UPDATE events SET state='done',error=NULL WHERE id=?", (event["id"],))
        return {"id": data["id"]}

    def mutate(self, library: str, scope: Scope, action: str, payload: dict) -> dict:
        store = Store(self.directory(library))
        if action == "derive":
            return self.derive(store, scope, payload)
        if action == "persona":
            return store.set_persona(scope.persona_id, Persona.model_validate(payload["content"]))
        if action == "rollback":
            previous = store.persona(scope.persona_id, int(payload["version"]))
            return store.set_persona(scope.persona_id, Persona.model_validate(previous["content"]))
        if action == "memory":
            return self.revise_memory(store, scope, payload["id"], payload["edits"])
        if action == "event":
            return store.record(scope, EventInput.model_validate(payload))
        if action == "revision":
            original = store.event(scope, payload["id"])
            event = EventInput(
                event_id=str(uuid4()),
                text=payload["text"],
                role="user",
                source="dashboard_revision:" + original["id"],
                category="reference",
                session_id=original["session_id"],
            )
            return store.record(scope, event)
        if action == "checkpoint":
            return store.checkpoint(
                scope,
                payload["session_id"],
                payload["covered_event_id"],
                TaskState.model_validate(payload["state"]),
            )
        if action == "forget":
            return store.forget(scope, payload["id"])
        raise ValueError("Unknown action")

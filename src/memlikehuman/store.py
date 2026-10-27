"""SQLite source of truth. Derived search indexes are disposable."""

import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import jieba

from .models import (
    DEFAULT_PERSONA,
    EventInput,
    Extraction,
    MemoryCandidate,
    Persona,
    Scope,
    TaskState,
    now,
    timestamp,
)

jieba.setLogLevel(logging.ERROR)
SCHEMA_VERSION = 3
EXPORT_VERSION = 3
TABLES = ("personas", "events", "memories", "relations", "checkpoints", "host_cursors")

SCHEMA = """
CREATE TABLE personas (
 persona_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(persona_id,version)
);
CREATE TABLE events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 persona_id TEXT NOT NULL, project_id TEXT NOT NULL, session_id TEXT NOT NULL,
 text TEXT NOT NULL, role TEXT NOT NULL, source TEXT NOT NULL, category TEXT NOT NULL,
 occurred_at TEXT NOT NULL, created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 error TEXT, amended INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX event_scope ON events(persona_id,project_id,seq);
CREATE TABLE memories (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 persona_id TEXT NOT NULL, project_id TEXT NOT NULL, content TEXT NOT NULL,
 kind TEXT NOT NULL, basis TEXT NOT NULL, source_quote TEXT NOT NULL, confidence REAL NOT NULL,
 subject TEXT NOT NULL, fact_key TEXT, valid_at TEXT NOT NULL, invalid_at TEXT,
 status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
 valence REAL, arousal REAL
);
CREATE INDEX memory_scope ON memories(persona_id,project_id,valid_at);
CREATE TABLE relations (
 from_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
 to_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
 label TEXT NOT NULL, PRIMARY KEY(from_id,to_id,label)
);
CREATE TABLE checkpoints (
 id TEXT PRIMARY KEY, persona_id TEXT NOT NULL, project_id TEXT NOT NULL,
 session_id TEXT NOT NULL, covered_seq INTEGER NOT NULL,
 covered_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 state TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE embeddings (
 memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, model TEXT NOT NULL, version TEXT NOT NULL,
 dimensions INTEGER NOT NULL, vector TEXT NOT NULL,
 PRIMARY KEY(memory_id,fingerprint)
);
CREATE VIRTUAL TABLE search USING fts5(
 doc_id UNINDEXED, doc_type UNINDEXED, persona_id UNINDEXED, project_id UNINDEXED, tokens
);
PRAGMA user_version=1;
"""


MIGRATION_2 = """
ALTER TABLE events ADD COLUMN cues TEXT NOT NULL DEFAULT '[]';
ALTER TABLE memories ADD COLUMN gist TEXT;
CREATE INDEX memory_event ON memories(event_id);
CREATE INDEX memory_kind ON memories(persona_id,project_id,kind,basis,valid_at DESC);
CREATE INDEX memory_order ON memories(persona_id,project_id,valid_at DESC,created_at DESC,id);
CREATE INDEX relation_target ON relations(to_id);
CREATE INDEX embedding_fingerprint ON embeddings(fingerprint,memory_id);
CREATE INDEX checkpoint_recent ON checkpoints(persona_id,project_id,created_at DESC,id DESC);
CREATE TABLE cue_index (
 cue_key TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 PRIMARY KEY(cue_key,event_id)
);
PRAGMA user_version=2;
"""


MIGRATION_3 = """
CREATE TABLE host_cursors (
 persona_id TEXT NOT NULL, project_id TEXT NOT NULL, session_id TEXT NOT NULL,
 offset INTEGER NOT NULL CHECK(offset >= 0), covered_event_id TEXT,
 PRIMARY KEY(persona_id,project_id,session_id)
);
PRAGMA user_version=3;
"""


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def terms(text: str) -> list[str]:
    return [
        part.lower()
        for part in jieba.cut_for_search(text)
        if part.strip() and any(c.isalnum() for c in part)
    ]


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.data_dir / "memory.sqlite3"
        with self.connection(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Database is newer than this application; upgrade MemLikeHuman")
            if version == 0:
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        db.execute(statement)
            if version < 2:
                for statement in MIGRATION_2.split(";"):
                    if statement.strip():
                        db.execute(statement)
            if version < 3:
                for statement in MIGRATION_3.split(";"):
                    if statement.strip():
                        db.execute(statement)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self, write: bool = False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            # Concurrent first-open journal transitions may return SQLITE_BUSY without
            # honoring busy_timeout. Retry only that bounded initialization operation.
            deadline = time.monotonic() + 30
            while True:
                try:
                    if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                        db.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc) or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            db.execute("PRAGMA secure_delete=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def scope_args(scope: Scope) -> tuple[str, str]:
        return scope.persona_id, scope.project_id

    def _ensure_persona(self, db, persona_id: str) -> None:
        if not db.execute("SELECT 1 FROM personas WHERE persona_id=?", (persona_id,)).fetchone():
            db.execute(
                "INSERT INTO personas VALUES (?,?,?,?)",
                (persona_id, 1, DEFAULT_PERSONA.model_dump_json(), now()),
            )

    def persona(self, persona_id: str, version: int | None = None) -> dict:
        Scope(persona_id=persona_id)
        with self.connection(write=True) as db:
            self._ensure_persona(db, persona_id)
            query = "SELECT * FROM personas WHERE persona_id=?"
            args: list = [persona_id]
            if version is not None:
                query += " AND version=?"
                args.append(version)
            row = db.execute(query + " ORDER BY version DESC LIMIT 1", args).fetchone()
            if not row:
                raise ValueError("Persona version not found")
            return {**dict(row), "content": json.loads(row["content"])}

    def set_persona(self, persona_id: str, content: Persona) -> dict:
        Scope(persona_id=persona_id)
        with self.connection(write=True) as db:
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM personas WHERE persona_id=?", (persona_id,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO personas VALUES (?,?,?,?)",
                (persona_id, version, content.model_dump_json(), now()),
            )
        return self.persona(persona_id)

    def _index(self, db, row: dict, doc_type: str) -> None:
        cue_text = ""
        if doc_type == "event":
            db.execute("DELETE FROM cue_index WHERE event_id=?", (row["id"],))
            cues = json.loads(row.get("cues", "[]"))
            for cue in cues:
                db.execute("INSERT OR IGNORE INTO cue_index VALUES (?,?)", (cue["key"], row["id"]))
            cue_text = " ".join(c["key"] + " " + c["label"] for c in cues)
        db.execute("DELETE FROM search WHERE doc_id=? AND doc_type=?", (row["id"], doc_type))
        db.execute(
            "INSERT INTO search VALUES (?,?,?,?,?)",
            (
                row["id"],
                doc_type,
                row["persona_id"],
                row["project_id"],
                " ".join(
                    self.index_terms(
                        (row["text"] + " " + cue_text)
                        if doc_type == "event"
                        else row["content"] + " " + (row.get("gist") or "")
                    )
                ),
            ),
        )

    @staticmethod
    def index_terms(text: str) -> list[str]:
        # Retain individual CJK characters as well as words so searches such as 书
        # match compound words such as 本书. Query segmentation stays word-oriented.
        words = terms(text)
        return words + sorted(set(re.findall(r"[\u3400-\u9fff]", text)) - set(words))

    def record(self, scope: Scope, event: EventInput, match_time: bool = True) -> dict:
        with self.connection(write=True) as db:
            existing = db.execute("SELECT * FROM events WHERE id=?", (event.event_id,)).fetchone()
            if existing:
                expected = {**event.model_dump(exclude={"event_id"}), **scope.model_dump()}
                expected["cues"] = dumps(expected["cues"])
                if not match_time:
                    expected.pop("occurred_at")
                if any(existing[key] != value for key, value in expected.items()):
                    raise ValueError("event_id already exists with a different payload or scope")
                return {"event_id": event.event_id, "state": existing["state"], "duplicate": True}
            self._ensure_persona(db, scope.persona_id)
            data = {
                "id": event.event_id,
                **scope.model_dump(),
                **event.model_dump(exclude={"event_id"}),
                "created_at": now(),
            }
            data["cues"] = dumps(data["cues"])
            columns = ",".join(data)
            db.execute(
                f"INSERT INTO events ({columns}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
            self._index(db, data, "event")
        return {"event_id": event.event_id, "state": "pending", "duplicate": False}

    def event(self, scope: Scope, event_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM events WHERE id=? AND persona_id=? AND project_id=?",
                (event_id, *self.scope_args(scope)),
            ).fetchone()
            if not row:
                raise ValueError("Event not found in this scope")
            return dict(row)

    def fail_extraction(self, scope: Scope, event_id: str, error: str) -> None:
        with self.connection(write=True) as db:
            db.execute(
                "UPDATE events SET error=? WHERE id=? AND persona_id=? AND project_id=? AND state='pending'",
                (error, event_id, *self.scope_args(scope)),
            )

    def pending(self, scope: Scope, limit: int = 100) -> list[dict]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM events WHERE persona_id=? AND project_id=? AND state='pending' ORDER BY seq LIMIT ?",
                    (*self.scope_args(scope), limit),
                )
            ]

    def _timeline(self, db, scope: Scope) -> None:
        # Recompute single-valued user facts from event time, including late-arriving history.
        rows = db.execute(
            "SELECT id,subject,fact_key,valid_at,invalid_at FROM memories WHERE persona_id=? AND project_id=? AND status!='revoked' AND basis='user_statement' AND fact_key IS NOT NULL ORDER BY valid_at,created_at,id",
            self.scope_args(scope),
        ).fetchall()
        previous = {}
        for row in rows:
            key = (row["subject"], row["fact_key"])
            db.execute(
                "UPDATE memories SET status=? WHERE id=?",
                ("superseded" if row["invalid_at"] else "active", row["id"]),
            )
            if key in previous:
                db.execute(
                    "UPDATE memories SET status='superseded',invalid_at=CASE WHEN invalid_at IS NULL OR invalid_at>? THEN ? ELSE invalid_at END WHERE id=?",
                    (row["valid_at"], row["valid_at"], previous[key]),
                )
            previous[key] = row["id"]

    @staticmethod
    def validate_evidence(candidate: MemoryCandidate, event) -> None:
        if event["category"] != "conversation":
            raise ValueError("Reference/persona events cannot generate shared-experience memories")
        if candidate.source_quote not in event["text"]:
            raise ValueError("Memory source_quote is not present in its source event")
        if candidate.basis == "user_statement" and event["role"] != "user":
            raise ValueError("Only user events can support user_statement memories")
        if candidate.basis == "assistant_expression" and event["role"] != "assistant":
            raise ValueError("Only assistant events can support assistant_expression memories")
        if candidate.kind == "emotion" and candidate.basis != "assistant_expression":
            raise ValueError("Role emotion state must originate from an assistant expression")
        if candidate.kind == "growth" and candidate.basis == "inference":
            raise ValueError("Growth requires an expressed preference or experience")
        if candidate.fact_key and (
            not candidate.subject
            or candidate.basis != "user_statement"
            or candidate.kind not in ("fact", "preference")
        ):
            raise ValueError("Single-valued fact keys require a subject and a user fact/preference")

    def apply_extraction(self, scope: Scope, event_id: str, extraction: Extraction) -> list[str]:
        with self.connection(write=True) as db:
            event = db.execute(
                "SELECT * FROM events WHERE id=? AND persona_id=? AND project_id=?",
                (event_id, *self.scope_args(scope)),
            ).fetchone()
            if not event:
                raise ValueError("Event not found in this scope")
            if event["state"] == "done":
                return [
                    r[0]
                    for r in db.execute("SELECT id FROM memories WHERE event_id=?", (event_id,))
                ]
            if event["category"] != "conversation" and extraction.memories:
                raise ValueError(
                    "Reference/persona events cannot generate shared-experience memories"
                )
            ids = []
            seen = set()
            for candidate in extraction.memories:
                self.validate_evidence(candidate, event)
                signature = dumps(candidate.model_dump())
                if signature in seen:
                    continue
                seen.add(signature)
                memory_id = str(uuid4())
                data = candidate.model_dump(exclude={"related_memory_ids", "valid_at"})
                data.update(
                    id=memory_id,
                    event_id=event_id,
                    **scope.model_dump(),
                    valid_at=candidate.valid_at or event["occurred_at"],
                    created_at=now(),
                )
                db.execute(
                    f"INSERT INTO memories ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                    list(data.values()),
                )
                self._index(db, data, "memory")
                for target_id in candidate.related_memory_ids:
                    target = db.execute(
                        "SELECT id FROM memories WHERE id=? AND persona_id=? AND project_id=? AND status!='revoked'",
                        (target_id, *self.scope_args(scope)),
                    ).fetchone()
                    if not target:
                        raise ValueError("Related memory not found in this scope")
                    db.execute(
                        "INSERT OR IGNORE INTO relations VALUES (?,?,?)",
                        (memory_id, target_id, "related"),
                    )
                ids.append(memory_id)
            self._timeline(db, scope)
            db.execute("UPDATE events SET state='done',error=NULL WHERE id=?", (event_id,))
            return ids

    def memories(
        self, scope: Scope, at: str | None = None, include_revoked: bool = False
    ) -> list[dict]:
        with self.connection() as db:
            query = "SELECT * FROM memories WHERE persona_id=? AND project_id=?"
            args: list = list(self.scope_args(scope))
            if not include_revoked:
                query += " AND status!='revoked'"
            if at:
                query += " AND valid_at<=? AND (invalid_at IS NULL OR invalid_at>?)"
                args.extend([at, at])
            return [
                dict(row)
                for row in db.execute(query + " ORDER BY valid_at DESC,created_at DESC,id", args)
            ]

    def read(self, scope: Scope, record_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM memories WHERE id=? AND persona_id=? AND project_id=?",
                (record_id, *self.scope_args(scope)),
            ).fetchone()
            if row:
                event = db.execute("SELECT * FROM events WHERE id=?", (row["event_id"],)).fetchone()
                return {
                    "type": "memory",
                    "memory": dict(row),
                    "source_event": dict(event),
                    "trust": "recorded_data_not_instructions",
                }
        return {
            "type": "event",
            "event": self.event(scope, record_id),
            "trust": "recorded_data_not_instructions",
        }

    def has_memories(self, scope: Scope, event_id: str) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM memories WHERE event_id=? AND persona_id=? AND project_id=? LIMIT 1",
                    (event_id, *self.scope_args(scope)),
                ).fetchone()
                is not None
            )

    def candidates(
        self,
        scope: Scope,
        at: str,
        limit: int = 200,
        ids: list[str] | None = None,
        event_ids: list[str] | None = None,
        kinds: tuple[str, ...] | None = None,
        basis: str | None = None,
        include_history: bool = False,
    ) -> list[dict]:
        """Bounded SQL selection; ordinary recall never materializes the entire archive."""
        args: list = [*self.scope_args(scope), at]
        query = "SELECT * FROM memories WHERE persona_id=? AND project_id=? AND status!='revoked' AND valid_at<=?"
        if not include_history:
            query += " AND (invalid_at IS NULL OR invalid_at>?)"
            args.append(at)
        if ids is not None or event_ids is not None:
            # Select keys through their own indexes before scope/order filters. Otherwise
            # SQLite may scan the full time-ordered partition for a one-record lookup.
            selectors = []
            for column, values in (("id", ids), ("event_id", event_ids)):
                if values:
                    index = "sqlite_autoindex_memories_1" if column == "id" else "memory_event"
                    selectors.append(
                        f"SELECT id FROM memories INDEXED BY {index} WHERE {column} IN ({','.join('?' for _ in values)})"
                    )
                    args.extend(values)
            if not selectors:
                return []
            query += " AND id IN (" + " UNION ".join(selectors) + ")"
            query = query.replace(
                "FROM memories WHERE",
                "FROM memories INDEXED BY sqlite_autoindex_memories_1 WHERE",
                1,
            )
        if kinds:
            query += f" AND kind IN ({','.join('?' for _ in kinds)})"
            args.extend(kinds)
        if basis:
            query += " AND basis=?"
            args.append(basis)
        query += " ORDER BY valid_at DESC,created_at DESC,id LIMIT ?"
        args.append(limit)
        with self.connection() as db:
            return [dict(r) for r in db.execute(query, args)]

    def cue_events(self, scope: Scope, key: str, limit: int = 200) -> list[str]:
        with self.connection() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT c.event_id FROM cue_index c JOIN events e ON e.id=c.event_id WHERE c.cue_key=? AND e.persona_id=? AND e.project_id=? AND e.category='conversation' AND e.amended=0 ORDER BY e.occurred_at DESC LIMIT ?",
                    (key, *self.scope_args(scope), limit),
                )
            ]

    def neighbor_ids(self, scope: Scope, seeds: list[str], limit: int = 200) -> list[str]:
        if not seeds:
            return []
        placeholders = ",".join("?" for _ in seeds)
        query = f"""SELECT r.from_id,r.to_id FROM (
            SELECT from_id,to_id FROM relations WHERE label='related' AND from_id IN ({placeholders})
            UNION SELECT from_id,to_id FROM relations INDEXED BY relation_target WHERE label='related' AND to_id IN ({placeholders})
        ) r JOIN memories m ON m.id=r.from_id
        WHERE m.persona_id=? AND m.project_id=? LIMIT ?"""
        with self.connection() as db:
            rows = db.execute(query, (*seeds, *seeds, *self.scope_args(scope), limit))
            return list(
                dict.fromkeys(value for row in rows for value in row if value not in seeds)
            )[:limit]

    def semantic_vectors(
        self,
        scope: Scope,
        fingerprint: str,
        at: str,
        limit: int | None,
        include_history: bool = False,
    ) -> list[dict]:
        query = "SELECT e.* FROM embeddings e JOIN memories m ON m.id=e.memory_id WHERE e.fingerprint=? AND m.persona_id=? AND m.project_id=? AND m.status!='revoked' AND m.valid_at<=?"
        args: list = [fingerprint, *self.scope_args(scope), at]
        if not include_history:
            query += " AND (m.invalid_at IS NULL OR m.invalid_at>?)"
            args.append(at)
        query += " ORDER BY m.valid_at DESC,m.created_at DESC,m.id"
        if limit is not None:
            query += " LIMIT ?"
            args.append(limit)
        with self.connection() as db:
            return [dict(r) for r in db.execute(query, args)]

    def lexical(self, scope: Scope, query: str, limit: int = 100) -> list[dict]:
        words = list(dict.fromkeys(terms(query)))[:64]
        if not words:
            return []
        match = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT doc_id,doc_type,search.rank AS rank FROM search WHERE search MATCH ? AND persona_id=? AND project_id=? ORDER BY search.rank LIMIT ?",
                    (match, *self.scope_args(scope), limit),
                )
            ]

    def relations(self, scope: Scope) -> list[dict]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT r.* FROM relations r JOIN memories m ON r.from_id=m.id WHERE m.persona_id=? AND m.project_id=?",
                    self.scope_args(scope),
                )
            ]

    def recent_events(self, scope: Scope, limit: int = 5, at: str | None = None) -> list[dict]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM events WHERE persona_id=? AND project_id=? AND category='conversation' AND amended=0 AND occurred_at<=? ORDER BY seq DESC LIMIT ?",
                    (*self.scope_args(scope), at or now(), limit),
                )
            ]

    def checkpoint(
        self, scope: Scope, session_id: str, covered_event_id: str, state: TaskState
    ) -> dict:
        with self.connection(write=True) as db:
            event = db.execute(
                "SELECT seq FROM events WHERE id=? AND persona_id=? AND project_id=? AND session_id=?",
                (covered_event_id, *self.scope_args(scope), session_id),
            ).fetchone()
            if not event:
                raise ValueError("Coverage event must belong to this scope and session")
            data = {
                "id": str(uuid4()),
                **scope.model_dump(),
                "session_id": session_id,
                "covered_seq": event[0],
                "covered_event_id": covered_event_id,
                "state": state.model_dump_json(),
                "created_at": now(),
            }
            db.execute(
                f"INSERT INTO checkpoints ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
        return {**data, "state": state.model_dump()}

    def latest_checkpoint(self, scope: Scope, session_id: str | None = None) -> dict | None:
        with self.connection() as db:
            query = "SELECT * FROM checkpoints WHERE persona_id=? AND project_id=?"
            args: list = list(self.scope_args(scope))
            if session_id:
                query += " AND session_id=?"
                args.append(session_id)
            row = db.execute(query + " ORDER BY created_at DESC,id DESC LIMIT 1", args).fetchone()
            return (
                {
                    **dict(row),
                    "state": json.loads(row["state"]),
                    "trust": "host_reported_task_state",
                }
                if row
                else None
            )

    def correct(
        self, scope: Scope, memory_id: str, content: str, reason: str, valid_at: str | None = None
    ) -> dict:
        if not content.strip() or len(content) > 4000 or not reason.strip() or len(reason) > 4000:
            raise ValueError(
                "Correction content and reason must be nonempty and at most 4000 characters"
            )
        with self.connection(write=True) as db:
            row = db.execute(
                "SELECT * FROM memories WHERE id=? AND persona_id=? AND project_id=? AND status!='revoked'",
                (memory_id, *self.scope_args(scope)),
            ).fetchone()
            if not row:
                raise ValueError("Correctable memory not found in this scope")
            if row["kind"] == "emotion":
                raise ValueError(
                    "Forget an incorrect emotion and record a new assistant expression"
                )
            event_id, replacement_id = str(uuid4()), str(uuid4())
            event = {
                "id": event_id,
                **scope.model_dump(),
                "session_id": "corrections",
                "text": content + "\nCorrection reason: " + reason,
                "role": "user",
                "source": "explicit_correction",
                "category": "conversation",
                "occurred_at": now(),
                "created_at": now(),
                "state": "done",
            }
            db.execute(
                f"INSERT INTO events ({','.join(event)}) VALUES ({','.join('?' for _ in event)})",
                list(event.values()),
            )
            self._index(db, event, "event")
            data = dict(row)
            data.update(
                id=replacement_id,
                event_id=event_id,
                content=content,
                source_quote=content,
                gist=None,
                basis="user_statement",
                confidence=1.0,
                status="active",
                invalid_at=None,
                valid_at=timestamp(valid_at) if valid_at else row["valid_at"],
                created_at=now(),
            )
            db.execute(
                f"INSERT INTO memories ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
                list(data.values()),
            )
            self._index(db, data, "memory")
            db.execute("UPDATE memories SET status='revoked' WHERE id=?", (memory_id,))
            db.execute("UPDATE events SET amended=1 WHERE id=?", (row["event_id"],))
            db.execute("DELETE FROM embeddings WHERE memory_id=?", (memory_id,))
            db.execute(
                "DELETE FROM relations WHERE label!='corrects' AND (from_id=? OR to_id=?)",
                (memory_id, memory_id),
            )
            db.execute(
                "INSERT INTO relations VALUES (?,?,?)", (replacement_id, memory_id, "corrects")
            )
            # Task prose cannot be reliably scrubbed; require a fresh checkpoint after corrections.
            removed = db.execute(
                "DELETE FROM checkpoints WHERE persona_id=? AND project_id=?",
                self.scope_args(scope),
            ).rowcount
            self._timeline(db, scope)
        return {
            "replacement_id": replacement_id,
            "event_id": event_id,
            "revoked_id": memory_id,
            "invalidated_checkpoints": removed,
        }

    def forget(self, scope: Scope, record_id: str) -> dict:
        with self.connection(write=True) as db:
            row = db.execute(
                "SELECT event_id FROM memories WHERE id=? AND persona_id=? AND project_id=?",
                (record_id, *self.scope_args(scope)),
            ).fetchone()
            event_id = row[0] if row else record_id
            if not db.execute(
                "SELECT 1 FROM events WHERE id=? AND persona_id=? AND project_id=?",
                (event_id, *self.scope_args(scope)),
            ).fetchone():
                raise ValueError("Record not found in this scope")
            # A correction is derived from its predecessor. Forget the connected
            # correction lineage and all co-derived memories from those source events.
            event_ids = {event_id}
            memory_ids = set()
            while True:
                previous = (len(event_ids), len(memory_ids))
                for eid in list(event_ids):
                    memory_ids.update(
                        r[0] for r in db.execute("SELECT id FROM memories WHERE event_id=?", (eid,))
                    )
                for mid in list(memory_ids):
                    for relation in db.execute(
                        "SELECT from_id,to_id FROM relations WHERE label='corrects' AND (from_id=? OR to_id=?)",
                        (mid, mid),
                    ):
                        memory_ids.update(relation)
                for mid in list(memory_ids):
                    event_ids.add(
                        db.execute("SELECT event_id FROM memories WHERE id=?", (mid,)).fetchone()[0]
                    )
                if previous == (len(event_ids), len(memory_ids)):
                    break
            for mid in memory_ids:
                db.execute("DELETE FROM search WHERE doc_id=? AND doc_type='memory'", (mid,))
            removed = db.execute(
                "DELETE FROM checkpoints WHERE persona_id=? AND project_id=?",
                self.scope_args(scope),
            ).rowcount
            for eid in event_ids:
                db.execute("DELETE FROM search WHERE doc_id=? AND doc_type='event'", (eid,))
                db.execute("DELETE FROM events WHERE id=?", (eid,))
            # Do not revive expired facts just because their successor was forgotten.
        return {
            "deleted_event_id": event_id,
            "deleted_memory_ids": sorted(memory_ids),
            "deleted_event_ids": sorted(event_ids),
            "invalidated_checkpoints": removed,
            "note": "Independent copies and previous backups are not modified",
        }

    def vectors(self, scope: Scope, fingerprint: str) -> list[dict]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT e.* FROM embeddings e JOIN memories m ON e.memory_id=m.id WHERE m.persona_id=? AND m.project_id=? AND m.status!='revoked' AND e.fingerprint=?",
                    (*self.scope_args(scope), fingerprint),
                )
            ]

    def save_vectors(
        self,
        scope: Scope,
        fingerprint: str,
        model: str,
        version: str,
        rows: list[dict],
        vectors: list[list[float]],
        replace: bool = True,
    ) -> None:
        with self.connection(write=True) as db:
            if replace:
                db.execute(
                    "DELETE FROM embeddings WHERE memory_id IN (SELECT id FROM memories WHERE persona_id=? AND project_id=?)",
                    self.scope_args(scope),
                )
            for row, vector in zip(rows, vectors, strict=True):
                current = db.execute(
                    "SELECT content,status FROM memories WHERE id=? AND persona_id=? AND project_id=?",
                    (row["id"], *self.scope_args(scope)),
                ).fetchone()
                if (
                    current
                    and current["content"] == row["content"]
                    and current["status"] != "revoked"
                ):
                    db.execute(
                        "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?)",
                        (row["id"], fingerprint, model, version, len(vector), dumps(vector)),
                    )

    def export(self) -> dict:
        with self.connection() as db:
            db.execute("BEGIN")  # One consistent snapshot across all authoritative tables.
            tables = {
                table: [dict(r) for r in db.execute(f"SELECT * FROM {table}")] for table in TABLES
            }
        return {
            "format": "memlikehuman",
            "version": EXPORT_VERSION,
            "exported_at": now(),
            "tables": tables,
        }

    def import_archive(self, archive: dict) -> dict:
        if (
            not isinstance(archive, dict)
            or archive.get("format") != "memlikehuman"
            or archive.get("version") not in (1, 2, EXPORT_VERSION)
        ):
            raise ValueError("Unsupported archive format/version")
        # Copy before applying archive upgrades; do not mutate the caller's object.
        archive = json.loads(dumps(archive))
        tables = archive.get("tables")
        if isinstance(tables, dict) and archive["version"] < 3:
            tables.setdefault("host_cursors", [])
        if not isinstance(tables, dict) or set(tables) != set(TABLES):
            raise ValueError("Archive table set is invalid")
        if any(
            not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            for rows in tables.values()
        ):
            raise ValueError("Archive tables must be lists of objects")
        if archive["version"] == 1:
            for row in archive.get("tables", {}).get("events", []):
                row.setdefault("cues", "[]")
            for row in archive.get("tables", {}).get("memories", []):
                row.setdefault("gist", None)
        # Validate records before any writes. Additional relational invariants checked below.
        for row in tables["host_cursors"]:
            Scope(persona_id=row["persona_id"], project_id=row["project_id"])
            if (
                not isinstance(row["session_id"], str)
                or not row["session_id"]
                or len(row["session_id"]) > 200
                or type(row["offset"]) is not int
                or row["offset"] < 0
                or (
                    row["covered_event_id"] is not None
                    and not isinstance(row["covered_event_id"], str)
                )
            ):
                raise ValueError("Invalid host cursor")
        for row in tables["personas"]:
            Scope(persona_id=row["persona_id"])
            Persona.model_validate_json(row["content"])
            if not isinstance(row["version"], int) or row["version"] < 1:
                raise ValueError("Invalid persona version")
        for row in tables["events"]:
            Scope(persona_id=row["persona_id"], project_id=row["project_id"])
            EventInput.model_validate(
                {
                    "event_id": row["id"],
                    **{
                        k: (json.loads(row[k]) if k == "cues" else row[k])
                        for k in EventInput.model_fields
                        if k != "event_id"
                    },
                }
            )
            if row["state"] not in ("pending", "done") or row["amended"] not in (0, 1):
                raise ValueError("Invalid event state")
        for row in tables["memories"]:
            MemoryCandidate.model_validate(
                {k: row[k] for k in MemoryCandidate.model_fields if k != "related_memory_ids"}
            )
            if row["status"] not in ("active", "superseded", "revoked"):
                raise ValueError("Invalid memory status")
        for row in tables["checkpoints"]:
            TaskState.model_validate_json(row["state"])
        with self.connection(write=True) as db:
            if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in TABLES):
                raise ValueError(
                    "Restore requires an empty data directory; existing data is never overwritten"
                )
            for table in TABLES:
                columns = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
                for row in tables[table]:
                    if set(row) != set(columns):
                        raise ValueError(f"Invalid columns for {table}")
                    for field in ("created_at", "occurred_at", "valid_at", "invalid_at"):
                        if field in row and row[field] is not None:
                            if timestamp(row[field]) != row[field]:
                                raise ValueError("Archive timestamps must be canonical UTC")
                    db.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        [row[k] for k in columns],
                    )
            invalid = db.execute(
                "SELECT 1 FROM memories m JOIN events e ON m.event_id=e.id WHERE m.persona_id!=e.persona_id OR m.project_id!=e.project_id OR instr(e.text,m.source_quote)=0 LIMIT 1"
            ).fetchone()
            if invalid:
                raise ValueError("Archive contains invalid provenance or mixed scopes")
            for memory in tables["memories"]:
                event = db.execute(
                    "SELECT * FROM events WHERE id=?", (memory["event_id"],)
                ).fetchone()
                candidate = MemoryCandidate.model_validate(
                    {
                        k: memory[k]
                        for k in MemoryCandidate.model_fields
                        if k != "related_memory_ids"
                    }
                )
                self.validate_evidence(candidate, event)
                if memory["invalid_at"] and memory["invalid_at"] < memory["valid_at"]:
                    raise ValueError("Invalid memory validity interval")
            if db.execute(
                "SELECT 1 FROM events e WHERE NOT EXISTS (SELECT 1 FROM personas p WHERE p.persona_id=e.persona_id) LIMIT 1"
            ).fetchone():
                raise ValueError("Archive event has no persona")
            if any(row["label"] not in ("related", "corrects") for row in tables["relations"]):
                raise ValueError("Unknown relation label")
            invalid = db.execute(
                "SELECT 1 FROM relations r JOIN memories a ON a.id=r.from_id JOIN memories b ON b.id=r.to_id WHERE a.persona_id!=b.persona_id OR a.project_id!=b.project_id LIMIT 1"
            ).fetchone()
            if invalid:
                raise ValueError("Archive relations cross scopes")
            invalid = db.execute(
                "SELECT 1 FROM checkpoints c JOIN events e ON e.id=c.covered_event_id WHERE c.persona_id!=e.persona_id OR c.project_id!=e.project_id OR c.session_id!=e.session_id OR c.covered_seq!=e.seq LIMIT 1"
            ).fetchone()
            if invalid:
                raise ValueError("Archive checkpoint has invalid coverage")
            for table, kind in (("events", "event"), ("memories", "memory")):
                for row in db.execute(f"SELECT * FROM {table}").fetchall():
                    self._index(db, dict(row), kind)
        return {
            "imported": {table: len(rows) for table, rows in tables.items()},
            "indexes": "lexical rebuilt; embeddings require reindex",
        }

    def doctor(self) -> dict:
        with self.connection() as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = [tuple(r) for r in db.execute("PRAGMA foreign_key_check")]
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (*TABLES, "embeddings")
            }
            pending = db.execute("SELECT count(*) FROM events WHERE state='pending'").fetchone()[0]
        return {
            "schema_version": SCHEMA_VERSION,
            "integrity": integrity,
            "foreign_key_errors": foreign_keys,
            "counts": counts,
            "pending_extractions": pending,
        }

    def backup(self, destination: Path) -> None:
        destination = Path(destination)
        # Exclusive creation avoids overwriting a user's backup or the live database.
        with destination.open("xb"):
            pass
        destination.chmod(0o600)
        try:
            with self.connection() as source:
                target = sqlite3.connect(destination)
                try:
                    source.backup(target)
                finally:
                    target.close()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

"""Import normalized historical JSONL events locally, without any model/API calls.

This is not a universal converter for chat-platform exports. Keep source IDs,
roles, timestamps and exact text when preparing EventInput JSONL.
"""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from pydantic import ValidationError

from memlikehuman.models import EventInput, Scope
from memlikehuman.store import Store

REQUIRED = {"event_id", "text", "role", "source", "session_id", "occurred_at"}


def import_history(path: Path, data_dir: Path, scope: Scope, dry_run: bool = False) -> dict:
    count = 0
    seen = {}
    # Snapshot validated input in a temporary file, not in model context or memory.
    # A bad later line cannot cause an earlier line to be imported first.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as staged:
        with path.open(encoding="utf-8-sig") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict) or not REQUIRED <= value.keys():
                        raise ValueError("Missing explicit historical fields")
                    event = EventInput.model_validate(value)
                except (ValueError, ValidationError):
                    raise ValueError(
                        f"Invalid event at line {line_number}; check required fields, timezone and schema. No events imported."
                    ) from None
                normalized = event.model_dump_json()
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                if event.event_id in seen and seen[event.event_id] != digest:
                    raise ValueError(
                        f"Conflicting event ID at line {line_number}. No events imported."
                    )
                seen[event.event_id] = digest
                staged.write(json.dumps({"line": line_number, "event": event.model_dump()}) + "\n")
                count += 1
        if dry_run:
            return {"validated_events": count, "unique_ids": len(seen), "dry_run": True}
        store = Store(data_dir)
        staged.seek(0)
        inserted = duplicates = 0
        for line in staged:
            item = json.loads(line)
            try:
                result = store.record(scope, EventInput.model_validate(item["event"]))
            except ValueError:
                raise ValueError(
                    f"Archive conflict at input line {item['line']}. Earlier records remain committed; "
                    "inspect ID/scope/payload, then retry with the same source IDs."
                ) from None
            duplicates += int(result["duplicate"])
            inserted += int(not result["duplicate"])
        return {
            "validated_events": count,
            "inserted": inserted,
            "duplicates": duplicates,
            "model_calls": 0,
            "next_step": "Configure extraction and run scoped retry; imported originals are already durable.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--persona", default="whale")
    parser.add_argument("--project", default="companionship")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = import_history(
            args.input,
            args.data_dir,
            Scope(persona_id=args.persona, project_id=args.project),
            args.dry_run,
        )
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

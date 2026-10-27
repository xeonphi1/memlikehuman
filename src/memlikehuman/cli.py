"""Local administration. No credentials are accepted on the command line."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .archive import load_archive, write_archive
from .config import Settings, default_data_dir
from .engine import Engine
from .models import Extraction, Persona, Scope, TaskState
from .providers import ProviderError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memlikehuman", description="Local persona and memory for MCP assistants"
    )
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--persona", default="default")
    p.add_argument("--project", default="default")
    subs = p.add_subparsers(dest="command", required=True)
    for name in ("init", "serve", "doctor", "reindex"):
        subs.add_parser(name)
    subs.add_parser("host-ingest", help="Offline host bridge: one JSON request on stdin")
    config = subs.add_parser(
        "config", help="Show configuration or validate and install a JSON config"
    )
    config.add_argument("--file", type=Path)
    persona = subs.add_parser("persona", help="Show, version, or roll back core personality")
    choice = persona.add_mutually_exclusive_group()
    choice.add_argument("--file", type=Path, help="Save a new persona version from JSON")
    choice.add_argument(
        "--rollback", type=int, help="Copy a past version into a new current version"
    )
    choice.add_argument("--version", type=int, help="Read a past version")
    record = subs.add_parser("record", help="Submit one EventInput JSON file (or - for stdin)")
    record.add_argument("file")
    extract = subs.add_parser(
        "derive", help="Apply locally reviewed extraction JSON to a saved event"
    )
    extract.add_argument("event_id")
    extract.add_argument("file", type=Path)
    retry = subs.add_parser("retry", help="Retry pending extractions")
    retry.add_argument("--limit", type=int, default=100)
    recall = subs.add_parser("recall")
    recall.add_argument("query")
    recall.add_argument("--limit", type=int, default=10)
    recall.add_argument("--as-of")
    recall.add_argument("--history", action="store_true")
    recall.add_argument("--detail", choices=("auto", "gist", "detailed"), default="auto")
    recall.add_argument("--search-mode", choices=("fast", "semantic", "deep"), default="fast")
    recall.add_argument("--cue-key")
    read = subs.add_parser("read")
    read.add_argument("record_id")
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--max-chars", type=int, default=4000)
    checkpoint = subs.add_parser("checkpoint")
    checkpoint.add_argument("file", type=Path, help="TaskState JSON")
    checkpoint.add_argument("--covered-event", required=True)
    checkpoint.add_argument("--session", default="default")
    resume = subs.add_parser("resume")
    resume.add_argument("--query", default="")
    resume.add_argument("--budget", type=int, default=4096)
    resume.add_argument("--model")
    resume.add_argument("--session")
    correct = subs.add_parser("correct")
    correct.add_argument("memory_id")
    correct.add_argument("--content", required=True)
    correct.add_argument("--reason", required=True)
    correct.add_argument("--valid-at")
    forget = subs.add_parser(
        "forget", help="Delete the source event, all its memories and scoped checkpoints"
    )
    forget.add_argument("record_id")
    for name in ("export", "import", "backup", "restore"):
        command = subs.add_parser(name)
        command.add_argument("file", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .server import create_server

            create_server(args.data_dir).run(transport="stdio")
            return 0
        scope = Scope(persona_id=args.persona, project_id=args.project)
        if args.command == "host-ingest":
            from .host import ingest

            result = ingest(args.data_dir, scope, json.load(sys.stdin))
        elif args.command == "config" and args.file:
            settings = Settings.model_validate_json(args.file.read_text(encoding="utf-8"))
            settings.save(args.data_dir)
            result = {"configured": True, "restart_server": True}
        else:
            engine = Engine(args.data_dir)
            store = engine.store
            if args.command == "init":
                store.persona(args.persona)
                if not (store.data_dir / "config.json").exists():
                    engine.settings.save(store.data_dir)
                result = {
                    "data_dir": str(store.data_dir),
                    "initialized": True,
                    "network_configured": bool(engine.extractor),
                }
            elif args.command == "doctor":
                result = {
                    **store.doctor(),
                    "extraction_configured": bool(engine.extractor),
                    "embedding_configured": bool(engine.embedder),
                }
            elif args.command == "config":
                result = engine.settings.model_dump()
            elif args.command == "persona":
                if args.file:
                    result = store.set_persona(
                        args.persona,
                        Persona.model_validate_json(args.file.read_text(encoding="utf-8")),
                    )
                elif args.rollback:
                    old = store.persona(args.persona, args.rollback)
                    result = store.set_persona(args.persona, Persona.model_validate(old["content"]))
                else:
                    result = store.persona(args.persona, args.version)
            elif args.command == "record":
                text = (
                    sys.stdin.read()
                    if args.file == "-"
                    else Path(args.file).read_text(encoding="utf-8")
                )
                result = engine.record(scope, **json.loads(text))
            elif args.command == "derive":
                result = {
                    "memory_ids": store.apply_extraction(
                        scope,
                        args.event_id,
                        Extraction.model_validate_json(args.file.read_text(encoding="utf-8")),
                    )
                }
            elif args.command == "retry":
                result = engine.retry(scope, args.limit)
            elif args.command == "reindex":
                result = engine.reindex(scope)
            elif args.command == "recall":
                result = engine.recall(
                    scope,
                    args.query,
                    args.limit,
                    args.as_of,
                    args.history,
                    args.detail,
                    args.search_mode,
                    args.cue_key,
                )
            elif args.command == "read":
                result = engine.read(scope, args.record_id, args.offset, args.max_chars)
            elif args.command == "checkpoint":
                result = engine.checkpoint(
                    scope,
                    args.session,
                    args.covered_event,
                    TaskState.model_validate_json(args.file.read_text(encoding="utf-8")),
                )
            elif args.command == "resume":
                result = engine.resume(scope, args.query, args.budget, args.model, args.session)
            elif args.command == "correct":
                result = store.correct(
                    scope, args.memory_id, args.content, args.reason, args.valid_at
                )
            elif args.command == "forget":
                result = store.forget(scope, args.record_id)
            elif args.command == "export":
                write_archive(args.file, store.export())
                result = {"exported": str(args.file), "contains_secrets_config": False}
            elif args.command in ("import", "restore"):
                result = store.import_archive(load_archive(args.file))
            elif args.command == "backup":
                store.backup(args.file)
                result = {"backup": str(args.file)}
            else:
                raise ValueError("Unknown command")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except ValidationError as exc:
        print(
            json.dumps(
                {
                    "error": "Input validation failed",
                    "details": exc.errors(include_input=False, include_context=False),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except (
        ValueError,
        OSError,
        ProviderError,
        sqlite3.Error,
        KeyError,
        TypeError,
        StopIteration,
    ) as exc:
        # No tracebacks or API response dumps in normal operation.
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Portable JSON/JSONL archives, and read-only loading of SQLite backups."""

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .store import SCHEMA_VERSION, TABLES, dumps


def write_archive(path: Path, archive: dict) -> None:
    with path.open("x", encoding="utf-8") as file:
        path.chmod(0o600)
        if path.suffix == ".jsonl":
            header = {k: v for k, v in archive.items() if k != "tables"}
            file.write(dumps({"header": header}) + "\n")
            for table, rows in archive["tables"].items():
                for row in rows:
                    file.write(dumps({"table": table, "row": row}) + "\n")
        else:
            json.dump(archive, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")


def load_archive(path: Path) -> dict:
    with path.open("rb") as file:
        sqlite = file.read(16) == b"SQLite format 3\x00"
    if sqlite:
        db = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (1, SCHEMA_VERSION):
                raise ValueError("Unsupported SQLite backup version")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite backup is corrupt")
            db.execute("BEGIN")
            return {
                "format": "memlikehuman",
                "version": db.execute("PRAGMA user_version").fetchone()[0],
                "tables": {
                    table: [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
                    for table in TABLES
                },
            }
        finally:
            db.close()
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as file:
            archive = json.loads(next(file))["header"]
            archive["tables"] = {table: [] for table in TABLES}
            for line in file:
                if line.strip():
                    item = json.loads(line)
                    if item["table"] not in TABLES:
                        raise ValueError("Unknown archive table")
                    archive["tables"][item["table"]].append(item["row"])
            return archive
    return json.loads(path.read_text(encoding="utf-8"))

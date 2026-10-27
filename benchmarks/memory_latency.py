"""Reproducible synthetic retrieval benchmark; no model calls, ingestion cost excluded."""

import argparse
import json
import math
import platform
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from memlikehuman.config import Settings
from memlikehuman.engine import Engine
from memlikehuman.models import Scope
from memlikehuman.store import dumps

SCOPE = Scope(project_id="latency-benchmark")
QUERY = "蓝色风筝"


def seed(directory: Path, count: int) -> Engine:
    engine = Engine(directory, Settings())
    store = engine.store
    store.persona("default")
    with store.connection(write=True) as db:
        if db.execute("SELECT count(*) FROM events").fetchone()[0]:
            raise ValueError("Benchmark requires a fresh database directory")
        has_gist = "gist" in [r[1] for r in db.execute("PRAGMA table_info(memories)")]
        for start in range(0, count, 1000):
            events, memories, search = [], [], []
            for i in range(start, min(start + 1000, count)):
                date = (datetime(2010, 1, 1, tzinfo=UTC) + timedelta(days=i % 6000)).isoformat(
                    timespec="microseconds"
                )
                key = QUERY if i == 0 else f"主题{i % 250}"
                text = f"第{i}次日记：和朋友围绕{key}一起活动，讨论了出行计划，并记录当天的天气、路线和感想。"
                content = f"用户记录了与朋友有关的{key}经历。"
                kind = "agreement" if i % 997 == 1 else "observation"
                event_id, mid = f"event-{i}", f"memory-{i}"
                events.append(
                    (
                        event_id,
                        "default",
                        SCOPE.project_id,
                        "benchmark",
                        text,
                        "user",
                        "synthetic-benchmark",
                        "conversation",
                        date,
                        date,
                        "done",
                    )
                )
                memory = (
                    mid,
                    event_id,
                    "default",
                    SCOPE.project_id,
                    content,
                    kind,
                    "user_statement",
                    text,
                    0.9,
                    "user",
                    None,
                    date,
                    date,
                )
                if has_gist:
                    memory += (f"曾与朋友有过{key}的经历。",)
                memories.append(memory)
                # Bulk seed pre-tokenized fixtures, not the production extraction path.
                tokens = " ".join(store.index_terms(text))
                search.extend(
                    [
                        (event_id, "event", "default", SCOPE.project_id, tokens),
                        (
                            mid,
                            "memory",
                            "default",
                            SCOPE.project_id,
                            " ".join(store.index_terms(content)),
                        ),
                    ]
                )
            db.executemany(
                "INSERT INTO events(id,persona_id,project_id,session_id,text,role,source,category,occurred_at,created_at,state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                events,
            )
            columns = (
                "id,event_id,persona_id,project_id,content,kind,basis,source_quote,confidence,subject,fact_key,valid_at,created_at"
                + (",gist" if has_gist else "")
            )
            db.executemany(
                f"INSERT INTO memories({columns}) VALUES ({','.join('?' for _ in memories[0])})",
                memories,
            )
            db.executemany("INSERT INTO search VALUES (?,?,?,?,?)", search)
        db.execute("INSERT INTO search(search) VALUES ('optimize')")
    return engine


def measure(call, repeats: int):
    times, result = [], None
    for _ in range(repeats):
        start = time.perf_counter()
        result = call()
        times.append((time.perf_counter() - start) * 1000)
    ordered = sorted(times)
    return {
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "samples_ms": [round(t, 3) for t in times],
    }, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clock": datetime.now(UTC).isoformat(),
        "repeats": args.repeats,
        "scope": "local in-process memory retrieval only; no network, embedding or LLM generation; OS disk cache not flushed",
        "results": [],
    }
    for size in args.sizes:
        directory = args.root / str(size)
        engine = Engine(directory, Settings()) if args.reuse else seed(directory, size)
        # One fresh Engine + one first call; this is not an OS-cold-cache measurement.
        first, _ = measure(
            lambda directory=directory: Engine(directory, Settings()).resume(
                SCOPE, query=QUERY, token_budget=8000
            ),
            1,
        )
        recall, found = measure(lambda engine=engine: engine.recall(SCOPE, QUERY), args.repeats)
        resume, packet = measure(
            lambda engine=engine: engine.resume(SCOPE, QUERY, token_budget=8000), args.repeats
        )
        broad, broad_result = measure(
            lambda engine=engine: engine.recall(SCOPE, "朋友"), args.repeats
        )
        blank, _ = measure(
            lambda engine=engine: engine.resume(SCOPE, token_budget=8000), args.repeats
        )
        result = {
            "memories": size,
            "first_engine_resume": first,
            "selective_recall": recall,
            "query_resume": resume,
            "common_term_recall": broad,
            "blank_resume": blank,
            "found_expected": any(m["id"] == "memory-0" for m in found["memories"]),
            "common_result_count": len(broad_result["memories"]),
            "context_estimate": packet["tokens"],
            "context_bytes": len(packet["context"].encode()),
            "database_mb": round(engine.store.path.stat().st_size / 1024**2, 2),
        }
        report["results"].append(result)
        print(dumps(result), flush=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

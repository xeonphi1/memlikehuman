![MemLikeHuman](docs/assets/banner.svg)

# MemLikeHuman

**Local, portable persona and evidence-backed memory for MCP assistants.**

[中文说明](README.zh-CN.md) · [Architecture](docs/architecture.md) · [MCP contract](docs/mcp.md)

MemLikeHuman keeps personality, shared experiences, attributed facts and unfinished work outside the chat model. Restart a session or switch models, then restore a small relevant context from the same local archive.

This is a working **v0.2 developer preview**, not a claim of human consciousness or perfect recall. The implementation is inspired by [Graphiti's temporal facts and provenance](https://github.com/getzep/graphiti), with SQLite instead of a graph database. No Docker, account, or API key is required for local storage, lexical retrieval, reviewed memory derivation and restoration.

## What is implemented

- Original submitted events persist before any extraction API request. Stable event IDs make retries idempotent.
- Every derived memory points to an exact source quote. User statements, assistant expressions and inferences remain distinct.
- Single-valued facts carry validity intervals; late-arriving history does not overwrite newer facts.
- User-edited core persona versions are separate from learned habits, agreements and decaying role emotion.
- Chinese word search, source-aware ranking, explicit relations and optional semantic retrieval.
- Budgeted context packs, task checkpoints, corrections, deletion, JSON/JSONL export, SQLite backup and validated restore.
- Seven stdio MCP tools, a persona resource, a session prompt, a CLI and offline tests.

**MCP only sees submitted events.** It does not intercept chats, install lifecycle hooks, measure the host's context usage or force a model to call tools. Start/record/checkpoint calls must come from the host, its instructions or the user. A model that does not follow the calling contract may miss events. Different models may interpret the same persona differently.

## Install and try without an API

Python 3.11+ with SQLite FTS5 support. From this checkout:

```sh
uv sync --frozen --group dev
uv run python examples/demo.py --data-dir /tmp/memlikehuman-demo
uv run memlikehuman --data-dir /tmp/memlikehuman-demo --project synthetic-demo resume --budget 16000
```

The demo uses only fictional Chinese conversations and locally reviewed extraction fixtures. It demonstrates moving from Shanghai to Hangzhou, an agreement about testing code, a shared work habit, expressed emotion, an uncertain inference and a task handoff.

For everyday use:

```sh
uv run memlikehuman init
uv run memlikehuman record examples/event.json
uv run memlikehuman derive synthetic-demo-001 examples/extraction.json
uv run memlikehuman checkpoint examples/checkpoint.json --covered-event synthetic-demo-001 --session demo
uv run memlikehuman resume --budget 8000
```

Default storage: `~/.local/share/memlikehuman/`. Override with `MEMLIKEHUMAN_HOME` or global `--data-dir`. Keep real data outside this source repository. Select a persona/project with CLI global flags `--persona` / `--project` or explicit MCP arguments. A persona is shared across its projects; experiences and task state are project-scoped.

No configured extraction provider means events stay `pending` and remain readable/searchable as raw events. `derive` applies a locally reviewed extraction file; `retry` processes pending events after configuring a model.

For installation without uv: `python -m pip install .`. The optional tokenizer extra is `python -m pip install '.[tokenizer]'`. The package is prepared for distribution; no PyPI publication is implied.

## Connect an MCP client

See [examples/mcp.json](examples/mcp.json). Replace both absolute paths; Windows uses `.venv/Scripts/memlikehuman.exe`. Start with:

```sh
/path/to/checkout/.venv/bin/memlikehuman --data-dir /path/to/private/data serve
```

Enable the `start_session` prompt or add [the host calling contract](docs/mcp.md) to your client's instructions. The recommended flow is:

1. `session_resume` at conversation start, with the selected scope and budget.
2. `memory_record` after each event the user wants retained, with original text, accurate role and a stable unique ID.
3. `memory_recall` / `memory_read` when a past fact or exact source is needed.
4. `session_checkpoint` before known compression, handoff or ending work.

A tool schema alone does not ensure this flow runs. MCP server instructions and prompts are guidance, not enforced hooks. No specific chat application is required or configured by the project.

## Optional model APIs

Copy and edit [examples/config.json](examples/config.json), then:

```sh
uv run memlikehuman config --file /path/to/private/config.json
uv run memlikehuman retry
```

Set the API credential in the environment variable named by `api_key_env` before starting the CLI/server. The sample uses a DeepSeek-compatible chat endpoint; select a model available in your own account that supports JSON-object responses. Credentials are not accepted in config or command-line arguments. Restart a running server after config changes.

Extraction and embedding providers are independently configured; neither determines which model chats with you. A provider config contains `base_url`, `model`, `api_key_env`, `version` and `timeout_seconds`. Set `embedding` to such an object to enable embeddings. The server sends the submitted event to the extraction API, derived memory text to the embedding API, and retrieval queries to the embedding API. **Local storage does not mean offline inference.** With both providers `null`, no model API is called.

New automatically extracted memories are embedded when configured. After changing embedding model/version, importing an archive, applying manual derivation or correcting memories:

```sh
uv run memlikehuman reindex
```

Fingerprints include endpoint, model and explicit version. Mismatched vectors are never mixed. Incomplete/unavailable semantic retrieval reports a warning and uses lexical retrieval. The default `fast` path stays local even when an embedder is configured. Explicit `semantic` mode scans up to 2,000 recent vectors and warns about coverage; `deep` scans all eligible indexed vectors. Both semantic modes call the configured embedding API. Neither is an ANN index.

## Personality, history and maintenance

```sh
uv run memlikehuman persona
uv run memlikehuman persona --file examples/persona.json
uv run memlikehuman persona --rollback 1
uv run memlikehuman recall '住在哪里' --as-of 2026-02-01T00:00:00Z
uv run memlikehuman recall '住在哪里' --history
uv run memlikehuman doctor
uv run memlikehuman export /path/to/private/archive.jsonl
uv run memlikehuman backup /path/to/private/backup.sqlite3
uv run memlikehuman --data-dir /path/to/new/empty/directory restore /path/to/private/archive.jsonl
```

Restore accepts JSON, JSONL or a SQLite backup. It requires an empty destination and never merges or overwrites an existing archive. All authoritative records and IDs survive; lexical indexes rebuild, embeddings require `reindex`. Config and credential environment values are excluded. Events themselves may contain whatever text the host submitted; exports are not a secret-redaction service.

`correct MEMORY_ID --content ... --reason ...` preserves an audit record and revokes the old memory. Use a new event for a real change over time. `forget RECORD_ID` deletes the source event **and all memories derived from it, including its correction lineage**, related index entries and relationships. Both operations invalidate all task checkpoints in the selected scope because their prose may contain obsolete data. Older expired facts are not revived by deletion. Existing backups, separately submitted copies and provider-side logs are outside that operation. Age-based forgetting reduces rank and surfaces old episodes as gists; it never deletes the source diary. Facts, preferences, agreements and growth remain detailed. Use `memory_read` for originals.

The data is local plaintext protected by directory/file permissions where supported. This is a single-user stdio service; scopes prevent accidental mixing, not authorization against an untrusted client. A source quote proves attribution, not semantic truth. Treat imported archives and model-derived claims accordingly. [Detailed behavior and limitations](docs/architecture.md).

## Context budget

`session_resume` prioritizes the complete core persona, latest task checkpoint, agreements/growth, query-relevant memories, current expressed emotion and recent submitted events. It returns `context`, token count, counting method, `omitted`, and warnings. If even the core cannot fit, it returns `insufficient_budget` with an empty context and the required size.

When the optional `tiktoken` package recognizes the requested model, counts are exact for the **returned context string**. Tokenizer assets may need a first-use download. Without a known tokenizer/assets, a conservative UTF-8-byte estimate is reported. It is not an exact count for arbitrary models. Host instructions, tool definitions, MCP wrappers and prior conversation tokens are excluded; the caller must reserve room for them. Retrieval is selective, even when the status is `ok`.

## Test and build

```sh
uv run pytest -q
uv run ruff check src tests examples benchmarks scripts
uv run ruff format --check src tests examples benchmarks scripts
uv build
```

Offline tests include a real stdio MCP subprocess, temporal facts, attribution, scope isolation, persona rollback, context budgets, failure recovery, corrections, deletion, embeddings and archive validation. CI covers Python 3.11/3.13 on Linux, macOS and Windows; local execution is not evidence that those CI jobs have run.

To explicitly evaluate two real models using only the bundled synthetic scenario:

```sh
uv run python examples/eval_models.py \
  --provider-a /path/to/model-a.json \
  --provider-b /path/to/model-b.json \
  --output /path/to/private/evaluation.json
```

Each file is a `ProviderConfig` object (not the full settings file). This opt-in command makes billable calls to the two configured endpoints. It checks facts, agreements, task continuity and uncertainty handling. It is an acceptance probe, not a benchmark or proof of identical personality; inspect answers for tone and naturalness. No live-model results are bundled or claimed.

## Open source

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE) and [CONTRIBUTING.md](CONTRIBUTING.md). Examples are synthetic and the neutral persona is original. Future work: host-specific lifecycle adapters, optional Graphiti backend, evaluation datasets and more efficient vector indexes. No GitHub or PyPI publishing happens automatically.

## Fading, cues and performance

Version 0.2 presents old episodes as source-linked gists without deleting the diary. Stable facts, preferences, agreements and growth remain detailed. `memory_read` retrieves originals; photo/text cue keys can retrieve linked experiences without image recognition. See the [performance report](docs/performance.md) for reproducible synthetic benchmarks, raw samples and limits. At 100,000 memories, selective local recall measured 5.36 ms median and restoration 37.48 ms; common-word recall was 83.60 ms. These exclude network, model generation and process startup.

## Star trend

![Daily real star-count snapshots](docs/assets/star-history.svg)

The [Star trend workflow](.github/workflows/stars.yml) records actual daily GitHub counts using the built-in Actions token. History begins at the first successful sample and can decline when stars are removed. No synthetic history or third-party chart credentials are used.

## Import existing conversations

The [historical migration workflow (Chinese)](docs/history-migration.zh-CN.md) explains how to preserve existing conversations before switching models. Normalize your actual platform export to EventInput JSONL, then run [import_chat_history.py](examples/import_chat_history.py) with `--dry-run` before importing. The example preserves raw events without API calls and supports retries with stable IDs; extraction is a separate scoped `retry` step. It does not convert arbitrary DeepSeek, ChatGPT or Claude exports. The CLI `import` command restores MemLikeHuman archives, a different format.

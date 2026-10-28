<div align="center">

![MemLikeHuman](docs/assets/banner.svg)

**A new model. The same continuing story.**

Local memory · Portable persona · Offline memory dashboard

[![CI](https://github.com/xeonphi1/memlikehuman/actions/workflows/ci.yml/badge.svg)](https://github.com/xeonphi1/memlikehuman/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache--2.0-5b8c85)](LICENSE)

[中文首页](README.md) · [Quick start](#quick-start) · [Dashboard](#offline-memory-dashboard) · [CLI reference](docs/cli.md)

</div>

MemLikeHuman keeps persona, shared experiences, attributed memories and unfinished work on your computer. Models retrieve relevant context through MCP; you can inspect, edit and transfer memories in a local browser dashboard.

**Python + SQLite. No Docker, graph database, account or API key is required for local management and keyword retrieval.** Extraction and embedding providers are optional and configured separately.

## Quick start

Requires Python 3.11+. Using [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
git clone https://github.com/xeonphi1/memlikehuman.git
cd memlikehuman
uv sync --frozen
uv run memlikehuman init
uv run memlikehuman web
```

The last command starts a loopback-only service and opens its authenticated URL in your browser. After dependencies are installed, the dashboard works offline: no CDN, remote fonts, telemetry or model API requests.

Data defaults to `~/.local/share/memlikehuman/`, outside the repository. Open an existing library with:

```sh
uv run memlikehuman --data-dir /ABSOLUTE/PATH/private-memory web
```

Windows paths work too. Without uv, install with `python -m pip install .` in a virtual environment and run `memlikehuman web`. The Python package is not currently published on PyPI.

## Offline memory dashboard

![Memory dashboard using synthetic data](docs/assets/dashboard.png)

Select **library → persona/project → memory layer**. The current interface is in Chinese; the workflow is documented in [English](docs/dashboard.md).

| Layer | Available operations |
|---|---|
| Core persona | Edit traits, values, style and boundaries; create versions and roll back |
| Original events | Add records, inspect sources, save reference revisions, derive memories manually |
| Facts, preferences, agreements, growth, episodes, observations | Edit content, gist and confidence while preserving source and attribution |
| Expressed emotions | Edit expression, valence and arousal independently of persona |
| Work checkpoints | Save goals, completed work, pending work, constraints and the next step |

**Import** MemLikeHuman JSON/JSONL archives or SQLite backups into separate libraries without overwriting the current one. **Export** the entire selected library, including every persona and project. Browser uploads are limited to 64 MiB; use the CLI for larger files.

Edits to derived memories create revisions; original events remain intact. User statements, assistant expressions and inferences keep their existing attribution. Manual derivation validates exact source quotes without an API. Corrected memories invalidate scoped checkpoints so stale task summaries are not reused.

The dashboard writes directly to the selected SQLite library. To connect an imported library to MCP, change the MCP server's `--data-dir` to the directory shown at the bottom of the page. [Dashboard guide →](docs/dashboard.md)

## DeepSeek Harness and Whale

Install the Python core first, then the GitHub-distributed DSH bundle:

```sh
dsh plugin --profile web add github:xeonphi1/memlikehuman
```

Follow the [installation guide](docs/dsh-install.md) to configure paths, persona and project. The adapter targets **Harness 0.2.1-rc.3**. It captures visible conversation text and waits for durable handoff before compaction proceeds. It retries from a persistent cursor after restart. Retrieval and new-session resume still use MCP.

The bundle is distributed from GitHub; it is not published on npm and is not a one-click in-app marketplace installation. For tool-only integrations, see the [MCP setup guide](docs/deepseek-harness.md) and [generic configuration](examples/mcp.json).

Whale refers to the community project [linsport/dsh-whale-persona](https://github.com/linsport/dsh-whale-persona). This project is independent and does not bundle its persona text or artwork. Tests exercise official packages, real lifecycle events and stdio; actual Harness UI and paid-model end-to-end behavior remain unverified.

## Existing conversations

Export original transcripts, normalize them to event JSONL, import offline, derive memories manually or in model-backed batches, then verify persona and task continuity. Use the [migration workflow](docs/history-migration.zh-CN.md) and [resumable importer](examples/import_chat_history.py).

Platform chat exports are not MemLikeHuman archives. The dashboard does not automatically parse arbitrary DeepSeek, ChatGPT or Claude export formats. It cannot recover original messages that are no longer available.

## Selective recall and gradual fading

Original events remain available as a diary. Episodes normally become gist views after 180 days, with broader time labels after 730 days; facts, preferences and agreements remain detailed. Role emotion decays without replacing the core persona.

Restore packs use bounded retrieval and caller-supplied budgets. For 100,000 synthetic Chinese memories, the measured in-process medians were 5.36 ms for a selective query and 37.48 ms for query-based resume; a common term took 83.60 ms. These figures exclude the dashboard, subprocess startup, network and model generation, and do not measure recall accuracy. [Benchmark details →](docs/performance.md)

## Data and trust

- Original events commit before extraction. Stable IDs support retry without duplication.
- The dashboard never constructs an extraction or embedding provider. Separately configured CLI/MCP operations may send content to your chosen provider.
- Local files are plaintext. Exported archives exclude configuration secrets, but transcripts can contain private information.
- The local dashboard uses an ephemeral access token, loopback binding, Host/Origin validation and a restrictive content policy. It is a trusted single-user tool, not an Internet-facing multi-user application.
- Generic MCP sees submitted events only. Automatic capture needs a host adapter. Different models may interpret the same persona differently.

This remains a developer preview, not a claim of human consciousness or perfect recall.

## Documentation and development

| Task | Documentation |
|---|---|
| Manage memories visually | [Dashboard](docs/dashboard.md) / [中文](docs/dashboard.zh-CN.md) |
| Configure API providers, backup and restore | [CLI reference](docs/cli.md) / [中文](docs/cli.zh-CN.md) |
| Integrate models | [MCP contract](docs/mcp.md) / [Harness setup](docs/deepseek-harness.md) |
| Understand persistence and retrieval | [Architecture](docs/architecture.md) / [Performance](docs/performance.md) |
| Contribute | [Contribution guide](CONTRIBUTING.md) |

```sh
uv sync --frozen --group dev --extra tokenizer
uv run pytest -q
uv run ruff check src tests examples benchmarks scripts
uv run ruff format --check src tests examples benchmarks scripts
uv build
```

CI covers Python 3.11/3.13 on Linux, macOS and Windows, plus the DSH adapter. Dashboard tests cover real loopback HTTP, archive transfer, attribution, revision history and isolation.

## Star trend

[![Daily real star snapshots](docs/assets/star-history.svg)](https://github.com/xeonphi1/memlikehuman/stargazers)

The [workflow](.github/workflows/stars.yml) records actual daily totals from its first successful sample. No fabricated earlier history or personal token is required.

---

Apache-2.0 · [LICENSE](LICENSE) · [NOTICE](NOTICE). Inspired by [Graphiti](https://github.com/getzep/graphiti)'s temporal provenance and relationship design; no Graphiti dependency or copied implementation.

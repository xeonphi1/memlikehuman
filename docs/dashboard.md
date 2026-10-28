# Offline memory dashboard

[Home](../README.en.md) · [中文说明](dashboard.zh-CN.md) · [CLI reference](cli.md)

## Run

```sh
memlikehuman --data-dir /ABSOLUTE/PATH/private-memory web
```

The Python service binds only to `127.0.0.1`, chooses an available port and opens a URL with an ephemeral access token. Use `--no-browser` to print the URL without opening it, or `--port 8765` for a fixed port. Stop with Ctrl+C. Old tokens expire when the process restarts.

This is a local Python service with bundled static assets, not a standalone HTML file. Installing dependencies requires Internet access; using the installed dashboard does not. No extraction/embedding providers are constructed, even if API configuration exists. No Node/npm installation is required to run the dashboard.

## Workflow and labels

The UI currently uses Chinese labels:

| Label | Meaning |
|---|---|
| 记忆库 / 人格／项目 | Library / persona and project |
| 导入记忆包 | Import an archive as a separate library |
| 导出与备份 | Export the entire selected library |
| 保存新版本 | Save a revision, preserving the prior record |
| 从这段原文新增提炼记忆 | Derive a reviewed memory from this original event |
| 删除及关联记忆 | Delete the source and associated derived memories |

Select a library and scope, choose a memory layer, and open a record. Lists are paginated in groups of 20, with bounded previews and on-demand details. Layer search is local substring matching, not semantic retrieval. Counts and substring queries may take longer on large libraries.

## Editing rules

- **Persona:** edit name, traits, values, style and boundaries. Lists use one item per line. Saving creates a version; restoring an old version creates a new current version. Persona is shared across projects with the same persona ID.
- **Original events:** add events or save a reference revision. Original text is not overwritten. Reference revisions do not automatically change existing derived memories and cannot be promoted into shared historical experiences.
- **Facts, preferences, agreements, growth, episodes, observations:** revise content, gist and confidence. Existing sources, exact quotes, attribution, kind and validity dates remain intact. Actual changes over time require a new dated source and the CLI extraction fields for temporal fact keys.
- **Emotions:** additionally edit valence and arousal. The record still refers to the original assistant expression and retains its original time for decay. Core persona is unaffected.
- **Checkpoints:** save goals, completed work, pending tasks, constraints and next step. Coverage must reference an event in the same scope and session. Memory edits and deletion invalidate scoped checkpoints; recreate them after review.
- **Manual derivation:** choose a type, content, exact quote and attribution. Quotes must exist in the original text, and role constraints still apply. The source is marked manually processed; additional manual memories can still be added.

## Import, export and model connection

Import MemLikeHuman versioned JSON/JSONL archives or SQLite backups, up to **64 MiB**. Platform chat exports and plain event JSONL are different formats; use the [history importer](../examples/import_chat_history.py) first. Import validates the package and creates a separate library; it never overwrites or merges the active database.

Imported libraries live under `<main-data-dir>/dashboard-libraries/<id>/`. The page footer shows the actual path. Point MCP/Harness `--data-dir` there and restart to use that imported library. Existing MCP connections to the main library can see subsequent dashboard saves through fresh reads.

Exports include **all personas and projects in the selected library**, regardless of filters. JSON/JSONL include persona versions, originals, derived memories, relationships, emotions, checkpoints and host capture cursors, but exclude configuration secrets and rebuildable indexes. SQLite backups include database indexes. Exporting the main library does not include separate imported libraries; export each independently. Large exports are assembled in memory: prefer CLI backup for very large datasets.

## Deletion and security

Deletion follows the existing `memory_forget` cascade: remove the source event, co-derived memories and connected correction lineage, clear indexes, and invalidate scoped checkpoints. The UI asks for confirmation because this deletion is permanent. Independent revision copies, other libraries, earlier exports and provider logs remain untouched.

The server validates an ephemeral token, Host and Origin. It serves a restrictive content policy and renders memory text without HTML interpretation. Local files remain plaintext. Do not publish the service through a proxy or tunnel; this is a trusted single-user tool, not a network authentication system.

If edits do not appear in model responses, check the data directory and scope, then call recall/resume again. Already loaded model context is not rewritten automatically. Edited memories have no new embedding until you separately run the configured `reindex` operation, which can make provider requests.

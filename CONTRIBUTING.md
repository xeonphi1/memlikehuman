# Contributing

MemLikeHuman is an early single-user, local-first memory service. Please keep changes small and demonstrate observable behavior with synthetic data.

## Development

```sh
uv sync --frozen --group dev --extra tokenizer
uv run pytest -q
uv run ruff check src tests examples benchmarks scripts
uv run ruff format --check src tests examples benchmarks scripts
uv build
```

Do not commit real conversations, credentials, databases, backups, generated exports or private evaluation responses. Defaults keep runtime data outside the source tree. Tests must not call paid model APIs; use httpx mock transports. The optional real-model probe is explicitly invoked by the operator.

Preserve these invariants: original event commits before network calls; facts have sources; role/inference distinctions survive export; scoped queries never mix projects/personas; core persona is versioned and cannot be changed by model tools; deletion cleans derived state; context limits never silently truncate the core.

Schema changes require a versioned migration and an upgrade test. Archive changes require an explicit format-version policy and round-trip tests. Model/provider additions must document data egress and error redaction. Please include the rationale and tests in pull requests. Contributions are licensed under Apache-2.0.

## Publication

Source repository: https://github.com/xeonphi1/memlikehuman. Build artifacts live in `dist/` and are ignored. Keep release files limited to source, docs, code-generated visuals and synthetic fixtures; never include a private memory database or provider configuration. PyPI publication is a separate step and has not been configured.

The Star trend workflow writes only public daily star counts and a generated SVG. It uses the repository's automatic Actions token. Forks start their own snapshot history; no personal token or third-party chart credential is needed. Branch protection or restricted Actions permissions may require an owner to run the script and commit the output manually.

# rowlab

AI labeling, filtering, verification and analysis for tabular data.

Load a CSV, JSON, JSONL or Parquet file from disk, a URL or S3, explore it, compose a per-row prompt from its
columns, and run it through a decision model (yes/no, choice, score — e.g. TypeSafe Jev) or a classic LLM:
classify rows, extract typed fields, or write new text such as summaries and translations. Get the
original data back with new columns added, as a new dataset you can filter and label again.

**Status:** pre-alpha. Datasets can be loaded, explored, labeled and exported; every run makes a new
dataset.
Domain: [rowlab.dev](https://rowlab.dev)

## Principles

- **Data in → process → data out.** Your storage stays the source of truth; rowlab is a workspace.
- **API first.** The web UI uses only the public API — anything the UI can do, an agent can do.
- **Easy to run.** One process, one SQLite file, one data folder: `uvx rowlab`.
- **Paid calls are never repeated.** Per-row results are stored as they complete, and responses are cached
  by `hash(model + params + questions + rendered prompt)`.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the milestones to MVP.

## Stack

- `server/` — Python: FastAPI, Pydantic, DuckDB, SQLite (`sqlite3`), packaged with `uv`
- `web/` — Next.js static export, TanStack Table, TipTap, shadcn; API client generated from `openapi.json`
- The MCP server will live in the same Python package and call the same `core/` logic as the API

## Development

Requires [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```sh
cd server && uv sync && cd ../web && pnpm install && cd ..
make dev          # API on :8000 (docs at /docs), web on :3000
make test         # server tests (SQLite, datasets on disk)
make test-hosted  # the same on Postgres (ROWLAB_TEST_DATABASE_URL) with datasets on S3
make lint         # ruff, eslint, tsc
make gen-client   # after any API change: regenerate openapi.json + web/src/lib/api/schema.ts
make build        # web static export bundled into the Python wheel → server/dist/
```

Model calls go through [OpenRouter](https://openrouter.ai): set `OPENROUTER_API_KEY`, or save a key from
the UI (stored in the data folder, never returned by the API).

Run the built package as a user would: `uvx --from server/dist/rowlab-*.whl rowlab serve`.

rowlab keeps its state (SQLite database, ingested datasets as Parquet) in `~/.rowlab`. Set
`ROWLAB_DATA_DIR` to use another folder.

## Configuration

rowlab runs in one of two modes. `local` (the default) is one person on their own machine: no sign-in,
and files on the server's disk can be read and written. `hosted` is a shared server: the protections it
needs are on, and sign-in (coming). Everything else is configuration, from environment variables:

| Variable | Default | |
|---|---|---|
| `ROWLAB_MODE` | `local` | `local` or `hosted` |
| `ROWLAB_DATA_DIR` | `~/.rowlab` | local state: temporary files, and the SQLite database by default |
| `ROWLAB_DATABASE_URL` | a SQLite file in the data folder | or `postgresql://…` |
| `ROWLAB_STORAGE_URL` | the data folder's `datasets` | or `s3://bucket/prefix`, with the usual `AWS_*` credentials (`AWS_ENDPOINT_URL` for MinIO) |
| `ROWLAB_SERVER_FILES` | on when `local`, off when `hosted` | whether datasets can be added from, and exported to, paths on the server |
| `OPENROUTER_API_KEY` | | or save it in Settings |

Postgres and S3 need `pip install "rowlab[hosted]"`. With Postgres, the API and the runners that process
runs can be separate processes, and several runners share the queue:

```sh
rowlab serve --no-runner   # the API and UI
rowlab runner              # processes runs; start as many as you like
```

`rowlab serve` alone runs both, which is all a local setup needs.

## Non-goals

- Dataset versioning or branching — use git, DVC or your data lake. A dataset made by a run only records
  which dataset it came from and how, shown as a tree in the dataset list.
- Being a system of record or long-term storage
- A general-purpose BI or spreadsheet tool

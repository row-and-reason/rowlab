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
and files on the server's disk can be read and written. `hosted` is a shared server: people sign in with
[WorkOS](https://workos.com), everything belongs to an organisation, and the protections a shared server
needs are on. Everything else is configuration, from environment variables:

| Variable | Default | |
|---|---|---|
| `ROWLAB_MODE` | `local` | `local` or `hosted` |
| `ROWLAB_DATA_DIR` | `~/.rowlab` | local state: temporary files, and the SQLite database by default |
| `ROWLAB_DATABASE_URL` | a SQLite file in the data folder | or `postgresql://…` |
| `ROWLAB_STORAGE_URL` | the data folder's `datasets` | or `s3://bucket/prefix`, with the usual `AWS_*` credentials (`AWS_ENDPOINT_URL` for MinIO) |
| `ROWLAB_SERVER_FILES` | on when `local`, off when `hosted` | whether datasets can be added from, and exported to, the server's own files: paths on its disk, and buckets its AWS credentials reach |
| `ROWLAB_PRIVATE_URLS` | on when `local`, off when `hosted` | whether web sources and S3 endpoints can be private addresses (localhost, the local network, cloud metadata) |
| `OPENROUTER_API_KEY` | | or save it in Settings |
| `ROWLAB_URL` | | `hosted` only: where people reach rowlab, e.g. `https://rowlab.example.com` |
| `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, `WORKOS_AUTHKIT_DOMAIN` | | `hosted` only: the WorkOS project people sign in with, and its AuthKit domain (`https://….authkit.app`) |
| `ROWLAB_SECRET_KEY` | | encrypts saved keys (OpenRouter, S3); any long random string. Required when `hosted` |

Limits, the same in both modes. They are modest, so a shared server stays up; raise them for bigger
data:

| Variable | Default | |
|---|---|---|
| `ROWLAB_DUCKDB_MEMORY` | `1GB` | memory per DuckDB connection; past it, DuckDB spills to disk |
| `ROWLAB_DUCKDB_TEMP` | `10GB` | how much DuckDB may spill to disk |
| `ROWLAB_DUCKDB_THREADS` | `2` | threads per query |
| `ROWLAB_QUERY_SECONDS` | `30` | time per query; adding and exporting a dataset get ten times as long |
| `ROWLAB_MAX_FILE` | `1GB` | the largest file to upload, download or read from S3 |
| `ROWLAB_RUNS_PER_ORG` | `2` | runs an organisation has going at once; the rest wait their turn |
| `ROWLAB_RUN_WAIT_SECONDS` | `300` | a run waiting this long goes next; otherwise the run with least left does |

Postgres, S3 and WorkOS need `pip install "rowlab[hosted]"`. In the WorkOS project, add
`<ROWLAB_URL>/auth/callback` as a redirect URI and `<ROWLAB_URL>/` as the sign-out redirect. The first
person to sign in gets an organisation of their own as its admin, and invites the others in Settings →
Members. Scripts use an API key from Settings → API keys: `Authorization: Bearer rl_…`. Rate limits
per client aren't rowlab's job: put them in front of it (e.g. Cloudflare). Nor, fully, is keeping
requests off private addresses: rowlab refuses them, but DuckDB follows redirects from S3 endpoints, so
a hosted setup should also block private addresses (other than its database and storage) in its network.

With Postgres, the API and the runners that process runs can be separate processes, and several runners
share the queue, taking turns a chunk of 500 rows at a time:

```sh
rowlab serve --no-runner   # the API and UI
rowlab runner              # processes runs; start as many as you like
```

`rowlab serve` alone runs both, which is all a local setup needs.

## MCP

Agents work with rowlab over MCP: the same data work as the API (list and add datasets, query with SQL,
compare columns, preview and start runs, export), with instructions that teach the workflow. The server
is at `/mcp` on a running rowlab, or `rowlab mcp` over stdio. Locally nothing signs in; hosted, the
client signs in with WorkOS when it first connects, or sends an API key from Settings → API keys.

```sh
claude mcp add --transport http rowlab http://localhost:8000/mcp          # Claude Code
claude mcp add --transport http rowlab https://rowlab.example.com/mcp --header "Authorization: Bearer rl_…"
codex mcp add rowlab --url http://localhost:8000/mcp                       # Codex
```

Cursor: `.cursor/mcp.json` with `{"mcpServers": {"rowlab": {"url": "http://localhost:8000/mcp"}}}`
(add `"headers": {"Authorization": "Bearer rl_…"}` for a hosted rowlab). A client that wants a command
rather than a URL gets `uvx rowlab mcp`.

Hosted, WorkOS needs `WORKOS_AUTHKIT_DOMAIN` set and, under Connect → Configuration → MCP Auth,
Dynamic Client Registration on and `<ROWLAB_URL>/mcp` listed as a resource indicator, so clients can
sign in on their own and get tokens that are for rowlab alone. Someone connecting over MCP must have
signed in to rowlab in a browser once, which is where they join their organisation.

The skills in [agent-skills](https://github.com/row-and-reason/agent-skills) teach agents how to label
well with it: `npx skills add row-and-reason/agent-skills --skill rowlab-labeling`, and
`rowlab-model-selection` and `rowlab-labeling-at-scale`.

## Non-goals

- Dataset versioning or branching — use git, DVC or your data lake. A dataset made by a run only records
  which dataset it came from and how, shown as a tree in the dataset list.
- Being a system of record or long-term storage
- A general-purpose BI or spreadsheet tool

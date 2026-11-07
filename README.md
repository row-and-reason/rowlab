# rowlab

Ask a question of every row. rowlab labels, extracts and rewrites tabular data with AI: add a CSV,
JSON, JSONL or Parquet file, write the question from the row's own columns, try it on twenty rows,
then run it on a million. Every run makes a new dataset with the answers added; your data is never
changed in place.

Open source (Apache-2.0). Runs on your laptop, on your own servers, or hosted at
[app.rowlab.dev](https://app.rowlab.dev). Docs at [docs.rowlab.dev](https://docs.rowlab.dev).

**Status:** pre-alpha, on its way to a first release.

## Quickstart

```sh
uvx rowlab
```

Open [localhost:8000](http://localhost:8000), paste an [OpenRouter](https://openrouter.ai) key in
Settings (or set `OPENROUTER_API_KEY`), add a file, and ask it something. State lives in
`~/.rowlab`.

Or with Docker: `docker compose up` in this repository runs it with Postgres and S3 storage, the way
a shared server does ([more](https://docs.rowlab.dev/self-host#with-docker)).

- [Get started](https://docs.rowlab.dev/get-started), then the
  [guides](https://docs.rowlab.dev/guides/labeling).
- [Configuration](https://docs.rowlab.dev/self-host/configuration) and
  [a shared server](https://docs.rowlab.dev/self-host/hosted): Postgres, S3, sign-in with WorkOS,
  limits.
- [MCP](https://docs.rowlab.dev/agents/mcp) for agents, with
  [skills](https://github.com/row-and-reason/agent-skills) that teach them to label well:
  `claude mcp add --transport http rowlab http://localhost:8000/mcp`.
- [API reference](https://docs.rowlab.dev/api/): the web app uses only the public API, so anything
  it can do, a script can do.

## Compare columns

The **Compare** tab uses its own analysis workspace: select a model or pair in the ranking to inspect
its confusion table, label metrics, value distribution or missing-answer coverage. Numeric pairs show
signed differences, mean absolute difference, error quantiles and a histogram with matched/different
segments driven by the same comparison rule. All calculations and
exact row filters come from the comparison API, also available through MCP `columns_compare`.
Columns, reference, matching rules, selected pair and detail view are saved in the URL.
Click a count or histogram bar to inspect those rows; this replaces the Rows tab's search, filters and
limit and brings compared columns to the front. Returning to Rows restores the run composer. In Compare, ⌘↵ inspects differing rows; ⌘K also opens
matching rules and column selection.

Matching is exact by default. Text columns support independent `ignore_case` (Unicode lowercase, not
full case folding) and `trim_whitespace` (ASCII whitespace) rules. These normalize comparison groups,
metrics and row filters, never source data. Empty strings remain answers; NULLs are missing.
Numeric/date tolerance must be finite and nonnegative; dates compare only with dates, in days.
Positive floating tolerances allow four machine-epsilon units scaled to the operand magnitudes for
subtraction roundoff; zero tolerance remains exact. Numeric diagnostics exclude non-finite pairs and
report the excluded count. Reference metrics exclude missing pairs; macro F1 and balanced accuracy
use all labels even when the displayed label table is truncated. Completeness metadata reports omitted
groups and counts. API/MCP callers may scope a comparison with a SELECT query; returned row predicates
apply to that same query. The UI compares the whole dataset.


## Principles

- **Data in → process → data out.** Your storage stays the source of truth; rowlab is a workspace.
- **API first.** The web UI uses only the public API — anything the UI can do, an agent can do.
- **Easy to run.** One process, one SQLite file, one data folder: `uvx rowlab`.
- **Paid calls are never repeated.** Per-row results are stored as they complete, and responses are
  cached by `hash(model + params + questions + rendered prompt)`.


## Development

Requires [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/) and Node 24.

```sh
cd server && uv sync && cd ../web && pnpm install && cd ..
make dev          # API on :8000 (docs at /docs), web on :3000
make test         # server tests (SQLite, datasets on disk)
make test-hosted  # the same on Postgres (ROWLAB_TEST_DATABASE_URL) with datasets on S3
make lint         # ruff, eslint, tsc
make gen-client   # after any API change: regenerate openapi.json + web/src/lib/api/schema.ts
make build        # web static export bundled into the Python wheel → server/dist/
make site         # the website and the docs → site/*/dist
```

Run the built package as a user would: `uvx --from server/dist/rowlab-*.whl rowlab serve`.

- `server/` — Python: FastAPI, Pydantic, DuckDB, SQLite or Postgres, packaged with `uv`. The MCP
  server lives in the same package and calls the same `core/` logic as the API.
- `web/` — Next.js static export, TanStack Table, TipTap, shadcn; API client generated from
  `openapi.json`
- `site/` — the website and the docs (Astro, Starlight); see [site/README.md](site/README.md)

[ROADMAP.md](ROADMAP.md) has the milestones to MVP, [AGENTS.md](AGENTS.md) how to work in this repo,
and [CONTRIBUTING.md](CONTRIBUTING.md) how to send a change.

## Non-goals

- Dataset versioning or branching — use git, DVC or your data lake. A dataset made by a run only
  records which dataset it came from and how, shown as a tree in the dataset list.
- Being a system of record or long-term storage
- A general-purpose BI or spreadsheet tool

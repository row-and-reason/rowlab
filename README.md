# rowlab

Ask a question of every row. rowlab labels, extracts and rewrites tabular data with AI: add a CSV,
JSON, JSONL or Parquet file, write the question from the row's own columns, try it on twenty rows,
then run it on a million. Every run makes a new dataset of the selected rows with the answers added;
your data is never changed in place.

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
  [one Rowlab skill](https://github.com/row-and-reason/agent-skills/tree/main/skills/rowlab) for
  labeling, comparison and scaling:
  `claude mcp add --transport http rowlab http://localhost:8000/mcp`.
- [API reference](https://docs.rowlab.dev/api/): the web app uses only the public API, so anything
  it can do, a script can do.

## Settings and storage

**Storage** shows current recorded dataset size for the whole organization, separately from external
S3 connections. **Usage** repeats this current figure above the monthly activity breakdown. Members
see their own run activity, but storage always covers the organization. The figure sums registered
dataset sizes; it is not a live disk inventory and excludes external bucket contents. Organization
storage quotas and billing are not enforced yet; **Plans** is an explicitly labeled pricing preview.

## Dataset origin

The **Origin** tab records where a dataset came from. For runs it shows selected rows, processed model
calls, failed calls, spend, output columns, and each task's models and prompt. Counts distinguish dataset
rows from the rows selected for the run. The scope SQL remains available below the recipe. Imported
files show their source and import time. **Edit and run again** loads the recorded settings onto the
parent dataset without starting a run; replacing an existing draft requires confirmation.

## Compare columns

The **Compare** tab keeps the three-pane workspace and labeling tools visible. Its summary table
shows every model against the reference (or every pair without one). Select a row to inspect the
confusion table with precision and recall margins, or a numeric difference histogram. Key metrics
and missing-answer links stay visible; model-to-model pairs sit in one fold when a reference is set.
Matrix totals count paired rows, not all-row value distributions. Numeric pairs show mean absolute
difference, bias, error quantiles and matched/different histogram segments.
All calculations and exact row filters come from the comparison API, also available through MCP
`columns_compare`. Columns, reference, matching rules and selected pair are saved in the URL.
Click a count or histogram bar to inspect those rows; this replaces the Rows tab's search, filters
and limit and brings compared columns to the front. In Compare, ⌘↵ inspects differing rows; ⌘K also
opens matching rules and column selection.

Matching is exact by default. Text columns support independent `ignore_case` (Unicode lowercase, not
full case folding) and `trim_whitespace` (ASCII whitespace) rules. These normalize comparison groups,
metrics and row filters, never source data. Empty strings remain answers; NULLs are missing.
Numeric/date tolerance must be finite and nonnegative; dates compare only with dates, in days.
Positive floating tolerances allow four machine-epsilon units scaled to the operand magnitudes for
subtraction roundoff; zero tolerance remains exact. Numeric diagnostics exclude non-finite pairs and
report the excluded count. Reference metrics exclude missing pairs; macro F1 and balanced accuracy
use all labels even when the displayed confusion table is truncated. Completeness metadata reports omitted
groups and counts. API/MCP callers may scope a comparison with a SELECT query; returned row predicates
apply to that same query. The UI compares the whole dataset.


## Principles

- **Data in → process → data out.** Your storage stays the source of truth; rowlab is a workspace.
- **API first.** The web UI uses only the public API — anything the UI can do, an agent can do.
- **Easy to run.** One process, one SQLite file, one data folder: `uvx rowlab`.
- **Paid calls are never repeated.** Per-row results are stored as they complete, and model replies are
  kept with the datasets they made, by `hash(model + params + questions + rendered prompt)`: a run
  reuses those of the done runs in its dataset tree. The database holds only the replies of chunks under way.


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
make smoke        # end to end against that wheel (make smoke-compose: against docker-compose.yml)
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

## Agent setup and dataset names

Open **Settings → Connect agents** for copyable Codex and Claude Code commands, including sign-in
on hosted servers and installation of the single Rowlab skill. The commands use this server's URL.
Rename imports or run results from the dataset menu, the command palette, or MCP `dataset_rename`.
Names are display labels; IDs and lineage stay unchanged.

MCP `models_list` returns 20 models by default with `total` and `next_offset`; filter by `search` or
`kind`, or page with `offset` and `limit` (up to 100). `columns_compare` defaults to a compact summary
with per-class precision and recall; use `detail="full"` for distributions and all drill-down filters.
New sampled runs contain only selected rows, preserving source `__row_id` values. Existing result
datasets keep their stored rows; rerun from the source to create a result using the new behavior.

### Label manually

Define the same task and select **Label manually** instead of **Label with an LLM**. The new
run opens its selected rows with the rendered prompt and answer choices. Choosing an answer
saves it and advances to the next row. For text, press Enter to submit; Shift+Enter adds a
new line. You can return later to continue. **Finish labeling** locks the output dataset;
unanswered cells remain null. Compare, query, export and subsequent runs work as usual.

Manual labels use the task's output name without a model suffix, probability or status column.
All task types are supported; structured extraction accepts JSON matching the task's fields.
No model is called and no provider key is required.

The API uses `POST /v1/datasets/{id}/runs` with `method: "manual"`,
`PUT /v1/runs/{id}/tasks/{task_id}/answers` with
`{"answers": [{"row_id": 0, "value": true}]}`, and `POST /v1/runs/{id}/finish`.
Null clears an answer. MCP exposes the same flow as `run_start(method="manual")`,
`run_answers`, and `run_finish`.

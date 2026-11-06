# Roadmap to MVP

**Today:** milestones 1 and 2 are done. CSV, TSV, JSON, JSONL and Parquet files can be uploaded, or loaded
by local path or public http(s) URL (pulled forward from milestone 7), and explored with server-side search,
filters, sort and paging; 1M rows ingest in under a second and every page query returns in about 0.1 s.
A prompt template can be composed from columns with a live per-row preview and token estimates.
Milestone 3 is in progress: a job runs several tasks (yes/no, pick one, pick any, scale), each with one or
more decision models or LLMs, on the rows its scope picks (search, filters, sort, limit), with costs per
task and model; LLM-only answer types are next.
`rowlab serve` serves the API and UI on one port, and `make build` produces a wheel with the UI bundled.

**MVP:** a local tool that takes a CSV/JSON/JSONL/Parquet file from disk, HTTP or S3, runs a configured
labeling or extraction job over its rows with any OpenRouter decision model or LLM, can be stopped and
resumed without paying twice, shows all work and its live progress, and writes the result to disk or S3.

## Terms

- **Dataset** — an ingested file, or the result of a run. Stored once as Parquet with a stable `__row_id`;
  never modified.
- **Job** — a saved configuration: the dataset rows to process and the tasks to run on each.
- **Task** — one thing to produce per row: a prompt (the question, with the row's columns in it), an answer
  type with its options, a result column name, and the models that answer it.
- **Run** — one execution of a job. Holds a frozen copy of the job's settings, progress and per-row results,
  and produces a new dataset.

## Workflow: a loop

Labeling a dataset never changes it; a run produces a new dataset with the result columns added, which
appears in the dataset list like any upload. Pick it to filter on the new labels and label again, e.g. a
cheap yes/no filter first, then an LLM extraction on the "yes" rows only.

- A produced dataset holds **only the rows the run processed** (the job's scope), with the
  parent's columns plus the result columns. `__row_id` is kept from the parent, so every row can be traced
  back to the original file.
- It records its parent dataset and the run that made it — one link, shown as an origin line ("from
  customers.csv · sentiment"). No version history or branching graph.

## UI layout

One page with three resizable columns (widths are remembered):

- **Datasets** — a feed of recent dataset activity, newest first: uploads, and datasets being produced by
  runs with a small live progress bar (labeling, stopped, failed), plus "Add data".
- **Rows** — the selected dataset's data: the rows table (search, filters, sort, limit), a Columns tab
  with statistics for every column and nested field, and a Runs tab listing its runs. Columns are
  dragged from here into a task's prompt. The search, filters, sort and limit are the new run's
  **scope**: the table shows exactly the rows it processes. Viewing a run shows its rows with its
  answers as extra columns. A dataset still being produced shows the rows finished so far, with
  stop/resume.
- **Run** — while composing ("New run"): the tasks (each a prompt with columns dragged in, an answer
  type, a result column and models) and **Run**. While viewing a past run (picked in the middle's Runs
  tab): its settings and costs, and later its progress (rows per second, ETA, errors) and exporting to a
  file or S3.

It works like a desktop app: thin column toolbars, Filter and Display popovers instead of forms, menus
for actions, a ⌘K command palette and shortcuts (⌘↵ run, J/K switch dataset, / search), dark mode
following the system. `AGENTS.md` lists the conventions.

What is selected lives in the query string, e.g. `/?dataset=<id>&tab=columns`: the UI is a static export,
which can't have routes for ids that only exist at runtime, and path-style URLs would need a server-side
fallback. Selecting something is a client-side navigation, so the columns stay mounted.

## Milestones

Ordered so that the tool is usable end to end as early as possible (local files first, remote storage
later). Each milestone ships API, UI and tests together, and ends with `make lint test build` green.

### 1. Datasets: load and explore local files ✅

- Ingest CSV/TSV, JSON (array of objects), JSONL and Parquet, optionally gzipped, with DuckDB →
  `datasets/{id}/data.parquet` plus `__row_id`. The format is detected from the content, not the name.
  Nested values stay as structs/lists and are shown as JSON.
- SQLite app state (`datasets` table) with plain SQL migrations. Data dir `~/.rowlab`, overridable.
- API: `POST /v1/datasets` (upload or local path), list, get, delete, `profile`, `query`.
- UI: dataset list with upload, table explorer with server-side sort, filter, search and paging.
- **Done when** a 1M-row file loads and the table stays responsive.

### 2. Prompt composer ✅

- Template syntax: `{{column}}` and `{{column.nested}}`, no quoting needed for names with spaces or dots.
  Empty values render as an empty string; other non-text values as compact JSON.
- API: `POST /v1/datasets/{id}/render` → rendered rows, the fields a template can use, warnings
  (unknown fields with suggestions, empty values, no fields used) and token estimates from a sample of
  200 rows, using OpenAI's o200k tokenizer as a model-independent estimate.
- UI: TipTap editor with column chips (click, drag or type `{{…}}`), a searchable column list, live
  per-row preview with the source values, and token stats. The template is kept in the browser until
  milestone 3 saves it as part of a job.

### 3. Models and job configuration (in progress)

The model never limits what a job can do: decision models and LLMs answer the same answer types and
write the same columns. Choosing one is a matter of cost, speed and accuracy. Answer types come from the
use-case archetypes; phase 1 covers everything decision models can answer, phase 2 adds what only LLMs can.

**Phase 1 — done.** Four answer types, each with any model:

| Answer type | Archetypes | Decision model | LLM (structured outputs) |
|---|---|---|---|
| Yes / no | filters, safety, PII, verification, consistency | `noul` | `{answer: bool, proba}` |
| Pick one | sentiment, intent, routing, A/B, correctness | `choice` | `{answer: enum, proba}` |
| Pick any | tags, topics, several policies | one `noul` per option, one call | `{answers: {option: {answer, proba}}}` |
| Scale | urgency, quality, ratings | `score` (most likely level) | `{answer: enum of levels, proba}` |

- A job has several tasks, so labeling many things is set up once and run in one pass. Each task has its
  own prompt, answer type, result column and models; several models answer the same task for comparison.
- Every model writes its own columns, named after it: `<column>__<model>` and `<column>__<model>_proba`,
  the probability that the answer is right (pick any: `<column>_<option>__<model>`), e.g.
  `team__jev-1.14`, `team__kimi-k3`. Decision models give probabilities; LLMs are asked for one in a
  JSON reply whose shape is enforced by a schema and checked on arrival (`core/answers.py`).
- A task has one prompt: the question with the row's columns in it. Decision models get it as `state` with
  a fixed instruction ("Answer the question in the text."), which answers the same as sending the question
  separately (checked on 3 models); LLMs get it as the user message.
- `core/providers/openrouter.py`: one model catalog — decision models, then LLMs supporting structured
  outputs — cached for an hour; Decisions API and chat completion calls.
- Response cache in SQLite, keyed on a hash of the full request, pulled forward from milestone 4: running
  the same task on the same row with the same model never pays twice.
- OpenRouter key from `OPENROUTER_API_KEY` or saved from the UI after OpenRouter accepts it.
- Jobs (`GET`/`POST /v1/datasets/{id}/jobs`, `PUT /v1/jobs/{id}`) hold the scope (the Rows tab's search,
  filters, sort and limit) and the tasks; the UI creates one per dataset and saves as you edit. A new job
  is limited to 20 rows, so its first run is cheap. Tasks are small cards that expand to their prompt,
  answer and models.
- `POST /v1/jobs/{id}/run` runs every task and model on the rows in scope: answers, probabilities and cost
  per task and model. The UI shows the answers as columns next to the rows. Runs happen within the request
  for now, so they are limited to 1,000 rows; milestone 4 moves them to the background.

**Phase 2 — to do:** answer types only LLMs can produce: extract named fields, numbers, lists, free text,
normalization. An optional reason column is a candidate too.

- **Done when** a user can configure each answer type and run it on a few rows.

### 4. Runs: start, stop, resume (started)

Done so far — runs are kept and browsable:

- `POST /v1/jobs/{id}/runs` starts a run in a background thread and returns at once. The run keeps a
  frozen copy of its scope and tasks, its status (`running`, `done`, `failed`) and progress (model calls
  done of total, saved about twice a second), then its answers per row and cost per task and model.
  Runs are numbered per dataset (#1, #2, …). Runs cut off by a server restart are marked failed.
  `GET /v1/datasets/{id}/runs` lists them; `GET /v1/runs/{id}` returns one with its answers.
- UI: a Runs tab in the middle lists a dataset's runs. Opening one (`?run=<id>`) shows its settings and
  costs on the right, and its rows and answers in the middle, read-only, with its own scope. "New run"
  goes back to composing with one empty task on the rows you have picked; "Edit as new run" starts
  from the run you were looking at instead, its rows and tasks.

Still to do:

- Answers stored as they arrive, so a run can resume after a restart; then lift the 1,000-row limit.
- Starting a run creates its output dataset right away, with a status: `running`, `stopped`, `failed` or
  `ready`. The dataset records its parent dataset and run.
- When the run finishes, the output dataset's Parquet is written once: the processed rows with the
  parent's columns (and `__row_id`) plus the result columns. A `ready` dataset never changes.
- Uses the response cache from milestone 3, so answers already given are free.
- One asyncio worker in the server process: bounded concurrency, retry with backoff on rate limits and
  transient errors, failed rows recorded with their error and retryable.
- API: `POST /v1/runs/{id}/stop`, `POST /v1/runs/{id}/resume`.
- Runs left `running` when the server stopped are resumed on startup.
- **Done when** killing the server mid-run and restarting completes the run with no duplicate paid calls.

### 5. Live progress in the dataset feed (started)

Done so far: the dataset list is ordered by latest activity (added or last run), a run slides its dataset
to the top, and a running run shows as a thin progress bar on top of its dataset, refreshed every second.


- API: `GET /v1/datasets` lists datasets by latest activity and includes progress counts for datasets
  still being produced; `GET /v1/runs/{id}` for one run's details.
- UI: the dataset feed shows a small progress bar on datasets being produced, refreshed by polling while
  any run is active. Selecting one shows the rows finished so far in the middle column, with stop/resume;
  the job column shows done/failed/cached counts, rows per second, ETA, cost so far and errors.

### 6. Export to local

- Export any dataset (uploaded or produced) as CSV, JSONL or Parquet. A produced dataset already holds the
  original columns plus the result columns.
- API: `POST /v1/datasets/{id}/export` → download, or write to a local path.
- UI: export in the job column for the selected dataset.

### 7. Remote storage: read and write

- ~~Read from public HTTP(S) URLs~~ — done early: downloaded with the standard library, then ingested like
  an upload. Still to do: read from S3-compatible storage (AWS, R2, MinIO, …).
- Export to S3-compatible storage.
- Connections: named S3 configs (endpoint, region, bucket, keys) stored locally; secrets are never
  returned by the API. Environment/AWS profile credentials work without configuring a connection.
- API: connections CRUD; `source` accepts `s3://` URIs (it already accepts `https://`), and so does the
  export `destination`.
- UI: S3 sources in "Add data", S3 destination on export.
- **Done when** tested against MinIO in CI.

### 8. MVP release

- Dockerfile, README quickstart and API docs page; end-to-end smoke test from upload to export.
- Error states and empty states across the UI.
- Release `rowlab` 0.1.0 to PyPI via GitHub Actions trusted publishing.

## After MVP

MCP server (`rowlab mcp`, `/mcp`) · human review and corrections · discover → label (LLM proposes
categories) · one-click cascades (low-confidence rows escalated to an LLM; already possible by hand
through the workflow loop) · decision model vs LLM agreement
comparison · provider batch APIs.

## Risks and open questions

- **"JSONLD":** implemented as JSONL (one JSON object per line). JSON-LD (linked data) would need its own
  flattening step — still to be confirmed.
- **OpenRouter Decisions API is alpha.** Keeping it behind one module limits the impact of changes.
  Confirm the exact request/response fields and whether the model catalog can be filtered via the API.
- **Local secret storage** (OpenRouter key, S3 keys) is plaintext in the local data dir in MVP — acceptable
  for a single-user local tool, revisit before any hosted offering.
- **Large files:** 1M+ rows must stay responsive in the explorer and runs; test early with real data.

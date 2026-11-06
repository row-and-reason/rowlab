# Roadmap to MVP

**Today:** milestones 1 and 2 are done. CSV, TSV, JSON, JSONL and Parquet files can be uploaded, or loaded
by local path or public http(s) URL (pulled forward from milestone 7), and explored with server-side search,
filters, sort and paging; 1M rows ingest in under a second and every page query returns in about 0.1 s.
A prompt template can be composed from columns with a live per-row preview and token estimates.
`rowlab serve` serves the API and UI on one port, and `make build` produces a wheel with the UI bundled.

**MVP:** a local tool that takes a CSV/JSON/JSONL/Parquet file from disk, HTTP or S3, runs a configured
labeling or extraction job over its rows with any OpenRouter decision model or LLM, can be stopped and
resumed without paying twice, shows all work and its live progress, and writes the result to disk or S3.

## Terms

- **Dataset** — an ingested file, or the result of a run. Stored once as Parquet with a stable `__row_id`;
  never modified.
- **Job** — a saved configuration: dataset rows to process, prompt template, model, and outputs.
- **Run** — one execution of a job. Holds a frozen copy of the job's settings, progress and per-row results,
  and produces a new dataset.

## Workflow: a loop

Labeling a dataset never changes it; a run produces a new dataset with the result columns added, which
appears in the dataset list like any upload. Pick it to filter on the new labels and label again, e.g. a
cheap yes/no filter first, then an LLM extraction on the "yes" rows only.

- A produced dataset holds **only the rows the run processed** (after the job's row selection), with the
  parent's columns plus the result columns. `__row_id` is kept from the parent, so every row can be traced
  back to the original file.
- It records its parent dataset and the run that made it — one link, shown as an origin line ("from
  customers.csv · sentiment"). No version history or branching graph.

## UI layout

One page with three columns:

- **Datasets** — a feed of recent dataset activity, newest first: uploads, and datasets being produced by
  runs with a small live progress bar (labeling, stopped, failed), plus "Add data".
- **Contents** — the selected dataset: rows (filtering), columns, and the prompt / job configuration. A
  dataset still being produced shows the rows finished so far, with stop/resume.
- **Output** — details of the selected dataset's run (cost, rows per second, ETA, errors) and exporting the
  selected dataset to a file or S3 (milestones 4–7; a placeholder until then).

What is selected lives in the query string, e.g. `/?dataset=<id>&tab=prompt`: the UI is a static export,
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

### 3. Models and job configuration

- OpenRouter integration behind one module (`core/providers/openrouter.py`):
  - **Decision models** via the Decisions API (`noul`, `choice`, `score`).
  - **LLMs** via chat completions with structured outputs (JSON schema).
  - Model catalog from OpenRouter, cached, filterable by decision vs LLM.
- API key from `OPENROUTER_API_KEY` or set once in the UI (stored locally, never returned by the API).
- Job configuration covering the archetypes from scoping:
  - Decision: yes/no filter, single label, multi-label (one `noul` per tag), ordinal score, rubric
    (several questions in one call).
  - LLM: extraction into named fields, free-text generation, labeling with an explanation.
  - Row selection (saved query), output column names, model parameters.
  - The prompt template from milestone 2, saved with the job instead of in the browser.
- API: jobs CRUD, `POST /v1/jobs/{id}/preview` (runs N sample rows synchronously).
- UI: job builder (template + questions/fields + model) with a sample preview next to the source rows,
  showing labels, confidence and cost.
- **Done when** a user can configure each archetype and preview it on 20 rows.

### 4. Runs: start, stop, resume

- Starting a run creates its output dataset right away, with a status: `running`, `stopped`, `failed` or
  `ready`. The dataset records its parent dataset and run.
- Per-row results stored as they complete; a run is a frozen copy of its job's settings.
- When the run finishes, the output dataset's Parquet is written once: the processed rows with the
  parent's columns (and `__row_id`) plus the result columns. A `ready` dataset never changes.
- Response cache keyed on `hash(model + params + questions + rendered prompt)`.
- One asyncio worker in the server process: bounded concurrency, retry with backoff on rate limits and
  transient errors, failed rows recorded with their error and retryable.
- API: `POST /v1/jobs/{id}/runs`, `POST /v1/runs/{id}/stop`, `POST /v1/runs/{id}/resume`,
  `GET /v1/runs/{id}/results`.
- Runs left `running` when the server stopped are resumed on startup.
- **Done when** killing the server mid-run and restarting completes the run with no duplicate paid calls.

### 5. Live progress in the dataset feed

- API: `GET /v1/datasets` lists datasets by latest activity and includes progress counts for datasets
  still being produced; `GET /v1/runs/{id}` for one run's details.
- UI: the dataset feed shows a small progress bar on datasets being produced, refreshed by polling while
  any run is active. Selecting one shows the rows finished so far in the middle column, with stop/resume;
  the output column shows done/failed/cached counts, rows per second, ETA, cost so far and errors.

### 6. Export to local

- Export any dataset (uploaded or produced) as CSV, JSONL or Parquet. A produced dataset already holds the
  original columns plus the result columns.
- API: `POST /v1/datasets/{id}/export` → download, or write to a local path.
- UI: export in the output column for the selected dataset.

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

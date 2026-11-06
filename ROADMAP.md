# Roadmap to MVP

**Today:** milestones 1 to 7 are done; the MVP release (8) is next. CSV, TSV, JSON, JSONL and Parquet
files are uploaded, or loaded by local path, public http(s) URL or from S3, and explored with
server-side search, filters, sort and paging; 1M rows ingest in under a second and every page query
returns in about 0.1 s. A job runs several tasks, each with one or more decision models or LLMs, on the
rows its scope picks: tasks classify (yes/no, pick one, pick any, scale), extract typed fields, or write
new text. Every run makes a new dataset that appears at once and fills in as the run works in the
background in chunks of 500 rows; runs can be stopped and resumed, survive a server restart without
paying twice, and show live progress. Any dataset exports as CSV, JSONL or Parquet, to disk or S3.
`rowlab serve` serves the API and UI on one port, and `make build` produces a wheel with the UI bundled.

**MVP:** a local tool that takes a CSV/JSON/JSONL/Parquet file from disk, HTTP or S3, runs a configured
labeling or extraction job over its rows with any OpenRouter decision model or LLM, can be stopped and
resumed without paying twice, shows all work and its live progress, and writes the result to disk or S3.

## Terms

- **Dataset** — an ingested file, or what a run made from another dataset. Stored as Parquet with a stable
  `__row_id`, whatever the original format; never modified once complete. Named after the file without
  its extension (`titanic`), and a made dataset after its branch, numbered like an outline:
  `titanic__1`, `titanic__2`, … for those made from `titanic`, `titanic__1.1` for the first made from
  `titanic__1`. They are branches, not versions: siblings are alternatives side by side, children
  refine their parent. Numbers count per parent and aren't reused. The UI never names runs; it shows
  datasets. The format to export to is picked at export time.
- **Job** — a saved configuration: the dataset rows to process and the tasks to run on each.
- **Task** — one thing to produce per row: a prompt (the question, with the row's columns in it), an answer
  type with its options, a result column name, and the models that answer it.
- **Run** — one execution of a job, which makes a new dataset. Holds a frozen copy of the job's settings,
  its progress and costs. It belongs to the dataset it makes: that dataset's Lineage tab shows it.

## Workflow: a loop

Labeling a dataset never changes it; a run makes a new dataset with the result columns added, which
appears under its parent in the dataset list straight away and fills in as the run goes. Pick it to filter
on the new labels and label again, e.g. a cheap yes/no filter first, then an LLM extraction on the "yes"
rows only.

- A run's dataset holds **every row of its parent**, with the parent's columns plus the result columns.
  Only the rows in the job's scope are asked; the others keep empty result columns. So each step is the
  complete data with every label so far, and the last one is the one to export. `__row_id` is kept from
  the parent, so every row can be traced back to the original file.
- It records its parent dataset and the run that made it: it sits under its parent in the dataset list,
  and its Lineage tab shows what it was made from and how (scope, tasks, models, costs). Its rows are
  copied when the run starts, so it doesn't depend on its parent; each run is a full copy, which a cheaper
  storage model can replace later if needed.

## UI layout

One page with three resizable columns (widths are remembered):

- **Datasets** — every dataset as a tree: added files at the root, and each run's dataset under the one
  it ran on, with a thin live progress bar while a run is making it, plus "Add data". Families go by their
  latest activity, so a run brings its family to the top; a dataset folds away what was made from it,
  except while a run is still making one. Indentation stops after three levels. At the bottom, "Your
  account" (it will show who is signed in once there are accounts): Settings, API keys & MCP
  connections and Log out (both still to come). Settings is its own page (`/settings/`, ⌘,): sections
  on the left (Providers, with the OpenRouter key; Storage, with S3 connections), Back or Esc returns to the dataset
  you came from.
- **Rows** — the selected dataset's data: the rows table (search, filters, sort, limit), a Columns tab
  with statistics for every column and nested field, and a Lineage tab. Columns are dragged from here
  into a task's prompt. The search, filters, sort and limit are the next run's **scope**: the table
  shows exactly the rows it processes. A dataset still being made shows its answers as they come in,
  with Stop/Resume in its toolbar.
- **New run** — the tasks (each a prompt with columns dragged in, an answer type, a result column and
  models) and **Run**, which opens the dataset the run makes. Later also exporting to a file or S3.

It works like a desktop app: thin column toolbars, Filter and Display popovers instead of forms, menus
for actions, a ⌘K command palette and shortcuts (⌘↵ run, J/K switch dataset, / search, E export), dark mode
following the system. `AGENTS.md` lists the conventions.

What is selected lives in the query string, e.g. `/?dataset=<id>&tab=columns`: the UI is a static export,
which can't have routes for ids that only exist at runtime, and path-style URLs would need a server-side
fallback. Selecting something is a client-side navigation, so the columns stay mounted.

## Milestones

Ordered so that the tool is usable end to end as early as possible (local files first, remote storage
later). Each milestone ships API, UI and tests together, and ends with `make lint test build` green.

### 1. Datasets: load and explore local files ✅

- Ingest CSV/TSV, JSON (array of objects), JSONL and Parquet, optionally gzipped, with DuckDB →
  `datasets/{id}/data.parquet` plus `__row_id`. The format is detected from the content, not the name,
  and the name drops the file's extension.
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

### 3. Models and job configuration ✅

Answer types come in three families, by what the answer is: **Classify** puts the row in a known box,
**Extract** pulls typed facts out of it, **Write** produces new text from it. For Classify the model never
limits what a job can do: decision models and LLMs answer the same answer types and write the same
columns, so choosing one is a matter of cost, speed and accuracy. Extract and Write need an LLM.

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
- OpenRouter key from `OPENROUTER_API_KEY` or saved in Settings after OpenRouter accepts it.
- Jobs (`GET`/`POST /v1/datasets/{id}/jobs`, `PUT /v1/jobs/{id}`) hold the scope (the Rows tab's search,
  filters, sort and limit) and the tasks; the UI creates one per dataset and saves as you edit. A new job
  is limited to 20 rows, so its first run is cheap; on a dataset a run made, it starts on the rows that
  run answered instead (its first answer column is not null). Tasks are small cards that expand to their prompt,
  answer and models.
- Running a job asks every task and model about the rows in scope: answers, probabilities and cost per
  task and model. The UI shows the answers as columns next to the rows. Runs are milestone 4.

**Phase 2 — done.** What only LLMs can give, and making every task effortless to set up:

- **Extract:** named fields, each text, number, true/false, date, a list of text, or items (a list of
  objects with fields of their own, one level deep, e.g. invoice line items). One field writes
  `<column>__<model>`, several write `<column>_<field>__<model>`, typed (`DOUBLE`, `DATE`,
  `STRUCT(...)[]`, …). Every field may be empty: the model is told to leave out what the text doesn't
  give rather than guess. No `_proba`. In the API, `"amount:number"` is short for a field.
- **Write:** one text column, `<column>__<model>`. Presets are starting prompts, not types: Summarize,
  Translate (into a picked language), Rewrite, Redact, Clean up, Answer a question, Draft a reply.
  Normalizing to a strict format is Extract with a typed field; open-ended tags are Extract with a list.
- **Reason:** any Classify or Extract task answered by LLMs can also write why, in
  `<column>__<model>_reason`; the model writes it before answering.
- **Defaults:** a task needs only its prompt and type; the result column and models default to ones that
  suit the type (a decision model for Classify, `anthropic/claude-haiku-5.5` for Extract and Write).
  `GET /v1/task-types` lists the types by family, the presets, field types and languages: the UI builds
  its menus from it, and API clients can discover everything there.
- **One call to run:** `POST /v1/datasets/{id}/runs` with `{tasks, scope}` (all rows without a scope).
  Jobs remain the UI's saved draft. `POST /v1/datasets/{id}/estimate` with the same body returns the rows,
  model calls and rough cost (from sample rows' token counts and the models' prices), or why it can't
  run and what to change.
- **UI:** the task's type menu is grouped by family, with the Write presets (and a language submenu for
  Translate) under it; picking a type that needs an LLM switches a decision model to the default one and
  says so. Extract fields are a short list (name, type, description; Enter adds the next). The Run
  button's tooltip shows the estimated cost, and what still needs doing shows under the tasks as you
  type. ⌘K adds a task from any preset.

### 4. Runs: start, stop, resume ✅

- `POST /v1/datasets/{id}/runs` queues a run and returns at once with the dataset it makes (`dataset_id`):
  every row of the parent is copied into it (`rows.parquet`) and the rows in scope listed
  (`asked.parquet`); it is named after its place in the tree (`titanic__1.2`), with empty
  answer columns. The run keeps a frozen copy of its scope and tasks.
  `GET /v1/runs/{id}` returns its status (`queued`, `running`, `stopping`, `stopped`, `done`, `failed`),
  progress and cost per task and model; each dataset carries its run's status and progress too.
- One runner thread in the server works through queued runs one at a time, oldest first, with 16 model
  calls in flight. The rows in scope are split into fixed chunks of 500 by `__row_id`. Each finished chunk's answers
  are written to its own Parquet part file (`datasets/<id>/parts/part-<n>.parquet`, written to a temporary
  file and renamed), and SQLite only records the next chunk to do. Progress is saved about twice a second.
  Until the run is done the dataset is read as its rows joined with the parts written so far, so search,
  filters and sort work on the answers as they come in.
- Model calls time out after 60 seconds and are retried up to 4 times with backoff on rate limits, server
  errors and timeouts, honouring `Retry-After`. A row that still fails has empty answer columns and counts
  as failed for its task and model.
  The response cache from milestone 3 means answers already given are free.
- `POST /v1/runs/{id}/stop` stops after the chunk in progress; `POST /v1/runs/{id}/resume` first asks
  the answers that failed in the chunks already written again (past the response cache, so an unusable
  reply isn't just repeated), then continues from the next chunk. A done run with failed answers can be
  resumed too ("Retry failed" in its dataset's toolbar). Runs cut off by a server restart are queued again on startup and continue where they
  left off: killing the server mid-run and restarting completes the run without paying twice (tested).
- When a run finishes, its dataset is written out as `data.parquet`, like any other dataset. The run's
  files stay next to it, so its failed answers can be asked again later.
  Deleting a dataset deletes the run that makes it; datasets made from it stay.
- UI: Run opens the new dataset. Its rows fill in as chunks finish; its toolbar has Stop or Resume; its
  Lineage tab shows what it was made from, the run's status, progress bar, answers per second and time
  left, its settings and costs, and "Use these settings again" (puts its scope and tasks back on the parent).

### 5. Live progress in the dataset feed ✅

- In the dataset list, a run brings its family to the top, sliding there, with its dataset under the one
  it ran on. While a run is making it, a thin progress bar shows on top of it, refreshed every second
  while any run is active.
- A dataset being made shows its rows filling in, and its Lineage tab the progress, answers per second,
  time left, cost so far and failed answers per task and model.

### 6. Export to local ✅

- Export any dataset (added or made by a run) as CSV, JSONL or Parquet, picked at export time: every row
  and column, by `__row_id`, which is left out unless asked for. In CSV, nested values are written as
  JSON text. A dataset still being made can't be exported until its run is done.
- API: `GET /v1/datasets/{id}/export?format=…` downloads it as `<name>.<format>`;
  `POST /v1/datasets/{id}/export` writes it to a path on the server (a folder or a file name),
  replacing the file atomically.
- UI: "Export…" in a dataset's menus and the ⌘K palette (shortcut E): a dialog with the format, whether
  to include the `#` column, and Download or Save to a path.

### 7. Remote storage: read and write ✅

- Read from public HTTP(S) URLs (done early: downloaded, then ingested like an upload) and from
  S3-compatible storage (AWS S3, Cloudflare R2, MinIO, …): `source` accepts `s3://bucket/key`. DuckDB
  reads the object where it is, so no new dependency; as its content can't be looked at first, Parquet,
  JSON and CSV readers are tried in turn, and `.gz` objects are decompressed by their name.
- Export to S3: the export `path` accepts `s3://bucket/key`, or `s3://bucket/folder/` for
  `<name>.<format>` in it.
- Connections (`GET`/`POST /v1/connections`, `PUT`/`DELETE /v1/connections/{id}`): a name, an
  endpoint (empty for AWS; storage other than AWS is addressed by path), a region and keys, stored
  locally; the secret key is never returned. Creating a dataset and exporting take a `connection_id`;
  without one, the AWS credentials in the environment (variables, `~/.aws`) are used, and public buckets
  work without any.
- UI: connections in Settings → Storage (add, edit, delete); "Add data" and Export take `s3://` paths
  and then ask which connection to use.
- **Done** with tests against a local S3 server (moto), started by the tests themselves, so they run on
  every `make test` and in CI (`.github/workflows/ci.yml`: lint, test, build, and a check that the
  generated API client is current) without a storage service. Not yet tried against MinIO, R2 or AWS
  themselves.

### Comparing columns ✅ (pulled forward)

Most people labeling data have no correct answers to check against: that is why they label. How often
columns agree is the cheapest sign of where labels are wrong, and comparing against labels someone
trusts measures accuracy. So any columns compare: several models' answers to one task, a model against
existing labels, or two columns of the original data.

- `POST /v1/datasets/{id}/compare` with two or more `columns` (or one and a `reference`), an optional
  `tolerance` for numbers and dates, and the usual search and filters: rows where all agree, disagree,
  are partly answered or not answered; how often each two columns agree; how often each column gives
  each value; for exactly two columns, the crosstab of their values; with a reference, each column's
  accuracy, precision and recall per value. Lists are the same when they hold the same items; empty
  values never count as a disagreement. Nothing is saved: comparisons are asked for, not kept.
- Every count comes with the filter for its rows, in the scope's language: two new filter ops,
  `agree` and `disagree`, over any number of `columns`. So the rows behind a count can be looked at
  (`query`) or asked about again (`runs`), e.g. a stronger model on just the disagreements.
- Write answers compare exactly only, for good: to judge whether two texts say the same, label another
  column with a task that asks.
- UI: a Compare tab picks the columns (to start with, the models' answers of the run that made the
  dataset), a reference and a tolerance; every count opens its rows in the Rows tab.

### 8. MVP release

- Dockerfile, README quickstart and API docs page; end-to-end smoke test from upload to export.
- Error states and empty states across the UI.
- Release `rowlab` 0.1.0 to PyPI via GitHub Actions trusted publishing.

## After MVP

MCP server (`rowlab mcp`, `/mcp`) · discover → label (LLM proposes
categories) · one-click cascades (low-confidence rows escalated to an LLM; already possible by hand
through the workflow loop) · provider batch APIs.

- **Human review.** A UI for people to label or correct rows, which writes a label column like any
  task does. With comparisons in place it is just another way to make a column: marked as a
  comparison's reference, it turns agreement into accuracy. Ideas to be written up.

### Ideas

Not planned yet; noted so they aren't lost. Add new ones here.

- **Translation APIs for Translate.** Machine translation services (e.g. DeepL, Google Translate) as
  models for the Translate preset, next to LLMs: cheaper and faster for plain translation. They'd be a
  third kind of model that only answers Write tasks started from Translate, with the target language as
  a setting rather than part of the prompt.
- **More model providers.** OpenRouter is the only provider today; Settings → Providers is where others
  would go: direct API keys for OpenAI, Anthropic, Google and the like, or a local OpenAI-compatible
  server (Ollama, vLLM) for private data. Each adds its models to the picker next to OpenRouter's.
- **More kinds of storage.** S3-compatible storage is the first (milestone 7); Settings → Storage is
  where others would go: Google Cloud Storage, Azure Blob Storage, and maybe databases or warehouses
  (Postgres, BigQuery) as sources and destinations.
- **SQL instead of our own filter language.** Scopes describe rows with a small filter language of our
  own (search, `eq`, `contains`, `agree`, …) through `POST /v1/datasets/{id}/query`, a name that
  suggests SQL it isn't. Rows could be picked with DuckDB SQL instead (a `WHERE` clause, or a whole
  `SELECT`), and the UI's filters become SQL templates it fills in: one language for people, the UI
  and agents, and nothing to extend when a new kind of filter is needed.
- **Recommended models first.** In the model picker, show a short "Recommended for <type>" group at the
  top, picked by the task's type (e.g. fast decision models for Classify, LLMs good at structured output
  for Extract), then the rest sorted as now.

## Risks and open questions

- **"JSONLD":** implemented as JSONL (one JSON object per line). JSON-LD (linked data) would need its own
  flattening step — still to be confirmed.
- **OpenRouter Decisions API is alpha.** Keeping it behind one module limits the impact of changes.
  Confirm the exact request/response fields and whether the model catalog can be filtered via the API.
- **Local secret storage** (OpenRouter key, S3 keys) is plaintext in the local data dir in MVP — acceptable
  for a single-user local tool, revisit before any hosted offering.
- **Large files:** 1M+ rows must stay responsive in the explorer and runs; test early with real data.

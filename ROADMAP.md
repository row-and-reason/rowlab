# Roadmap to MVP

**Today:** milestones 1 to 13 are done, and launch (14) is done apart from the first PyPI release. CSV, TSV, JSON, JSONL and Parquet
files are uploaded, or loaded by local path, public http(s) URL or from S3, and explored with SQL
(which the UI's search, filters and sort write for you) and paging; 1M rows ingest in under a second and
every page query returns in about 0.1 s. A run asks several tasks, each with one or more decision models
or LLMs, about the rows a query picks: tasks classify (yes/no, pick one, pick any, scale), extract typed
fields, or write new text. Any columns can be compared, e.g. several models' answers. Every run makes a new dataset that appears at once and fills in as the run works in the
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
- **Query** — one DuckDB `SELECT` over the table `data`, the dataset: which rows to look at, run on or
  export. The UI's search, filters, sort and limit write it; it can also be written by hand.
- **Draft** — the next run of a dataset, as the UI holds it: its query and tasks. Kept in the browser;
  the server only sees runs.
- **Task** — one thing to produce per row: a prompt (the question, with the row's columns in it), an answer
  type with its options, a result column name, and the models that answer it.
- **Run** — the tasks asked about the rows a query picks, which makes a new dataset. Holds a frozen copy
  of its query and tasks, its progress and costs. It belongs to the dataset it makes: that dataset's Origin tab shows it.

## Workflow: a loop

Labeling a dataset never changes it; a run makes a new dataset with the result columns added, which
appears under its parent in the dataset list straight away and fills in as the run goes. Pick it to filter
on the new labels and label again, e.g. a cheap yes/no filter first, then an LLM extraction on the "yes"
rows only.

- A run's dataset holds **only the selected rows of its parent**, with the parent's columns plus the
  result columns. A 100-row sample makes a 100-row result. `__row_id` is kept from
  the parent, so every row can be traced back to the original file.
- It records its parent dataset and the run that made it: it sits under its parent in the dataset list,
  and its Origin tab shows what it was made from and how (query, tasks, models, costs). Its rows are
  copied when the run starts, so it doesn't depend on its parent; each run is a full copy, which a cheaper
  storage model can replace later if needed.

## UI layout

One page with three resizable columns (widths are remembered):

- **Datasets** — every dataset as a tree: added files at the root, and each run's dataset under the one
  it ran on, with a thin live progress bar while a run is making it, plus "Add data". Families go by their
  latest activity, so a run brings its family to the top; a dataset folds away what was made from it,
  except while a run is still making one. Indentation stops after three levels. At the bottom, the
  account menu (who is signed in, on a hosted server): Settings, and when signed in API keys and Log
  out. Settings is its own page (`/settings/`, ⌘,): sections
  on the left (Providers, with the OpenRouter key; Storage, with S3 connections), Back or Esc returns to the dataset
  you came from.
- **Rows** — the selected dataset's data: the rows table (search, filters, sort, limit, and the SQL they
  make, to read or write by hand), a Columns tab with statistics for every column and nested field, a
  Compare tab, and a Origin tab. Columns are dragged from here into a task's prompt. The table's query
  is the next run's: the table shows exactly the rows it asks about. A dataset still being made shows its answers as they come in,
  with Stop/Resume in its toolbar.
- **New run** — the tasks (each a prompt with columns dragged in, an answer type, a result column and
  models) and **Run**, which opens the dataset the run makes. Later also exporting to a file or S3.

It works like a desktop app: thin column toolbars, Filter and Display popovers instead of forms, menus
for actions, a ⌘K command palette and shortcuts (⌘↵ run, J/K switch dataset, / search, E export), dark mode
following the system. `AGENTS.md` lists the conventions.

## API

Everything the UI does goes through this API, so a script or an agent can do it too. Rows are always
picked with SQL: one DuckDB `SELECT` over the table `data`, e.g.
`SELECT * FROM data WHERE stars = 1 ORDER BY review LIMIT 20`. It runs where it can read nothing but
the dataset's own files, and write nothing. To pick rows for a run, an estimate or an export it must
return `__row_id` (as `SELECT *` does). `agree([a, b, …])`, `disagree([a, b, …])`, and
`agree_within`/`disagree_within` with a tolerance, compare columns in a row.

| | | |
|---|---|---|
| `GET` `POST` | `/v1/datasets` | list; add (upload a `file`, or a `source`: path, URL or `s3://`, with a `connection_id`) |
| `GET` `DELETE` | `/v1/datasets/{id}` | |
| `GET` | `/v1/datasets/{id}/profile` | column statistics |
| `POST` | `/v1/datasets/{id}/query` | `{sql, offset, limit}` → `{columns, rows, total}` |
| `POST` | `/v1/datasets/{id}/compare` | `{columns, reference, tolerance, sql}`: agreement, accuracy, and SQL for each count |
| `POST` | `/v1/datasets/{id}/render` | `{template, sql, offset, limit}`: a prompt as sent, with token estimates |
| `GET` `POST` | `/v1/datasets/{id}/export` | download, or write to a path or `s3://`; `sql` exports only the rows it picks |
| `POST` | `/v1/datasets/{id}/runs` | `{sql, tasks}` → the run, and the dataset it makes |
| `POST` | `/v1/datasets/{id}/estimate` | `{sql, tasks}` → rows, model calls, rough cost, or what to change |
| `GET` | `/v1/runs/{id}` | status, progress, costs |
| `POST` | `/v1/runs/{id}/stop`, `/v1/runs/{id}/resume` | |
| `GET` | `/v1/settings` | |
| `PUT` | `/v1/settings/openrouter-key` | checked with OpenRouter, never returned |
| `GET` `POST` | `/v1/settings/connections` | S3 connections; secrets never returned |
| `PUT` `DELETE` | `/v1/settings/connections/{id}` | |
| `GET` | `/v1/utils/models` | decision models and LLMs |
| `GET` | `/v1/utils/task-types` | answer types, write presets, field types |
| `GET` | `/v1/health` | |

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
  per-row preview with the source values, and token stats. The template is kept in the browser, as part
  of the dataset's draft.

### 3. Models and tasks ✅

Answer types come in three families, by what the answer is: **Classify** puts the row in a known box,
**Extract** pulls typed facts out of it, **Write** produces new text from it. For Classify the model never
limits what a run can do: decision models and LLMs answer the same answer types and write the same
columns, so choosing one is a matter of cost, speed and accuracy. Extract and Write need an LLM.

**Phase 1 — done.** Four answer types, each with any model:

| Answer type | Archetypes | Decision model | LLM (structured outputs) |
|---|---|---|---|
| Yes / no | filters, safety, PII, verification, consistency | `noul` | `{answer: bool, proba}` |
| Pick one | sentiment, intent, routing, A/B, correctness | `choice` | `{answer: enum, proba}` |
| Pick any | tags, topics, several policies | one `noul` per option, one call | `{answers: {option: {answer, proba}}}` |
| Scale | urgency, quality, ratings | `score` (most likely level) | `{answer: enum of levels, proba}` |

- A run has several tasks, so labeling many things is set up once and run in one pass. Each task has its
  own prompt, answer type, result column and models; several models answer the same task for comparison.
- Every model writes its own columns, named after it: `<column>__<model>` and `<column>__<model>_proba`,
  the probability that the answer is right (pick any: `<column>_<option>__<model>`), e.g.
  `team__jev-1.14`, `team__kimi-k3`. Decision models give probabilities; LLMs are asked for one in a
  JSON reply whose shape is enforced by a schema and checked on arrival (`core/tasks.py`).
- A task has one prompt: the question with the row's columns in it. Decision models get it as `state` with
  a fixed instruction ("Answer the question in the text."), which answers the same as sending the question
  separately (checked on 3 models); LLMs get it as the user message.
- `core/providers/openrouter.py`: one model catalog — decision models, then LLMs supporting structured
  outputs — cached for an hour; Decisions API and chat completion calls.
- Response cache, keyed on a hash of the full request, pulled forward from milestone 4: running
  the same task on the same row with the same model never pays twice. (Since launch, replies are kept
  with the datasets they made instead of in a database table; see milestone 14.)
- OpenRouter key from `OPENROUTER_API_KEY` or saved in Settings after OpenRouter accepts it.
- Each dataset has a draft of its next run, its query and tasks, kept in the browser and saved as you
  edit (it was a server-side "job" until queries became SQL). A new draft is limited to 20 rows, so its
  first run is cheap; on a dataset a run made, it starts on the rows that run answered instead (its first
  answer column is not null). Tasks are small cards that expand to their prompt, answer and models.
- A run asks every task and model about the rows its query picks: answers, probabilities and cost per
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
  `GET /v1/utils/task-types` lists the types by family, the presets, field types and languages: the UI builds
  its menus from it, and API clients can discover everything there.
- **One call to run:** `POST /v1/datasets/{id}/runs` with `{sql, tasks}` (all rows without a query).
  `POST /v1/datasets/{id}/estimate` with the same body returns the rows,
  model calls and rough cost (from sample rows' token counts and the models' prices), or why it can't
  run and what to change.
- **UI:** the task's type menu is grouped by family, with the Write presets (and a language submenu for
  Translate) under it; picking a type that needs an LLM switches a decision model to the default one and
  says so. Extract fields are a short list (name, type, description; Enter adds the next). The Run
  button's tooltip shows the estimated cost, and what still needs doing shows under the tasks as you
  type. ⌘K adds a task from any preset.

### 4. Runs: start, stop, resume ✅

- `POST /v1/datasets/{id}/runs` queues a run and returns at once with the dataset it makes (`dataset_id`):
  only the selected parent rows are copied into it (`rows.parquet`) and their IDs listed
  (`asked.parquet`); it is named after its place in the tree (`titanic__1.2`), with empty
  answer columns. The run keeps a frozen copy of its query and tasks.
  `GET /v1/runs/{id}` returns its status (`queued`, `running`, `stopping`, `stopped`, `done`, `failed`),
  progress and cost per task and model; each dataset carries its run's status and progress too.
- One runner thread in the server works through queued runs one at a time, oldest first, with 16 model
  calls in flight. The rows it asks about are split into fixed chunks of 500 by `__row_id`. Each finished chunk's answers
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
  Origin tab shows what it was made from, the run's status, progress bar, answers per second and time
  left, its settings and costs, and "Use these settings again" (puts its query and tasks in the parent's draft).

### 5. Live progress in the dataset feed ✅

- In the dataset list, a run brings its family to the top, sliding there, with its dataset under the one
  it ran on. While a run is making it, a thin progress bar shows on top of it, refreshed every second
  while any run is active.
- A dataset being made shows its rows filling in, and its Origin tab the progress, answers per second,
  time left, cost so far and failed answers per task and model.

### 6. Export to local ✅

- Export any dataset (added or made by a run) as CSV, JSONL or Parquet, picked at export time: every row
  and column, by `__row_id`, which is left out unless asked for. In CSV, nested values are written as
  JSON text. A dataset still being made can't be exported until its run is done.
- API: `GET /v1/datasets/{id}/export?format=…` downloads it as `<name>.<format>`;
  `POST /v1/datasets/{id}/export` writes it to a path on the server (a folder or a file name),
  replacing the file atomically.
- UI: "Export…" in a dataset's menus and the ⌘K palette (shortcut E): a dialog in two steps, like "Add
  data": where to (Download or S3), then the format, whether to include the `#` column, and for S3 the
  connection and object. Writing to a path on the server stays in the API.

### 7. Remote storage: read and write ✅

- Read from public HTTP(S) URLs (done early: downloaded, then ingested like an upload) and from
  S3-compatible storage (AWS S3, Cloudflare R2, MinIO, …): `source` accepts `s3://bucket/key`. DuckDB
  reads the object where it is, so no new dependency; as its content can't be looked at first, Parquet,
  JSON and CSV readers are tried in turn, and `.gz` objects are decompressed by their name.
- Export to S3: the export `path` accepts `s3://bucket/key`, or `s3://bucket/folder/` for
  `<name>.<format>` in it.
- Connections (`GET`/`POST /v1/settings/connections`, `PUT`/`DELETE /v1/settings/connections/{id}`): a name, an
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
  `tolerance` for numbers and dates, and a query for the rows to compare: rows where all agree, disagree,
  are partly answered or not answered; how often each two columns agree; how often each column gives
  each value; for exactly two columns, the crosstab of their values; with a reference, each column's
  accuracy, precision and recall per value. Lists are the same when they hold the same items; empty
  values never count as a disagreement. Nothing is saved: comparisons are asked for, not kept.
- Every count comes with SQL for its rows (`where`), e.g. `disagree([a, b, c])`, using the comparing
  functions every query has. So the rows behind a count can be looked at (`query`), asked about again
  (`runs`, e.g. a stronger model on just the disagreements) or exported.
- Write answers compare exactly only, for good: to judge whether two texts say the same, label another
  column with a task that asks.
- UI: a Compare tab picks the columns (to start with, the models' answers of the run that made the
  dataset), a reference and a tolerance; every count opens its rows in the Rows tab.

## Launch plan

rowlab becomes an open-source project (one public repo, **Apache-2.0**, the name kept as a trademark),
and Row & Reason hosts it for those who don't want to run it themselves. The hosted version is the same
code with a different configuration: nothing in it is private. The milestones below get it there.

**Two modes, the rest is configuration.** `local` is one person on their own machine: no sign-in,
localhost only, files on the server's disk allowed. `hosted` is shared, by Row & Reason or anyone:
sign-in required, everything belongs to an organisation, and the protections a shared server needs are
on. Everything else is a setting read once at startup into one config object, and the API says what is
on so the UI shows only that:

| Setting | Options |
|---|---|
| `ROWLAB_MODE` | `local` · `hosted` |
| Database | SQLite file · Postgres URL |
| Dataset storage | local folder · S3 bucket (MinIO, R2, AWS) |
| Sign-in (hosted) | WorkOS (browser and MCP) · API keys (scripts) |
| Model keys | BYOK (only option at launch) |
| Billing | off; plans shown as "coming soon" |
| Files on the server's disk | on in `local`, off by default in `hosted` |

**Deployed as one image.** The API server serves the UI (a static export), runs as `api` or as
`runner` (the same image, another command; runners share the queue in Postgres), and serves MCP at
`/mcp`. Locally: `uvx rowlab`, or `docker compose` with Postgres and S3 (VersityGW), which is also the reference
for hosted setups. Row & Reason's runs on k3s behind a Cloudflare tunnel, which also rate-limits
requests. The website is a separate static site.

**Pricing, to start with** (to check against real server costs once it runs). A subscription pays for
the servers and the product, as BYOK brings no usage to mark up; credits on the platform's model key
cost the provider's price plus 25% (OpenRouter's fee on credits, payment fees, failed calls, margin),
but at least $0.01 per 1,000 answers, so cheap decision models don't run at a loss.

| | Free | Pro | Team |
|---|---|---|---|
| Price | $0 | $20 / month | $20 / seat / month |
| Model keys | BYOK | BYOK or credits | BYOK or credits |
| Answers a month | 50,000 | 2 million | 5 million per seat |
| Storage | 2 GB | 25 GB | 100 GB |

**Roles in an organisation:** **Admin** (settings, connections, users), **Member** (everything day to
day: adding data, running, labeling, exporting; runs cost money, so Member and up), **Verifier** (reads,
and labels by hand once human review exists; no exports). Connections are made by admins and used by
members, who never see their secrets. Roles live in rowlab's database whatever the sign-in provider,
which only says who someone is and which organisation they are in. Locally, the one user is Admin.

### 8. Deployment modes and Postgres ✅

- `ROWLAB_MODE` and the config object; `GET /v1/settings` says what is on.
- A thin `db` module over SQLite and Postgres (`connect()`, one placeholder style; no ORM), SQL both
  understand, migrations per database where they must differ. The test suite runs against both.
- Datasets in a local folder or an S3 bucket, chosen by configuration (DuckDB reads either).
- Runners take queued runs with `SELECT … FOR UPDATE SKIP LOCKED`, so several can share the queue.
- Migrations were reset to one `001_initial.sql` before the repo goes public; from here every change
  must be safe to apply to existing databases. Applied once per process, tracked in `schema_version`.
- Built: `core/config.py` (the settings, read once), `core/db.py` (SQLite or Postgres, `?`
  placeholders, rows as dicts; Postgres through a psycopg pool), `core/storage.py` (dataset files in a
  folder or on S3: DuckDB reads and writes, boto3 checks and deletes), runners claiming runs atomically
  and taking back only runs silent for two minutes (`STALE_SECONDS`), `rowlab serve --no-runner` and
  `rowlab runner`, the `rowlab[hosted]` extra, `make test-hosted` and a CI job with Postgres. The suite
  passes on SQLite with datasets on disk, and in CI on Postgres with datasets on S3.

### 9. Organisations, sign-in and roles ✅

- Everything (datasets, runs, connections, settings, the response cache) belongs to an organisation;
  locally there is one, implicit (`local`), and every call is its admin.
- Hosted, the app talks to WorkOS directly, no proxy: browsers sign in with AuthKit (`/auth/sign-in`,
  `/auth/callback`, `/auth/sign-out`) and get a session cookie; scripts send an API key
  (`Authorization: Bearer rl_…`) made in Settings → API keys. MCP will sign in with WorkOS's OAuth
  (milestone 12). Self-hosters who want sign-in bring their own WorkOS project.
- The first sign-in makes an organisation with that person as its admin; an invited address joins its
  organisation instead (nobody is emailed). An organisation always keeps an admin. One organisation per
  person for now; the tables allow several.
- Roles checked on every endpoint: any role reads; members add, run and export; admins change settings,
  connections and members.
- Built: migration `002_organisations.sql` (orgs, users, members, invites, sessions, API keys; `org_id`
  on datasets, connections and settings), `core/auth.py` (who is calling, sign-in, sessions, API keys),
  `core/members.py`, `core/providers/workos.py`, `api/auth.py` (`CanRead`, `CanEdit`, `CanAdmin`),
  `GET /v1/me`, Settings → Members and API keys, the account menu showing who is signed in, and the UI
  hiding what a role can't do. Tested by signing in as if WorkOS had, on SQLite and on Postgres, and
  end to end against Row & Reason's WorkOS Staging environment.

### 10. Hosted protections ✅

- The server's own files and credentials are off limits when hosted (`ROWLAB_SERVER_FILES`): no paths
  on its disk, no buckets reached with its AWS credentials, and never the bucket datasets are kept in.
- Web sources and S3 endpoints can't reach private addresses (SSRF; `ROWLAB_PRIVATE_URLS`), checked on
  every redirect of a web source too. Two ways past it need the network to block private addresses as
  well: DNS rebinding, and S3 endpoints redirecting DuckDB, which follows redirects with no way to stop
  it. The k3s manifests (milestone 14) include that egress policy.
- Limits as settings with modest defaults, the same in both modes: DuckDB memory, disk and threads,
  time per query, file size (checked before an upload is read, while copying, and on S3 objects).
- Runners take turns, a chunk at a time: a run waiting long goes next, otherwise the one with least
  left, so a try on a few rows is done at once next to a big run; at most `ROWLAB_RUNS_PER_ORG` runs
  per organisation going at once (a soft cap: two runners claiming at the same moment can pass it).
- Saved keys encrypted at rest with `ROWLAB_SECRET_KEY` (required hosted; Fernet). Keys saved before a
  secret key was set are read as they are, and encrypted when saved again.
- Rate limits per client are left to what is in front of rowlab: Cloudflare, for Row & Reason's.
- Built: `core/network.py`, `core/crypto.py`, the limits in `core/config.py` and `storage.connect`,
  migration `003_run_turns.sql`, `tests/test_protections.py`.

### 11. Usage and plans ✅

- A usage ledger (`usage` table): a row per run, task, model and day, with the organisation, who
  started the run (`runs.created_by`), answers, cached and failed answers, tokens, cost and whose key
  paid (`organisation`, or `server` for `OPENROUTER_API_KEY`). Added to as answers come in (every
  half second, and however a chunk ends), so a stop or an error loses nothing paid for; a hard crash
  at most half a second. Recorded for BYOK too, and kept when the run's dataset is deleted. Cached
  answers count as answers, with no cost or tokens; a chunk redone after a stop counts its cached
  answers again.
- `GET /v1/settings/usage?month=YYYY-MM`, and Settings → Usage: answers, spend, tokens and storage for
  a month, by day (a bar chart), model and person. Admins see the organisation, anyone else their own.
- Settings → Plans (hosted): Free, Pro and Team as a teaser, "coming soon"; everyone is on Free with
  their own key until billing is built. Plan limits aren't enforced yet.

### 12. MCP and the agent skills ✅

- MCP server (FastMCP) at `/mcp` in both modes, and `rowlab mcp` over stdio. Tools are each a
  thin call into `core` like the API's endpoints: `datasets_list`, `dataset_get` (with a profile),
  `dataset_add`, `dataset_rename`, `dataset_delete`, `sql_query`, `columns_compare`, `run_preview` (estimate plus the
  prompt rendered for a few rows), `run_start`, `run_get`, `run_stop`, `run_resume` (the three with
  `wait_seconds`), `run_answers`, `run_finish`, `dataset_export`, `task_types_get`, `models_list`. Each description says what the
  tool does, why it exists and when to use it; session instructions carry the workflow.
- Hosted, MCP clients sign in with WorkOS (AuthKit as the authorization server, with Dynamic Client
  Registration; `/.well-known/oauth-protected-resource/mcp` says so) or send an API key. Both come
  through one token verifier; WorkOS tokens are JWTs checked against AuthKit's keys, issuer and
  `<ROWLAB_URL>/mcp` as audience (a resource indicator in the dashboard), and their user must have
  signed in in a browser before. Settings aren't in MCP, nor uploads of file content.
- One `rowlab` skill in agent-skills covers manual and model labeling, representative evaluation,
  model selection and large runs. Methodology stays in the skill; tool contracts stay in MCP.
- Tested in-process, over stdio, and end to end against WorkOS Staging: Claude Code registered
  itself (Dynamic Client Registration), signed in, got a token for `http://localhost:8001/mcp` (the
  resource indicator) and called `datasets_list`; the API-key path too.

### 13. Website: landing, pricing, docs ✅

- `site/www` (rowlab.dev: landing and pricing, plain Astro) and `site/docs` (docs.rowlab.dev:
  Starlight, with the API reference from `openapi.json`), both in one nginx image (`site/Dockerfile`)
  that picks the site by hostname; served from k3s behind the Cloudflare tunnel, which caches it.
- PostHog with its default capture, one project of rowlab's own in Row & Reason's PostHog, nothing
  hand-picked in code. The sites take a token at build time and run only on their real origin; the
  app gets it from the API at runtime (`ROWLAB_POSTHOG_TOKEN`, hosted only, since the web build in
  the wheel is the same for everyone) and identifies the signed-in person and their organisation.
- The README is a quickstart; the docs are the reference.

### 14. Launch

- ✅ The image (`Dockerfile`; amd64 and arm64, runs as any user on a read-only filesystem) and
  `rowlab-site`, both pushed to `ghcr.io/row-and-reason` by CI; `docker-compose.yml` with Postgres
  and S3 (VersityGW). Row & Reason's own deployment (k3s, with a network policy that keeps the API
  and runners from private addresses other than Postgres and storage) lives in the company's
  infrastructure repository, not here.
- ✅ README quickstart; LICENSE (Apache-2.0), CONTRIBUTING (DCO sign-off, checked on pull
  requests), code of conduct, security policy, issue templates. Self-hosted rowlab sends nothing
  home; product analytics exist only where `ROWLAB_POSTHOG_TOKEN` is set, which is the hosted app.
- ✅ An end-to-end smoke test through the API, from adding a file to an export, with a run when
  `OPENROUTER_API_KEY` is set: `make smoke` against the built wheel installed fresh (in CI too,
  without the run), `make smoke-compose` against the Compose setup.
- ✅ A pass over error and empty states across the UI (failed runs, bad SQL, no key, models down).
- ✅ Data handling for the hosted version, kept short (docs: _Your data on app.rowlab.dev_): where
  data lives, what deleting removes, and the services data goes through (WorkOS, OpenRouter and the
  model providers, Cloudflare, PostHog). The web app masks all page text from PostHog, so rows,
  prompts and answers never reach it.
- ✅ The repo is public (7 November 2026), with private vulnerability reporting on.
- ✅ The database keeps only a working set, so it doesn't grow with every row labelled: model
  replies live with the datasets runs make (`answers/*.parquet`) and go when they are deleted; the
  database journals only the replies of chunks under way (`core/answers.py`). Runs reuse the replies
  of the done runs in their dataset tree, replacing the response cache table.
- `rowlab` 0.1.0 on PyPI via GitHub Actions trusted publishing.

## After launch

Discover → label (LLM proposes categories) · one-click cascades (low-confidence rows escalated to an
LLM; already possible by hand through the workflow loop) · provider batch APIs.

- **Human review.** A UI for people to label or correct rows, which writes a label column like any
  task does. With comparisons in place it is just another way to make a column: marked as a
  comparison's reference, it turns agreement into accuracy. Ideas to be written up.
- **Data processing terms for the hosted version:** a DPA, a retention policy, GDPR requests.
- **The smoke test's run step in CI,** with a low-limit OpenRouter key as a secret; until then it
  runs only locally.

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
- **Other sign-in providers.** WorkOS is the only one; a generic OIDC login (Keycloak, Authentik,
  Google) would let self-hosters sign in without a WorkOS project, if they ask for it.
- **Recommended models first.** In the model picker, show a short "Recommended for <type>" group at the
  top, picked by the task's type (e.g. fast decision models for Classify, LLMs good at structured output
  for Extract), then the rest sorted as now.

## Risks and open questions

- **"JSONLD":** implemented as JSONL (one JSON object per line). JSON-LD (linked data) would need its own
  flattening step — still to be confirmed.
- **OpenRouter Decisions API is alpha.** Keeping it behind one module limits the impact of changes.
  Confirm the exact request/response fields and whether the model catalog can be filtered via the API.
- **Local secret storage** (OpenRouter key, S3 keys) is plaintext in the local data dir unless
  `ROWLAB_SECRET_KEY` is set — acceptable for a single-user local tool; always encrypted when hosted.
- **Large files:** 1M+ rows must stay responsive in the explorer and runs; test early with real data.

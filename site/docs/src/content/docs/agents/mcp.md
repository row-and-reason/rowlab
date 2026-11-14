---
title: MCP
description: Connect Claude Code, Codex, Cursor or any MCP client to rowlab.
---

rowlab is an MCP server: the same data work as the API, as tools, with instructions that teach the
workflow. It is at `/mcp` on a running rowlab, or `rowlab mcp` over stdio.

## Connect

**Settings → Connect agents** has copyable commands for this server, including skill installation.

A local rowlab (`uvx rowlab`) needs no sign-in:

```sh
claude mcp add --transport http rowlab http://localhost:8000/mcp    # Claude Code
codex mcp add rowlab --url http://localhost:8000/mcp                 # Codex
```

Cursor and other clients that take a JSON config:

```json
{ "mcpServers": { "rowlab": { "url": "http://localhost:8000/mcp" } } }
```

A client that wants a command rather than a URL gets `uvx rowlab mcp`, which runs its own rowlab
on the same data folder.

## A hosted rowlab

Hosted, the client signs in with WorkOS when it first connects, so a person's agent works as them,
in their organisation:

```sh
claude mcp add --transport http rowlab https://app.rowlab.dev/mcp && claude mcp login rowlab
codex mcp add rowlab --url https://app.rowlab.dev/mcp && codex mcp login rowlab
```

Or it sends an API key from **Settings → API keys**, for a script or a server that can't sign in:

```sh
claude mcp add --transport http rowlab https://app.rowlab.dev/mcp --header "Authorization: Bearer rl_…"
```

In a JSON config, that is `"headers": {"Authorization": "Bearer rl_…"}` next to the URL. Someone
connecting over MCP must have signed in to rowlab in a browser once, which is where they join their
organisation.

## Tools

| Tool                                              | What it does                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------- |
| `datasets_list`, `dataset_get`                    | the datasets, and one dataset with its columns, lineage and profile         |
| `dataset_add`, `dataset_rename`, `dataset_delete` | add a file from a URL or S3 (locally, also a path); rename; delete          |
| `dataset_upload`, `dataset_download`              | links to upload a file from the agent's machine, or download one, with curl |
| `sql_query`                                       | rows from one DuckDB `SELECT` over `data`                                   |
| `columns_compare`                                 | agreement between answer columns, and accuracy against a reference          |
| `run_preview`                                     | the estimate and the rendered prompts for a run, before it costs anything   |
| `run_start`, `run_get`, `run_resume`, `run_stop`  | runs, with `run_get` and `run_resume` waiting up to 30 seconds for progress |
| `run_answers`, `run_finish`                       | save manual labels and finish the manual run                                |
| `dataset_export`                                  | a dataset as CSV, JSONL or Parquet, to S3 (locally, also a path)            |
| `task_types_get`, `models_list`                   | the answer types and their fields; models by name or kind                   |

Each tool's description says why it exists and when to use it, and the server's instructions give the
order of work: read the dataset, run on a few rows, read the answers, then run on all. The
[Rowlab skill](/agents/skills) goes further.

`models_list` returns `{models, total, next_offset}`: 20 models by default, at most 100 per page.
Use `search` and `kind` to narrow results and `offset` to continue. `columns_compare` keeps per-class
precision and recall, κ, α, intervals, calibration and cost in its default summary; `detail="full"`
includes distributions and all row filters. New run datasets contain only the selected source rows,
keeping their original row IDs.

Each call stands alone (the server keeps no MCP sessions), so a restart or deploy doesn't disconnect
agents.

## Files on the agent's machine

A local rowlab reads and writes paths on its own disk, which is the agent's. A hosted one can't, so
`dataset_upload` gives a link to post a file to, and `dataset_download` a link to get a dataset from,
each with the curl command to run:

```sh
curl -fsS -F 'file=@reviews.csv' 'https://app.rowlab.dev/v1/links/…'    # prints the new dataset
curl -fsS -o 'reviews__1.csv' 'https://app.rowlab.dev/v1/links/…'
```

A link needs no sign-in: it acts for the organisation of whoever asked for it, so treat it like a
password. It works for 15 minutes.

## Manual labeling

Tasks can be completed manually as well as with models. Call `run_start` with `method="manual"`
to create a run, then `run_answers(run_id, task_id, answers=[{"row_id": 0, "value": true}])`
to enter labels. No model is called or provider key required. Only submit labels the user
provides or explicitly asks you to produce.

The values follow the task: boolean for yes/no, option name for pick one or scale, a list of
option names for pick any, text for write, or an object keyed by field name for extract.
Null clears a label. Batches contain up to 1,000 answers. Read the saved task with `run_get`
and select or inspect rows using `sql_query` on its output dataset.

`run_finish` locks the output dataset, leaving unanswered cells null. Labels occupy the
named task columns without model suffixes or extra status columns. Existing comparison
and export tools work unchanged. Before finishing, last saved value wins; retry an
interrupted batch with the same values. There is no separate review or judgment lifecycle.

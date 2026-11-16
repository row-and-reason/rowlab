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

| Tool                                              | What it does                                                                     |
| ------------------------------------------------- | -------------------------------------------------------------------------------- |
| `datasets_list`, `dataset_get`                    | the datasets, and one dataset with its columns, answer columns and profile       |
| `dataset_add`, `dataset_rename`, `dataset_delete` | add a file from a URL or S3 (locally, also a path); rename; delete               |
| `dataset_upload`, `dataset_download`              | links to upload a file from the agent's machine, or download one, with curl      |
| `sql_query`                                       | rows from one DuckDB `SELECT` over `data`                                        |
| `columns_compare`                                 | coverage, agreement between answer columns, and accuracy against a reference     |
| `run_preview`                                     | the estimate and the rendered prompts for a run, before it costs anything        |
| `run_start`, `run_get`, `run_stop`, `runs_list`   | runs, with `run_start` and `run_get` waiting up to 30 seconds for progress       |
| `labels_set`                                      | set or clear labels people give, in a column of their own                        |
| `answers_delete`                                  | delete a model's answers to a task, or a column of labels                        |
| `dataset_export`                                  | a dataset as CSV, JSONL or Parquet, to S3 (locally, also a path)                 |
| `task_types_get`, `models_list`                   | the answer types and their fields; models by name, kind or tag                   |
| `model_add`, `model_update`                       | add a model of the organisation's own, e.g. a checkpoint; change its note, price |

Each tool's description says why it exists and when to use it, and the server's instructions give the
order of work: read the dataset, run on a sample in a stable order
(`ORDER BY md5('s1' || __row_id) LIMIT 50`), read and compare the answers, then run the same tasks on
all rows, asking only for the answers still missing. A stopped or failed run is started again with
`run_start`. The
[Rowlab skill](/agents/skills) goes further.

`models_list` returns `{models, total, next_offset}`: 20 models by default, at most 100 per page,
the organisation's own first, with their provider and note, then rowlab's list, recommended ones at
the top. Use `search`, `kind` and `tag` (`recommended`,
`budget`, `accurate`) to narrow results, `all` to search the rest of OpenRouter's catalog too, and
`offset` to continue. A run can use any model `all` finds. `model_add` adds a model served at one of
the organisation's providers, once it answers a short question, and `model_update` changes its note
or prices; see
[Self-hosted models](/guides/self-hosted-models). `columns_compare` keeps per-class
precision and recall, κ, α, intervals, calibration and cost in its default summary; `detail="full"`
includes distributions and all row filters, and it reports each column's coverage first.

Each call stands alone (the server keeps no MCP sessions), so a restart or deploy doesn't disconnect
agents.

## Files on the agent's machine

A local rowlab reads and writes paths on its own disk, which is the agent's. A hosted one can't, so
`dataset_upload` gives a link to post a file to, and `dataset_download` a link to get a dataset from,
each with the curl command to run:

```sh
curl -fsS -F 'file=@reviews.csv' 'https://app.rowlab.dev/v1/links/…'    # prints the new dataset
curl -fsS -o 'reviews.csv' 'https://app.rowlab.dev/v1/links/…'
```

A link needs no sign-in: it acts for the organisation of whoever asked for it, so treat it like a
password. It works for 15 minutes.

## Labels

`labels_set(dataset_id, column, labels=[{"row_id": 0, "value": true}], task=…)` sets labels people
give, in a column of their own, on any rows, before or after models run; the first labels in a column
bring the task they answer, which can be the models' task or a yes/no judgement of a model's answer.
No model is called or provider key required. Only submit labels the user provides or explicitly asks
you to produce. The values follow the [answer type](/how-it-works/answer-types), null clears a
label, and a batch holds up to 1,000. Read them with `sql_query`, and compare models against them with
`columns_compare(…, reference="gold")`.

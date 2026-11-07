---
title: MCP
description: Connect Claude Code, Codex, Cursor or any MCP client to rowlab.
---

rowlab is an MCP server: the same data work as the API, as tools, with instructions that teach the
workflow. It is at `/mcp` on a running rowlab, or `rowlab mcp` over stdio.

## Connect

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
```

Or it sends an API key from **Settings → API keys**, for a script or a server that can't sign in:

```sh
claude mcp add --transport http rowlab https://app.rowlab.dev/mcp --header "Authorization: Bearer rl_…"
```

In a JSON config, that is `"headers": {"Authorization": "Bearer rl_…"}` next to the URL. Someone
connecting over MCP must have signed in to rowlab in a browser once, which is where they join their
organisation.

## Tools

| Tool                                             | What it does                                                                |
| ------------------------------------------------ | --------------------------------------------------------------------------- |
| `datasets_list`, `dataset_get`                   | the datasets, and one dataset with its columns, lineage and profile         |
| `dataset_add`, `dataset_delete`                  | add a file from a path, URL or S3; delete                                   |
| `sql_query`                                      | rows from one DuckDB `SELECT` over `data`                                   |
| `columns_compare`                                | agreement between answer columns, and accuracy against a reference          |
| `run_preview`                                    | the estimate and the rendered prompts for a run, before it costs anything   |
| `run_start`, `run_get`, `run_resume`, `run_stop` | runs, with `run_get` and `run_resume` waiting up to 30 seconds for progress |
| `dataset_export`                                 | a dataset as CSV, JSONL or Parquet, to a path or S3                         |
| `task_types_get`, `models_list`                  | the answer types and their fields; models by name or kind                   |

Each tool's description says why it exists and when to use it, and the server's instructions give the
order of work: read the dataset, run on a few rows, read the answers, then run on all. The
[skills](/agents/skills) go further.

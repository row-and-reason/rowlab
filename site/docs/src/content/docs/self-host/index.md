---
title: Running rowlab
description: One process on a laptop, or Postgres, S3 and sign-in on your own servers.
---

rowlab is one Python package with two modes.

**Local** (the default) is one person on their own machine: no sign-in, the server's own files
readable and writable, one SQLite file and one data folder.

```sh
uvx rowlab                # or: pip install rowlab && rowlab serve
rowlab serve --host 0.0.0.0 --port 8000
```

**Hosted** is a shared server: people sign in with [WorkOS](https://workos.com), everything belongs
to an organisation, and the protections a shared server needs are on: no reading the server's disk,
no requests to private addresses, saved keys encrypted, runs taking turns. It wants Postgres, S3 and
the `hosted` extra:

```sh
pip install "rowlab[hosted]"
```

See [A shared server](/self-host/hosted) for the setup, and [Configuration](/self-host/configuration)
for every setting.

## Commands

| Command          |                                                                                |
| ---------------- | ------------------------------------------------------------------------------ |
| `rowlab serve`   | the API, the web app and, unless `--no-runner`, the runner that processes runs |
| `rowlab runner`  | a runner on its own; with Postgres, start as many as you like                  |
| `rowlab mcp`     | the MCP server over stdio, for an agent on this machine                        |
| `rowlab openapi` | the OpenAPI spec as JSON                                                       |

## Where things are

Locally, `~/.rowlab` (or `ROWLAB_DATA_DIR`) holds the SQLite database, the datasets as Parquet and
temporary files. Back it up like any folder; delete it to start over. A saved OpenRouter key is in
the database, never returned by the API, and encrypted when `ROWLAB_SECRET_KEY` is set.

rowlab sends nothing home: no telemetry, no update checks. Model calls go to OpenRouter with your
key, and nowhere else.

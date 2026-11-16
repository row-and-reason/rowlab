---
title: Configuration
description: Every environment variable rowlab reads, with its default.
---

rowlab is configured from environment variables, read once at start.

## Mode and storage

| Variable               | Default                            |                                                                                                                                                               |
| ---------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ROWLAB_MODE`          | `local`                            | `local` or `hosted`                                                                                                                                           |
| `ROWLAB_DATA_DIR`      | `~/.rowlab`                        | local state: temporary files, and the SQLite database by default                                                                                              |
| `ROWLAB_DATABASE_URL`  | a SQLite file in the data folder   | or `postgresql://…`                                                                                                                                           |
| `ROWLAB_STORAGE_URL`   | the data folder's `datasets`       | or `s3://bucket/prefix`, with the usual `AWS_*` credentials (`AWS_ENDPOINT_URL` for storage other than AWS)                                                   |
| `ROWLAB_SERVER_FILES`  | on when `local`, off when `hosted` | whether datasets can be added from, and exported to, the server's own files: paths on its disk, and buckets its AWS credentials reach                         |
| `ROWLAB_PRIVATE_URLS`  | on when `local`, off when `hosted` | whether web sources, S3 endpoints and model providers can be private addresses (localhost, the local network, cloud metadata)                                 |
| `ROWLAB_PRIVATE_HOSTS` |                                    | comma-separated hostnames S3 connections and model providers may reach even on a private address, e.g. your own MinIO or LiteLLM; see [below](#private-hosts) |
| `OPENROUTER_API_KEY`   |                                    | the server's own OpenRouter key, used for every organisation instead of the providers they add in Settings; on a shared server, it pays for everyone          |
| `ROWLAB_METRICS_PORT`  |                                    | serves [Prometheus metrics](/self-host/hosted#metrics) on this port, apart from the API's                                                                     |

### Private hosts

With private addresses off, a connection can't reach storage on rowlab's own network, nor a model
provider a gateway on it. `ROWLAB_PRIVATE_HOSTS` names the hosts they may reach anyway, e.g.
`s3.nas.example.com` or `litellm.example.com`. A name matches exactly, in any case: no wildcards or
address ranges, and not its subdomains, nor another name for the same address. Web sources still can't
reach those hosts.

Every rowlab user who can add a connection or provider can then aim it at those hosts. They still need
valid keys for them, but the protection against requests to private addresses no longer covers them.
Name only storage and gateways whose keys you trust to keep people apart, and let rowlab reach them in
the network as well.

## Hosted mode

| Variable                             |                                                                                                                                                                 |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ROWLAB_URL`                         | where people reach rowlab, e.g. `https://rowlab.example.com`                                                                                                    |
| `WORKOS_CLIENT_ID`, `WORKOS_API_KEY` | the WorkOS project people sign in with                                                                                                                          |
| `WORKOS_AUTHKIT_DOMAIN`              | its AuthKit domain, `https://….authkit.app`                                                                                                                     |
| `ROWLAB_SECRET_KEY`                  | encrypts saved keys (model providers, S3); any long random string. Required when `hosted`; optional locally                                                     |
| `ROWLAB_POSTHOG_TOKEN`               | a PostHog project token (`phc_…`): the web app sends product analytics there, identified by person and organisation. Unset, nothing is collected; never locally |
| `ROWLAB_POSTHOG_HOST`                | `https://eu.i.posthog.com` by default                                                                                                                           |

## Limits

The same in both modes. They are modest, so a shared server stays up; raise them for bigger data.

| Variable                  | Default |                                                                           |
| ------------------------- | ------- | ------------------------------------------------------------------------- |
| `ROWLAB_DUCKDB_MEMORY`    | `1GB`   | memory per DuckDB connection; past it, DuckDB spills to disk              |
| `ROWLAB_DUCKDB_TEMP`      | `10GB`  | how much DuckDB may spill to disk                                         |
| `ROWLAB_DUCKDB_THREADS`   | `2`     | threads per query                                                         |
| `ROWLAB_QUERY_SECONDS`    | `30`    | time per query; adding and exporting a dataset get ten times as long      |
| `ROWLAB_MAX_FILE`         | `1GB`   | the largest file to upload, download or read from S3                      |
| `ROWLAB_RUN_WAIT_SECONDS` | `300`   | a run waiting this long goes next; otherwise the run with least left does |
| `ROWLAB_RUNNER_CALLS`     | `16`    | model calls each runner makes at once: how fast one run goes              |
| `ROWLAB_DRAIN_SECONDS`    | `15`    | on `SIGTERM`, how long the API keeps serving, not ready; `0` locally      |

Sizes are written like `500MB` or `2GB`.

---
title: A shared server
description: Postgres, S3, sign-in with WorkOS, runners, and what to put in front of rowlab.
---

A shared rowlab is `ROWLAB_MODE=hosted` with Postgres, S3 and WorkOS. The pieces:

## Database and storage

`ROWLAB_DATABASE_URL=postgresql://…` and `ROWLAB_STORAGE_URL=s3://bucket/prefix`, with AWS
credentials in the environment (`AWS_ENDPOINT_URL` for storage other than AWS: R2, MinIO, VersityGW,
…). Migrations run at start. Datasets live under the prefix as Parquet; the database holds
everything else.

## Sign-in

Make a WorkOS project and set `WORKOS_CLIENT_ID`, `WORKOS_API_KEY` and `WORKOS_AUTHKIT_DOMAIN`. In
the project, add `<ROWLAB_URL>/auth/callback` as a redirect URI and `<ROWLAB_URL>/` as the sign-out
redirect.

The first person to sign in gets an organisation of their own as its admin, and invites the others
in **Settings → Members**. Roles: **admin** (settings, connections, members), **member** (adding
data, running, exporting), **verifier** (reads). Roles live in rowlab; WorkOS only says who someone
is.

For agents over MCP, under _Connect → Configuration → MCP Auth_ in WorkOS, turn Dynamic Client
Registration on and list `<ROWLAB_URL>/mcp` as a resource indicator, so clients can sign in on their
own and get tokens that are for rowlab alone. Scripts use an API key from **Settings → API keys**:
`Authorization: Bearer rl_…`.

## Keys

`ROWLAB_SECRET_KEY` encrypts the model provider keys and S3 credentials people save. Leave
`OPENROUTER_API_KEY` unset and each organisation brings its own: OpenRouter, a LiteLLM gateway, or a
server of its own, in **Settings → Providers**. Set it to pay for everyone's calls to rowlab's models
instead; models an organisation adds go to its own providers either way. A server on your own
network needs its host in [`ROWLAB_PRIVATE_HOSTS`](/self-host/configuration#private-hosts); any
other is reached over HTTPS only, so a key never travels in clear. **Settings → Usage** shows what was spent, by day, model and person; members see
their own.

**Settings → Storage** shows how much the organisation's datasets take, from their recorded sizes:
not the files in S3 connections, and not a count of the disk. There are no storage quotas or billing
yet; **Plans** is a preview of pricing.

## Analytics

With `ROWLAB_POSTHOG_TOKEN` set, the web app sends product analytics to that
[PostHog](https://posthog.com) project with the SDK's default capture, identified by the signed-in
person (id, email, name) and their organisation. Text on the page is never sent: clicks carry no
element text, and replays (if turned on in PostHog) show it masked. Without the token, and always in local mode, nothing is collected. The API and MCP send
nothing.

## Runners

With Postgres, the API and the runners that process runs can be separate processes, and several
runners share the queue, taking turns a chunk of 500 rows at a time:

```sh
rowlab serve --no-runner   # the API and web app
rowlab runner              # as many as you like
```

A run is with one runner at a time, which makes `ROWLAB_RUNNER_CALLS` (16) model calls at once. To
make one run go faster, raise it; to have more runs going at once, add runners. How far it can go is
up to each organisation's provider, key and model: calls still rate-limited after four tries become
failed answers, which resuming the run asks again. Watch `rate_limited` in the
[metrics](#metrics) after raising it.

Both stop gracefully on `SIGTERM`. The API stops taking connections and finishes the requests under
way. A runner takes no more runs, lets the model calls in flight finish (a few seconds usually; up
to about four minutes when the provider keeps timing out and is retried), then puts its run back in the
queue, where the next runner continues it at once. The chunk under way is redone, without paying again
for the replies it already got. A runner that is killed instead loses only the calls in flight, and
its run is taken back after two minutes of silence.

## Metrics

With `ROWLAB_METRICS_PORT` set, the API and every runner serve [Prometheus](https://prometheus.io)
metrics at `/metrics` on that port. It is a port of its own so that the address people reach never
shows them: let only your Prometheus reach it.

| Metric                                                      |                                                                                                                                       |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `rowlab_http_request_duration_seconds{method,route,status}` | API requests, by route template (`/v1/datasets/{dataset_id}`); MCP as `/mcp`, the web app as `other`                                  |
| `rowlab_model_call_duration_seconds{model,outcome}`         | every attempt at a model call, retries too; `outcome` is `ok`, `rate_limited`, `server_error`, `unreachable` (timed out) or `refused` |
| `rowlab_runner_calls_in_flight`, `rowlab_runner_call_slots` | a runner's call slots in use (a call waiting to be retried too) and how many it has (`ROWLAB_RUNNER_CALLS`)                           |
| `rowlab_answers_total{model,result}`                        | answers given to runs: `answered` (paid for), `cached` (free) or `failed`                                                             |
| `rowlab_model_cost_usd_total{model}`                        | USD paid for answers                                                                                                                  |
| `rowlab_model_tokens_total{model,kind}`                     | tokens billed, `input` and `output`                                                                                                   |
| `rowlab_runs_finished_total{status}`                        | runs `done` or `failed`                                                                                                               |
| `rowlab_runs{status}`                                       | runs `queued`, `running` or `stopping`, from the database                                                                             |
| `rowlab_run_queue_wait_seconds`                             | how long the run first in line has waited for its turn                                                                                |

The last two are read from the database at every scrape, so every process reports the same figures,
even when no runner is up; take their `max`. Runner capacity is the sum of
`rowlab_runner_call_slots`: when the slots in use stay near it and the queue wait grows, add a runner.
Slots full with nothing waiting is one run going as fast as `ROWLAB_RUNNER_CALLS` lets it.
As in Settings → Usage, the replies paid for in a chunk that is redone after a stop or a restart count
again, as `cached`. A series labelled by model starts when a process first sees that model, so
`increase()` misses that first step: for exact spend, use Settings → Usage.

## In front of it

Put a reverse proxy or a tunnel in front, with TLS. Rate limits per client aren't rowlab's job: set
them there (Cloudflare does this well). Nor, fully, is keeping requests off private addresses:
rowlab refuses them, but DuckDB follows redirects from S3 endpoints, so block private addresses
(other than the database, storage and any [private hosts](/self-host/configuration#private-hosts))
in the network, with a network policy or an egress firewall.

Uploads need a `Content-Length`; a proxy that strips it gets `411`. An upload well past
`ROWLAB_MAX_FILE` is refused with `413` before it is read; any file past it, uploaded or from a URL,
S3 or disk, gets a `400` saying so.

## In containers

The [image](/self-host#with-docker) runs `rowlab serve --host 0.0.0.0` on port 8000; give it the
command `runner` for a runner, or `serve --host 0.0.0.0 --no-runner` for the API alone. It runs as
any user, with a read-only filesystem, as long as `/data` is writable: with Postgres and S3 it holds
only temporary files, so an empty volume will do (DuckDB spills to it, up to `ROWLAB_DUCKDB_TEMP`).
`GET /v1/health` answers once it is ready.

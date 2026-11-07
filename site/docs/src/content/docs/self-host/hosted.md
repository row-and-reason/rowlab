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

`ROWLAB_SECRET_KEY` encrypts the OpenRouter keys and S3 credentials people save. Set
`OPENROUTER_API_KEY` on the server to pay for everyone's calls; leave it unset and each organisation
brings its own key. **Settings → Usage** shows what was spent, by day, model and person.

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

## In front of it

Put a reverse proxy or a tunnel in front, with TLS. Rate limits per client aren't rowlab's job: set
them there (Cloudflare does this well). Nor, fully, is keeping requests off private addresses:
rowlab refuses them, but DuckDB follows redirects from S3 endpoints, so block private addresses
(other than the database and storage) in the network, with a network policy or an egress firewall.

Uploads need a `Content-Length`; a proxy that strips it gets `411`. An upload well past
`ROWLAB_MAX_FILE` is refused with `413` before it is read; any file past it, uploaded or from a URL,
S3 or disk, gets a `400` saying so.

## In containers

The [image](/self-host#with-docker) runs `rowlab serve --host 0.0.0.0` on port 8000; give it the
command `runner` for a runner, or `serve --host 0.0.0.0 --no-runner` for the API alone. It runs as
any user, with a read-only filesystem, as long as `/data` is writable: with Postgres and S3 it holds
only temporary files, so an empty volume will do (DuckDB spills to it, up to `ROWLAB_DUCKDB_TEMP`).
`GET /v1/health` answers once it is ready.

# The website

Two static sites, built with [Astro](https://astro.build) and served from one nginx image:

- `www/` is [rowlab.dev](https://rowlab.dev): the landing page and pricing. Plain Astro pages with
  one stylesheet, using the app's theme colours.
- `docs/` is [docs.rowlab.dev](https://docs.rowlab.dev): [Starlight](https://starlight.astro.build),
  with the API reference generated from `../openapi.json` at build time by `starlight-openapi`.

The app itself is served by the Python package, at app.rowlab.dev.

## Working on them

Node 24 (the root `.nvmrc`) and pnpm. In either folder:

```sh
pnpm install
pnpm dev      # localhost:4321
pnpm build    # dist/
```

`make site` at the repository root builds both. Docs pages are Markdown in `docs/src/content/docs/`;
the sidebar is in `docs/astro.config.mjs`. After an API change, `make gen-client` updates
`openapi.json`, and the next docs build picks it up.

## Analytics

Both sites use [PostHog](https://posthog.com) with its default capture: pageviews, clicks, and
whatever else the project's settings in PostHog turn on, nothing hand-picked in code. The token
comes from the build environment, so a build without
`PUBLIC_POSTHOG_TOKEN` sends nothing, and the script also checks that the page is on the site's
real origin, so a production build served elsewhere sends nothing either.

| Variable               |                                       |
| ---------------------- | ------------------------------------- |
| `PUBLIC_POSTHOG_TOKEN` | the PostHog project's token           |
| `PUBLIC_POSTHOG_HOST`  | `https://eu.i.posthog.com` by default |

The project is [rowlab](https://eu.posthog.com/project/338538) in Row & Reason's PostHog; its token,
`phc_pUVWTmhSNyyuAFHec6mhqYVT6u5CaeCKGstjqpzmchxe`, is public by design (it ships in the page).

The app does the same from `web/src/lib/analytics.ts`, with the token served by the API at runtime
(`ROWLAB_POSTHOG_TOKEN`, hosted only), identified as the signed-in person and their organisation.
Same project, so a visitor who signs in links up with their earlier visits to the sites.

## The image

```sh
docker build -f site/Dockerfile --build-arg PUBLIC_POSTHOG_TOKEN=phc_… -t rowlab-site .
docker run --rm -p 8080:8080 rowlab-site
curl -H 'Host: rowlab.dev' localhost:8080/pricing
curl -H 'Host: docs.rowlab.dev' localhost:8080/get-started/
```

nginx picks the site by hostname, listens on 8080, runs as any user, and answers `/healthz`.
Cloudflare caches what it serves; the pod sees little traffic.

## Branding and link previews

All three sites share the R mark, favicon set and social-card design. The source and
regeneration command are in [`../brand/README.md`](../brand/README.md). Marketing
pages and docs articles have page-specific metadata and preview images; generated
API pages share an API-reference card. Regenerate assets (`make brand`) when adding a docs article.
The app uses generic previews to avoid exposing workspace data and supports a
build-time `NEXT_PUBLIC_APP_URL` override for its canonical origin.

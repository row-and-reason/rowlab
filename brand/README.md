# rowlab branding

The rounded, single-stroke R belongs to the same visual family as Periplus and Stolosio.
Keep the lowercase wordmark, monochrome chrome and violet accent used by the app.
`mark.svg` is the shared source. Generated assets are committed so production builds
need no image-generation step or additional fonts.

Regenerate from the repository root after installing the docs dependencies:

```sh
pnpm --dir site/docs install --frozen-lockfile
node brand/generate.mjs
```

This writes SVG marks and wordmarks, adaptive SVG favicons, 16/32/48px ICO fallbacks,
180px Apple icons, and 1200×630 PNG social cards into all three sites. It also creates
one card per Markdown docs page and the docs card manifest. Run it when adding or
renaming a docs page. API endpoints share an API-reference image while retaining
page-specific titles and descriptions.

Marketing and docs use their configured production origins. The app defaults to
`https://app.rowlab.dev`; set `NEXT_PUBLIC_APP_URL` at build time for another public
origin. Its metadata is generic and marked noindex: dataset names, prompts, query
parameters and organization information never enter link previews.

Use Node 24 for site builds. The docs renderer is externalized and explicitly
installed so its platform-specific native binding resolves in the prerender build.

After building all three sites, run `python3 brand/check.py` to check page titles,
unique metadata, canonical origins, social-card dimensions and icon files.

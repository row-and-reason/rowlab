# AGENTS.md

Guidance for AI agents (and humans) working in this repo. See `README.md` for what rowlab is.

## Write simple, boring code

- Use the most obvious solution that works. Plain functions over classes, standard library over a new
  dependency, explicit code over clever code.
- Build for today's requirements. No speculative abstractions, plugin systems, config switches or
  "in case we need it later" layers. When the second use case shows up, refactor then.
- Match the code around you: naming, structure, error handling and comment density.
- Keep logic in `server/src/rowlab/core/`. `api/` and `mcp/` stay thin adapters that call into `core/`.
  In `web/`, logic that doesn't render lives in `src/lib/`; components render.
- If you are unsure whether something is over-engineered, it probably is. Pick the smaller version.

## Use shadcn for UI, don't hand-craft components

- Build the web UI from [shadcn](https://ui.shadcn.com) components (`pnpm dlx shadcn@latest add <name>`
  in `web/`). Check the registry before writing any UI element: buttons, inputs, tables, dialogs,
  empty states, spinners, toasts, pagination and so on all exist.
- Don't hand-craft a component, or restyle a shadcn one beyond layout classes, unless explicitly asked.
  If nothing in the registry fits, ask before building one.
- Leave the generated files in `web/src/components/ui/` as shadcn wrote them.

## Tests guard regressions, not snapshots

- Test what would hurt if it broke: data integrity, paid calls never repeated, auth and permissions,
  migrations, and contracts the web app depends on. Go through the API or MCP the way a caller would.
- Don't assert literal catalogs, versions, prose or library behaviour (e.g. a Pydantic round-trip).
  A test that breaks on every legitimate change, and on nothing else, is a cost, not a guard.
- One test file per `core/` module. Shared fakes and helpers go in `server/tests/helpers.py`,
  fixtures in `conftest.py`. Test files never import from each other.

## Docs have one home

- Feature documentation goes in `site/docs/` (see `site/README.md`). `README.md` is the quickstart,
  principles and development setup only; `server/README.md` is the PyPI page.
- When behaviour changes, rewrite the existing text, whether docstring, doc page or comment, so it
  reads as one description. Don't add a new paragraph next to the old one.

## Make it feel like an app, not a website

- The window never scrolls; each column scrolls on its own and starts with a thin toolbar (`PaneHeader`)
  holding its title and actions. No page-style headings or hero sections.
- Dense: small control sizes (`size="sm"`/`"xs"`), no cards inside cards, lists over boxed forms.
- Settings live in toolbars and popovers (Filter ▾, Display ▾); actions on a thing live in its menu
  (right-click or "…"), not in loose buttons.
- Everything important is in the ⌘K palette, common actions get a shortcut, and shortcuts are shown in
  tooltips and menus (`TooltipButton`, `Kbd`).
- Interface chrome isn't selectable text; data (table cells) and inputs are.
- One accent colour, dark mode following the system; both come from the theme variables in `globals.css`.

## Clean up tech debt when you find it, not later

"Later" never comes. When your work touches an area with debt, fix it as part of the same change.

- **Finish what you start.** A rename, file move, API change or structural migration is done only when
  `git grep` for the old name finds nothing: code, tests, docs, config, `openapi.json`, `ROADMAP.md`.
  Never leave two names, two layouts or two ways of doing the same thing side by side.
- **Delete, don't deprecate.** This project has no external users to protect yet. Remove dead code,
  unused files, stale comments and old code paths instead of keeping them around.
- **No TODOs as a substitute for doing the work.** If something must truly be deferred, say so
  explicitly in your summary to the user so they can decide — don't bury it in a comment.
- **Fix what you notice nearby.** Small issues in the code you are already editing (misleading names,
  duplicated logic, outdated docs) get fixed in the same change. If a cleanup is large or unrelated,
  stop and ask instead of starting it halfway.
- **Leave the repo consistent.** Before you finish, `make check` (lint, test, build, site) passes (plus
  `make test-hosted` if you touched the database or storage), `openapi.json` and the web client are
  committed as `make build` regenerated them, and the README still describes reality.

## Publish, never deploy

- This repository publishes images (`.github/workflows/publish.yml`: `sha-` tags from `main`, versions
  from `v*` tags). It never deploys. Ekku's homelab decides what runs and when: it pins a published
  image in its own PR, and merging that PR deploys
  ([homelab releases](https://github.com/ekkuleivonen/homelab/blob/main/docs/kubernetes.md#releases)).
  Report *published* separately from *released to production*.

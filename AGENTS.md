# AGENTS.md

Guidance for AI agents (and humans) working in this repo. See `README.md` for what rowlab is.

## Write simple, boring code

- Use the most obvious solution that works. Plain functions over classes, standard library over a new
  dependency, explicit code over clever code.
- Build for today's requirements. No speculative abstractions, plugin systems, config switches or
  "in case we need it later" layers. When the second use case shows up, refactor then.
- Match the code around you: naming, structure, error handling and comment density.
- Keep logic in `server/src/rowlab/core/`. `api/` and `mcp/` stay thin adapters that call into `core/`.
- If you are unsure whether something is over-engineered, it probably is. Pick the smaller version.

## Use shadcn for UI, don't hand-craft components

- Build the web UI from [shadcn](https://ui.shadcn.com) components (`pnpm dlx shadcn@latest add <name>`
  in `web/`). Check the registry before writing any UI element: buttons, inputs, tables, dialogs,
  empty states, spinners, toasts, pagination and so on all exist.
- Don't hand-craft a component, or restyle a shadcn one beyond layout classes, unless explicitly asked.
  If nothing in the registry fits, ask before building one.
- Leave the generated files in `web/src/components/ui/` as shadcn wrote them.

## Clean up tech debt when you find it, not later

"Later" never comes. When your work touches an area with debt, fix it as part of the same change.

- **Finish what you start.** A rename, file move, API change or structural migration is done only when
  every reference has been updated — code, tests, docs, config and `openapi.json`. Never leave two
  names, two layouts or two ways of doing the same thing side by side.
- **Delete, don't deprecate.** This project has no external users to protect yet. Remove dead code,
  unused files, stale comments and old code paths instead of keeping them around.
- **No TODOs as a substitute for doing the work.** If something must truly be deferred, say so
  explicitly in your summary to the user so they can decide — don't bury it in a comment.
- **Fix what you notice nearby.** Small issues in the code you are already editing (misleading names,
  duplicated logic, outdated docs) get fixed in the same change. If a cleanup is large or unrelated,
  stop and ask instead of starting it halfway.
- **Leave the repo consistent.** Before you finish, check that tests pass, the generated API client is
  up to date, and the README still describes reality.

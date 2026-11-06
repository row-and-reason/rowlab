# rowlab

AI labeling, filtering, verification and analysis for tabular data.

Load a CSV or Parquet file, explore it, compose a per-row prompt from its columns, and run it through a
decision model (yes/no, choice, score — e.g. TypeSafe Jev) or a classic LLM. Get the original data back
with new columns added.

**Status:** pre-alpha, scoping. Domain: [rowlab.dev](https://rowlab.dev)

## Principles

- **Data in → process → data out.** Your storage stays the source of truth; rowlab is a workspace.
- **API first.** The web UI uses only the public API — anything the UI can do, an agent can do.
- **Easy to run.** One process, one SQLite file, one data folder: `uvx rowlab`.
- **Paid calls are never repeated.** Per-row results are stored as they complete, and responses are cached
  by `hash(model + params + questions + rendered prompt)`.

## Milestone 1 — upload, explore, compose

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/datasets` | Upload a file or pass `{path\|url}` → ingested dataset |
| `GET` | `/v1/datasets` | List datasets |
| `GET` | `/v1/datasets/{id}` | Metadata + schema |
| `DELETE` | `/v1/datasets/{id}` | Delete |
| `GET` | `/v1/datasets/{id}/profile` | Column stats + top values |
| `POST` | `/v1/datasets/{id}/query` | Filters, search, sort, paging |
| `POST` | `/v1/datasets/{id}/render` | Template + rows → rendered text, token counts, warnings |

UI: upload button, sortable/filterable table, prompt editor with drag-in column chips and a live
per-row preview.

**Next (M2):** runs with decision-model and LLM backends, sample runs, resume, cache, export.
**Later:** MCP server (`rowlab mcp` and `/mcp`), reading from and exporting to `s3://` URLs.

## Stack

- `server/` — Python: FastAPI, Pydantic, DuckDB, SQLite (`sqlite3`), packaged with `uv`
- `web/` — Next.js static export, TanStack Table, TipTap, shadcn; API client generated from `openapi.json`
- The MCP server will live in the same Python package and call the same `core/` logic as the API

## Non-goals

- Dataset versioning, lineage or branching — use git, DVC or your data lake
- Being a system of record or long-term storage
- Multi-tenant cloud hosting (for now)
- A general-purpose BI or spreadsheet tool

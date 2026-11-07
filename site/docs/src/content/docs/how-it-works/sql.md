---
title: SQL
description: One DuckDB SELECT over the table data picks rows to view, run on, and export.
---

Everywhere rowlab takes rows, it takes a DuckDB `SELECT` over one table, `data`, which is the dataset.
The same query views rows, selects the rows a run asks about, and chooses what to export.

```sql
SELECT * FROM data WHERE stars <= 2 AND length(review) > 40 ORDER BY random() LIMIT 200
```

The query runs read-only, in a connection that can see nothing but `data`. For a run or an export it
must return the dataset's row id (`SELECT *` does), since it picks rows: a run's prompts read the
dataset's own columns, and an export writes all of them, so computed columns show up when viewing
and nowhere else.

## Useful patterns

- **A sample with the hard cases**: `ORDER BY random() LIMIT 100`, or a filter for the rows that
  matter, rather than the first rows of the file.
- **A cascade**: run an expensive question only on rows a cheap one selected:
  `WHERE "delivery__jev-1.14" = true`.
- **Rows without an answer**: `WHERE "delivery__jev-1.14" IS NULL`. On a running run, those are rows
  not reached yet; on a finished one, rows the run's query didn't pick, rows whose call failed, and,
  for Extract, rows where the text didn't say.

Column names with dots or dashes need double quotes: `"team__jev-1.14"`.

## Limits

Each query gets `ROWLAB_QUERY_SECONDS` (30 by default; ten times that for adding and exporting a
dataset), `ROWLAB_DUCKDB_THREADS` threads and `ROWLAB_DUCKDB_MEMORY` of memory. DuckDB's full SQL
is available: window functions, `regexp_matches`, list and struct functions, and so on.

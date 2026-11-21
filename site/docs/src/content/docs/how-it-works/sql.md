---
title: SQL
description: One DuckDB SELECT over the table data picks rows to view, run on, and export.
---

Everywhere rowlab takes rows, it takes a DuckDB `SELECT` over one table, `data`, which is the dataset.
The same query views rows, selects the rows a run asks about, and chooses what to export.

```sql
SELECT * FROM data WHERE stars <= 2 AND length(review) > 40 ORDER BY md5('s1' || __row_id) LIMIT 200
```

The query runs read-only, in a connection that can see nothing but `data`. For a run or an export it
must return the dataset's row id (`SELECT *` does), since it picks rows: a run's prompts read the
dataset's own columns, and an export writes all of them, so computed columns show up when viewing
and nowhere else.

## Useful patterns

- **A sample**: `ORDER BY md5('s1' || __row_id) LIMIT 100`, rather than the first rows of the file.
  The order stays the same, so a run on it again asks nothing new, and a bigger sample keeps the
  smaller one. Another seed (`'s2'`) gives other rows. Add a filter for the hard cases.
- **A cascade**: run an expensive question only on rows a cheap one selected:
  `WHERE "delivery__jev-1.14" = true`.
- **Rows without an answer**: `WHERE "delivery__jev-1.14" IS NULL`: rows no run has asked yet (or a
  running run hasn't reached), rows whose call failed, and, for Extract, rows where the text didn't
  say.

Column names with dots or dashes need double quotes: `"team__jev-1.14"`.

## Limits

Each query gets `ROWLAB_QUERY_SECONDS` (30 by default; ten times that for adding and exporting a
dataset), `ROWLAB_DUCKDB_THREADS` threads and `ROWLAB_DUCKDB_MEMORY` of memory. DuckDB's full SQL
is available: window functions, `regexp_matches`, list and struct functions, and so on.

Answer columns add up: a Classify task where any of twenty options can apply has two columns per
option, for each model, so a dataset many models have answered many such tasks on has thousands.
Only the columns a query reads take memory, and all of them at once take more than a query gets. So
on such a dataset name the columns to view (`SELECT __row_id, review, "team__jev-1.14" FROM data`)
rather than `SELECT *`. The table in the app does that for you: it reads the columns it shows,
picked under **Display**, and the search looks in those. Through the API, `columns` on a query does
the same for `SELECT *`. Picking rows for a run with `SELECT *` is fine: only the row ids are read.

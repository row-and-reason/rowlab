---
title: Exporting
description: Get a dataset out as CSV, JSONL or Parquet, downloaded or written to a folder or S3.
---

Any dataset whose run is done, stopped or failed can be exported. The format is chosen at export
time, whatever the source was: CSV, JSONL or Parquet. All columns go, in the dataset's order.

## Download

From the dataset's menu, or `GET /v1/datasets/{id}/export?format=parquet`. A SQL query narrows the
rows, so an export can be a filter on an answer column:

```sql
SELECT * FROM data WHERE "delivery__jev-1.14" = true
```

The query picks rows only; it must return the dataset's row id (`SELECT *` does), and the columns
it lists make no difference.

## To a destination

Write the file where the data lives instead: a folder on the server's disk (locally, with
`ROWLAB_SERVER_FILES` on), or an `s3://` path through a storage connection. A destination ending in
`/` gets `<dataset>.<format>` in it; otherwise it is the file's name, replacing a file that is there.

Over MCP, agents export with `dataset_export`, with the same options. An agent using a hosted
rowlab gets the file onto its own machine with `dataset_download` instead: a link it downloads with
curl, for 15 minutes ([MCP](/agents/mcp#files-on-the-agents-machine)).

## Row ids

rowlab gives every row an id of its own to join answers to rows. Exports leave it out by default;
include it (`include_row_id`) when you will join an export back to a later one.

## Manually labeled datasets

Choose **Finish labeling** to lock a manual run's output, then export it like any other dataset.
The named output columns contain the entered labels; unanswered cells are null. Source data
is preserved. There are no extra human, probability or status columns, and no separate
judgment-history export.

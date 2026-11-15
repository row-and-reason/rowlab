---
title: Datasets
description: Where data comes from, how it is kept, and how answers are added to it as columns.
---

A dataset is a table rowlab has read in and keeps as Parquet. Your source, a file on disk, a URL or an
object in S3, is read once and never written to.

## Sources

CSV, JSON (an array of objects), JSONL and Parquet, plain or gzipped. The format is detected from the
content, so the file name doesn't matter. Sources:

- **Upload** from the browser, or the API's multipart endpoint.
- **A URL**, fetched by the server. On a shared server, private addresses are refused.
- **A path on the server's disk**, locally. On a shared server this is off unless the operator turns
  `ROWLAB_SERVER_FILES` on.
- **S3**, through a connection (**Settings → Storage**) that holds the bucket's credentials. Members
  use connections without seeing their secrets.

## Answer columns

A dataset is the rows of one file, each with a stable `__row_id`. Its own columns never change; runs
and people add answer columns to it, and the table `data` that SQL reads is the file's columns with
every answer column joined by row:

- **A model's answers** go in `<column>__<model>`, e.g. `delivery__jev-1.14`, with its
  [extra columns](/how-it-works/runs#tasks) beside it.
- **Labels people set** go in a column named for them, e.g. `gold`
  ([Labeling](/guides/labeling#labels-people-set)).

An answer column is often sparse: empty means not asked yet, or asked and failed. A column name keeps
its question: a task with a changed prompt, options or answer type needs a new name, so answers to two
different questions never share a column. The dataset's page, and `GET /v1/datasets/{id}`, list each
answer column with its task, its model or labels, how many rows have an answer and what it cost.

Delete an answer column (a model's answers to a task, or a column of labels) from its menu,
`DELETE /v1/datasets/{id}/answers?column=&model=` or MCP `answers_delete`, e.g. a try you no longer
want. The model replies stay kept, so asking the same again is free. Rename a dataset from its menu,
⌘K or MCP `dataset_rename`; its id and data stay the same.

This is deliberately not versioning. rowlab is a workspace between your storage and your storage;
keep the source and the exports where you keep data, and delete datasets here when you are done.

## Profile

Each column has a profile: its type, min and max, average, number of distinct values and the share
of empty cells. It is the first thing to read when writing a prompt, since it says which columns hold
the text, which the ids, and where the gaps are.

## Limits

Files up to `ROWLAB_MAX_FILE` (1 GB by default) are read, with `ROWLAB_DUCKDB_MEMORY` (1 GB) of
memory per query and the rest spilled to disk. Raise them in [Configuration](/self-host/configuration)
for bigger data.

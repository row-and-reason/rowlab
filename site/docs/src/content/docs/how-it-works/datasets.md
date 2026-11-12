---
title: Datasets
description: Where data comes from, how it is kept, and how datasets form a tree.
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

## The tree

A run never changes a dataset. It makes a new one, with the selected rows of the original and the answer
columns added, and records which dataset it came from and how. Names say where a dataset sits:
`reviews` → `reviews__1` → `reviews__1.2`. The datasets list shows the tree, and each dataset's page
says what made it: the SQL, the tasks and the models.

A 100-row run makes a 100-row result, with the original `__row_id` values. Existing results
keep their stored rows. Rename a dataset from its menu, ⌘K or MCP `dataset_rename`; IDs and
lineage stay unchanged, and descendants keep their own names.

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

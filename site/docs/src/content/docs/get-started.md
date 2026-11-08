---
title: Get started
description: Install rowlab, add a file, and run a first question on a few rows.
---

## Install

rowlab is a Python package. With [uv](https://docs.astral.sh/uv/):

```sh
uvx rowlab
```

That starts the API and the web app at [localhost:8000](http://localhost:8000), and keeps its
state (a SQLite database, and datasets as Parquet) in `~/.rowlab`. `pip install rowlab` and
`rowlab serve` do the same.

Model calls go through [OpenRouter](https://openrouter.ai). Paste a key in **Settings → Providers**,
or set `OPENROUTER_API_KEY` before starting.

## Add a dataset

Drop a file on the datasets list, or paste a URL. CSV, JSON, JSONL and Parquet are read by their
content, gzipped or not; from disk, the web, or S3 (with a connection from **Settings → Storage**).
rowlab keeps a copy as Parquet; your file is never changed.

Open the dataset to see its rows and, per column, a profile: type, range, distinct values and the
share of empty cells.

## Ask a question

Pick the rows with SQL over the table `data`, for the first try a few of them:

```sql
SELECT * FROM data WHERE stars <= 2 LIMIT 20
```

Write the question with the row's columns in it, pick an answer type and a model:

```
Is this review about delivery?
Review of a kitchen product: {{review}}
```

Answer type **yes/no**, model `typesafe/jev-1.14`, a fast decision model. The preview shows the
prompt rendered for the first rows, the number of calls, and the estimated cost. Start the run.

## Read the answers

The run makes a new dataset, `reviews__1`, with a column `delivery__jev-1.14` and its probability.
Read the answers next to the rows they came from. If the question was unclear for some rows, fix the
prompt and run again from the original dataset: the cost of twenty rows is nothing, and the same
prompt on the same row is never paid for twice in the datasets made from one file.

Then take the `LIMIT` off and run on all rows. Export the result as CSV, JSONL or Parquet when it is
done.

## Next

- [Labeling](/guides/labeling), the workflow in full.
- [Comparing models](/guides/comparing-models), before a run that costs real money.
- [MCP](/agents/mcp), to let an agent do this for you.

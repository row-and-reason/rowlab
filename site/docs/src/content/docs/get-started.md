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

Model calls go to a provider with your own key: [OpenRouter](https://openrouter.ai), an
OpenAI-compatible server such as a [LiteLLM](https://docs.litellm.ai) gateway, or a server of
decision models you run yourself. Add one in **Settings → Providers** (base URL and API key;
OpenRouter's is filled in), or set `OPENROUTER_API_KEY` before starting. An organisation can save
several, each by a name of its own. rowlab's models go to the active one, and a run keeps the
provider it started with; a gateway runs them under rowlab's model ids with an optional prefix (e.g.
`openrouter/`). Models you serve yourself are added to their own provider, and always go there (see
[Self-hosted models](/guides/self-hosted-models)). Where a provider doesn't say what a call cost,
rowlab works it out from the model's tokens and prices. A saved key is sent only to the base URL it
was saved with: to change the address, enter the key again.

## Add a dataset

Drop a file on the datasets list, or paste a URL. CSV, JSON, JSONL and Parquet are read by their
content, gzipped or not; from disk, the web, or S3 (with a connection from **Settings → Storage**).
rowlab keeps a copy as Parquet; your file is never changed.

Open the dataset to see its rows and, per column, a profile: type, range, distinct values and the
share of empty cells.

A dataset nothing has happened on for 24 hours (no run started or ended, failed ones too, and no
labels set or cleared) moves to **Settled** at the bottom of the list, and comes back when something
happens on it. An admin can settle or unsettle one by right-clicking it, choose there whether it settles by
itself, and turn settling by itself off for the whole organisation in the list's display menu.

## Ask a question

Pick the rows with SQL over the table `data`, for the first try a sample of them, in an order that
stays the same:

```sql
SELECT * FROM data ORDER BY md5('s1' || __row_id) LIMIT 20
```

Write the question with the row's columns in it, pick an answer type and a model:

```
Is this review about delivery?
Review of a kitchen product: {{review}}
```

Answer type **yes/no**, model `typesafe/jev-1.14`, a fast decision model. The preview shows the
prompt rendered for the first rows, the number of calls, and the estimated cost. Start the run.

## Read the answers

The run adds a column `delivery__jev-1.14` to the dataset, with its probability beside it, filled in
for the twenty rows. Read the answers next to the rows they came from. If the question was unclear for
some rows, fix the prompt and run it under a new column name, `delivery_v2`, on the same rows: the
cost of twenty rows is nothing.

Then take the `LIMIT` off and run the same task on all rows: the twenty answers already there are not
asked or paid for again. Export the dataset as CSV, JSONL or Parquet when it is done.

## Next

- [Labeling](/guides/labeling), the workflow in full.
- [Comparing models](/guides/comparing-models), before a run that costs real money.
- [MCP](/agents/mcp), to let an agent do this for you.
- [Python SDK](/agents/python), to do it from a script or a notebook.

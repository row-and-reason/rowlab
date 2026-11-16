---
title: Changelog
description: What changed in each release.
---

## Unreleased

rowlab is pre-alpha, on its way to a first release. What is in it today:

- Datasets from CSV, JSON, JSONL and Parquet; from upload, URL, disk or S3.
- Runs with Classify, Extract and Write tasks, on decision models and LLMs through your model
  provider: rowlab's picked list first (recommended ones at the top), or any other in OpenRouter's
  catalog, at OpenRouter's current prices, or models of your own, such as open-weight models and
  fine-tuned checkpoints you serve with vLLM; answers added to the dataset as columns, only those it is
  missing asked and replies kept so no call is paid for twice, and estimates before a run.
- Labels people set, in columns of their own, on any rows, before or after models run.
- Comparing answer columns, against a reference, on the rows they all have answers in.
- Exports as CSV, JSONL or Parquet, to a download, a folder or S3.
- Model providers on your own key: OpenRouter, an OpenAI-compatible server (a LiteLLM gateway, or
  vLLM), or a System One server of decision models; several per organisation, one active for
  rowlab's models, and each of your own models on its own.
- Organisations, sign-in with WorkOS, roles, API keys and a usage ledger for shared servers.
- An MCP server with the same work as tools, and skills for agents. It keeps no sessions, so
  deploys don't disconnect agents, and on a hosted rowlab agents upload and download files with
  short-lived links.
- A Python SDK, `rowlab-python-sdk`: a typed client to upload, run, export and compare from scripts
  and notebooks, and to add your own models, such as each checkpoint a training script saves.

## rowlab-python-sdk 0.2.0

For the server's answers as columns of the dataset you uploaded; 0.1.0 doesn't work against it.

- A run adds its answers to the dataset as columns, `run.columns`, instead of making a new dataset:
  export and compare `ds.id`. Running the same task again asks only for the answers still missing,
  so `runs.resume` is gone.
- Labels go in columns of their own with `datasets.set_labels`, on any rows, instead of manual runs:
  `runs.create(method=...)`, `runs.save_answers` and `runs.finish` are gone.
- New: `datasets.list` (`DatasetSummary`), `datasets.delete_answers`, `runs.list`,
  `compare(rows="pairwise")`, `models.list(all=True)` for OpenRouter's whole catalog, `Model.listed`,
  and `Dataset.answers`, each an `AnswerColumn`. `Dataset.parent_id` and `branch` are gone.

---
title: Changelog
description: What changed in each release.
---

## Unreleased

rowlab is pre-alpha, on its way to a first release. What is in it today:

- Datasets from CSV, JSON, JSONL and Parquet; from upload, URL, disk or S3.
- Runs with Classify, Extract and Write tasks, decision models and LLMs through OpenRouter, replies
  kept with the datasets they made so no call in a dataset's tree is paid for twice, and estimates
  before a run.
- Comparing answer columns, against a reference.
- Exports as CSV, JSONL or Parquet, to a download, a folder or S3.
- Organisations, sign-in with WorkOS, roles, API keys and a usage ledger for shared servers.
- An MCP server with the same work as tools, and skills for agents. It keeps no sessions, so
  deploys don't disconnect agents, and on a hosted rowlab agents upload and download files with
  short-lived links.

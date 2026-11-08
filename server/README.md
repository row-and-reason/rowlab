# rowlab

Ask a question of every row. rowlab labels, extracts and rewrites tabular data with AI: add a CSV,
JSON, JSONL or Parquet file, write the question from the row's own columns, try it on twenty rows,
then run it on a million. Every run makes a new dataset of the selected rows with the answers added;
your data is never changed in place.

```sh
uvx rowlab
```

Open [localhost:8000](http://localhost:8000), paste an [OpenRouter](https://openrouter.ai) key in
Settings, add a file, and ask it something.

- Docs: [docs.rowlab.dev](https://docs.rowlab.dev)
- Source, issues and contributing:
  [github.com/row-and-reason/rowlab](https://github.com/row-and-reason/rowlab)
- Hosted: [app.rowlab.dev](https://app.rowlab.dev)

Open source under Apache-2.0, by [Row & Reason](https://rowlab.dev).

## Agent setup and dataset names

Open **Settings → Connect agents** for copyable Codex and Claude Code commands, including sign-in
on hosted servers and installation of the single Rowlab skill. The commands use this server's URL.
Rename imports or run results from the dataset menu, the command palette, or MCP `dataset_rename`.
Names are display labels; IDs and lineage stay unchanged.

MCP `models_list` returns 20 models by default with `total` and `next_offset`; filter by `search` or
`kind`, or page with `offset` and `limit` (up to 100). `columns_compare` defaults to a compact summary
with per-class precision and recall; use `detail="full"` for distributions and all drill-down filters.
New sampled runs contain only selected rows, preserving source `__row_id` values. Existing result
datasets keep their stored rows; rerun from the source to create a result using the new behavior.

### Manual runs

`POST /v1/datasets/{id}/runs` accepts `method: "manual"` (the default is `"llm"`).
It freezes the tasks and selected rows, creates the output dataset, and waits for labels in
status `manual`. There are no model calls or provider-key requirements. All task types work;
output columns use task names without model suffixes, probabilities or status columns.

Use `PUT /v1/runs/{id}/tasks/{task_id}/answers` with
`{"answers": [{"row_id": 0, "value": true}]}` (up to 1,000 answers).
Yes/no takes a boolean; pick one and scale take an option name; pick any takes a list of
option names; write takes text; extract takes an object keyed by field name. Null clears.
`POST /v1/runs/{id}/finish` freezes the output with unanswered cells null. Repeating finish
is safe. Completed outputs use the existing query, compare and export interfaces.

Manual saves reuse the run's typed Parquet parts, rewriting only affected chunks of at most
500 source row IDs. No per-answer database records, retry receipts or history are retained.
Saves and finishing serialize on the run. Last saved value wins; retry an interrupted batch
with the same values, since a batch spanning parts can be partially saved. After a crash
before finish commits, readers still use the parts and finishing can be retried. Deleting
the output dataset deletes its run and files. Manual runs ask no models, so keep no model replies.

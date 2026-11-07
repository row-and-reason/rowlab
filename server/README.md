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
on hosted servers and installation of all three rowlab skills. The commands use this server's URL.
Rename imports or run results from the dataset menu, the command palette, or MCP `dataset_rename`.
Names are display labels; IDs and lineage stay unchanged.

MCP `models_list` returns 20 models by default with `total` and `next_offset`; filter by `search` or
`kind`, or page with `offset` and `limit` (up to 100). `columns_compare` defaults to a compact summary
with per-class precision and recall; use `detail="full"` for distributions and all drill-down filters.
New sampled runs contain only selected rows, preserving source `__row_id` values. Existing result
datasets keep their stored rows; rerun from the source to create a result using the new behavior.

---
title: Python SDK
description: Drive rowlab from a script or a notebook with the typed rowlab-python-sdk client.
---

`rowlab-python-sdk` is a typed client for the [API](/api/), for work that should live in code: the
dataset, the prompt, the models and the run ID, recorded in a script or a marimo notebook. Its models
are generated from the API's schema, so every reply is a typed object your editor can complete.

```sh
pip install 'rowlab-python-sdk[polars]'    # or [notebook], with marimo
```

It needs Python 3.11 or newer. Without the `polars` extra everything works except reading an export
into a DataFrame.

## Connect

`Client()` connects to the hosted rowlab, [app.rowlab.dev](https://app.rowlab.dev), with an API key
from **Settings → API keys**:

```sh
export ROWLAB_API_KEY=rl_…
```

A local rowlab (`uvx rowlab`) needs no key:

```sh
export ROWLAB_API_URL=http://localhost:8000
```

Both can be passed instead: `Client("http://localhost:8000")`, `Client(api_key="rl_…")`. A key is
sent only over HTTPS, or to localhost. Each request may take up to five minutes; uploading or
exporting a very large file may need more: `Client(timeout=900)`.

## Label, export, compare

```python
from rowlab_sdk import Client, Task

with Client() as rl:
    ds = rl.datasets.upload(df, name="listings")       # a polars or pandas DataFrame, a path, or bytes
    task = Task(
        template="Is this listing about transport? {{text}}",
        type="yes_no",
        column="transport",
        models=["typesafe/jev-1.14"],
    )
    rl.runs.estimate(ds.id, task)                       # rows, calls, cost; nothing is asked
    run = rl.runs.wait(rl.runs.create(ds.id, task).id)
    assert run.status == "done", run.error

    out = rl.datasets.export(run.dataset_id)            # a polars DataFrame
    cmp = rl.datasets.compare(run.dataset_id, run.columns, reference="manual_answer")
    cmp.agreement.alpha, cmp.agreement.alpha_level
    acc = cmp.reference[0]
    acc.accuracy, acc.accuracy_ci, acc.calibration.ece, acc.usd_per_correct
```

- A task needs only its `template` and `type`; the column and models default to ones that suit the
  type. `rl.models.list()` has the models and their prices. `sql=` picks the rows to run on, e.g.
  `sql="SELECT * FROM data LIMIT 20"` to try a prompt first.
- A run makes a new dataset, `run.dataset_id`, with the answers added: export and compare that, not
  the dataset you uploaded. Its answer columns are `run.columns`, named `{column}__{model}`.
- `wait` returns once the run is done, failed or stopped, without raising: check `run.status`, and
  `run.costs[i].failed` for rows without an answer (`rl.runs.resume(run.id)` asks them again). With
  `timeout=`, it raises `TimeoutError` when that passes; the run carries on.
- The `reference` is a column you uploaded with the data, or the labels of an earlier run on the same
  dataset tree. [Comparing models](/guides/comparing-models) says what each number means.
  `calibration` is `None` for a column without a `_proba` column next to it, and `cmp.costs` lists
  only the columns a run wrote.
- `export(..., format="csv", path="out.csv")` writes a file instead; `sql=` exports only some rows.

## Manual labels

A run with `method="manual"` asks no model: it waits for labels, by `__row_id`, in columns named
after its tasks.

```python
run = rl.runs.create(ds.id, Task(template="Transport? {{text}}", column="manual_answer"), method="manual")
task_id = run.config.tasks[0].id
rl.runs.save_answers(run.id, task_id, {0: True, 1: False, 2: None})   # None clears a label
rl.runs.finish(run.id)                                                  # freezes the dataset
```

The values follow the [answer type](/how-it-works/answer-types), as for
[manual runs](/how-it-works/runs#manual-runs); any number of answers can be saved at once.

## Errors

Everything the client raises is a `RowlabError`:

- `ApiError`: rowlab refused the request. `status_code` and `detail` are the API's; the message says
  what to change.
- `TransportError`: rowlab couldn't be reached. Nothing is retried, because a request that starts a
  run may have gone through: check with `rl.runs.get` before trying again.
- `ConfigurationError`: a bad URL or key, raised before anything is sent.
- `ResponseError`: a reply this version doesn't understand; upgrade the SDK.

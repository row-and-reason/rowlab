# rowlab-python-sdk

A typed Python client for [rowlab](https://rowlab.dev): upload a dataset, label it with models or
by hand, then export and compare the answers, from a script or a notebook.

```sh
pip install 'rowlab-python-sdk[polars]'
```

```python
from rowlab_sdk import Client, Task

with Client() as rl:  # app.rowlab.dev with ROWLAB_API_KEY, or ROWLAB_API_URL=http://localhost:8000
    ds = rl.datasets.upload(df, name="reviews")
    task = Task(template="Is this review negative? {{review}}", type="yes_no")
    run = rl.runs.wait(rl.runs.create(ds.id, task).id)
    answers = rl.datasets.export(run.dataset_id)
```

Python 3.11 or newer. The guide is at
[docs.rowlab.dev/agents/python](https://docs.rowlab.dev/agents/python); the code is in
[row-and-reason/rowlab](https://github.com/row-and-reason/rowlab/tree/main/sdk), Apache-2.0.

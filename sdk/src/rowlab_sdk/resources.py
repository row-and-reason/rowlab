"""`rl.datasets`, `rl.runs` and `rl.models`: one method per API call, named and typed like the API."""

from __future__ import annotations

import io
import time
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ._models import (
    AnswerColumn,
    Comparison,
    Dataset,
    DatasetSummary,
    Estimate,
    Model,
    Run,
    TaskInput,
)

if TYPE_CHECKING:
    import polars

    from .client import Client

# A run with one of these statuses won't change by itself.
INACTIVE = {"done", "failed", "stopped"}
# The most labels `PUT /v1/datasets/{id}/labels/{column}` takes at once.
LABELS_PER_REQUEST = 1000


def _polars():
    try:
        import polars
    except ImportError:
        raise ImportError(
            "Reading an export into a DataFrame needs polars: "
            "pip install 'rowlab-python-sdk[polars]'."
        ) from None
    return polars


def _file(data: Any, name: str | None) -> tuple[str, bytes]:
    """The file name and content to upload. The server names the dataset after the file name,
    without its extension, and detects the format from the content."""
    if hasattr(data, "write_parquet"):  # polars
        buffer = io.BytesIO()
        data.write_parquet(buffer)
        return f"{name or 'dataframe'}.parquet", buffer.getvalue()
    if hasattr(data, "to_parquet"):  # pandas
        buffer = io.BytesIO()
        data.to_parquet(buffer)
        return f"{name or 'dataframe'}.parquet", buffer.getvalue()
    if isinstance(data, bytes):
        return name or "upload", data
    if isinstance(data, (str, PathLike)):
        path = Path(data)
        return name or path.name, path.read_bytes()
    raise TypeError("Upload a DataFrame, a file path or bytes.")


def _task(task: TaskInput) -> dict:
    # Only what the caller set: the server picks the column and models that suit each task's type.
    return task.model_dump(mode="json", exclude_unset=True)


def _run_request(tasks: tuple[TaskInput, ...], sql: str | None) -> dict:
    body: dict = {"tasks": [_task(task) for task in tasks]}
    if sql is not None:
        body["sql"] = sql
    return body


class DatasetsResource:
    def __init__(self, client: Client):
        self._client = client

    def upload(self, data: Any, *, name: str | None = None) -> Dataset:
        """Add a dataset from a polars or pandas DataFrame, a CSV, TSV, JSON(L) or Parquet file
        (by path), or that file's bytes. `name` defaults to the file's name."""
        filename, content = _file(data, name)
        return self._client._request(
            "POST", "v1/datasets", Dataset, files={"file": (filename, content)}
        )

    def list(self) -> list[DatasetSummary]:
        """The organisation's datasets, newest first; `get` one for its columns and answers."""
        return self._client._request("GET", "v1/datasets", list[DatasetSummary])

    def get(self, id: str) -> Dataset:
        """The dataset with every column of `data`, and what its answer columns are: the task, the
        model or labels, how many rows have an answer and what they cost."""
        return self._client._request("GET", f"v1/datasets/{id}", Dataset)

    def export(
        self,
        id: str,
        *,
        sql: str | None = None,
        include_row_id: bool = False,
        format: Literal["csv", "jsonl", "parquet"] = "parquet",
        path: str | PathLike | None = None,
    ) -> polars.DataFrame | Path:
        """The dataset, or the rows `sql` picks (it must return `__row_id`): as a polars DataFrame,
        or with `path`, written to that file in `format`."""
        params: dict = {"format": format, "include_row_id": include_row_id}
        if sql is not None:
            params["sql"] = sql
        if path is not None:
            path = Path(path)
            self._client._download(f"v1/datasets/{id}/export", path, params=params)
            return path
        if format != "parquet":
            raise ValueError("Give a `path` to export as CSV or JSONL.")
        polars = _polars()
        content = self._client._content("GET", f"v1/datasets/{id}/export", params=params)
        return polars.read_parquet(io.BytesIO(content))

    def compare(
        self,
        id: str,
        columns: list[str],
        *,
        reference: str | None = None,
        tolerance: float | None = None,
        ignore_case: bool = False,
        trim_whitespace: bool = False,
        sql: str | None = None,
        rows: Literal["common", "pairwise"] = "common",
    ) -> Comparison:
        """How often the columns agree, and with a `reference`, each one's accuracy against it. By
        default every statistic uses the rows where all the columns have a value; with
        `rows="pairwise"`, each uses the rows where its own columns do."""
        body: dict = {
            "columns": columns,
            "ignore_case": ignore_case,
            "trim_whitespace": trim_whitespace,
            "rows": rows,
        }
        for key, value in {"reference": reference, "tolerance": tolerance, "sql": sql}.items():
            if value is not None:
                body[key] = value
        return self._client._request("POST", f"v1/datasets/{id}/compare", Comparison, json=body)

    def set_labels(
        self,
        id: str,
        column: str,
        labels: Mapping[int, Any],
        *,
        task: TaskInput | None = None,
    ) -> AnswerColumn:
        """Set, change or clear labels in `column`, by `__row_id`; `None` clears one. The first
        labels in a column need the `task` they answer, which makes them a typed column to compare
        models against. Each 1,000 labels are saved whole or not at all."""
        items = [{"row_id": row_id, "value": value} for row_id, value in labels.items()]
        if not items:
            raise ValueError("Give at least one label.")
        body: dict = {}
        if task is not None:
            body["task"] = _task(task)
        for start in range(0, len(items), LABELS_PER_REQUEST):
            body["labels"] = items[start : start + LABELS_PER_REQUEST]
            answers = self._client._request(
                "PUT", f"v1/datasets/{id}/labels/{column}", AnswerColumn, json=body
            )
        return answers

    def delete_answers(self, id: str, column: str, *, model: str | None = None) -> None:
        """Delete a task's answers from `model`, or without one, its labels. Model replies are
        kept, so asking the same again is free. Stop a run still asking for them first."""
        params = {"column": column}
        if model is not None:
            params["model"] = model
        self._client._content("DELETE", f"v1/datasets/{id}/answers", params=params)


class RunsResource:
    def __init__(self, client: Client):
        self._client = client

    def estimate(
        self,
        dataset_id: str,
        *tasks: TaskInput,
        sql: str | None = None,
    ) -> Estimate:
        """What `create` with the same arguments would take and roughly cost. Nothing is asked."""
        return self._client._request(
            "POST",
            f"v1/datasets/{dataset_id}/estimate",
            Estimate,
            json=_run_request(tasks, sql),
        )

    def create(self, dataset_id: str, *tasks: TaskInput, sql: str | None = None) -> Run:
        """Start a run of every task with every model on the rows `sql` picks (all by default). It
        adds the answers to the dataset as columns, `<column>__<model>`, which fill in as it goes;
        `wait` for it. It asks only for answers the dataset doesn't have yet: a run on all rows
        after a try on a few pays only for the rest, and creating the same run again after a stop
        or a failure asks only what is still missing."""
        return self._client._request(
            "POST",
            f"v1/datasets/{dataset_id}/runs",
            Run,
            json=_run_request(tasks, sql),
        )

    def list(self, dataset_id: str) -> list[Run]:
        """The dataset's runs, newest first."""
        return self._client._request("GET", f"v1/datasets/{dataset_id}/runs", list[Run])

    def get(self, id: str) -> Run:
        return self._client._request("GET", f"v1/runs/{id}", Run)

    def stop(self, id: str) -> Run:
        """Stop after the calls in flight. `create` the same run again to ask what it didn't get
        to; answers it paid for are free."""
        return self._client._request("POST", f"v1/runs/{id}/stop", Run)

    def wait(self, id: str, *, interval: float = 2.0, timeout: float | None = None) -> Run:
        """The run once it's done, failed or stopped. It doesn't raise when the run failed: check
        `run.status`, and `run.costs[i].failed` for rows without an answer. Raises `TimeoutError` after `timeout` seconds; the run carries on regardless."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            run = self.get(id)
            if run.status in INACTIVE:
                return run
            if deadline is None:
                time.sleep(interval)
                continue
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"Run {id} is still {run.status} after {timeout} seconds.")
            time.sleep(min(interval, left))


class ModelsResource:
    def __init__(self, client: Client):
        self._client = client

    def list(self, *, all: bool = False) -> list[Model]:
        """Decision models and LLMs, with their prices: rowlab's list, recommended first; with `all`,
        the rest of OpenRouter's catalog after it. Any of them can be asked, by id."""
        params = {"all": "true"} if all else None
        return self._client._request("GET", "v1/utils/models", list[Model], params=params)

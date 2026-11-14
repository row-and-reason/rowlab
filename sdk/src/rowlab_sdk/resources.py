"""`rl.datasets`, `rl.runs` and `rl.models`: one method per API call, named and typed like the API."""

from __future__ import annotations

import io
import time
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ._models import Comparison, Dataset, Estimate, Model, Run, TaskInput

if TYPE_CHECKING:
    import polars

    from .client import Client

# A run with one of these statuses won't change by itself.
INACTIVE = {"done", "failed", "stopped", "manual"}
# The most answers `PUT /v1/runs/{id}/tasks/{task_id}/answers` takes at once.
ANSWERS_PER_REQUEST = 1000


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


def _run_request(tasks: tuple[TaskInput, ...], sql: str | None, method: str) -> dict:
    # Only what the caller set: the server picks the column and models that suit each task's type.
    body: dict = {
        "tasks": [task.model_dump(mode="json", exclude_unset=True) for task in tasks],
        "method": method,
    }
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

    def get(self, id: str) -> Dataset:
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
    ) -> Comparison:
        """How often the columns agree, and with a `reference`, each one's accuracy against it."""
        body: dict = {
            "columns": columns,
            "ignore_case": ignore_case,
            "trim_whitespace": trim_whitespace,
        }
        for key, value in {"reference": reference, "tolerance": tolerance, "sql": sql}.items():
            if value is not None:
                body[key] = value
        return self._client._request("POST", f"v1/datasets/{id}/compare", Comparison, json=body)


class RunsResource:
    def __init__(self, client: Client):
        self._client = client

    def estimate(
        self,
        dataset_id: str,
        *tasks: TaskInput,
        sql: str | None = None,
        method: Literal["llm", "manual"] = "llm",
    ) -> Estimate:
        """What `create` with the same arguments would take and roughly cost. Nothing is asked."""
        return self._client._request(
            "POST",
            f"v1/datasets/{dataset_id}/estimate",
            Estimate,
            json=_run_request(tasks, sql, method),
        )

    def create(
        self,
        dataset_id: str,
        *tasks: TaskInput,
        sql: str | None = None,
        method: Literal["llm", "manual"] = "llm",
    ) -> Run:
        """Start a run of every task with every model on the rows `sql` picks (all by default). It
        makes a new dataset, `run.dataset_id`, whose answer columns fill in as it goes; `wait` for
        it. A manual run waits for `save_answers` and `finish` instead."""
        return self._client._request(
            "POST",
            f"v1/datasets/{dataset_id}/runs",
            Run,
            json=_run_request(tasks, sql, method),
        )

    def get(self, id: str) -> Run:
        return self._client._request("GET", f"v1/runs/{id}", Run)

    def stop(self, id: str) -> Run:
        return self._client._request("POST", f"v1/runs/{id}/stop", Run)

    def resume(self, id: str) -> Run:
        """Continue a stopped or failed run, or ask a done run's failed answers again."""
        return self._client._request("POST", f"v1/runs/{id}/resume", Run)

    def wait(self, id: str, *, interval: float = 2.0, timeout: float | None = None) -> Run:
        """The run once it's done, failed, stopped or waiting for manual answers. It doesn't raise
        when the run failed: check `run.status`, and `run.costs[i].failed` for rows without an
        answer. Raises `TimeoutError` after `timeout` seconds; the run carries on regardless."""
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

    def save_answers(self, id: str, task_id: str, answers: Mapping[int, Any]) -> Run:
        """Set labels on a manual run, by `__row_id`; `None` clears one. `task_id` is
        `run.config.tasks[i].id`."""
        items = [{"row_id": row_id, "value": value} for row_id, value in answers.items()]
        if not items:
            return self.get(id)
        for start in range(0, len(items), ANSWERS_PER_REQUEST):
            run = self._client._request(
                "PUT",
                f"v1/runs/{id}/tasks/{task_id}/answers",
                Run,
                json={"answers": items[start : start + ANSWERS_PER_REQUEST]},
            )
        return run

    def finish(self, id: str) -> Run:
        """Finish a manual run and freeze its dataset; labels can't change after."""
        return self._client._request("POST", f"v1/runs/{id}/finish", Run)


class ModelsResource:
    def __init__(self, client: Client):
        self._client = client

    def list(self) -> list[Model]:
        """The decision models and LLMs a task can use, with their prices."""
        return self._client._request("GET", "v1/utils/models", list[Model])

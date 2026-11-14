"""The Python SDK (`sdk/`) against the real API: what a notebook does, through the SDK's own HTTP
client. Requests reach the app through a `MockTransport` that hands them to a `TestClient`, so the
SDK's headers, auth and error handling are the ones a user gets."""

from types import SimpleNamespace

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient
from rowlab_sdk import ApiError, Client, Task

from rowlab.app import create_app
from rowlab.core import runs

URL = "http://localhost"
REVIEWS = pl.DataFrame(
    {
        "review": ["Terrible product", "Love it", "Broke after a day"],
        "manual_answer": [True, False, False],
    }
)
NEGATIVE = Task(template="Is this review negative? {{review}}", type="yes_no", column="negative")


def connect(app: TestClient, api_key: str | None = None) -> Client:
    """An SDK client whose requests `app` answers."""

    def send(request: httpx.Request) -> httpx.Response:
        response = app.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.content
        )
        return httpx.Response(
            response.status_code, headers=dict(response.headers), content=response.content
        )

    return Client(URL, api_key=api_key, _transport=httpx.MockTransport(send))


@pytest.fixture
def rl(client):
    with connect(client) as rl:
        yield rl


def drain():
    """Let the runner work through the queue, as its thread would."""
    while runs.process_next():
        pass


def test_a_labelling_run_from_upload_to_comparison(rl, api_key, tmp_path):
    ds = rl.datasets.upload(REVIEWS, name="reviews")
    assert ds.name == "reviews"
    assert {"review", "manual_answer"} <= {c.name for c in ds.columns}
    assert "typesafe/jev-1.14" in {m.id for m in rl.models.list()}

    estimate = rl.runs.estimate(ds.id, NEGATIVE)
    assert (estimate.rows, estimate.problem) == (3, None)
    created = rl.runs.create(ds.id, NEGATIVE)
    drain()
    run = rl.runs.wait(created.id, interval=0)
    assert (run.status, run.columns) == ("done", ["negative__jev-1.14"])

    out = rl.datasets.export(run.dataset_id)
    assert out["negative__jev-1.14"].to_list() == [True, False, True]
    path = rl.datasets.export(run.dataset_id, format="csv", path=tmp_path / "out.csv")
    assert pl.read_csv(path)["review"].to_list() == REVIEWS["review"].to_list()

    comparison = rl.datasets.compare(run.dataset_id, run.columns, reference="manual_answer")
    [accuracy] = comparison.reference
    assert (accuracy.column, accuracy.correct, accuracy.compared) == ("negative__jev-1.14", 2, 3)

    # Answers T F T against T F F, each answered with probability 0.9 for $0.001.
    agreement = comparison.agreement
    assert (round(agreement.alpha, 3), agreement.alpha_level) == (0.444, "nominal")
    ci = accuracy.accuracy_ci
    assert (round(ci.low, 3), round(ci.high, 3)) == (0.208, 0.939)  # Wilson, 2 of 3
    calibration = accuracy.calibration
    assert (calibration.probability_column, calibration.rows) == ("negative__jev-1.14_proba", 3)
    assert (round(calibration.brier, 3), round(calibration.ece, 3)) == (0.277, 0.233)
    assert calibration.bins
    [cost] = comparison.costs
    assert (cost.column, cost.run_id, cost.model) == (run.columns[0], run.id, "typesafe/jev-1.14")
    assert (round(cost.usd, 4), cost.answered) == (0.003, 3)
    assert round(accuracy.usd_per_correct, 4) == 0.0015


def test_a_task_gets_the_servers_defaults_for_its_type(rl, client, api_key):
    ds = rl.datasets.upload(REVIEWS)
    run = rl.runs.create(ds.id, Task(template="Sum up {{review}}", type="write"))
    [task] = run.config.tasks
    [write] = [t for t in client.get("/v1/utils/task-types").json()["types"] if t["id"] == "write"]
    assert (task.column, task.models) == (write["column"], [write["model"]])


def test_wait_returns_runs_that_stopped_and_times_out_on_the_rest(rl, api_key):
    ds = rl.datasets.upload(REVIEWS)
    manual = rl.runs.create(ds.id, NEGATIVE, method="manual")
    assert rl.runs.wait(manual.id).status == "manual"

    queued = rl.runs.create(ds.id, NEGATIVE)
    with pytest.raises(TimeoutError):
        rl.runs.wait(queued.id, timeout=0)
    assert rl.runs.stop(queued.id).status == "stopped"
    assert rl.runs.resume(queued.id).status == "queued"
    rl.runs.stop(queued.id)

    broke = rl.runs.create(ds.id, Task(template="no credits", column="negative"))
    with pytest.raises(runs.KeyProblem):
        runs.process_next()
    failed = rl.runs.wait(broke.id)
    assert failed.status == "failed"
    assert failed.error.startswith("The OpenRouter key is out of credits.")


def test_wait_polls_until_its_timeout_and_no_longer(rl, api_key, monkeypatch):
    """With a fake clock, only in the SDK: the app under test keeps the real one."""
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    clock = SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
    monkeypatch.setattr("rowlab_sdk.resources.time", clock)
    queued = rl.runs.create(rl.datasets.upload(REVIEWS).id, NEGATIVE)
    with pytest.raises(TimeoutError):
        rl.runs.wait(queued.id, interval=2, timeout=5)
    assert (slept, now[0]) == ([2, 2, 1], 5)
    slept.clear()
    with pytest.raises(TimeoutError):
        rl.runs.wait(queued.id, interval=2, timeout=1)
    assert slept == [1]


def test_manual_labels_are_saved_cleared_and_frozen(rl):
    ds = rl.datasets.upload(REVIEWS)
    run = rl.runs.create(ds.id, NEGATIVE, method="manual")
    task_id = run.config.tasks[0].id
    rl.runs.save_answers(run.id, task_id, {0: True, 1: False})
    rl.runs.save_answers(run.id, task_id, {1: None})
    assert rl.runs.save_answers(run.id, task_id, {}).id == run.id
    assert rl.runs.finish(run.id).status == "done"
    assert rl.datasets.export(run.dataset_id)["negative"].to_list() == [True, None, None]
    with pytest.raises(ApiError):
        rl.runs.save_answers(run.id, task_id, {2: True})


def test_saving_more_answers_than_one_request_takes(rl):
    many = pl.DataFrame({"review": [f"Review {i}" for i in range(2500)]})
    ds = rl.datasets.upload(many, name="many")
    run = rl.runs.create(ds.id, NEGATIVE, method="manual")
    rl.runs.save_answers(run.id, run.config.tasks[0].id, {i: i % 2 == 0 for i in range(2500)})
    rl.runs.finish(run.id)
    labels = rl.datasets.export(run.dataset_id, include_row_id=True).sort("__row_id")["negative"]
    assert labels.to_list() == [i % 2 == 0 for i in range(2500)]


def test_hosted_needs_a_valid_key(hosted):
    ada = hosted("ada@example.com")
    key = ada.post("/v1/settings/api-keys", json={"name": "notebook"}).json()["key"]
    app = TestClient(create_app())

    with connect(app, api_key=key) as rl:
        ds = rl.datasets.upload(b"name\nAda\nAlan\n", name="people")
        assert (ds.name, ds.row_count) == ("people", 2)
    with connect(app, api_key="rl_wrong") as rl, pytest.raises(ApiError) as caught:
        rl.datasets.get(ds.id)
    assert caught.value.status_code == 401

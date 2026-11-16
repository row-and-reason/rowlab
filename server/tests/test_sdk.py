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
    assert "review" in {c.name for c in ds.columns}
    assert [d.id for d in rl.datasets.list()] == [ds.id]
    assert "typesafe/jev-1.14" in {m.id for m in rl.models.list()}

    sample = rl.runs.create(ds.id, NEGATIVE, sql="SELECT * FROM data WHERE __row_id < 2")
    drain()
    run = rl.runs.wait(sample.id, interval=0)
    assert (run.status, run.dataset_id, run.columns) == ("done", ds.id, ["negative__jev-1.14"])
    assert rl.datasets.export(ds.id)["negative__jev-1.14"].to_list() == [True, False, None]

    # All rows: only the one the sample didn't answer is asked.
    estimate = rl.runs.estimate(ds.id, NEGATIVE)
    assert (estimate.rows, estimate.answered, estimate.calls, estimate.problem) == (3, 2, 1, None)
    created = rl.runs.create(ds.id, NEGATIVE)
    assert created.row_count == 1
    drain()
    run = rl.runs.wait(created.id, interval=0)
    assert [r.id for r in rl.runs.list(ds.id)] == [run.id, sample.id]

    out = rl.datasets.export(ds.id)
    assert out["negative__jev-1.14"].to_list() == [True, False, True]
    path = rl.datasets.export(ds.id, format="csv", path=tmp_path / "out.csv")
    assert pl.read_csv(path)["review"].to_list() == REVIEWS["review"].to_list()

    gold = rl.datasets.set_labels(ds.id, "gold", {0: True, 1: False, 2: False}, task=NEGATIVE)
    assert (gold.name, gold.model, gold.answered) == ("gold", None, 3)
    answers = {(a.name, a.model): a.answered for a in rl.datasets.get(ds.id).answers}
    assert answers == {("negative", "typesafe/jev-1.14"): 3, ("gold", None): 3}

    comparison = rl.datasets.compare(ds.id, run.columns, reference="gold")
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
    assert (cost.column, cost.model) == (run.columns[0], "typesafe/jev-1.14")
    assert (round(cost.usd, 4), cost.answered) == (0.003, 3)
    assert round(accuracy.usd_per_correct, 4) == 0.0015


def test_compare_uses_the_rows_every_column_has_unless_pairwise(rl, api_key):
    ds = rl.datasets.upload(REVIEWS)
    rl.runs.create(ds.id, NEGATIVE)
    drain()
    rl.datasets.set_labels(ds.id, "gold", {0: True, 1: False}, task=NEGATIVE)
    common = rl.datasets.compare(ds.id, ["negative__jev-1.14"], reference="gold")
    assert (common.scope_rows, common.rows) == (3, 2)
    pairwise = rl.datasets.compare(ds.id, ["negative__jev-1.14"], reference="gold", rows="pairwise")
    assert (pairwise.scope_rows, pairwise.rows) == (3, 3)


def test_a_task_gets_the_servers_defaults_for_its_type(rl, client, api_key):
    ds = rl.datasets.upload(REVIEWS)
    run = rl.runs.create(ds.id, Task(template="Sum up {{review}}", type="write"))
    [task] = run.config.tasks
    [write] = [t for t in client.get("/v1/utils/task-types").json()["types"] if t["id"] == "write"]
    assert (task.column, task.models) == (write["column"], [write["model"]])


def test_wait_returns_runs_that_ended_and_times_out_on_the_rest(rl, api_key):
    ds = rl.datasets.upload(REVIEWS)
    queued = rl.runs.create(ds.id, NEGATIVE)
    with pytest.raises(TimeoutError):
        rl.runs.wait(queued.id, timeout=0)
    rl.runs.stop(queued.id)
    assert rl.runs.wait(queued.id).status == "stopped"
    # Starting it again asks for what it didn't get to.
    again = rl.runs.create(ds.id, NEGATIVE)
    assert (again.status, again.row_count) == ("queued", 3)
    rl.runs.stop(again.id)

    broke = rl.runs.create(ds.id, Task(template="no credits", column="broke"))
    with pytest.raises(runs.ProviderProblem):
        runs.process_next()
    failed = rl.runs.wait(broke.id)
    assert failed.status == "failed"
    assert failed.error.startswith("The model provider's key is out of credits.")


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


def test_labels_are_set_changed_cleared_and_deleted(rl, api_key):
    ds = rl.datasets.upload(REVIEWS)
    with pytest.raises(ApiError):  # The first labels in a column need their task.
        rl.datasets.set_labels(ds.id, "gold", {0: True})
    rl.datasets.set_labels(ds.id, "gold", {0: True, 1: False, 2: True}, task=NEGATIVE)
    gold = rl.datasets.set_labels(ds.id, "gold", {1: True, 2: None})
    assert gold.answered == 2
    assert rl.datasets.export(ds.id)["gold"].to_list() == [True, True, None]
    with pytest.raises(ApiError):  # Saved whole or not at all.
        rl.datasets.set_labels(ds.id, "gold", {0: False, 2: "maybe"})
    with pytest.raises(ValueError):
        rl.datasets.set_labels(ds.id, "gold", {})
    assert rl.datasets.export(ds.id)["gold"].to_list() == [True, True, None]

    rl.datasets.delete_answers(ds.id, "gold")
    assert rl.datasets.get(ds.id).answers == []
    with pytest.raises(ApiError):
        rl.datasets.delete_answers(ds.id, "gold")


def test_deleting_a_models_answers_keeps_its_replies(rl, api_key):
    ds = rl.datasets.upload(REVIEWS)
    rl.runs.create(ds.id, NEGATIVE)
    drain()
    rl.datasets.delete_answers(ds.id, "negative", model="typesafe/jev-1.14")
    assert rl.datasets.get(ds.id).answers == []
    rl.runs.create(ds.id, NEGATIVE)
    drain()
    [answers] = rl.datasets.get(ds.id).answers
    assert (answers.answered, answers.cost) == (3, 0)  # From the kept replies, for free.


def test_setting_more_labels_than_one_request_takes(rl):
    many = pl.DataFrame({"review": [f"Review {i}" for i in range(2500)]})
    ds = rl.datasets.upload(many, name="many")
    gold = rl.datasets.set_labels(
        ds.id, "gold", {i: i % 2 == 0 for i in range(2500)}, task=NEGATIVE
    )
    assert gold.answered == 2500
    labels = rl.datasets.export(ds.id, include_row_id=True).sort("__row_id")["gold"]
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


def test_a_fine_tuning_script_registers_each_checkpoint_and_scores_it(rl, client, api_key):
    gpu = {
        "type": "openai",
        "name": "gpu",
        "base_url": "https://gpu.example.com",
        "api_key": "sk-good",
    }
    assert client.post("/v1/settings/providers", json=gpu).status_code == 201
    ds = rl.datasets.upload(REVIEWS, name="reviews")
    for step in (100, 200):
        # Run twice, as a script restarted after a crash would: the same model is returned.
        for _ in range(2):
            ckpt = rl.models.create(
                f"ft-step-{step}", provider="gpu", upstream=f"ft-{step}", note=f"qwen3.5-4b, {step}"
            )
        rl.runs.create(ds.id, NEGATIVE.model_copy(update={"models": [ckpt.id]}))
        drain()
    columns = {c.model: c.answered for c in rl.datasets.get(ds.id).answers}
    assert columns == {"ft-step-100": 3, "ft-step-200": 3}
    assert rl.models.update("ft-step-100", note="discarded").note == "discarded"
    rl.models.delete("ft-step-100")
    assert "ft-step-100" not in {m.id for m in rl.models.list()}
    with pytest.raises(ApiError, match="was a model here before"):
        rl.models.create("ft-step-100", provider="gpu", upstream="ft-101")


def test_a_gpu_script_points_its_provider_at_each_new_machine(rl, api_key, fake):
    gpu = rl.providers.create(
        "gpu", type="systemone", base_url="https://gpu-1.example.com", api_key="sk-good"
    )
    assert {p.name for p in rl.providers.list()} == {"OpenRouter", "gpu"}
    rl.models.create("kev-base", provider="gpu", upstream="kev-latest")
    ds = rl.datasets.upload(REVIEWS, name="reviews")
    # The next session's GPU: the same provider, the same model, a new address.
    moved = rl.providers.move("gpu", base_url="https://gpu-2.example.com", api_key="sk-good")
    assert (moved.id, moved.base_url) == (gpu.id, "https://gpu-2.example.com")
    fake.urls.clear()
    rl.runs.create(ds.id, NEGATIVE.model_copy(update={"models": ["kev-base"]}))
    drain()
    assert {u for u in fake.urls if "systemone" in u} == {"https://gpu-2.example.com/v1/systemone"}

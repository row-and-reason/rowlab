import json

import pytest

from rowlab.core import runs
from rowlab.core.providers import openrouter

CSV = "review,stars\nTerrible product,1\nLove it,5\nBroke after a day,1\n"


def chat_model(id_, price, structured=True):
    return {
        "id": id_,
        "name": id_.title(),
        "pricing": {"prompt": price, "completion": "0.000001"},
        "architecture": {"output_modalities": ["text"]},
        "supported_parameters": ["structured_outputs"] if structured else [],
    }


class FakeOpenRouter:
    """Stands in for OpenRouter's HTTP API. Says yes when the prompt mentions a bad experience."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, *, api_key, body=None):
        self.calls.append((method, path, api_key, body))
        if path == "/v1/key":
            if api_key != "sk-good":
                raise openrouter.OpenRouterError("HTTP 401: Invalid key")
            return {"data": {}}
        if path == "/v1/models?output_modalities=decisions":
            return {
                "data": [
                    {"id": "typesafe/jev-1.14", "name": "Jev", "pricing": {"prompt": "0.00000004"}},
                    {"id": "a/cheap", "name": "Cheap", "pricing": {"prompt": "0.00000001"}},
                ]
            }
        if path == "/v1/models":
            return {
                "data": [
                    chat_model("x/llm", "0.000002"),
                    chat_model("y/no-schema", "0.000001", structured=False),
                ]
            }
        if path == "/v1/chat/completions":
            prompt = body["messages"][1]["content"]
            content = json.dumps({"answer": _bad(prompt), "proba": 0.8})
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.01}}
        if body["state"] == "fail":
            raise openrouter.OpenRouterError("HTTP 402: Insufficient credits")
        return {
            "answers": {"answer": {"type": "noul", "noul": 0.9 if _bad(body["state"]) else 0.1}},
            "usage": {"input_tokens": 100, "output_tokens": 1, "cost": 0.001},
        }


def _bad(text):
    return any(word in text for word in ["Terrible", "Broke"])


@pytest.fixture(autouse=True)
def inline_runs(monkeypatch):
    """Run a run's work right away instead of in a background thread."""
    monkeypatch.setattr(runs, "_start", lambda work: work())


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    fake = FakeOpenRouter()
    monkeypatch.setattr(openrouter, "_request", fake)
    monkeypatch.setattr(openrouter, "_catalog", None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return fake


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text(CSV)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


NEGATIVE = {"template": "Is this review negative? {{review}}", "column": "negative"}


@pytest.fixture
def job(client, dataset):
    response = client.post(f"/v1/datasets/{dataset['id']}/jobs", json={"tasks": [NEGATIVE]})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def api_key(client):
    assert client.put("/v1/settings/openrouter-key", json={"key": "sk-good"}).status_code == 200


def update(client, job, **config):
    response = client.put(f"/v1/jobs/{job['id']}", json={**job, **config})
    assert response.status_code == 200, response.text
    return response.json()


def run(client, job):
    return client.post(f"/v1/jobs/{job['id']}/runs").json()


def test_create_list_and_update_jobs(client, dataset, job):
    [task] = job["tasks"]
    assert task["models"] == ["typesafe/jev-1.14"]
    assert task["type"] == "yes_no"
    assert job["scope"] == {"search": "", "filters": [], "sort": [], "limit": 20}
    assert [j["id"] for j in client.get(f"/v1/datasets/{dataset['id']}/jobs").json()] == [job["id"]]

    updated = update(client, job, scope={"search": "love", "filters": [], "limit": 5})
    assert updated["scope"]["search"] == "love"
    assert updated["scope"]["limit"] == 5
    assert updated["tasks"] == job["tasks"]
    assert updated["created_at"] == job["created_at"]


def test_a_new_job_starts_with_one_empty_task_on_a_few_rows(client, dataset):
    job = client.post(f"/v1/datasets/{dataset['id']}/jobs", json={}).json()
    assert [(t["template"], t["column"]) for t in job["tasks"]] == [("", "answer")]
    assert job["scope"]["limit"] == 20


def test_jobs_are_deleted_with_their_dataset(client, dataset, job):
    client.delete(f"/v1/datasets/{dataset['id']}")
    assert client.put(f"/v1/jobs/{job['id']}", json={}).status_code == 404


def test_run_answers_each_row(client, job, api_key, fake):
    result = run(client, job)
    assert result["columns"] == ["negative__jev-1.14"]
    assert [(r["row_id"], r["values"]) for r in result["rows"]] == [
        (0, {"negative__jev-1.14": True, "negative__jev-1.14_proba": 0.9}),
        (1, {"negative__jev-1.14": False, "negative__jev-1.14_proba": pytest.approx(0.9)}),
        (2, {"negative__jev-1.14": True, "negative__jev-1.14_proba": 0.9}),
    ]
    assert result["cost"] == pytest.approx(0.003)

    # Rows are asked in parallel, so in any order.
    decisions = sorted(
        (call for call in fake.calls if call[1] == "/alpha/decisions"),
        key=lambda call: call[3]["state"],
    )
    _, _, key, body = decisions[0]
    assert key == "sk-good"
    assert body["model"] == "typesafe/jev-1.14"
    assert body["state"] == "Is this review negative? Broke after a day"
    assert body["questions"] == {
        "answer": {"type": "noul", "instructions": "Answer the question in the text."}
    }


def test_run_runs_every_task_with_every_model(client, job, api_key):
    stars = {
        "template": "How many stars? {{review}}",
        "type": "scale",
        "column": "stars",
        "options": [{"name": "1"}, {"name": "5"}],
        "models": ["x/llm"],
    }
    negative = {**NEGATIVE, "models": ["typesafe/jev-1.14", "x/llm"]}
    result = run(client, update(client, job, tasks=[negative, stars]))
    assert result["columns"] == ["negative__jev-1.14", "negative__llm", "stars__llm"]
    first = result["rows"][0]["values"]
    assert first["negative__jev-1.14"] is True
    assert first["negative__llm"] is True
    assert first["negative__llm_proba"] == 0.8
    # The fake LLM answers yes/no questions only, so the scale task fails with a format error.
    assert result["rows"][0]["errors"] == {
        "stars__llm": "The model's reply did not have the expected answer."
    }
    assert [(c["model"], c["failed"]) for c in result["costs"]] == [
        ("typesafe/jev-1.14", 0),
        ("x/llm", 0),
        ("x/llm", 3),
    ]
    assert result["cost"] == pytest.approx(0.003 + 0.03 + 0.03)


def test_run_never_pays_twice(client, job, api_key, fake):
    run(client, job)
    calls = len(fake.calls)
    again = run(client, job)
    assert len(fake.calls) == calls
    assert again["cost"] == 0


def test_run_uses_the_scope(client, job, api_key):
    scope = {
        "search": "",
        "filters": [{"column": "stars", "op": "eq", "value": "1"}],
        "sort": [{"column": "review", "desc": False}],
        "limit": 1,
    }
    result = run(client, update(client, job, scope=scope))
    # Sorted by review, "Broke after a day" (row 2) comes before "Terrible product" (row 0).
    assert [r["row_id"] for r in result["rows"]] == [2]


def test_run_is_limited_to_a_thousand_rows(client, job, api_key, monkeypatch):
    monkeypatch.setattr(runs, "MAX_RUN_ROWS", 2)
    response = client.post(f"/v1/jobs/{update(client, job, scope={'limit': None})['id']}/runs")
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "The scope has 3 rows. Runs are limited to 2 rows for now: set a limit."
    )


def test_run_reports_failed_rows(client, job, api_key):
    rows = run(client, update(client, job, tasks=[{**NEGATIVE, "template": "fail"}]))["rows"]
    assert rows[0]["errors"] == {"negative__jev-1.14": "HTTP 402: Insufficient credits"}
    assert rows[0]["values"] == {}


def test_runs_are_kept_numbered_and_frozen(client, dataset, job, api_key):
    first = run(client, job)
    assert first["number"] == 1
    assert first["row_count"] == 3
    assert first["config"]["tasks"] == job["tasks"]

    changed = update(client, job, scope={**job["scope"], "limit": 1})
    second = run(client, changed)
    assert second["number"] == 2
    assert second["row_count"] == 1

    listed = client.get(f"/v1/datasets/{dataset['id']}/runs").json()
    assert [(r["number"], r["row_count"]) for r in listed] == [(2, 1), (1, 3)]
    assert "rows" not in listed[0]

    # The first run keeps the settings and answers it ran with.
    again = client.get(f"/v1/runs/{first['id']}").json()
    assert again["config"]["scope"]["limit"] == 20
    assert again["rows"] == first["rows"]


def test_a_run_reports_its_progress_and_moves_its_dataset_to_the_top(
    client, tmp_path, dataset, job, api_key, monkeypatch
):
    other = tmp_path / "other.csv"
    other.write_text("a\n1\n")
    newer = client.post("/v1/datasets", data={"source": str(other)}).json()
    assert [d["id"] for d in client.get("/v1/datasets").json()] == [newer["id"], dataset["id"]]

    started = []
    monkeypatch.setattr(runs, "_start", started.append)
    created = run(client, job)
    assert (created["status"], created["done"], created["total"]) == ("running", 0, 3)
    listed = client.get("/v1/datasets").json()
    assert [d["id"] for d in listed] == [dataset["id"], newer["id"]]
    assert listed[0]["running"] == {
        "run_id": created["id"],
        "number": 1,
        "done": 0,
        "total": 3,
    }
    assert listed[0]["last_activity_at"] == created["created_at"]

    started[0]()
    finished = client.get(f"/v1/runs/{created['id']}").json()
    assert (finished["status"], finished["done"]) == ("done", 3)
    assert len(finished["rows"]) == 3
    assert client.get("/v1/datasets").json()[0]["running"] is None


def test_runs_cut_off_by_a_restart_are_failed(client, job, api_key, monkeypatch):
    monkeypatch.setattr(runs, "_start", lambda work: None)
    created = run(client, job)
    runs.fail_interrupted_runs()
    failed = client.get(f"/v1/runs/{created['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "The server stopped during the run."


def test_runs_are_deleted_with_their_dataset(client, dataset, job, api_key):
    created = run(client, job)
    client.delete(f"/v1/datasets/{dataset['id']}")
    assert client.get(f"/v1/runs/{created['id']}").status_code == 404


def test_run_explains_what_is_missing(client, job):
    def detail(**config):
        return run(client, update(client, job, **config))["detail"]

    assert detail() == "Set your OpenRouter API key first."
    assert detail(tasks=[]) == "Add a task."
    assert detail(tasks=[{**NEGATIVE, "template": " "}]) == "Task negative: Write the prompt."
    pick = {**NEGATIVE, "type": "pick_one", "column": "team"}
    assert detail(tasks=[pick]) == "Task team: Add at least two options."
    assert detail(tasks=[{**NEGATIVE, "models": ["nope/nope"]}]) == (
        "Task negative: Unknown model: nope/nope"
    )
    assert detail(tasks=[NEGATIVE, NEGATIVE]) == (
        "Two tasks write the same column: negative__jev-1.14."
    )


def test_saving_a_key_checks_it_and_never_returns_it(client):
    assert client.get("/v1/settings").json() == {"openrouter_key": None}
    bad = client.put("/v1/settings/openrouter-key", json={"key": "sk-bad"})
    assert bad.status_code == 400
    assert "did not accept" in bad.json()["detail"]
    saved = client.put("/v1/settings/openrouter-key", json={"key": " sk-good "})
    assert saved.json() == {"openrouter_key": "saved"}
    assert "sk-good" not in client.get("/v1/settings").text


def test_environment_key_wins(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    assert client.get("/v1/settings").json() == {"openrouter_key": "environment"}


def test_lists_decision_models_then_llms_with_structured_outputs(client):
    models = client.get("/v1/models").json()
    assert [(m["id"], m["kind"]) for m in models] == [
        ("a/cheap", "decision"),
        ("typesafe/jev-1.14", "decision"),
        ("x/llm", "llm"),
    ]
    assert models[2]["prompt_price"] == 2e-06
    assert models[2]["completion_price"] == 1e-06

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
    """Stands in for OpenRouter's HTTP API. Says yes when the prompt mentions a bad experience.

    `busy` makes the next calls fail with a rate limit; `crash_on` makes the call for that prompt
    fail once like a killed server would, with an error nothing catches; `flaky` prompts fail once,
    with an error that isn't retried."""

    def __init__(self):
        self.calls = []
        self.busy = 0
        self.crash_on = None
        self.flaky = set()

    def __call__(self, method, path, *, api_key, body=None):
        self.calls.append((method, path, api_key, body))
        if path == "/v1/key":
            if api_key != "sk-good":
                raise openrouter.OpenRouterError("HTTP 401: Invalid key", status=401)
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
                    chat_model("anthropic/claude-haiku-5.5", "0.0000001"),
                    chat_model("y/no-schema", "0.000001", structured=False),
                ]
            }
        if path == "/v1/chat/completions":
            prompt = body["messages"][1]["content"]
            schema = body["response_format"]["json_schema"]["schema"]
            content = json.dumps(_llm_reply(schema, prompt))
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.01}}
        if self.busy:
            self.busy -= 1
            raise openrouter.OpenRouterError("HTTP 429: Rate limited", status=429)
        if body["state"] == self.crash_on:
            self.crash_on = None
            raise KeyboardInterrupt
        if body["state"] in self.flaky:
            self.flaky.remove(body["state"])
            raise openrouter.OpenRouterError("HTTP 400: Provider error", status=400)
        if body["state"] == "fail":
            raise openrouter.OpenRouterError("HTTP 402: Insufficient credits", status=402)
        return {
            "answers": {"answer": {"type": "noul", "noul": 0.9 if _bad(body["state"]) else 0.1}},
            "usage": {"input_tokens": 100, "output_tokens": 1, "cost": 0.001},
        }


def _llm_reply(schema, prompt):
    """A reply with the shape the schema asks for. Yes/no answers say whether the prompt is bad."""
    reply = {}
    for name, prop in schema["properties"].items():
        if name == "answer":
            reply[name] = _bad(prompt)
        elif name == "proba":
            reply[name] = 0.8
        elif name == "reason":
            reply[name] = "Because it says so."
        elif name == "text":
            reply[name] = f"In short: {prompt}"
        else:
            reply[name] = _fake_value(prop)
    return reply


def _fake_value(prop):
    types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
    if "array" in types:
        item = prop["items"]
        return [_llm_reply(item, "")] if item["type"] == "object" else ["red", "blue"]
    if "number" in types:
        return 4
    if "boolean" in types:
        return True
    return "2024-05-01" if prop.get("description") == "YYYY-MM-DD" else "Widget"


def _bad(text):
    return any(word in text for word in ["Terrible", "Broke"])


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    fake = FakeOpenRouter()
    monkeypatch.setattr(openrouter, "_request", fake)
    monkeypatch.setattr(openrouter, "_catalog", None)
    monkeypatch.setattr(openrouter, "RETRY_BASE_SECONDS", 0)
    monkeypatch.setattr(runs, "PROGRESS_INTERVAL_SECONDS", 0.01)
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


def start(client, job):
    """Queue a run of the job, as the Run button does."""
    body = {"scope": job["scope"], "tasks": job["tasks"]}
    return client.post(f"/v1/datasets/{job['dataset_id']}/runs", json=body).json()


def run(client, job):
    """Queue a run and let the runner process it, as its thread would."""
    created = start(client, job)
    if "id" not in created:
        return created
    while runs.process_next():
        pass
    return client.get(f"/v1/runs/{created['id']}").json()


def rows(client, run_):
    """The rows of the dataset a run makes, by `__row_id`."""
    response = client.post(f"/v1/datasets/{run_['dataset_id']}/query", json={})
    return {r["__row_id"]: r for r in response.json()["rows"]}


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
    finished = run(client, job)
    assert finished["status"] == "done"
    assert (finished["done"], finished["total"]) == (3, 3)
    assert finished["columns"] == ["negative__jev-1.14"]
    assert finished["cost"] == pytest.approx(0.003)
    found = rows(client, finished)
    assert (found[0]["negative__jev-1.14"], found[0]["negative__jev-1.14_proba"]) == (True, 0.9)
    assert found[1]["negative__jev-1.14"] is False
    assert found[1]["negative__jev-1.14_proba"] == pytest.approx(0.9)

    # Rows are asked in parallel, so in any order.
    decisions = sorted(
        (call for call in fake.calls if call[1] == "/alpha/decisions"),
        key=lambda call: call[3]["state"],
    )
    _, _, key, body = decisions[0]
    assert key == "sk-good"
    assert body["state"] == "Is this review negative? Broke after a day"
    assert body["questions"] == {
        "answer": {"type": "noul", "instructions": "Answer the question in the text."}
    }


def test_a_run_makes_a_dataset_of_every_row_that_fills_in_as_it_goes(
    client, dataset, job, api_key, data_dir
):
    job = update(client, job, scope={"filters": [{"column": "stars", "op": "eq", "value": "1"}]})
    created = start(client, job)
    made = client.get(f"/v1/datasets/{created['dataset_id']}").json()
    assert (made["name"], made["source"]) == ("reviews__1", "Made from reviews")
    assert made["branch"] == "1"
    assert made["parent_id"] == dataset["id"]
    assert made["run"] == {
        "id": created["id"],
        "status": "queued",
        "done": 0,
        "failed": 0,
        "total": 2,
    }
    assert [c["name"] for c in made["columns"]] == [
        "__row_id",
        "negative__jev-1.14",
        "negative__jev-1.14_proba",
        "review",
        "stars",
    ]
    # Every row is carried over; only the rows in scope get asked.
    assert (made["row_count"], created["row_count"]) == (3, 2)
    # It is listed first, as the newest dataset, before a single answer is in.
    assert client.get("/v1/datasets").json()[0]["id"] == made["id"]
    assert [r["negative__jev-1.14"] for r in rows(client, created).values()] == [None] * 3

    while runs.process_next():
        pass
    assert [(i, r["negative__jev-1.14"]) for i, r in rows(client, created).items()] == [
        (0, True),
        (1, None),
        (2, True),
    ]
    done = client.get(f"/v1/datasets/{made['id']}").json()
    assert done["run"]["status"] == "done"
    assert done["columns"] == made["columns"]
    # Once done it is one Parquet file, like any other dataset.
    assert (data_dir / "datasets" / made["id"] / "data.parquet").is_file()


def test_run_runs_every_task_with_every_model(client, job, api_key):
    stars = {
        "template": "How many stars? {{review}}",
        "type": "scale",
        "column": "stars",
        "options": [{"name": "1"}, {"name": "5"}],
        "models": ["x/llm"],
    }
    negative = {**NEGATIVE, "models": ["typesafe/jev-1.14", "x/llm"]}
    finished = run(client, update(client, job, tasks=[negative, stars]))
    assert finished["columns"] == ["negative__jev-1.14", "negative__llm", "stars__llm"]
    first = rows(client, finished)[0]
    assert first["negative__jev-1.14"] is True
    assert first["negative__llm_proba"] == 0.8
    # The fake LLM answers yes/no questions only, so the scale task fails with a format error.
    assert first["stars__llm"] is None
    assert [(c["model"], c["failed"]) for c in finished["costs"]] == [
        ("typesafe/jev-1.14", 0),
        ("x/llm", 0),
        ("x/llm", 3),
    ]
    assert finished["cost"] == pytest.approx(0.003 + 0.03 + 0.03)


def test_runs_go_in_chunks_and_never_pay_twice(client, job, api_key, fake, monkeypatch):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 2)
    first = run(client, job)
    assert first["next_chunk"] == 2
    paid = len(fake.calls)
    again = run(client, job)
    assert len(fake.calls) == paid
    assert again["cost"] == 0
    assert [
        {k: v for k, v in r.items() if k.startswith("negative")}
        for r in rows(client, again).values()
    ] == [
        {k: v for k, v in r.items() if k.startswith("negative")}
        for r in rows(client, first).values()
    ]


def test_run_uses_the_scope(client, job, api_key):
    scope = {
        "filters": [{"column": "stars", "op": "eq", "value": "1"}],
        "sort": [{"column": "review", "desc": False}],
        "limit": 1,
    }
    finished = run(client, update(client, job, scope=scope))
    # Sorted by review, "Broke after a day" (row 2) comes before "Terrible product" (row 0).
    assert finished["row_count"] == 1
    answered = [i for i, r in rows(client, finished).items() if r["negative__jev-1.14"] is not None]
    assert answered == [2]


def test_run_retries_rate_limits(client, job, api_key, fake):
    fake.busy = 2
    finished = run(client, job)
    assert finished["costs"][0]["failed"] == 0


def test_run_reports_failed_rows(client, job, api_key):
    finished = run(client, update(client, job, tasks=[{**NEGATIVE, "template": "fail"}]))
    assert rows(client, finished)[0]["negative__jev-1.14"] is None
    assert finished["costs"][0]["failed"] == 3


def test_resuming_a_done_run_asks_its_failed_answers_again(client, job, api_key, fake):
    fake.flaky = {"Is this review negative? Love it"}
    finished = run(client, job)
    assert (finished["status"], finished["costs"][0]["failed"]) == ("done", 1)
    assert rows(client, finished)[1]["negative__jev-1.14"] is None
    made = client.get(f"/v1/datasets/{finished['dataset_id']}").json()
    assert made["run"]["failed"] == 1

    assert client.post(f"/v1/runs/{finished['id']}/resume").json()["status"] == "queued"
    asked = len(fake.calls)
    while runs.process_next():
        pass
    again = client.get(f"/v1/runs/{finished['id']}").json()
    assert (again["status"], again["costs"][0]["failed"]) == ("done", 0)
    assert rows(client, again)[1]["negative__jev-1.14"] is False
    # Only the failed answer was asked again.
    assert len(fake.calls) == asked + 1
    # Nothing failed now, so there is nothing to resume.
    assert client.post(f"/v1/runs/{finished['id']}/resume").status_code == 400


def test_a_new_job_on_a_made_dataset_starts_on_the_answered_rows(client, job, api_key):
    finished = run(client, update(client, job, scope={"limit": 2}))
    made = client.post(f"/v1/datasets/{finished['dataset_id']}/jobs", json={}).json()
    assert made["scope"] == {
        "search": "",
        "filters": [
            {
                "column": "negative__jev-1.14",
                "op": "is_not_null",
                "value": None,
                "columns": [],
                "tolerance": None,
            }
        ],
        "sort": [],
        "limit": None,
    }
    page = client.post(f"/v1/datasets/{finished['dataset_id']}/query", json=made["scope"]).json()
    assert [r["__row_id"] for r in page["rows"]] == [0, 1]


def test_a_stopped_run_resumes_where_it_was(client, job, api_key, monkeypatch):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 1)
    created = start(client, job)
    stopped = client.post(f"/v1/runs/{created['id']}/stop").json()
    assert stopped["status"] == "stopped"
    assert runs.process_next() is False

    resumed = client.post(f"/v1/runs/{created['id']}/resume").json()
    assert resumed["status"] == "queued"
    while runs.process_next():
        pass
    finished = client.get(f"/v1/runs/{created['id']}").json()
    assert (finished["status"], finished["next_chunk"]) == ("done", 3)
    assert client.post(f"/v1/runs/{created['id']}/resume").status_code == 400


def test_a_run_killed_mid_way_completes_after_a_restart_without_paying_twice(
    client, job, api_key, fake, monkeypatch
):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 1)
    fake.crash_on = "Is this review negative? Love it"  # row 1, the second chunk
    created = start(client, job)
    with pytest.raises(KeyboardInterrupt):
        runs.process_next()
    cut_off = client.get(f"/v1/runs/{created['id']}").json()
    assert (cut_off["status"], cut_off["next_chunk"]) == ("running", 1)

    # The server starts again: the run is queued and continues from its first unwritten chunk.
    runs.recover_interrupted_runs()
    while runs.process_next():
        pass
    finished = client.get(f"/v1/runs/{created['id']}").json()
    assert finished["status"] == "done"
    asked = [call[3]["state"] for call in fake.calls if call[1] == "/alpha/decisions"]
    # Each row was paid for once; the crashed call never got an answer, so it was asked again.
    assert sorted(asked) == sorted(
        [
            "Is this review negative? Terrible product",
            "Is this review negative? Love it",
            "Is this review negative? Love it",
            "Is this review negative? Broke after a day",
        ]
    )
    assert finished["cost"] == pytest.approx(0.003)


def test_made_datasets_are_named_after_their_place_in_the_tree(client, dataset, job, api_key):
    first = run(client, job)
    second = run(client, update(client, job, scope={**job["scope"], "limit": 1}))
    # Made from the first made dataset, it is numbered under it.
    made = client.post(f"/v1/datasets/{first['dataset_id']}/jobs", json={}).json()
    third = run(client, update(client, made, tasks=[{**NEGATIVE, "column": "again"}]))
    names = [
        client.get(f"/v1/datasets/{r['dataset_id']}").json()["name"] for r in (first, second, third)
    ]
    assert names == ["reviews__1", "reviews__2", "reviews__1.1"]
    # A deleted dataset's number isn't given out again.
    client.delete(f"/v1/datasets/{second['dataset_id']}")
    fourth = run(client, update(client, job, scope={**job["scope"], "limit": 2}))
    assert client.get(f"/v1/datasets/{fourth['dataset_id']}").json()["name"] == "reviews__3"
    assert (first["row_count"], second["row_count"]) == (3, 1)
    assert client.get(f"/v1/runs/{first['id']}").json()["config"]["scope"]["limit"] == 20


def test_a_run_goes_with_the_dataset_it_makes(client, dataset, job, api_key, data_dir):
    finished = run(client, job)
    # Deleting the parent keeps what was made from it: its rows were copied.
    client.delete(f"/v1/datasets/{dataset['id']}")
    made = client.get(f"/v1/datasets/{finished['dataset_id']}").json()
    assert made["row_count"] == 3
    assert client.get(f"/v1/runs/{finished['id']}").status_code == 200

    client.delete(f"/v1/datasets/{made['id']}")
    assert client.get(f"/v1/runs/{finished['id']}").status_code == 404
    assert not (data_dir / "datasets" / made["id"]).exists()


def test_a_dataset_still_being_made_cannot_be_exported_yet(client, job, api_key):
    created = start(client, job)
    export = f"/v1/datasets/{created['dataset_id']}/export"
    waiting = client.get(export, params={"format": "csv"})
    assert waiting.status_code == 400
    assert "still being made" in waiting.json()["detail"]
    while runs.process_next():
        pass
    lines = client.get(export, params={"format": "csv"}).text.splitlines()
    assert lines[0] == "negative__jev-1.14,negative__jev-1.14_proba,review,stars"
    assert lines[1] == "true,0.9,Terrible product,1"


def test_extract_writes_a_typed_column_per_field(client, dataset, api_key):
    extract = {
        "type": "extract",
        "template": "From this review: {{review}}",
        "column": "info",
        "fields": [
            "product",
            "stars:number",
            "bought:date",
            "colors:list",
            "recommends:boolean",
            {"name": "parts", "type": "items", "fields": ["name", "count:number"]},
        ],
        "reason": True,
    }
    created = client.post(f"/v1/datasets/{dataset['id']}/runs", json={"tasks": [extract]}).json()
    # Unless told otherwise, extract is asked of an LLM.
    assert created["config"]["tasks"][0]["models"] == ["anthropic/claude-haiku-5.5"]
    while runs.process_next():
        pass
    made = client.get(f"/v1/datasets/{created['dataset_id']}").json()
    types = {c["name"]: c["type"] for c in made["columns"]}
    assert {k: v for k, v in types.items() if k.startswith("info")} == {
        "info_product__claude-haiku-5.5": "VARCHAR",
        "info_stars__claude-haiku-5.5": "DOUBLE",
        "info_bought__claude-haiku-5.5": "DATE",
        "info_colors__claude-haiku-5.5": "VARCHAR[]",
        "info_recommends__claude-haiku-5.5": "BOOLEAN",
        "info_parts__claude-haiku-5.5": 'STRUCT("name" VARCHAR, count DOUBLE)[]',
        "info__claude-haiku-5.5_reason": "VARCHAR",
    }
    first = rows(client, created)[0]
    assert first["info_bought__claude-haiku-5.5"] == "2024-05-01"
    assert first["info_parts__claude-haiku-5.5"] == [{"name": "Widget", "count": 4.0}]
    assert first["info__claude-haiku-5.5_reason"] == "Because it says so."


def test_write_needs_only_a_prompt(client, dataset, api_key):
    task = {"type": "write", "template": "Summarize: {{review}}"}
    created = client.post(f"/v1/datasets/{dataset['id']}/runs", json={"tasks": [task]}).json()
    while runs.process_next():
        pass
    finished = client.get(f"/v1/runs/{created['id']}").json()
    assert finished["columns"] == ["text__claude-haiku-5.5"]
    # No scope means every row.
    assert finished["row_count"] == 3
    assert rows(client, finished)[1]["text__claude-haiku-5.5"] == "In short: Summarize: Love it"


def test_extract_write_and_reasons_need_an_llm(client, dataset, api_key):
    def problem(task):
        body = {"tasks": [{"template": "{{review}}", **task}]}
        return client.post(f"/v1/datasets/{dataset['id']}/estimate", json=body).json()["problem"]

    jev = ["typesafe/jev-1.14"]
    assert problem({"type": "write", "models": jev}) == (
        "Task text: Write needs an LLM: jev-1.14 is a decision model."
    )
    assert problem({"type": "extract", "fields": ["a"], "models": jev}).endswith(
        "Extract needs an LLM: jev-1.14 is a decision model."
    )
    assert problem({"reason": True}) == (
        "Task answer: Only LLMs give a reason: jev-1.14 is a decision model."
    )
    assert problem({"type": "extract"}) == "Task extracted: Add at least one of the fields."


def test_estimate_counts_rows_calls_and_cost(client, dataset, api_key):
    body = {
        "scope": {"limit": 2},
        "tasks": [{"template": "Bad? {{review}}", "models": ["typesafe/jev-1.14", "x/llm"]}],
    }
    estimate = client.post(f"/v1/datasets/{dataset['id']}/estimate", json=body).json()
    assert (estimate["rows"], estimate["calls"], estimate["problem"]) == (2, 4, None)
    assert 0 < estimate["cost"] < 0.01


def test_task_types_list_the_families_presets_and_field_types(client):
    types = client.get("/v1/task-types").json()
    assert [(t["id"], t["family"], t["llm_only"]) for t in types["types"]] == [
        ("yes_no", "classify", False),
        ("pick_one", "classify", False),
        ("pick_any", "classify", False),
        ("scale", "classify", False),
        ("extract", "extract", True),
        ("write", "write", True),
    ]
    assert "summarize" in [p["id"] for p in types["presets"]]
    assert "items" in [f["id"] for f in types["field_types"]]


def test_an_empty_scope_makes_nothing(client, job, api_key):
    empty = update(client, job, scope={"search": "no such review"})
    assert start(client, empty)["detail"] == "The scope has no rows."
    assert len(client.get("/v1/datasets").json()) == 1


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


def test_a_run_on_a_dataset_a_run_made_needs_new_column_names(client, job, api_key):
    finished = run(client, job)
    made = client.post(f"/v1/datasets/{finished['dataset_id']}/jobs", json={"tasks": [NEGATIVE]})
    again = run(client, made.json())
    assert again["detail"] == (
        "The dataset already has a column negative__jev-1.14. Rename the task's result column."
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
        ("anthropic/claude-haiku-5.5", "llm"),
        ("x/llm", "llm"),
    ]
    assert models[3]["prompt_price"] == 2e-06
    assert models[3]["completion_price"] == 1e-06

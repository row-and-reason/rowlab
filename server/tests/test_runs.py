import time

import pytest
from helpers import NEGATIVE, run, start, stored, stored_datasets

from rowlab.core import db, runs
from rowlab.core.config import config
from rowlab.core.providers import openrouter

CSV = "review,stars\nTerrible product,1\nLove it,5\nBroke after a day,1\n"


pytestmark = pytest.mark.usefixtures("fake")


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text(CSV)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


@pytest.fixture
def job(dataset):
    """What to run, as the UI's draft holds it: the dataset, a query for the rows, and the tasks."""
    return {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}


def update(job, **changes):
    return {**job, **changes}


def rows(client, run_):
    """The rows of the dataset a run makes, by `__row_id`."""
    response = client.post(f"/v1/datasets/{run_['dataset_id']}/query", json={})
    return {r["__row_id"]: r for r in response.json()["rows"]}


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


def test_a_run_makes_a_dataset_of_selected_rows_that_fills_in_as_it_goes(
    client, dataset, job, api_key, data_dir
):
    job = update(job, sql="SELECT * FROM data WHERE stars = 1")
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
        "error": None,
    }
    assert [c["name"] for c in made["columns"]] == [
        "__row_id",
        "negative__jev-1.14",
        "negative__jev-1.14_proba",
        "review",
        "stars",
    ]
    # Only selected rows are copied, keeping their original row IDs.
    assert (made["row_count"], created["row_count"]) == (2, 2)
    # It is listed first, as the newest dataset, before a single answer is in.
    assert client.get("/v1/datasets").json()[0]["id"] == made["id"]
    assert [r["negative__jev-1.14"] for r in rows(client, created).values()] == [None] * 2

    while runs.process_next():
        pass
    assert [(i, r["negative__jev-1.14"]) for i, r in rows(client, created).items()] == [
        (0, True),
        (2, True),
    ]
    done = client.get(f"/v1/datasets/{made['id']}").json()
    assert done["run"]["status"] == "done"
    assert done["columns"] == made["columns"]
    # Once done it is one Parquet file, like any other dataset.
    assert stored(made["id"], "data.parquet")


def test_run_runs_every_task_with_every_model(client, job, api_key):
    stars = {
        "template": "How many stars? {{review}}",
        "type": "scale",
        "column": "stars",
        "options": [{"name": "1"}, {"name": "5"}],
        "models": ["x/llm"],
    }
    negative = {**NEGATIVE, "models": ["typesafe/jev-1.14", "x/llm"]}
    finished = run(client, update(job, tasks=[negative, stars]))
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
    # Tokens as billed, three rows of the fake decision model's 100 in and 1 out.
    jev = finished["costs"][0]
    assert (jev["input_tokens"], jev["output_tokens"]) == (300, 3)


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


def test_run_asks_about_the_rows_the_query_picks(client, job, api_key):
    sql = "SELECT * FROM data WHERE stars = 1 ORDER BY review LIMIT 1"
    finished = run(client, update(job, sql=sql))
    # Sorted by review, "Broke after a day" (row 2) comes before "Terrible product" (row 0).
    assert finished["row_count"] == 1
    answered = [i for i, r in rows(client, finished).items() if r["negative__jev-1.14"] is not None]
    assert answered == [2]


def test_run_retries_rate_limits(client, job, api_key, fake):
    fake.busy = 2
    finished = run(client, job)
    assert finished["costs"][0]["failed"] == 0


def test_run_reports_failed_rows(client, job, api_key):
    finished = run(client, update(job, tasks=[{**NEGATIVE, "template": "fail"}]))
    assert rows(client, finished)[0]["negative__jev-1.14"] is None
    assert finished["costs"][0]["failed"] == 3


def test_a_key_out_of_credits_fails_the_run_until_resumed(client, job, api_key):
    created = start(client, update(job, tasks=[{**NEGATIVE, "template": "no credits"}]))
    with pytest.raises(runs.KeyProblem):
        runs.process_next()
    failed = client.get(f"/v1/runs/{created['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"].startswith("The OpenRouter key is out of credits.")
    assert "HTTP 402: Insufficient credits" in failed["error"]
    made = client.get(f"/v1/datasets/{created['dataset_id']}").json()
    assert made["run"]["error"] == failed["error"]
    assert client.post(f"/v1/runs/{created['id']}/resume").json()["status"] == "queued"


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
    assert runs.process_next()  # A turn: the first chunk.
    with pytest.raises(KeyboardInterrupt):
        runs.process_next()
    cut_off = client.get(f"/v1/runs/{created['id']}").json()
    assert (cut_off["status"], cut_off["next_chunk"]) == ("running", 1)

    # The server starts again: the run is queued and continues from its first unwritten chunk.
    runs.recover_interrupted_runs(stale_after=0)
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
    second = run(client, update(job, sql="SELECT * FROM data LIMIT 1"))
    # Made from the first made dataset, it is numbered under it.
    made = update(job, dataset_id=first["dataset_id"], tasks=[{**NEGATIVE, "column": "again"}])
    third = run(client, made)
    names = [
        client.get(f"/v1/datasets/{r['dataset_id']}").json()["name"] for r in (first, second, third)
    ]
    assert names == ["reviews__1", "reviews__2", "reviews__1.1"]
    # A deleted dataset's number isn't given out again.
    client.delete(f"/v1/datasets/{second['dataset_id']}")
    fourth = run(client, update(job, sql="SELECT * FROM data LIMIT 2"))
    assert client.get(f"/v1/datasets/{fourth['dataset_id']}").json()["name"] == "reviews__3"
    assert (first["row_count"], second["row_count"]) == (3, 1)
    assert client.get(f"/v1/runs/{fourth['id']}").json()["config"]["sql"] == (
        "SELECT * FROM data LIMIT 2"
    )


def test_a_run_goes_with_the_dataset_it_makes(client, dataset, job, api_key, data_dir):
    finished = run(client, job)
    # Deleting the parent keeps what was made from it: its rows were copied.
    client.delete(f"/v1/datasets/{dataset['id']}")
    made = client.get(f"/v1/datasets/{finished['dataset_id']}").json()
    assert made["row_count"] == 3
    assert client.get(f"/v1/runs/{finished['id']}").status_code == 200

    client.delete(f"/v1/datasets/{made['id']}")
    assert client.get(f"/v1/runs/{finished['id']}").status_code == 404
    assert made["id"] not in stored_datasets()


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
    # No query means every row.
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
        "sql": "SELECT * FROM data LIMIT 2",
        "tasks": [{"template": "Bad? {{review}}", "models": ["typesafe/jev-1.14", "x/llm"]}],
    }
    estimate = client.post(f"/v1/datasets/{dataset['id']}/estimate", json=body).json()
    assert (estimate["rows"], estimate["calls"], estimate["problem"]) == (2, 4, None)
    assert 0 < estimate["cost"] < 0.01


def test_an_estimate_counts_all_that_is_sent(client, dataset, api_key):
    def cost(task):
        body = {"sql": "SELECT * FROM data LIMIT 1", "tasks": [task]}
        return client.post(f"/v1/datasets/{dataset['id']}/estimate", json=body).json()["cost"]

    short = {
        "template": "{{review}}",
        "type": "pick_one",
        "options": [{"name": "a"}, {"name": "b"}],
    }
    long = {**short, "options": [{"name": "a", "description": "word " * 200}, {"name": "b"}]}
    # A decision model is billed for the options and its own framing, not just the prompt.
    jev = 0.00000004
    assert cost(short) > runs._DECISION_FRAMING_TOKENS * jev
    assert cost(long) - cost(short) > 100 * jev


def test_a_query_picking_no_rows_makes_nothing(client, job, api_key):
    empty = update(job, sql="SELECT * FROM data WHERE review = 'no such review'")
    assert start(client, empty)["detail"] == "The query picks no rows."
    assert len(client.get("/v1/datasets").json()) == 1


def test_a_run_needs_the_row_id_to_know_which_rows_it_asks_about(client, job, api_key):
    without = update(job, sql="SELECT review FROM data")
    assert start(client, without)["detail"].startswith("The query must return `__row_id`")


def test_run_explains_what_is_missing(client, job):
    def detail(**config):
        return run(client, update(job, **config))["detail"]

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
    again = run(client, update(job, dataset_id=finished["dataset_id"]))
    assert again["detail"] == (
        "The dataset already has a column negative__jev-1.14. Rename the task's result column."
    )


def test_only_runs_whose_runner_went_quiet_are_taken_back(client, job, api_key, monkeypatch):
    created = start(client, job)
    runs._set(created["id"], status="running")
    # Its runner saved progress just now: another runner leaves it alone.
    runs.recover_interrupted_runs()
    assert client.get(f"/v1/runs/{created['id']}").json()["status"] == "running"
    # Silent for longer than STALE_SECONDS: its runner is gone, so it is queued again.
    monkeypatch.setattr(runs, "STALE_SECONDS", 0)
    runs.recover_interrupted_runs()
    assert client.get(f"/v1/runs/{created['id']}").json()["status"] == "queued"


def test_each_queued_run_is_claimed_once(client, job, api_key, monkeypatch):
    first = start(client, job)
    second = start(client, update(job, sql="SELECT * FROM data LIMIT 1"))
    claimed = []
    monkeypatch.setattr(runs, "_process", claimed.append)
    while runs.process_next():
        pass
    # Oldest first, each once; a claimed run is marked running at once, so no other runner takes it.
    assert claimed == [first["id"], second["id"]]
    assert {client.get(f"/v1/runs/{r}").json()["status"] for r in claimed} == {"running"}


def test_runners_claiming_at_once_never_take_the_same_run(client, job, api_key, monkeypatch):
    import threading
    import time

    monkeypatch.setenv("ROWLAB_RUNS_PER_ORG", "10")
    config.cache_clear()
    created = [
        start(client, update(job, sql=f"SELECT * FROM data LIMIT {n}"))["id"] for n in (1, 2, 3)
    ]
    claimed = []
    monkeypatch.setattr(runs, "_process", lambda run_id: (claimed.append(run_id), time.sleep(0.2)))
    runners = [threading.Thread(target=runs.process_next) for _ in range(4)]
    for runner in runners:
        runner.start()
    for runner in runners:
        runner.join()
    assert sorted(claimed) == sorted(created)


def test_an_estimate_gives_the_cost_before_a_key_is_set(client, dataset):
    body = {"sql": "SELECT * FROM data LIMIT 2", "tasks": [NEGATIVE]}
    estimate = client.post(f"/v1/datasets/{dataset['id']}/estimate", json=body).json()
    assert estimate["problem"] == "Set your OpenRouter API key first."
    assert (estimate["rows"], estimate["calls"]) == (2, 2)
    assert estimate["cost"] > 0


def turns(monkeypatch):
    """The runs given a turn, in order, as the runner processes them."""
    taken = []
    process = runs._process
    monkeypatch.setattr(runs, "_process", lambda run_id: (taken.append(run_id), process(run_id)))
    return taken


def test_the_run_with_least_left_goes_next(client, job, api_key, monkeypatch):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 1)
    taken = turns(monkeypatch)
    big = start(client, job)["id"]  # three chunks
    small = start(client, update(job, sql="SELECT * FROM data LIMIT 1"))["id"]  # one
    while runs.process_next():
        pass
    # A try on a few rows is done at once, though it came second; a run gives up its turn per chunk.
    assert taken == [small, big, big, big]
    assert {client.get(f"/v1/runs/{r}").json()["status"] for r in (big, small)} == {"done"}


def test_a_run_waiting_long_goes_first(client, job, api_key, monkeypatch):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 1)
    monkeypatch.setenv("ROWLAB_RUN_WAIT_SECONDS", "0.000001")
    config.cache_clear()
    taken = turns(monkeypatch)
    big = start(client, job)["id"]
    small = start(client, update(job, sql="SELECT * FROM data LIMIT 1"))["id"]
    runs.process_next()
    # Both have waited long: the one waiting longest goes first, however much it has left.
    assert taken == [big]
    runs.process_next()
    assert taken == [big, small]


def test_an_organisation_has_a_few_runs_going_at_once(client, job, api_key, monkeypatch):
    monkeypatch.setenv("ROWLAB_RUNS_PER_ORG", "1")
    config.cache_clear()
    start(client, job)
    start(client, update(job, sql="SELECT * FROM data LIMIT 1"))
    claimed = []
    monkeypatch.setattr(runs, "_process", claimed.append)  # stays running
    assert runs.process_next()
    # The other waits while the first has its turn.
    assert not runs.process_next()
    runs._set(claimed[0], status="queued")
    assert runs.process_next()


def _paid_calls(fake):
    return [c for c in fake.calls if c[0] == "POST"]


def test_a_run_on_all_rows_after_a_try_on_a_few_pays_only_for_the_rest(client, job, api_key, fake):
    run(client, update(job, sql="SELECT * FROM data LIMIT 1"))
    fake.calls.clear()
    done = run(client, job)
    assert len(_paid_calls(fake)) == 2
    assert done["cost"] == pytest.approx(0.002)
    # The replies are kept with the dataset; the database keeps none once the run is done.
    assert stored(done["dataset_id"], "answers.parquet")
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM answer_journal").fetchone()["n"] == 0


def test_answers_are_reused_in_their_tree_until_their_datasets_are_deleted(
    client, job, api_key, fake
):
    first = run(client, job)
    fake.calls.clear()
    # The same question again, on the dataset the first run made.
    again = run(
        client,
        update(job, dataset_id=first["dataset_id"], tasks=[{**NEGATIVE, "column": "again"}]),
    )
    assert again["status"] == "done"
    assert _paid_calls(fake) == []
    # Each dataset keeps the replies it used: with the first one gone, the second still has them.
    assert client.delete(f"/v1/datasets/{first['dataset_id']}").status_code == 204
    run(client, job)
    assert _paid_calls(fake) == []
    for made in client.get("/v1/datasets").json():
        if made["parent_id"]:
            assert client.delete(f"/v1/datasets/{made['id']}").status_code == 204
    run(client, job)
    assert len(_paid_calls(fake)) == 3


def test_a_dataset_added_again_is_a_new_tree_and_asked_again(client, job, api_key, fake, tmp_path):
    run(client, job)
    path = tmp_path / "again.csv"
    path.write_text(CSV)
    added = client.post("/v1/datasets", data={"source": str(path)}).json()
    fake.calls.clear()
    run(client, update(job, dataset_id=added["id"]))
    assert len(_paid_calls(fake)) == 3


def test_rows_with_the_same_prompt_each_keep_their_reply(client, api_key, fake, tmp_path):
    path = tmp_path / "same.csv"
    path.write_text("review\nLove it\nLove it\nLove it\n")
    added = client.post("/v1/datasets", data={"source": str(path)}).json()
    job = {"dataset_id": added["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    run(client, job)
    fake.calls.clear()
    run(client, update(job, sql="SELECT * FROM data WHERE __row_id = 0"))
    assert _paid_calls(fake) == []


def _paid_for(fake, prompt):
    return [c for c in _paid_calls(fake) if c[3]["state"] == prompt]


def test_a_retry_cut_off_mid_way_keeps_what_it_paid_for(client, job, api_key, fake):
    love, broke = "Is this review negative? Love it", "Is this review negative? Broke after a day"
    fake.flaky = {love, broke}
    finished = run(client, job)
    assert finished["costs"][0]["failed"] == 2
    client.post(f"/v1/runs/{finished['id']}/resume")
    fake.calls.clear()
    fake.crash_on = broke
    with pytest.raises(KeyboardInterrupt):
        runs.process_next()
    runs.recover_interrupted_runs(stale_after=0)
    while runs.process_next():
        pass
    assert client.get(f"/v1/runs/{finished['id']}").json()["costs"][0]["failed"] == 0
    assert len(_paid_for(fake, love)) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM answer_journal").fetchone()["n"] == 0


def test_replies_stay_to_be_journaled_when_journaling_fails_once(
    client, job, api_key, fake, monkeypatch
):
    from rowlab.core import answers

    journal, failed = answers.journal, []

    def flaky_journal(run_id, replies):
        if replies and not failed:
            failed.append(True)
            raise RuntimeError("database away")
        journal(run_id, replies)

    def slow(method, path, *, api_key, body=None):
        # One slow call, so the others are journaled while it is under way.
        if body and body.get("state") == "Is this review negative? Broke after a day":
            time.sleep(0.3)
        return fake(method, path, api_key=api_key, body=body)

    monkeypatch.setattr(answers, "journal", flaky_journal)
    monkeypatch.setattr(openrouter, "_request", slow)
    created = start(client, job)
    with pytest.raises(RuntimeError):
        runs.process_next()
    # The `finally` journaled what the failed try didn't.
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM answer_journal").fetchone()["n"] == 3
    fake.calls.clear()
    client.post(f"/v1/runs/{created['id']}/resume")
    while runs.process_next():
        pass
    assert client.get(f"/v1/runs/{created['id']}").json()["status"] == "done"
    assert _paid_calls(fake) == []


def test_an_unusable_reply_from_the_cache_counts_as_failed_not_cached():
    from rowlab.core import usage

    spent = usage.Spent()
    runs._count(spent, runs._Answer(error="Not a yes or no", cached=True, cost=0.001))
    runs._count(spent, runs._Answer(cached=True, cost=0.001))
    runs._count(spent, runs._Answer(cost=0.002, input_tokens=10, output_tokens=1))
    assert spent == usage.Spent(
        answers=2, cached=1, failed=1, input_tokens=10, output_tokens=1, cost=0.002
    )

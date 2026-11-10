from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import call

from rowlab.core import db, manual, runs, storage
from rowlab.core.providers import openrouter


@pytest.fixture
def source(client, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def no_provider(*args, **kwargs):
        raise AssertionError("Manual runs must not call a model or its catalog")

    monkeypatch.setattr(openrouter, "_request", no_provider)
    path = tmp_path / "rows.csv"
    path.write_text("text,gold\nfirst,true\nsecond,false\nthird,true\n")
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def start(client, source, **changes):
    body = {
        "method": "manual",
        "tasks": [{"id": "task", "template": "Read {{text}}", "column": "label"}],
        **changes,
    }
    result = client.post(f"/v1/datasets/{source['id']}/runs", json=body)
    assert result.status_code == 201, result.text
    return result.json()


def save(client, run, values, task="task"):
    return client.put(
        f"/v1/runs/{run['id']}/tasks/{task}/answers",
        json={"answers": [{"row_id": row_id, "value": value} for row_id, value in values]},
    )


def query(client, run):
    return client.post(
        f"/v1/datasets/{run['dataset_id']}/query",
        json={"sql": "SELECT * FROM data ORDER BY __row_id"},
    ).json()


def test_manual_run_is_a_run_with_plain_labels(client, source):
    preview = client.post(
        f"/v1/datasets/{source['id']}/estimate",
        json={"method": "manual", "tasks": [{"template": "{{text}}"}]},
    ).json()
    assert preview == {"rows": 3, "calls": 0, "cost": 0, "problem": None}
    run = start(client, source)
    assert run["status"] == "manual" and run["columns"] == ["label"]
    assert run["config"]["tasks"][0]["models"] == []
    assert runs.process_next() is False
    assert [c["name"] for c in query(client, run)["columns"]] == [
        "__row_id",
        "label",
        "text",
        "gold",
    ]
    assert save(client, run, [(0, True), (1, False)]).json()["done"] == 2
    assert save(client, run, [(0, True), (1, False)]).json()["done"] == 2
    before = query(client, run)

    def comparison():
        result = client.post(
            f"/v1/datasets/{run['dataset_id']}/compare",
            json={"columns": ["label"], "reference": "gold"},
        )
        assert result.status_code == 200, result.text
        return result.json()

    compared = comparison()
    done = client.post(f"/v1/runs/{run['id']}/finish").json()
    assert done["status"] == "done" and done["done"] == 2
    assert query(client, run) == before and comparison() == compared
    assert client.post(f"/v1/runs/{run['id']}/finish").json()["status"] == "done"
    assert save(client, run, [(2, True)]).status_code == 400
    assert [r["label"] for r in before["rows"]] == [True, False, None]
    with db.connect() as conn:
        assert conn.execute(
            "SELECT total, done FROM runs WHERE id = ?", (run["id"],)
        ).fetchone() == {"total": 3, "done": 2}
    child = start(
        client,
        {"id": run["dataset_id"]},
        tasks=[{"id": "next", "template": "{{text}}", "column": "next"}],
    )
    assert [r["label"] for r in query(client, child)["rows"]] == [True, False, None]
    assert client.delete(f"/v1/datasets/{run['dataset_id']}").status_code == 204
    assert client.get(f"/v1/runs/{run['id']}").status_code == 404
    assert [r["label"] for r in query(client, child)["rows"]] == [True, False, None]


@pytest.mark.parametrize(
    "type_,extra,value,expected",
    [
        ("pick_one", {"options": [{"name": "a"}, {"name": "b"}]}, "b", {"label": "b"}),
        ("scale", {"options": [{"name": "low"}, {"name": "high"}]}, "low", {"label": "low"}),
        (
            "pick_any",
            {"options": [{"name": "a"}, {"name": "b"}]},
            ["b"],
            {"label_a": False, "label_b": True},
        ),
        ("write", {}, "", {"label": ""}),
        (
            "extract",
            {"fields": [{"name": "amount", "type": "number"}, {"name": "tags", "type": "list"}]},
            {"amount": 2.5, "tags": ["one"]},
            {"label_amount": 2.5, "label_tags": ["one"]},
        ),
    ],
)
def test_types_clear_and_finish(client, source, type_, extra, value, expected):
    run = start(
        client,
        source,
        tasks=[{"id": "task", "column": "label", "template": "{{text}}", "type": type_, **extra}],
    )
    assert save(client, run, [(0, value)]).json()["done"] == 1
    row = query(client, run)["rows"][0]
    assert all(row[k] == v for k, v in expected.items())
    assert save(client, run, [(0, None)]).json()["done"] == 0
    assert all(query(client, run)["rows"][0][k] is None for k in expected)
    assert save(client, run, [(0, value)]).status_code == 200
    assert client.post(f"/v1/runs/{run['id']}/finish").status_code == 200
    assert all(query(client, run)["rows"][0][k] == v for k, v in expected.items())


def test_validation_and_row_scope(client, source):
    run = start(client, source, sql="SELECT * FROM data WHERE __row_id = 1")
    assert save(client, run, [(0, True)]).status_code == 400
    assert save(client, run, [(1, "true")]).status_code == 400
    assert save(client, run, [(1, True), (1, False)]).status_code == 400
    assert save(client, run, [(1, True)], "missing").status_code == 404
    assert query(client, run)["rows"][0]["label"] is None
    result = client.post(
        f"/v1/datasets/{run['dataset_id']}/runs",
        json={"method": "manual", "tasks": [{"template": "{{text}}"}]},
    )
    assert result.status_code == 400


def test_finish_after_crash_uses_latest_parts(client, source, monkeypatch):
    run = start(client, source)
    save(client, run, [(0, True)])
    original = storage.write

    def crash(con, query_, target, params=None):
        original(con, query_, target, params)
        if target.endswith("data.parquet"):
            raise RuntimeError("process died before commit")

    monkeypatch.setattr(storage, "write", crash)
    with pytest.raises(RuntimeError, match="process died"):
        manual.finish(run["id"])
    assert runs.get_run(run["id"]).status == "manual"
    monkeypatch.setattr(storage, "write", original)
    save(client, run, [(0, False)])
    assert query(client, run)["rows"][0]["label"] is False
    manual.finish(run["id"])
    assert query(client, run)["rows"][0]["label"] is False


def test_multiple_tasks_and_concurrent_saves(client, source):
    run = start(
        client, source, tasks=[{"id": t, "column": t, "template": "{{text}}"} for t in ("a", "b")]
    )
    with ThreadPoolExecutor(2) as pool:
        list(
            pool.map(
                lambda item: manual.save(
                    run["id"],
                    item[0],
                    manual.Answers(answers=[manual.Answer(row_id=item[1], value=True)]),
                ),
                [("a", 0), ("b", 1)],
            )
        )
    rows = query(client, run)["rows"]
    assert rows[0]["a"] is True and rows[1]["b"] is True
    assert runs.get_run(run["id"]).done == 2
    assert runs.get_run(run["id"]).total == 6


def test_retry_interrupted_batch_between_chunks(client, source, monkeypatch):
    monkeypatch.setattr(runs, "CHUNK_ROWS", 1)
    run = start(client, source)
    original = runs._write_part

    def crash(dataset_id, tasks, name, rows, **kwargs):
        if name == "manual-1":
            raise RuntimeError("lost process")
        original(dataset_id, tasks, name, rows, **kwargs)

    monkeypatch.setattr(runs, "_write_part", crash)
    with pytest.raises(RuntimeError, match="lost process"):
        save(client, run, [(0, True), (1, False)])
    assert [row["label"] for row in query(client, run)["rows"]] == [True, None, None]
    assert runs.get_run(run["id"]).done == 1
    monkeypatch.setattr(runs, "_write_part", original)
    assert save(client, run, [(0, True), (1, False)]).json()["done"] == 2
    assert [row["label"] for row in query(client, run)["rows"]] == [True, False, None]


def test_access(hosted):
    owner = hosted("owner@example.com")
    source = owner.post("/v1/datasets", files={"file": ("data.csv", b"text\none\n")}).json()
    run = start(owner, source)
    other = hosted("other@example.com")
    assert save(other, run, [(0, True)]).status_code == 404
    assert other.post(f"/v1/runs/{run['id']}/finish").status_code == 404
    owner.post("/v1/settings/invites", json={"email": "reader@example.com", "role": "verifier"})
    reader = hosted("reader@example.com")
    assert save(reader, run, [(0, True)]).status_code == 403
    assert reader.post(f"/v1/runs/{run['id']}/finish").status_code == 403


def test_mcp_manual_flow(client, source):
    from rowlab.mcp.server import create_server

    mcp = create_server()
    run = call(
        mcp,
        "run_start",
        dataset_id=source["id"],
        method="manual",
        tasks=[{"id": "task", "column": "label", "template": "{{text}}"}],
    )
    result = call(
        mcp, "run_answers", run_id=run["id"], task_id="task", answers=[{"row_id": 0, "value": True}]
    )
    assert result["done"] == 1
    assert call(mcp, "run_finish", run_id=run["id"])["status"] == "done"

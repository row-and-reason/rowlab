"""`rowlab migrate`: datasets runs made, in the layout before answers became columns, folded into the
dataset they were made from, without asking or paying again. The old layout is written by hand, files
and database rows as the old code wrote them."""

import json
import sys

import pytest
import uvicorn
from helpers import NEGATIVE, run, stored, stored_datasets

from rowlab import cli
from rowlab.core import db, model_providers, replies, storage
from rowlab.core.tasks import Task

CSV = "review,stars\nTerrible product,1\nLove it,5\nBroke after a day,1\n"
JEV = "typesafe/jev-1.14"
ALL = "SELECT * FROM data"

pytestmark = pytest.mark.usefixtures("fake")


@pytest.fixture
def root(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text(CSV)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def write(dataset_id, name, query):
    with storage.connect() as con:
        storage.write(con, query, storage.location(dataset_id, *name.split("/")))


def data(dataset_id):
    return f"read_parquet('{storage.location(dataset_id, 'data.parquet')}')"


def made(dataset_id, parent_id, name, run_id, status, tasks, day, *, sql=ALL, **config):
    """Record a dataset a run made, and its run, as the old code did."""
    created = f"2026-11-0{day}T00:00:00+00:00"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO datasets (id, org_id, name, source, row_count, size_bytes, columns,"
            " created_at, parent_id, branch, root_id) VALUES (?, 'local', ?, 'Made', 0, 0, '[]',"
            " ?, ?, '1', ?)",
            (dataset_id, name, created, parent_id, parent_id),
        )
        conn.execute(
            "INSERT INTO runs (id, dataset_id, status, config, columns, costs, row_count,"
            " next_chunk, total, created_at) VALUES (?, ?, ?, ?, '[]', '[]', 3, ?, 3, ?)",
            (
                run_id,
                dataset_id,
                status,
                json.dumps({"sql": sql, "tasks": tasks, **config}),
                1 if status == "done" else 0,
                created,
            ),
        )


def reply(row_id, review, task=NEGATIVE):
    """The reply the old run kept for a row, with the key a run asks it by."""
    prompt = Task.model_validate(task).template.replace("{{review}}", review)
    request = model_providers.request("openrouter", "", Task.model_validate(task), JEV, prompt)
    yes = 0.9 if review != "Love it" else 0.1
    return (
        row_id,
        replies.key("local", request),
        json.dumps({"answer": {"type": "noul", "noul": yes}}),
    )


def replies_file(dataset_id, name, kept):
    values = ", ".join(f"({r}, '{k}', '{d}')" for r, k, d in kept) or "(0, '', '')"
    where = "" if kept else " WHERE false"
    write(
        dataset_id,
        name,
        f"SELECT * FROM (VALUES {values}) AS t(__row_id, key, data){where}",
    )


@pytest.fixture
def tree(root):
    """reviews ← A (done, 2 rows) ← C (manual labels); ← B (all rows, killed before its first
    chunk, one reply journaled); ← D (a different question in `negative`, done)."""
    r = root["id"]
    task = {**NEGATIVE, "id": "t1", "models": [JEV]}
    # A: done, on the first two rows; its file has its answers first, then the root's columns.
    made("a", r, "reviews__1", "run-a", "done", [task], 1, sql=f"{ALL} LIMIT 2")
    write(
        "a",
        "data.parquet",
        'SELECT d.__row_id, v.neg AS "negative__jev-1.14", v.p AS "negative__jev-1.14_proba",'
        f" d.* EXCLUDE (__row_id) FROM {data(r)} AS d JOIN (VALUES (0, true, 0.9),"
        " (1, false, 0.9)) AS v(id, neg, p) ON v.id = d.__row_id ORDER BY d.__row_id",
    )
    write("a", "asked.parquet", "SELECT unnest([0, 1])::BIGINT AS __row_id")
    kept = [reply(0, "Terrible product"), reply(1, "Love it")]
    replies_file("a", "answers/part-000000.parquet", kept)
    replies_file("a", "answers/part-schema.parquet", [])
    replies_file("a", "answers.parquet", kept)

    # B: on all rows, still running when the runners stopped: rows and an empty part only.
    made("b", r, "reviews__2", "run-b", "running", [task], 2)
    write("b", "rows.parquet", f"SELECT * FROM {data(r)}")
    write("b", "asked.parquet", "SELECT unnest([0, 1, 2])::BIGINT AS __row_id")
    write(
        "b",
        "parts/part-schema.parquet",
        'SELECT 0::BIGINT AS __row_id, NULL::BOOLEAN AS "negative__jev-1.14",'
        ' NULL::DOUBLE AS "negative__jev-1.14_proba", NULL::VARCHAR[] AS __failed WHERE false',
    )
    row_id, key, kept_data = reply(2, "Broke after a day")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO answer_journal (run_id, key, row_id, data) VALUES ('run-b', ?, ?, ?)",
            (key, row_id, kept_data),
        )

    # C: manual labels, made from A, still open: A's rows, and a part per chunk of labels.
    labels = [{"id": "g", "column": "gold"}]
    made("c", "a", "reviews__1.1", "run-c", "manual", labels, 3, method="manual")
    write("c", "rows.parquet", f"SELECT * FROM {data('a')}")
    write("c", "asked.parquet", "SELECT unnest([0, 1])::BIGINT AS __row_id")
    write(
        "c",
        "parts/manual-0.parquet",
        "SELECT * FROM (VALUES (0, true, NULL::VARCHAR[]), (1, false, NULL))"
        " AS t(__row_id, gold, __failed)",
    )

    # D: another question under the same name, done on the first row.
    other = {**task, "id": "t2", "template": "Is this review long? {{review}}"}
    made("d", r, "reviews__3", "run-d", "done", [other], 4)
    write(
        "d",
        "data.parquet",
        'SELECT __row_id, true AS "negative__jev-1.14", 0.7 AS "negative__jev-1.14_proba",'
        f" * EXCLUDE (__row_id) FROM {data(r)} WHERE __row_id = 0",
    )
    write("d", "asked.parquet", "SELECT 0::BIGINT AS __row_id")
    return root


def values(client, dataset_id, *columns):
    response = client.post(
        f"/v1/datasets/{dataset_id}/query",
        json={"sql": f"SELECT {', '.join(f'"{c}"' for c in columns)} FROM data ORDER BY __row_id"},
    )
    assert response.status_code == 200, response.text
    return [tuple(row[c] for c in columns) for row in response.json()["rows"]]


def rowlab(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["rowlab", *args])
    cli.main()


def test_a_tree_folds_into_one_dataset_with_its_answers_and_labels(
    client, tree, monkeypatch, capsys
):
    r = tree["id"]
    rowlab(monkeypatch, "migrate")
    assert "1 tree(s) folded" in capsys.readouterr().out

    assert [d["id"] for d in client.get("/v1/datasets").json()] == [r]
    assert stored_datasets() == {r}
    found = client.get(f"/v1/datasets/{r}").json()
    assert found["name"] == "reviews"
    answers = {(a["name"], a["model"]): a for a in found["answers"]}
    assert set(answers) == {("negative", JEV), ("negative_2", JEV), ("gold", None)}
    assert answers[("negative", JEV)]["answered"] == 2
    assert answers[("gold", None)]["answered"] == 2
    assert values(client, r, "negative__jev-1.14", "negative_2__jev-1.14", "gold", "stars") == [
        (True, True, True, 1),
        (False, None, False, 5),
        (None, None, None, 1),
    ]

    # The model runs are the root's now, ended; the manual one is gone, its labels kept.
    listed = {x["id"]: x for x in client.get(f"/v1/datasets/{r}/runs").json()}
    assert set(listed) == {"run-a", "run-b", "run-d"}
    assert {x["dataset_id"] for x in listed.values()} == {r}
    assert listed["run-b"]["status"] == "stopped"
    assert listed["run-d"]["config"]["tasks"][0]["column"] == "negative_2"
    assert client.get("/v1/runs/run-c").status_code == 404
    for run_id in listed:
        assert stored(r, "replies", f"{run_id}.parquet")

    compared = client.post(
        f"/v1/datasets/{r}/compare", json={"columns": ["negative__jev-1.14"], "reference": "gold"}
    )
    assert compared.status_code == 200, compared.text
    accuracy = compared.json()["reference"][0]
    assert (accuracy["compared"], accuracy["correct"]) == (2, 2)


def test_a_folded_run_started_again_pays_only_for_what_no_run_had(
    client, tree, api_key, fake, monkeypatch
):
    r = tree["id"]
    rowlab(monkeypatch, "migrate")
    fake.calls.clear()
    again = run(client, {"dataset_id": r, "sql": "SELECT * FROM data", "tasks": [NEGATIVE]})
    assert again["status"] == "done", again
    # Rows 0 and 1 have answers; row 2's reply was journaled by the run that stopped.
    assert [c for c in fake.calls if c[0] == "POST"] == []
    assert values(client, r, "negative__jev-1.14") == [(True,), (False,), (True,)]


def test_a_dry_run_changes_nothing_and_a_second_migrate_does_nothing(
    client, tree, monkeypatch, capsys
):
    # Before migrating, the database is read directly: the API doesn't serve the old layout.
    before = (_tables(), stored_datasets())
    rowlab(monkeypatch, "migrate", "--dry-run")
    said = capsys.readouterr().out
    assert "reviews__1.1: manual run run-c, 2 label(s) in ['gold']" in said
    assert "`negative` of run run-d is `negative_2`" in said
    assert "1 tree(s) to fold" in said
    assert (_tables(), stored_datasets()) == before

    rowlab(monkeypatch, "migrate")
    after = (client.get(f"/v1/datasets/{tree['id']}").json(), stored_datasets())
    capsys.readouterr()
    rowlab(monkeypatch, "migrate")
    assert "0 tree(s) folded" in capsys.readouterr().out
    assert (client.get(f"/v1/datasets/{tree['id']}").json(), stored_datasets()) == after


def test_a_dataset_whose_parent_was_deleted_becomes_one_of_its_own(client, root, monkeypatch):
    task = {**NEGATIVE, "id": "t1", "models": [JEV]}
    made("o", "deleted", "reviews__1.1", "run-o", "done", [task], 1)
    # Its file has its answers, then its deleted parent's (`earlier`), then the file's columns.
    write(
        "o",
        "data.parquet",
        'SELECT __row_id, (__row_id = 0) AS "negative__jev-1.14", 0.9 AS "negative__jev-1.14_proba",'
        f" 'x' AS earlier, * EXCLUDE (__row_id) FROM {data(root['id'])}",
    )
    write("o", "asked.parquet", f"SELECT __row_id FROM {data(root['id'])}")
    rowlab(monkeypatch, "migrate")

    found = client.get("/v1/datasets/o").json()
    assert [c["name"] for c in found["columns"]] == [
        "__row_id",
        "negative__jev-1.14",
        "negative__jev-1.14_proba",
        "earlier",
        "review",
        "stars",
    ]
    assert values(client, "o", "negative__jev-1.14", "earlier") == [
        (True, "x"),
        (False, "x"),
        (False, "x"),
    ]
    assert [x["id"] for x in client.get("/v1/datasets/o/runs").json()] == ["run-o"]
    assert not stored("o", "old-data.parquet")


def test_serving_waits_for_the_migration(client, tree, monkeypatch, capsys):
    served = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: served.append(args))
    for command in (["serve"], ["runner"]):
        with pytest.raises(SystemExit) as refused:
            rowlab(monkeypatch, *command)
        assert "rowlab migrate" in str(refused.value)
    assert served == []
    rowlab(monkeypatch, "migrate")
    rowlab(monkeypatch, "serve")
    assert served == [("rowlab.app:app",)]


def _tables():
    with db.connect() as conn:
        return [
            conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("datasets", "runs", "answer_columns", "labels")
        ]

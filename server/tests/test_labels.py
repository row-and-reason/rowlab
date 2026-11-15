"""Labels people set: on any rows, at any time, typed by their task, and compared like any column."""

import pytest
from helpers import NEGATIVE, run, start

from rowlab.core import runs

CSV = "text\nfirst\nsecond\nthird\n"


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text(CSV)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def put(client, dataset, column, labels, task=None):
    body = {"labels": [{"row_id": r, "value": v} for r, v in labels]}
    if task is not None:
        body["task"] = task
    return client.put(f"/v1/datasets/{dataset['id']}/labels/{column}", json=body)


def values(client, dataset, *columns):
    response = client.post(
        f"/v1/datasets/{dataset['id']}/query",
        json={"sql": f"SELECT {', '.join(f'"{c}"' for c in columns)} FROM data ORDER BY __row_id"},
    )
    assert response.status_code == 200, response.text
    return [tuple(r[c] for c in columns) for r in response.json()["rows"]]


def test_labels_are_set_changed_and_cleared_on_any_rows(client, dataset):
    yes_no = {"type": "yes_no", "column": "ignored: the path names the column"}
    first = put(client, dataset, "gold", [(0, True), (2, False)], task=yes_no)
    assert first.status_code == 200, first.text
    assert (first.json()["name"], first.json()["model"], first.json()["answered"]) == (
        "gold",
        None,
        2,
    )
    assert values(client, dataset, "gold") == [(True,), (None,), (False,)]
    # Later batches need no task, and change or clear what is there.
    assert put(client, dataset, "gold", [(0, None), (1, True)]).json()["answered"] == 2
    assert values(client, dataset, "gold") == [(None,), (True,), (False,)]
    found = client.get(f"/v1/datasets/{dataset['id']}").json()
    assert [c["name"] for c in found["columns"]] == ["__row_id", "gold", "text"]
    assert found["answers"][0]["columns"] == ["gold"]


def test_a_labels_task_types_its_columns(client, dataset):
    pick_any = {"type": "pick_any", "options": [{"name": "a"}, {"name": "b"}]}
    assert put(client, dataset, "tags", [(1, ["b"])], task=pick_any).status_code == 200
    assert values(client, dataset, "tags_a", "tags_b") == [
        (None, None),
        (False, True),
        (None, None),
    ]
    extract = {"type": "extract", "fields": ["amount:number", "when:date"]}
    assert put(client, dataset, "info", [(0, {"amount": 3, "when": "2026-01-02"})], task=extract)
    assert values(client, dataset, "info_amount", "info_when")[0] == (3.0, "2026-01-02")


def test_labels_say_what_is_wrong(client, dataset):
    def problem(*args, **kwargs):
        response = put(client, dataset, *args, **kwargs)
        assert response.status_code == 400, response.text
        return response.json()["detail"]

    assert "give the task" in problem("gold", [(0, True)])
    yes_no = {"type": "yes_no"}
    assert problem("gold", [(0, "yes")], task=yes_no) == "A yes/no label must be true or false."
    assert problem("gold", [(9, True)], task=yes_no) == "Every row must be one of the dataset's."
    assert problem("text", [(0, True)], task=yes_no) == (
        "The dataset already has a column text. Name the task's column differently."
    )
    put(client, dataset, "gold", [(0, True)], task=yes_no)
    assert "to a different question" in problem("gold", [(1, "x")], task={"type": "write"})
    # Nothing of a refused batch is saved.
    assert values(client, dataset, "gold") == [(True,), (None,), (None,)]


def test_labels_before_and_after_a_model_on_the_same_task(client, dataset, api_key):
    task = {**NEGATIVE, "template": "Is this negative? {{text}}"}
    put(client, dataset, "negative", [(0, True)], task={**task, "models": []})
    run(client, {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [task]})
    assert values(client, dataset, "negative", "negative__jev-1.14") == [
        (True, False),
        (None, False),
        (None, False),
    ]


def test_deleting_answers_removes_their_columns(client, dataset, api_key):
    put(client, dataset, "gold", [(0, True)], task={"type": "yes_no"})
    gone = client.delete(f"/v1/datasets/{dataset['id']}/answers", params={"column": "gold"})
    assert gone.status_code == 204
    assert "gold" not in [
        c["name"] for c in client.get(f"/v1/datasets/{dataset['id']}").json()["columns"]
    ]
    # A column a run is still asking for is deleted once the run is stopped.
    job = {
        "dataset_id": dataset["id"],
        "sql": "SELECT * FROM data",
        "tasks": [{**NEGATIVE, "template": "{{text}}"}],
    }
    created = start(client, job)
    params = {"column": "negative", "model": "typesafe/jev-1.14"}
    busy = client.delete(f"/v1/datasets/{dataset['id']}/answers", params=params)
    assert busy.status_code == 400
    assert busy.json()["detail"] == "A run is still asking for these answers. Stop it first."
    client.post(f"/v1/runs/{created['id']}/stop")
    assert runs.process_next() is False
    assert client.delete(f"/v1/datasets/{dataset['id']}/answers", params=params).status_code == 204

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import pytest

from rowlab.core import datasets, reviews, storage


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"message": "Broken", "topic__a": "bug", "topic__b": "billing", "urgent": True},
                {
                    "message": "Refund",
                    "topic__a": "billing",
                    "topic__b": "billing",
                    "urgent": False,
                },
            ]
        )
    )
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def test_review_preserves_source_and_is_available_everywhere(client, dataset, data_dir):
    id_ = dataset["id"]
    source = storage.location(id_, "data.parquet")
    with storage.connect() as con:
        original = con.execute("SELECT content FROM read_blob(?)", [source]).fetchone()[0]
    response = client.put(
        f"/v1/datasets/{id_}/reviews",
        json={
            "row_id": 0,
            "column": "topic__a",
            "value": "bug",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"name": "reviewed_topic", "type": "VARCHAR"}
    with storage.connect() as con:
        assert con.execute("SELECT content FROM read_blob(?)", [source]).fetchone()[0] == original
    assert client.get(f"/v1/datasets/{id_}").json()["columns"][-1]["name"] == "reviewed_topic"
    rows = client.post(f"/v1/datasets/{id_}/query", json={}).json()["rows"]
    assert rows[0]["topic__b"] == "billing"
    assert rows[0]["reviewed_topic"] == "bug"
    assert rows[1]["reviewed_topic"] is None
    result = client.post(
        f"/v1/datasets/{id_}/compare",
        json={
            "columns": ["topic__a", "topic__b"],
            "reference": "reviewed_topic",
        },
    ).json()
    assert result["reference"][0]["compared"] == 1
    assert result["reference"][0]["accuracy"] == 1
    assert result["reference"][1]["accuracy"] == 0
    exported = client.get(f"/v1/datasets/{id_}/export?format=jsonl").text
    assert json.loads(exported.splitlines()[0])["reviewed_topic"] == "bug"
    profile = client.get(f"/v1/datasets/{id_}/profile").json()
    assert next(c for c in profile if c["name"] == "reviewed_topic")["null_percentage"] == 50
    # A second model of the same task writes the same reviewed column; null clears it.
    client.put(
        f"/v1/datasets/{id_}/reviews",
        json={
            "row_id": 0,
            "column": "topic__b",
            "value": None,
        },
    ).raise_for_status()
    assert (
        client.post(f"/v1/datasets/{id_}/query", json={}).json()["rows"][0]["reviewed_topic"]
        is None
    )


def test_types_rows_and_original_review_columns_are_validated(client, dataset, tmp_path):
    url = f"/v1/datasets/{dataset['id']}/reviews"
    assert (
        client.put(url, json={"row_id": 999, "column": "urgent", "value": True}).status_code == 404
    )
    assert (
        client.put(url, json={"row_id": 0, "column": "missing", "value": True}).status_code == 400
    )
    assert (
        client.put(url, json={"row_id": 0, "column": "__row_id", "value": True}).status_code == 400
    )
    assert (
        client.put(url, json={"row_id": 0, "column": "urgent", "value": "yes"}).status_code == 400
    )
    assert (
        client.put(url, json={"row_id": 0, "column": "urgent", "value": False}).status_code == 200
    )
    rows = client.post(f"/v1/datasets/{dataset['id']}/query", json={}).json()["rows"]
    assert rows[0]["reviewed_urgent"] is False
    assert rows[0]["urgent"] is True
    path = tmp_path / "original.csv"
    path.write_text("answer,reviewed_answer\nx,y\n")
    other = client.post("/v1/datasets", data={"source": str(path)}).json()
    response = client.put(
        f"/v1/datasets/{other['id']}/reviews",
        json={
            "row_id": 0,
            "column": "answer",
            "value": "z",
        },
    )
    assert response.status_code == 400
    assert "original column" in response.json()["detail"]


def test_concurrent_reviews_and_child_copy_are_independent(client, dataset):
    id_ = dataset["id"]

    def save(row_id):
        reviews.save_review(
            id_, reviews.ReviewRequest(row_id=row_id, column="topic__a", value="bug")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save, [0, 1]))
    child = datasets.write_run_rows(id_, [0, 1])
    # Copying a run's source rows also copies human labels, separately from its immutable rows.
    with storage.connect() as con:
        storage.write(
            con,
            f"SELECT * FROM read_parquet({datasets.sql_string(storage.location(child, 'rows.parquet'))})",
            storage.location(child, "data.parquet"),
        )
    datasets._register(child, name="child", source="audit", parent_id=id_)
    reviews.save_review(id_, reviews.ReviewRequest(row_id=0, column="topic__a", value="billing"))
    rows = client.post(f"/v1/datasets/{child}/query", json={}).json()["rows"]
    assert [r["reviewed_topic"] for r in rows] == ["bug", "bug"]
    assert len([c for c in datasets.get_dataset(child).columns if c.name == "reviewed_topic"]) == 1
    datasets.delete_dataset(id_)
    assert client.post(f"/v1/datasets/{child}/query", json={}).status_code == 200


def test_rename_keeps_identity_data_and_export_name(client, dataset):
    id_ = dataset["id"]
    renamed = client.patch(f"/v1/datasets/{id_}", json={"name": "  Ticket quality sample  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Ticket quality sample"
    assert renamed.json()["id"] == id_
    assert "Ticket quality sample.csv" in unquote(
        client.get(f"/v1/datasets/{id_}/export?format=csv").headers["content-disposition"]
    )
    for name in [" ", "../bad", "a\\b", "x\ny"]:
        assert client.patch(f"/v1/datasets/{id_}", json={"name": name}).status_code == 400


def test_numeric_date_and_nested_review_labels_keep_their_types(client, tmp_path):
    path = tmp_path / "typed.jsonl"
    path.write_text(json.dumps({"count": 1, "amount": 1.5, "date": "2025-01-01", "tags": ["x"]}))
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    url = f"/v1/datasets/{dataset['id']}/reviews"
    for column, value in [
        ("count", 3),
        ("amount", 2.75),
        ("date", "2025-02-01"),
        ("tags", ["x", "y"]),
    ]:
        response = client.put(url, json={"row_id": 0, "column": column, "value": value})
        assert response.status_code == 200, response.text
    assert client.put(url, json={"row_id": 0, "column": "count", "value": 1.5}).status_code == 400
    assert (
        client.put(url, json={"row_id": 0, "column": "date", "value": "bad date"}).status_code
        == 400
    )
    row = client.post(f"/v1/datasets/{dataset['id']}/query", json={}).json()["rows"][0]
    assert (row["reviewed_count"], row["reviewed_amount"]) == (3, 2.75)
    assert row["reviewed_date"] == "2025-02-01"
    assert row["reviewed_tags"] == ["x", "y"]

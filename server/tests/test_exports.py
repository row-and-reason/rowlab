import csv
import json

import duckdb
import pytest

EVENTS = (
    '{"id": 1, "user": {"login": "ada"}, "tags": ["a", "b"]}\n{"id": 2, "user": null, "tags": []}\n'
)


@pytest.fixture
def events(client, tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(EVENTS)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def download(client, dataset, fmt, **params):
    response = client.get(f"/v1/datasets/{dataset['id']}/export", params={"format": fmt, **params})
    assert response.status_code == 200, response.text
    return response


def test_download_csv_names_the_file_and_writes_nested_values_as_json(client, events, data_dir):
    response = download(client, events, "csv")
    assert 'filename="events.csv"' in response.headers["content-disposition"]
    header, first, _ = csv.reader(response.text.splitlines())
    assert header == ["id", "user", "tags"]
    assert (json.loads(first[1]), json.loads(first[2])) == ({"login": "ada"}, ["a", "b"])
    # The temporary file is gone once it has been sent.
    assert not any((data_dir / "tmp").glob("*.csv"))


def test_download_jsonl_keeps_nested_values(client, events):
    rows = [json.loads(line) for line in download(client, events, "jsonl").text.splitlines()]
    assert rows == [
        {"id": 1, "user": {"login": "ada"}, "tags": ["a", "b"]},
        {"id": 2, "user": None, "tags": []},
    ]


def test_download_parquet_can_keep_the_row_id(client, events, tmp_path):
    path = tmp_path / "events.parquet"
    path.write_bytes(download(client, events, "parquet", include_row_id="true").content)
    assert duckdb.sql(f"SELECT __row_id, id FROM '{path}'").fetchall() == [(0, 1), (1, 2)]


def test_export_to_a_folder_or_a_file(client, events, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    response = client.post(
        f"/v1/datasets/{events['id']}/export", json={"format": "parquet", "path": str(out)}
    )
    assert response.status_code == 200, response.text
    written = response.json()
    assert written["path"] == str((out / "events.parquet").resolve())
    assert duckdb.sql(f"SELECT id FROM '{written['path']}'").fetchall() == [(1,), (2,)]

    named = client.post(
        f"/v1/datasets/{events['id']}/export",
        json={"format": "csv", "path": str(out / "mine.csv"), "include_row_id": True},
    ).json()
    assert (out / "mine.csv").read_text().splitlines()[0] == "__row_id,id,user,tags"
    assert named["size_bytes"] == (out / "mine.csv").stat().st_size


def test_export_explains_a_missing_folder(client, events, tmp_path):
    response = client.post(
        f"/v1/datasets/{events['id']}/export",
        json={"format": "csv", "path": str(tmp_path / "nope" / "x.csv")},
    )
    assert response.status_code == 400
    assert "Folder not found" in response.json()["detail"]

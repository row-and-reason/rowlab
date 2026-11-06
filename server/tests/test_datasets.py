import functools
import gzip
import http.server
import json
import threading

import duckdb
import pytest

CSV = "name,age,city\nAda,36,London\nAlan,41,Wilmslow\nGrace,,Arlington\n"


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "people.csv"
    path.write_text(CSV)
    return path


@pytest.fixture
def dataset(client, csv_file):
    response = client.post("/v1/datasets", data={"source": str(csv_file)})
    assert response.status_code == 201, response.text
    return response.json()


def query(client, dataset_id, **body):
    response = client.post(f"/v1/datasets/{dataset_id}/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_create_from_local_path(dataset, csv_file, data_dir):
    assert dataset["name"] == "people"
    assert dataset["source"] == str(csv_file)
    assert dataset["row_count"] == 3
    assert [c["name"] for c in dataset["columns"]] == ["__row_id", "name", "age", "city"]
    assert (data_dir / "datasets" / dataset["id"] / "data.parquet").is_file()


def test_upload(client):
    response = client.post("/v1/datasets", files={"file": ("people.csv", CSV.encode())})
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "upload:people.csv"
    assert response.json()["row_count"] == 3


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("people.json", json.dumps([{"name": "Ada", "tags": ["a"]}, {"name": "Alan", "tags": []}])),
        ("people.jsonl", '{"name": "Ada", "tags": ["a"]}\n{"name": "Alan", "tags": []}\n'),
    ],
)
def test_json_keeps_nested_values(client, tmp_path, filename, content):
    path = tmp_path / filename
    path.write_text(content)
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    assert dataset["columns"][2] == {"name": "tags", "type": "VARCHAR[]"}
    rows = query(client, dataset["id"])["rows"]
    assert rows == [
        {"__row_id": 0, "name": "Ada", "tags": ["a"]},
        {"__row_id": 1, "name": "Alan", "tags": []},
    ]


def test_parquet(client, tmp_path):
    path = tmp_path / "numbers.parquet"
    duckdb.sql(f"COPY (SELECT range AS n FROM range(5)) TO '{path}' (FORMAT parquet)")
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    assert dataset["name"] == "numbers"
    assert dataset["row_count"] == 5


def test_rejects_bad_input(client, tmp_path):
    assert client.post("/v1/datasets", data={}).status_code == 400
    missing = client.post("/v1/datasets", data={"source": str(tmp_path / "nope.csv")})
    assert missing.status_code == 400
    assert "File not found" in missing.json()["detail"]

    binary = tmp_path / "sheet.xlsx"
    binary.write_bytes(b"PK\x03\x04\x00\x00binary")
    unsupported = client.post("/v1/datasets", data={"source": str(binary)})
    assert unsupported.status_code == 400
    assert "is not a CSV" in unsupported.json()["detail"]

    clash = tmp_path / "clash.csv"
    clash.write_text("__row_id,a\n1,2\n")
    assert client.post("/v1/datasets", data={"source": str(clash)}).status_code == 400

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert client.post("/v1/datasets", data={"source": str(broken)}).status_code == 400
    assert not list((tmp_path / "data" / "datasets").iterdir())


def test_list_get_delete(client, dataset, data_dir):
    assert [d["id"] for d in client.get("/v1/datasets").json()] == [dataset["id"]]
    assert client.get(f"/v1/datasets/{dataset['id']}").json() == dataset

    assert client.delete(f"/v1/datasets/{dataset['id']}").status_code == 204
    assert client.get(f"/v1/datasets/{dataset['id']}").status_code == 404
    assert client.get("/v1/datasets").json() == []
    assert not (data_dir / "datasets" / dataset["id"]).exists()


def test_profile(client, dataset):
    profile = {p["name"]: p for p in client.get(f"/v1/datasets/{dataset['id']}/profile").json()}
    assert list(profile) == ["name", "age", "city"]
    assert profile["age"]["min"] == "36"
    assert profile["age"]["max"] == "41"
    assert profile["age"]["null_percentage"] == pytest.approx(33.33)


def test_query_pages_in_file_order(client, dataset):
    result = query(client, dataset["id"], page_size=2)
    assert result["total"] == 3
    assert [r["name"] for r in result["rows"]] == ["Ada", "Alan"]
    result = query(client, dataset["id"], page_size=2, offset=2)
    assert [r["name"] for r in result["rows"]] == ["Grace"]
    assert result["rows"][0] == {"__row_id": 2, "name": "Grace", "age": None, "city": "Arlington"}


def test_query_sort_puts_nulls_last(client, dataset):
    rows = query(client, dataset["id"], sort=[{"column": "age", "desc": True}])["rows"]
    assert [r["name"] for r in rows] == ["Alan", "Ada", "Grace"]


def test_query_search_is_case_insensitive(client, dataset):
    result = query(client, dataset["id"], search="LONDON")
    assert result["total"] == 1
    assert result["rows"][0]["name"] == "Ada"


@pytest.mark.parametrize(
    ("op", "value", "names"),
    [
        ("eq", "36", ["Ada"]),
        ("ne", "36", ["Alan", "Grace"]),
        ("gt", 36, ["Alan"]),
        ("lte", "41", ["Ada", "Alan"]),
        ("is_null", None, ["Grace"]),
        ("is_not_null", None, ["Ada", "Alan"]),
    ],
)
def test_query_filters(client, dataset, op, value, names):
    filters = [{"column": "age", "op": op, "value": value}]
    rows = query(client, dataset["id"], filters=filters)["rows"]
    assert [r["name"] for r in rows] == names


def test_query_contains_filter(client, dataset):
    filters = [{"column": "city", "op": "contains", "value": "ON"}]
    rows = query(client, dataset["id"], filters=filters)["rows"]
    assert [r["name"] for r in rows] == ["Ada", "Grace"]


def test_query_rejects_bad_columns_and_values(client, dataset):
    url = f"/v1/datasets/{dataset['id']}/query"
    unknown = client.post(url, json={"sort": [{"column": "nope"}]})
    assert unknown.status_code == 400
    bad_value = client.post(url, json={"filters": [{"column": "age", "op": "eq", "value": "x"}]})
    assert bad_value.status_code == 400
    assert client.post("/v1/datasets/nope/query", json={}).status_code == 404


@pytest.fixture
def http_dir(tmp_path):
    """A local HTTP server for the files in a directory. Yields (directory, base URL)."""
    directory = tmp_path / "www"
    directory.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield directory, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_create_from_url(client, http_dir):
    directory, base = http_dir
    (directory / "people.csv").write_text(CSV)
    with gzip.open(directory / "events.jsonl.gz", "wt") as f:
        f.write('{"user": {"id": 1}}\n{"user": {"id": 2}}\n')

    people = client.post("/v1/datasets", data={"source": f"{base}/people.csv"}).json()
    assert people["name"] == "people"
    assert people["source"] == f"{base}/people.csv"
    assert people["row_count"] == 3

    events = client.post("/v1/datasets", data={"source": f"{base}/events.jsonl.gz"}).json()
    assert events["name"] == "events"
    assert query(client, events["id"])["rows"][1] == {"__row_id": 1, "user": {"id": 2}}


def test_url_without_extension(client, http_dir):
    directory, base = http_dir
    (directory / "comments").write_text(json.dumps([{"id": 1, "body": "hi"}]))

    response = client.post("/v1/datasets", data={"source": f"{base}/comments"})
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "comments"
    assert response.json()["row_count"] == 1


def test_url_errors(client, http_dir):
    _, base = http_dir
    missing = client.post("/v1/datasets", data={"source": f"{base}/nope.csv"})
    assert missing.status_code == 400
    assert "HTTP 404" in missing.json()["detail"]

    unreachable = client.post("/v1/datasets", data={"source": "http://127.0.0.1:1/data.csv"})
    assert unreachable.status_code == 400
    assert "Could not download" in unreachable.json()["detail"]


def _gzip(text):
    return gzip.compress(text.encode())


def _parquet(tmp_path):
    path = tmp_path / "source.parquet"
    duckdb.sql(f"COPY (SELECT 'Ada' AS name) TO '{path}' (FORMAT parquet)")
    return path.read_bytes()


@pytest.mark.parametrize(
    "content",
    [
        lambda _: b"name,age\nAda,36\n",
        lambda _: b"name\tage\nAda\t36\n",
        lambda _: b"\xef\xbb\xbfname;age\nAda;36\n",
        lambda _: b'  [{"name": "Ada"}]',
        lambda _: b'{"name": "Ada"}\n',
        lambda _: _gzip("name,age\nAda,36\n"),
        lambda _: _gzip('{"name": "Ada"}\n'),
        _parquet,
    ],
    ids=["csv", "tsv", "csv-bom-semicolon", "json", "jsonl", "csv-gz", "jsonl-gz", "parquet"],
)
def test_detects_format_from_content(client, tmp_path, content):
    # No extension, and a misleading one: the content decides how the file is read.
    for filename in ["export", "export.json"]:
        path = tmp_path / filename
        path.write_bytes(content(tmp_path))
        dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
        assert dataset["name"] == "export"
        assert dataset["row_count"] == 1
        assert query(client, dataset["id"])["rows"][0]["name"] == "Ada"


@pytest.mark.parametrize(
    ("filename", "name"),
    [
        ("people.tsv", "people"),
        ("People.CSV", "People"),
        ("events.ndjson", "events"),
        ("events.jsonl.gz", "events"),
        ("notes.txt", "notes.txt"),
        ("v1.2 export.csv", "v1.2 export"),
    ],
)
def test_names_drop_the_data_file_extension(client, tmp_path, filename, name):
    path = tmp_path / filename
    path.write_bytes(_gzip("name\nAda\n") if filename.endswith(".gz") else b"name\nAda\n")
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    assert dataset["name"] == name
    assert dataset["source"] == str(path)


def test_profile_includes_nested_fields(client, tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"actor": {"login": "ada", "id": 1}}\n{"actor": {"login": "alan", "id": 2}}\n')
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    profile = {p["name"]: p for p in client.get(f"/v1/datasets/{dataset['id']}/profile").json()}
    assert list(profile) == ["actor", "actor.login", "actor.id"]
    assert profile["actor.login"]["min"] == "ada"
    assert profile["actor.id"]["max"] == "2"


def test_query_limit_keeps_only_the_first_rows_in_order(client, dataset):
    sort = [{"column": "age", "desc": True}]
    result = query(client, dataset["id"], sort=sort, limit=2, page_size=1, offset=1)
    assert result["total"] == 2
    assert result["matched"] == 3
    assert [r["name"] for r in result["rows"]] == ["Ada"]
    assert query(client, dataset["id"], limit=2, offset=2)["rows"] == []

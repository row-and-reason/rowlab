"""Reading datasets from and exporting them to S3-compatible storage, against a local S3 server."""

import gzip

import boto3
import duckdb
import pytest
from moto.server import ThreadedMotoServer

BUCKET = "rowlab-test"
CSV = b"name,age\nAda,36\nAlan,41\n"


@pytest.fixture(scope="module")
def s3(tmp_path_factory):
    """A local S3 server with a bucket, and a client to put objects in it and read them back."""
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key="people.csv", Body=CSV)
    client.put_object(
        Bucket=BUCKET, Key="events.jsonl.gz", Body=gzip.compress(b'{"id": 1}\n{"id": 2}\n')
    )
    parquet = tmp_path_factory.mktemp("s3") / "data.parquet"
    duckdb.sql("SELECT 'Ada' AS name").write_parquet(str(parquet))
    client.put_object(Bucket=BUCKET, Key="exports/data", Body=parquet.read_bytes())
    yield endpoint, client
    server.stop()


@pytest.fixture
def connection(client, s3):
    endpoint, _ = s3
    body = {
        "name": "Local",
        "endpoint": endpoint,
        "access_key_id": "key",
        "secret_access_key": "secret",
    }
    response = client.post("/v1/connections", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def add(client, source, connection):
    return client.post("/v1/datasets", data={"source": source, "connection_id": connection["id"]})


def test_connections_never_return_their_secret(client, connection):
    assert connection["name"] == "Local"
    assert "secret" not in str(client.get("/v1/connections").json())
    # Leaving the secret out of an update keeps the saved one.
    renamed = {**connection, "name": "MinIO", "access_key_id": "key"}
    assert client.put(f"/v1/connections/{connection['id']}", json=renamed).json()["name"] == "MinIO"
    assert add(client, f"s3://{BUCKET}/people.csv", connection).status_code == 201

    missing = client.post("/v1/connections", json={"name": "x", "access_key_id": "k"})
    assert missing.json()["detail"] == "Enter the secret access key."
    assert client.delete(f"/v1/connections/{connection['id']}").status_code == 204
    assert client.get("/v1/connections").json() == []


def test_reads_csv_json_and_parquet_from_s3_by_content(client, connection):
    people = add(client, f"s3://{BUCKET}/people.csv", connection)
    assert people.status_code == 201, people.text
    assert (people.json()["name"], people.json()["row_count"]) == ("people", 2)
    assert people.json()["source"] == f"s3://{BUCKET}/people.csv"

    events = add(client, f"s3://{BUCKET}/events.jsonl.gz", connection).json()
    assert (events["name"], events["row_count"]) == ("events", 2)
    # No extension to go by: the content says it is Parquet.
    data = add(client, f"s3://{BUCKET}/exports/data", connection).json()
    assert [c["name"] for c in data["columns"]] == ["__row_id", "name"]


def test_explains_a_missing_object_and_a_misplaced_connection(client, connection, tmp_path):
    missing = add(client, f"s3://{BUCKET}/nope.csv", connection)
    assert missing.status_code == 400
    assert "404" in missing.json()["detail"]

    local = tmp_path / "people.csv"
    local.write_bytes(CSV)
    misplaced = add(client, str(local), connection)
    assert misplaced.json()["detail"] == "A connection is only for s3:// sources."


def test_exports_to_s3(client, connection, s3):
    _, bucket = s3
    dataset = add(client, f"s3://{BUCKET}/people.csv", connection).json()
    export = f"/v1/datasets/{dataset['id']}/export"

    to_folder = client.post(
        export,
        json={"format": "csv", "path": f"s3://{BUCKET}/out/", "connection_id": connection["id"]},
    )
    assert to_folder.status_code == 200, to_folder.text
    written = to_folder.json()
    assert written["path"] == f"s3://{BUCKET}/out/people.csv"
    body = bucket.get_object(Bucket=BUCKET, Key="out/people.csv")["Body"].read()
    assert body == CSV
    assert written["size_bytes"] == len(CSV)

    named = client.post(
        export,
        json={
            "format": "jsonl",
            "path": f"s3://{BUCKET}/out/people.jsonl",
            "connection_id": connection["id"],
        },
    )
    assert named.status_code == 200, named.text
    lines = bucket.get_object(Bucket=BUCKET, Key="out/people.jsonl")["Body"].read().splitlines()
    assert lines[0] == b'{"name":"Ada","age":36}'

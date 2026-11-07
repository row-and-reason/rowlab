from urllib.request import Request

import duckdb
import pytest

from rowlab.core import connections, crypto, db, network, settings, storage
from rowlab.core.config import config
from rowlab.core.connections import ConnectionInput
from rowlab.core.errors import InvalidRequest
from rowlab.core.providers import openrouter

CSV = b"name,age\nAda,36\nAlan,41\n"


def configure(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config.cache_clear()


def upload(client):
    return client.post("/v1/datasets", files={"file": ("people.csv", CSV)})


def test_a_query_that_takes_too_long_is_stopped(client, monkeypatch):
    dataset = upload(client).json()
    configure(monkeypatch, ROWLAB_QUERY_SECONDS="0.2")
    slow = "SELECT sum(a.range * b.range) AS n FROM range(100000000) a, range(100) b"
    response = client.post(f"/v1/datasets/{dataset['id']}/query", json={"sql": slow})
    assert response.status_code == 400
    assert "took longer than 0.2 s" in response.json()["detail"]
    # The next query is fine.
    ok = client.post(f"/v1/datasets/{dataset['id']}/query", json={"sql": "SELECT * FROM data"})
    assert ok.json()["total"] == 2


def test_duckdb_runs_within_its_memory_and_threads(monkeypatch):
    configure(monkeypatch, ROWLAB_DUCKDB_MEMORY="300MB", ROWLAB_DUCKDB_THREADS="1")
    with storage.connect() as con:
        memory, threads = con.execute(
            "SELECT current_setting('memory_limit'), current_setting('threads')"
        ).fetchone()
    assert (memory, threads) == ("286.1 MiB", 1)


def test_files_over_the_limit_are_refused(client, monkeypatch):
    configure(monkeypatch, ROWLAB_MAX_FILE="10")
    response = upload(client)
    assert response.status_code == 400
    assert "bigger than 10 bytes, rowlab's limit" in response.json()["detail"]


def test_uploads_far_over_the_limit_are_refused_before_they_are_read(client, monkeypatch):
    configure(monkeypatch, ROWLAB_MAX_FILE="10")
    response = client.post("/v1/datasets", files={"file": ("big.csv", b"x" * 2_000_000)})
    assert response.status_code == 413


def test_limits_must_make_sense(monkeypatch):
    configure(monkeypatch, ROWLAB_MAX_FILE="lots")
    with pytest.raises(ValueError, match="ROWLAB_MAX_FILE"):
        config()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/data.csv",
        "http://localhost/data.csv",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/data.csv",
        "http://[::1]/data.csv",
        "http://[::ffff:192.168.0.1]/data.csv",
    ],
)
def test_hosted_private_addresses_are_out_of_reach(hosted, url):
    client = hosted("ada@example.com")
    response = client.post("/v1/datasets", data={"source": url})
    assert response.status_code == 400
    assert "private address" in response.json()["detail"]


def test_redirects_to_private_addresses_are_refused(hosted):
    request = Request("https://example.com/data.csv")
    with pytest.raises(InvalidRequest, match="private address"):
        network._CheckedRedirects().redirect_request(
            request, None, 302, "Found", {}, "http://169.254.169.254/"
        )


def test_locally_private_addresses_are_fine():
    network.check_url("http://localhost:9000/bucket/data.csv")
    with pytest.raises(InvalidRequest, match="isn't an http"):
        network.check_url("file:///etc/passwd")


def test_hosted_s3_endpoints_must_be_public(hosted):
    client = hosted("ada@example.com")
    connection = {"name": "MinIO", "access_key_id": "id", "secret_access_key": "secret"}
    response = client.post(
        "/v1/settings/connections", json={**connection, "endpoint": "http://localhost:9000"}
    )
    assert response.status_code == 400
    assert "private address" in response.json()["detail"]


def test_hosted_the_servers_own_aws_credentials_go_unused(hosted):
    with duckdb.connect() as con:
        connections.configure(con, "org", None)
        assert con.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0] == 0


def test_the_bucket_datasets_are_kept_in_is_off_limits(monkeypatch):
    configure(monkeypatch, ROWLAB_STORAGE_URL="s3://rowlab-datasets/prod")
    with pytest.raises(InvalidRequest, match="where rowlab keeps datasets"):
        storage.check_not_storage("s3://rowlab-datasets/prod/abc/data.parquet")
    storage.check_not_storage("s3://someone-elses/data.csv")


def test_hosted_saved_keys_are_encrypted(hosted, monkeypatch):
    monkeypatch.setattr(openrouter, "check_key", lambda key: None)
    client = hosted("ada@example.com")
    org_id = client.get("/v1/me").json()["org"]["id"]
    assert client.put("/v1/settings/openrouter-key", json={"key": "sk-or-1"}).status_code == 200
    connection = connections.create_connection(
        org_id, ConnectionInput(name="Lake", access_key_id="id", secret_access_key="s3-secret")
    )
    with db.connect() as conn:
        stored = [
            conn.execute("SELECT value FROM settings").fetchone()["value"],
            conn.execute("SELECT secret_access_key FROM connections").fetchone()[
                "secret_access_key"
            ],
        ]
    assert all(value.startswith("enc:") for value in stored)
    assert "sk-or-1" not in stored[0] and "s3-secret" not in stored[1]
    # Read back as they were.
    assert settings.openrouter_key(org_id) == "sk-or-1"
    assert crypto.decrypt(stored[1]) == "s3-secret"
    with duckdb.connect() as con:
        connections.configure(con, org_id, connection.id)
        assert con.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0] == 1


def test_the_limit_holds_for_every_query_on_a_connection(monkeypatch):
    import time

    with pytest.raises(InvalidRequest, match="took longer"), storage.connect(0.05) as con:
        time.sleep(0.2)  # The limit passes between queries…
        # …and the next one is stopped too.
        con.execute("SELECT sum(a.range * b.range) FROM range(100000000) a, range(100) b")


def test_uploads_must_say_how_big_they_are(client):
    def body():
        yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\n'
        yield b"a\n1\n\r\n--x--\r\n"

    response = client.post(
        "/v1/datasets", content=body(), headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert response.status_code == 411


def test_files_on_the_server_over_the_limit_are_refused(client, tmp_path, monkeypatch):
    path = tmp_path / "people.csv"
    path.write_bytes(CSV)
    configure(monkeypatch, ROWLAB_MAX_FILE="10")
    response = client.post("/v1/datasets", data={"source": str(path)})
    assert response.status_code == 400
    assert "bigger than" in response.json()["detail"]


def test_the_storage_credentials_reach_only_the_storage_bucket(monkeypatch):
    configure(
        monkeypatch,
        ROWLAB_STORAGE_URL="s3://rowlab-datasets/prod",
        AWS_ACCESS_KEY_ID="key",
        AWS_SECRET_ACCESS_KEY="secret",
    )
    with storage.connect() as con:
        which = "SELECT name FROM which_secret(?, 's3')"
        assert con.execute(which, ["s3://rowlab-datasets/prod/x"]).fetchone() == ("rowlab_storage",)
        assert con.execute(which, ["s3://rowlab-datasets-other/x"]).fetchone() is None


def test_keys_saved_before_a_secret_key_are_encrypted_when_saved_again(monkeypatch):
    plain = connections.create_connection(
        "local", ConnectionInput(name="Lake", access_key_id="id", secret_access_key="s3-secret")
    )
    configure(monkeypatch, ROWLAB_SECRET_KEY="now there is one")
    connections.update_connection(
        "local", plain.id, ConnectionInput(name="Lake", access_key_id="id")
    )
    with db.connect() as conn:
        stored = conn.execute("SELECT secret_access_key FROM connections").fetchone()
    assert stored["secret_access_key"].startswith("enc:")
    assert crypto.decrypt(stored["secret_access_key"]) == "s3-secret"

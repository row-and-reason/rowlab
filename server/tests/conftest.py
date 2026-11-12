"""Every test gets a fresh rowlab: its own data folder, and by default a SQLite database and datasets on
local disk. To run the same tests on a hosted setup:

- `ROWLAB_TEST_DATABASE_URL=postgresql://…`: each test gets its own schema in that database.
- `ROWLAB_TEST_STORAGE=s3`: datasets go to a local S3 server (moto), started once.

`make test-hosted` does both.
"""

import os
import uuid

import pytest

# Nothing from the shell running the tests reaches a real database or storage, not even on import.
for name in [n for n in os.environ if n.startswith(("ROWLAB_", "WORKOS_"))]:
    if not name.startswith("ROWLAB_TEST_"):
        del os.environ[name]

from fastapi.testclient import TestClient
from helpers import FakeOpenRouter

from rowlab.api.auth import SESSION_COOKIE
from rowlab.app import create_app
from rowlab.core import auth, db, runs
from rowlab.core.config import config
from rowlab.core.providers import openrouter
from rowlab.core.providers.workos import SignedIn


@pytest.fixture(scope="session")
def s3_storage():
    """A local S3 server with a bucket for datasets, if the tests run with storage on S3."""
    if os.environ.get("ROWLAB_TEST_STORAGE") != "s3":
        yield None
        return
    import boto3
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        region_name="us-east-1",
    ).create_bucket(Bucket="rowlab-datasets")
    yield endpoint
    server.stop()


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch, s3_storage):
    """Every test gets its own empty data dir instead of `~/.rowlab`, and its own database."""
    path = tmp_path / "data"
    monkeypatch.setenv("ROWLAB_DATA_DIR", str(path))
    schema = None
    database = os.environ.get("ROWLAB_TEST_DATABASE_URL")
    if database:
        import psycopg

        schema = f"test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
        separator = "&" if "?" in database else "?"
        monkeypatch.setenv(
            "ROWLAB_DATABASE_URL", f"{database}{separator}options=-csearch_path%3D{schema}"
        )
    if s3_storage:
        monkeypatch.setenv("ROWLAB_STORAGE_URL", f"s3://rowlab-datasets/{uuid.uuid4().hex[:12]}")
        monkeypatch.setenv("AWS_ENDPOINT_URL", s3_storage)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
    config.cache_clear()
    yield path
    db.close()
    config.cache_clear()
    if schema:
        with psycopg.connect(database, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def hosted(monkeypatch):
    """Hosted mode. Returns `sign_in(email)`, which gives a client signed in as that person, as if
    WorkOS had signed them in."""
    monkeypatch.setenv("ROWLAB_MODE", "hosted")
    monkeypatch.setenv("ROWLAB_URL", "http://testserver")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_test")
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test")
    monkeypatch.setenv("WORKOS_AUTHKIT_DOMAIN", "https://rowlab-test.authkit.app")
    monkeypatch.setenv("ROWLAB_SECRET_KEY", "test secret")
    config.cache_clear()

    def sign_in(email: str) -> TestClient:
        name = email.split("@")[0].title()
        token = auth.sign_in(
            SignedIn(workos_id=f"user_{name}", email=email, name=name, email_verified=True)
        )
        signed_in = TestClient(create_app())
        signed_in.cookies.set(SESSION_COOKIE, token)
        return signed_in

    return sign_in


@pytest.fixture
def fake(monkeypatch):
    """OpenRouter replaced by a `FakeOpenRouter`, with no waiting between retries."""
    fake = FakeOpenRouter()
    monkeypatch.setattr(openrouter, "_request", fake)
    monkeypatch.setattr(openrouter, "_catalog", None)
    monkeypatch.setattr(openrouter, "RETRY_BASE_SECONDS", 0)
    monkeypatch.setattr(runs, "PROGRESS_INTERVAL_SECONDS", 0.01)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return fake


@pytest.fixture
def api_key(client, fake):
    assert client.put("/v1/settings/openrouter-key", json={"key": "sk-good"}).status_code == 200

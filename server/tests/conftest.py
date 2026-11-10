"""Every test gets a fresh rowlab: its own data folder, and by default a SQLite database and datasets on
local disk. To run the same tests on a hosted setup:

- `ROWLAB_TEST_DATABASE_URL=postgresql://…`: each test gets its own schema in that database.
- `ROWLAB_TEST_STORAGE=s3`: datasets go to a local S3 server (moto), started once.

`make test-hosted` does both.
"""

import asyncio
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from rowlab.api.auth import SESSION_COOKIE
from rowlab.app import create_app
from rowlab.core import auth, db, runs, storage
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


def stored(dataset_id, *names):
    """Whether a dataset's file is in storage, local or S3, e.g. `stored(id, "data.parquet")`."""
    return storage.exists(storage.location(dataset_id, *names))


def stored_datasets():
    """The ids of the datasets with files in storage."""
    if not config().s3_storage:
        root = config().data_dir / "datasets"
        return {p.name for p in root.iterdir()} if root.exists() else set()
    bucket, prefix = storage._split(config().storage_url + "/")
    found = storage._s3().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    return {o["Key"].removeprefix(prefix).split("/")[0] for o in found}


def chat_model(id_, price, structured=True):
    return {
        "id": id_,
        "name": id_.title(),
        "pricing": {"prompt": price, "completion": "0.000001"},
        "architecture": {"output_modalities": ["text"]},
        "supported_parameters": ["structured_outputs"] if structured else [],
    }


class FakeOpenRouter:
    """Stands in for OpenRouter's HTTP API. Says yes when the prompt mentions a bad experience.

    `busy` makes the next calls fail with a rate limit; `crash_on` makes the call for that prompt
    fail once like a killed server would, with an error nothing catches; `flaky` prompts fail once,
    with an error that isn't retried."""

    def __init__(self):
        self.calls = []
        self.busy = 0
        self.crash_on = None
        self.flaky = set()

    def __call__(self, method, path, *, api_key, body=None):
        self.calls.append((method, path, api_key, body))
        if path == "/v1/key":
            if api_key != "sk-good":
                raise openrouter.OpenRouterError("HTTP 401: Invalid key", status=401)
            return {"data": {}}
        if path == "/v1/models?output_modalities=decisions":
            return {
                "data": [
                    {"id": "typesafe/jev-1.14", "name": "Jev", "pricing": {"prompt": "0.00000004"}},
                    {"id": "a/cheap", "name": "Cheap", "pricing": {"prompt": "0.00000001"}},
                ]
            }
        if path == "/v1/models":
            return {
                "data": [
                    chat_model("x/llm", "0.000002"),
                    chat_model("anthropic/claude-haiku-5.5", "0.0000001"),
                    chat_model("y/no-schema", "0.000001", structured=False),
                ]
            }
        if path == "/v1/chat/completions":
            prompt = body["messages"][1]["content"]
            schema = body["response_format"]["json_schema"]["schema"]
            content = json.dumps(_llm_reply(schema, prompt))
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.01}}
        if self.busy:
            self.busy -= 1
            raise openrouter.OpenRouterError("HTTP 429: Rate limited", status=429)
        if body["state"] == self.crash_on:
            self.crash_on = None
            raise KeyboardInterrupt
        if body["state"] in self.flaky:
            self.flaky.remove(body["state"])
            raise openrouter.OpenRouterError("HTTP 400: Provider error", status=400)
        if body["state"] == "fail":
            raise openrouter.OpenRouterError("HTTP 400: Provider error", status=400)
        if body["state"] == "no credits":
            raise openrouter.OpenRouterError("HTTP 402: Insufficient credits", status=402)
        return {
            "answers": {"answer": {"type": "noul", "noul": 0.9 if _bad(body["state"]) else 0.1}},
            "usage": {"input_tokens": 100, "output_tokens": 1, "cost": 0.001},
        }


def _llm_reply(schema, prompt):
    """A reply with the shape the schema asks for. Yes/no answers say whether the prompt is bad."""
    reply = {}
    for name, prop in schema["properties"].items():
        if name == "answer":
            reply[name] = _bad(prompt)
        elif name == "proba":
            reply[name] = 0.8
        elif name == "reason":
            reply[name] = "Because it says so."
        elif name == "text":
            reply[name] = f"In short: {prompt}"
        else:
            reply[name] = _fake_value(prop)
    return reply


def _fake_value(prop):
    types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
    if "array" in types:
        item = prop["items"]
        return [_llm_reply(item, "")] if item["type"] == "object" else ["red", "blue"]
    if "number" in types:
        return 4
    if "boolean" in types:
        return True
    return "2024-05-01" if prop.get("description") == "YYYY-MM-DD" else "Widget"


def _bad(text):
    return any(word in text for word in ["Terrible", "Broke"])


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


def call(mcp, tool_name, **arguments):
    """Call a tool as an agent would, in-process, and return its result."""

    async def go():
        async with Client(mcp) as client:
            result = (await client.call_tool(tool_name, arguments)).structured_content
            # A list or a bare value comes wrapped.
            return result["result"] if set(result) == {"result"} else result

    return asyncio.run(go())


def tools(mcp):
    async def go():
        async with Client(mcp) as client:
            return {t.name: t.description for t in await client.list_tools()}

    return asyncio.run(go())

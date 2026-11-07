import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from test_runs import FakeOpenRouter

from rowlab.core import runs
from rowlab.core.providers import openrouter
from rowlab.mcp import server

CSV = b"review\nTerrible product\nLove it\nBroke after a day\n"


def call(mcp, name, **arguments):
    """Call a tool as an agent would, in-process, and return its result."""

    async def go():
        async with Client(mcp) as client:
            result = (await client.call_tool(name, arguments)).structured_content
            # A list or a bare value comes wrapped.
            return result["result"] if set(result) == {"result"} else result

    return asyncio.run(go())


def tools(mcp):
    async def go():
        async with Client(mcp) as client:
            return {t.name: t.description for t in await client.list_tools()}

    return asyncio.run(go())


@pytest.fixture
def mcp(client, monkeypatch):
    fake = FakeOpenRouter()
    monkeypatch.setattr(openrouter, "_request", fake)
    monkeypatch.setattr(openrouter, "_catalog", None)
    monkeypatch.setattr(runs, "PROGRESS_INTERVAL_SECONDS", 0.01)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client.put("/v1/settings/openrouter-key", json={"key": "sk-good"})
    return server.create_server()


def test_every_tool_says_what_it_is_for(mcp):
    found = tools(mcp)
    assert set(found) == {
        "datasets_list",
        "dataset_get",
        "dataset_add",
        "dataset_delete",
        "sql_query",
        "columns_compare",
        "run_preview",
        "run_start",
        "run_get",
        "run_stop",
        "run_resume",
        "dataset_export",
        "task_types_get",
        "models_list",
    }
    assert all(len(d) > 80 for d in found.values())


def test_the_workflow_from_a_file_to_an_export(mcp, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_bytes(CSV)
    added = call(mcp, "dataset_add", source=str(path))
    assert [c["name"] for c in added["columns"]] == ["__row_id", "review"]
    assert [d["id"] for d in call(mcp, "datasets_list")] == [added["id"]]

    detail = call(mcp, "dataset_get", dataset_id=added["id"], profile=True)
    assert detail["profile"][0]["name"] == "review"

    task = {"template": "Is this review negative? {{review}}", "column": "negative"}
    preview = call(mcp, "run_preview", dataset_id=added["id"], tasks=[task])
    assert preview["estimate"]["rows"] == 3
    assert preview["estimate"]["problem"] is None
    assert "Terrible product" in preview["rendered"][0]["rows"][0]["prompt"]

    run = call(mcp, "run_start", dataset_id=added["id"], tasks=[task])
    assert run["status"] == "queued"
    while runs.process_next():  # the runner thread, by hand
        pass
    run = call(mcp, "run_get", run_id=run["id"], wait_seconds=1)
    assert run["status"] == "done"
    rows = call(mcp, "sql_query", dataset_id=run["dataset_id"], sql="SELECT * FROM data")
    assert [r["negative__jev-1.14"] for r in rows["rows"]] == [True, False, True]

    out = tmp_path / "out.csv"
    exported = call(
        mcp, "dataset_export", dataset_id=run["dataset_id"], format="csv", path=str(out)
    )
    assert exported["size_bytes"] > 0
    assert "negative" in out.read_text().splitlines()[0]


def test_errors_say_what_went_wrong(mcp):
    with pytest.raises(ToolError, match="not found"):
        call(mcp, "dataset_get", dataset_id="nope")
    with pytest.raises(ToolError, match="File not found"):
        call(mcp, "dataset_add", source="/nowhere/data.csv")


def test_the_catalog_tools(mcp):
    types = call(mcp, "task_types_get")
    assert len(types["types"]) >= 3 and types["presets"]
    decision = call(mcp, "models_list", kind="decision")
    assert {m["kind"] for m in decision} == {"decision"}
    assert [m["id"] for m in call(mcp, "models_list", search="haiku")] == [
        "anthropic/claude-haiku-5.5"
    ]


def test_hosted_mcp_needs_a_token(hosted):
    client = hosted("ada@example.com")
    bare = client.post("/mcp", json={}, headers={"accept": "application/json, text/event-stream"})
    assert bare.status_code == 401
    assert "oauth-protected-resource" in bare.headers["www-authenticate"]
    metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["resource"] == "http://testserver/mcp"
    assert metadata["authorization_servers"] == ["https://rowlab-test.authkit.app"]


def test_hosted_an_api_key_signs_in_to_mcp(hosted):
    client = hosted("ada@example.com")
    key = client.post("/v1/settings/api-keys", json={"name": "agent"}).json()["key"]
    mcp = server.create_server()
    token = asyncio.run(mcp.auth.verify_token(key))
    assert isinstance(token, AccessToken)
    assert token.claims["rowlab"]["user"]["email"] == "ada@example.com"
    assert asyncio.run(mcp.auth.verify_token("rl_nope")) is None


def test_hosted_workos_tokens_must_be_for_this_server(hosted):
    hosted("ada@example.com")
    mcp = server.create_server()
    workos = mcp.auth.token_verifier._workos
    assert workos.audience == "http://testserver/mcp"
    assert workos.issuer == "https://rowlab-test.authkit.app"
    # Someone WorkOS vouches for, who hasn't signed in to rowlab in a browser yet.
    from rowlab.core import auth
    from rowlab.core.errors import Unauthorized

    with pytest.raises(Unauthorized, match="browser first"):
        auth.me_for_workos_user("user_nobody")
    assert auth.me_for_workos_user("user_Ada").user.email == "ada@example.com"

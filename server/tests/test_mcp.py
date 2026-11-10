import asyncio

import pytest
from conftest import call, tools
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from rowlab.core import runs
from rowlab.core.providers import openrouter
from rowlab.mcp import server

CSV = b"review\nTerrible product\nLove it\nBroke after a day\n"


@pytest.fixture
def mcp(api_key):
    return server.create_server()


def test_every_tool_says_what_it_is_for(mcp):
    found = tools(mcp)
    assert set(found) == {
        "datasets_list",
        "dataset_get",
        "dataset_add",
        "dataset_delete",
        "dataset_rename",
        "sql_query",
        "columns_compare",
        "run_preview",
        "run_start",
        "run_answers",
        "run_finish",
        "run_get",
        "run_stop",
        "run_resume",
        "dataset_export",
        "dataset_upload",
        "dataset_download",
        "task_types_get",
        "models_list",
    }
    assert all(found.values())


def test_the_workflow_from_a_file_to_an_export(mcp, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_bytes(CSV)
    added = call(mcp, "dataset_add", source=str(path))
    assert [c["name"] for c in added["columns"]] == ["__row_id", "review"]
    assert [d["id"] for d in call(mcp, "datasets_list")] == [added["id"]]
    renamed = call(mcp, "dataset_rename", dataset_id=added["id"], name="Reviews")
    assert renamed == {**added, "name": "Reviews"}

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


def test_tool_calls_need_no_session(monkeypatch):
    # As after a restart: no `initialize` first and no session id, and the call still works.
    monkeypatch.setenv("ROWLAB_NO_RUNNER", "1")  # The app's lifespan would start one, for good.
    from fastapi.testclient import TestClient

    from rowlab.app import create_app

    with TestClient(create_app()) as client:
        reply = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "task_types_get", "arguments": {}},
            },
            headers={"accept": "application/json, text/event-stream"},
        )
    assert reply.status_code == 200
    assert "yes_no" in reply.text


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


def test_comparison_text_rules_and_numeric_diagnostics_through_mcp(mcp, tmp_path):
    path = tmp_path / "compare.csv"
    path.write_text("a,b,x,y\nBug,bug,0.3,0.4\nBUG,bug,0.7,0.8\n")
    dataset = call(mcp, "dataset_add", source=str(path))
    result = call(
        mcp,
        "columns_compare",
        dataset_id=dataset["id"],
        columns=["a"],
        reference="b",
        ignore_case=True,
        trim_whitespace=True,
    )
    assert result["pairs"][0]["agree"] == 2
    assert result["ignore_case"] is True
    result = call(
        mcp, "columns_compare", dataset_id=dataset["id"], columns=["x", "y"], tolerance=0.1
    )
    assert result["pairs"][0]["agree"] == 2
    assert result["pairs"][0]["numeric"]["finite_pairs"] == 2
    with pytest.raises(ToolError):
        call(mcp, "columns_compare", dataset_id=dataset["id"], columns=["x", "y"], tolerance=-1)


def test_comparison_summary_preserves_class_metrics(mcp, tmp_path):
    path = tmp_path / "compare.csv"
    path.write_text("a,b,c,label\nyes,yes,no,yes\nno,yes,no,no\n")
    dataset = call(mcp, "dataset_add", source=str(path))
    args = {"dataset_id": dataset["id"], "columns": ["a", "b", "c"], "reference": "label"}
    summary = call(mcp, "columns_compare", **args)
    full = call(mcp, "columns_compare", **args, detail="full")
    assert summary["reference"] == full["reference"]
    assert "values" not in summary
    assert summary["pairs"][0]["coverage"]["missing_left"] == 0
    assert full["pairs"][0]["coverage"]["missing_left"]["rows"] == 0


def test_model_default_is_bounded_and_filters_before_paging(mcp, monkeypatch):
    catalog = [
        openrouter.Model(
            id=f"llm-{i}",
            name=f"Model {i}",
            kind="llm",
            prompt_price=0,
            completion_price=0,
            context_length=1000,
        )
        for i in range(423)
    ]
    monkeypatch.setattr(openrouter, "models", lambda: catalog)
    page = call(mcp, "models_list")
    assert len(page["models"]) == 20
    assert page["total"] == 423
    assert page["next_offset"] == 20
    page = call(mcp, "models_list", search="llm-42", offset=1)
    assert [m["id"] for m in page["models"]] == ["llm-420", "llm-421", "llm-422"]
    assert page["total"] == 4
    assert page["next_offset"] is None
    with pytest.raises(ToolError):
        call(mcp, "models_list", limit=101)

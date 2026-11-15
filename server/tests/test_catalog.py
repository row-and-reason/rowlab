"""The models: rowlab's list first, in its order, then any in OpenRouter's catalog, at current prices."""

import pytest
from fastmcp.exceptions import ToolError
from helpers import NEGATIVE, call, run

from rowlab.core import catalog
from rowlab.core.providers import model_api, openrouter
from rowlab.core.providers.model_api import ProviderError
from rowlab.mcp import server

pytestmark = pytest.mark.usefixtures("fake")


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nLove it\nBroke on day one\n")
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def test_lists_the_offered_models_in_order_at_openrouters_prices(client):
    models = client.get("/v1/utils/models").json()
    assert [m["id"] for m in models] == [
        "typesafe/jev-1.14",
        "a/cheap",
        "anthropic/claude-haiku-5.5",
        "x/llm",
        "x/unpriced",
    ]
    by_id = {m["id"]: m for m in models}
    assert by_id["typesafe/jev-1.14"]["tags"] == ["recommended"]
    assert by_id["x/llm"]["prompt_price"] == 2e-06
    # OpenRouter doesn't price it: the list's own prices, given per million tokens.
    assert by_id["x/unpriced"]["prompt_price"] == pytest.approx(3e-06)
    assert by_id["x/unpriced"]["completion_price"] == pytest.approx(4e-06)


def test_models_are_listed_when_openrouter_is_down(client, monkeypatch):
    def down():
        raise ProviderError("Could not reach openrouter.ai")

    monkeypatch.setattr(openrouter, "models", down)
    models = {m["id"]: m for m in client.get("/v1/utils/models").json()}
    assert models["typesafe/jev-1.14"]["prompt_price"] == pytest.approx(5e-08)

    # Nor when it answers in a shape it didn't before.
    monkeypatch.setattr(catalog, "_openrouter", None)
    monkeypatch.setattr(model_api, "_request", lambda *args, **kwargs: {"models": []})
    models = {m["id"]: m for m in client.get("/v1/utils/models").json()}
    assert models["typesafe/jev-1.14"]["prompt_price"] == pytest.approx(5e-08)


def test_all_lists_the_rest_of_openrouters_catalog_that_rowlab_can_ask(client):
    models = client.get("/v1/utils/models", params={"all": True}).json()
    assert [m["id"] for m in models] == [
        "typesafe/jev-1.14",
        "a/cheap",
        "anthropic/claude-haiku-5.5",
        "x/llm",
        "x/unpriced",
        # Not without structured outputs, nor priced per call.
        "b/decider",
        "y/other",
    ]
    assert [m["listed"] for m in models] == [True] * 5 + [False] * 2
    assert models[-2]["kind"] == "decision"


def test_any_model_openrouter_has_can_run_not_only_the_listed(client, dataset, api_key):
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data"}
    finished = run(client, {**job, "tasks": [{**NEGATIVE, "models": ["y/other", "b/decider"]}]})
    assert finished["status"] == "done"
    assert all(c["failed"] == 0 for c in finished["costs"])
    for model in ("z/plain", "r/auto", "nobody/nothing"):
        refused = run(client, {**job, "tasks": [{**NEGATIVE, "models": [model]}]})
        assert refused["detail"].startswith(f"Task negative: Unknown model: {model}.")
    # An unlisted decision model is still one.
    write = {"template": "{{review}}", "type": "write", "column": "short", "models": ["b/decider"]}
    assert "decision model" in run(client, {**job, "tasks": [write]})["detail"]


def test_an_unlisted_model_cant_be_checked_while_openrouter_is_down(
    client, dataset, api_key, monkeypatch
):
    def down():
        raise ProviderError("Could not reach openrouter.ai")

    monkeypatch.setattr(openrouter, "models", down)
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data"}
    refused = run(client, {**job, "tasks": [{**NEGATIVE, "models": ["y/other"]}]})
    assert "Couldn't check y/other" in refused["detail"]
    assert run(client, {**job, "tasks": [{**NEGATIVE, "models": ["x/llm"]}]})["status"] == "done"


def test_mcp_pages_filter_before_paging(api_key):
    mcp = server.create_server()
    page = call(mcp, "models_list", limit=2)
    assert [m["id"] for m in page["models"]] == ["typesafe/jev-1.14", "a/cheap"]
    assert (page["total"], page["next_offset"]) == (5, 2)
    page = call(mcp, "models_list", tag="recommended", kind="llm")
    assert [m["id"] for m in page["models"]] == ["anthropic/claude-haiku-5.5"]
    assert page["next_offset"] is None
    page = call(mcp, "models_list", search="other", all=True)
    assert [m["id"] for m in page["models"]] == ["y/other"]
    with pytest.raises(ToolError):
        call(mcp, "models_list", limit=101)

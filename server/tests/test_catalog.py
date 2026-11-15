"""The model list: what's offered, in what order, at what price."""

import pytest
from fastmcp.exceptions import ToolError
from helpers import NEGATIVE, call, run, start

from rowlab.core import catalog, runs
from rowlab.core.providers import openrouter
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
        raise openrouter.OpenRouterError("Could not reach OpenRouter")

    monkeypatch.setattr(openrouter, "prices", down)
    models = {m["id"]: m for m in client.get("/v1/utils/models").json()}
    assert models["typesafe/jev-1.14"]["prompt_price"] == pytest.approx(5e-08)


def test_deprecated_models_take_no_new_runs_but_old_ones_finish(client, dataset, api_key):
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data"}
    retired = {**NEGATIVE, "models": ["old/retired"]}
    assert run(client, {**job, "tasks": [retired]})["detail"] == (
        "Task negative: old/retired is no longer offered. Pick another model."
    )

    created = start(client, {**job, "tasks": [{**NEGATIVE, "models": ["x/llm"]}]})
    entry = next(e for e in catalog._load() if e.id == "x/llm")
    entry.deprecated = True
    while runs.process_next():
        pass
    finished = client.get(f"/v1/runs/{created['id']}").json()
    assert finished["status"] == "done"
    assert "x/llm" not in [m["id"] for m in client.get("/v1/utils/models").json()]


def test_mcp_pages_filter_before_paging(api_key):
    mcp = server.create_server()
    page = call(mcp, "models_list", limit=2)
    assert [m["id"] for m in page["models"]] == ["typesafe/jev-1.14", "a/cheap"]
    assert (page["total"], page["next_offset"]) == (5, 2)
    page = call(mcp, "models_list", tag="recommended", kind="llm")
    assert [m["id"] for m in page["models"]] == ["anthropic/claude-haiku-5.5"]
    assert page["next_offset"] is None
    with pytest.raises(ToolError):
        call(mcp, "models_list", limit=101)

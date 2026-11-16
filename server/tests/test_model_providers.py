"""Model providers: an organisation's own keys, one active for catalog models, and where each run's
calls go."""

import pytest
from helpers import NEGATIVE, call, run, start

from rowlab.core import db, model_providers, runs
from rowlab.core.providers import model_api
from rowlab.mcp import server

pytestmark = pytest.mark.usefixtures("fake")

GATEWAY = {
    "type": "openai",
    "name": "Gateway",
    "base_url": "https://litellm.example.com/v1/",
    "model_prefix": "openrouter/",
    "api_key": "sk-good",
}
LLM_TASK = {**NEGATIVE, "models": ["x/llm"]}
# Before the `fake` fixture replaces it.
REAL_REQUEST = model_api._request


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nLove it\nBroke on day one\n")
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def add(client, **provider):
    return client.post("/v1/settings/providers", json=provider)


def test_a_provider_is_saved_once_it_accepts_the_key_which_is_never_returned(client):
    assert client.get("/v1/settings").json()["provider"] is None
    bad = add(client, type="openrouter", api_key="sk-bad")
    assert bad.status_code == 400
    assert bad.json()["detail"].startswith("OpenRouter did not accept the key")
    assert add(client, type="openai", api_key="sk-good").json()["detail"] == (
        "Enter the server's address."
    )
    saved = add(client, type="openrouter", api_key=" sk-good ").json()
    assert (saved["name"], saved["base_url"], saved["active"]) == (
        "OpenRouter",
        "https://openrouter.ai/api",
        True,
    )
    assert client.get("/v1/settings").json()["provider"] == "organisation"
    assert "sk-good" not in client.get("/v1/settings/providers").text


def test_one_provider_is_active_and_a_run_keeps_the_one_it_started_with(client, dataset, fake):
    first = add(client, type="openrouter", api_key="sk-good").json()
    gateway = add(client, **GATEWAY).json()
    # Saved without its trailing `/v1`; the first provider stays active.
    assert gateway["base_url"] == "https://litellm.example.com"
    providers = client.get("/v1/settings/providers").json()
    assert {p["id"]: p["active"] for p in providers} == {first["id"]: True, gateway["id"]: False}

    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [LLM_TASK]}
    created = start(client, job)
    client.post(f"/v1/settings/providers/{gateway['id']}/activate")
    providers = client.get("/v1/settings/providers").json()
    assert {p["id"]: p["active"] for p in providers} == {first["id"]: False, gateway["id"]: True}
    while runs.process_next():
        pass
    assert client.get(f"/v1/runs/{created['id']}").json()["status"] == "done"
    asked = [u for u, c in zip(fake.urls, fake.calls, strict=True) if c[0] == "POST"]
    assert asked and all(u.startswith("https://openrouter.ai/") for u in asked)

    # The next run goes to the gateway, with its prefix before the model's id. (Asked something
    # new: a reply kept from the same model is used whichever provider it came through.)
    fake.calls.clear()
    fake.urls.clear()
    again = {**LLM_TASK, "column": "again", "template": LLM_TASK["template"] + " Really?"}
    finished = run(client, {**job, "tasks": [again]})
    assert finished["status"] == "done"
    assert finished["provider_id"] == gateway["id"]
    posts = [(u, c[3]) for u, c in zip(fake.urls, fake.calls, strict=True) if c[0] == "POST"]
    assert {u for u, _ in posts} == {"https://litellm.example.com/v1/chat/completions"}
    assert {body["model"] for _, body in posts} == {"openrouter/x/llm"}
    # Its columns are named after rowlab's model id, prefix or not.
    assert "again__llm" in finished["columns"]


def test_without_a_cost_in_the_reply_it_is_worked_out_from_prices(client, dataset, fake):
    add(client, **GATEWAY)
    fake.reports_cost = False
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [LLM_TASK]}
    finished = run(client, job)
    # 2 rows × (1000 tokens in at $2/M + 100 out at $1/M).
    assert finished["cost"] == pytest.approx(2 * (1000 * 2e-06 + 100 * 1e-06))


def test_decision_models_answer_through_an_openai_server_like_through_openrouter(
    client, dataset, fake
):
    add(client, **GATEWAY)
    review = "{{review}}"
    jev = ["typesafe/jev-1.14"]
    tasks = [
        {**NEGATIVE, "models": jev},
        {
            "template": review,
            "type": "pick_one",
            "column": "team",
            "models": jev,
            "options": [{"name": "ops"}, {"name": "sales", "description": "Selling things"}],
        },
        {
            "template": review,
            "type": "scale",
            "column": "stars",
            "models": jev,
            "options": [{"name": "1"}, {"name": "3"}, {"name": "5"}],
        },
        {
            "template": review,
            "type": "pick_any",
            "column": "topic",
            "models": jev,
            "options": [{"name": "price"}, {"name": "delivery"}],
        },
    ]
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": tasks}
    finished = run(client, job)
    assert finished["status"] == "done"
    assert all(c["failed"] == 0 for c in finished["costs"])
    posts = [(u, c[3]) for u, c in zip(fake.urls, fake.calls, strict=True) if c[0] == "POST"]
    assert {u for u, _ in posts} == {"https://litellm.example.com/v1/decisions"}
    assert {body["model"] for _, body in posts} == {"openrouter/typesafe/jev-1.14"}
    response = client.post(f"/v1/datasets/{finished['dataset_id']}/query", json={})
    broke = next(r for r in response.json()["rows"] if r["review"] == "Broke on day one")
    assert (broke["negative__jev-1.14"], broke["negative__jev-1.14_proba"]) == (True, 0.9)
    assert (broke["team__jev-1.14"], broke["team__jev-1.14_proba"]) == ("sales", 0.8)
    assert (broke["stars__jev-1.14"], broke["stars__jev-1.14_proba"]) == ("5", 1.0)
    assert broke["topic_delivery__jev-1.14"] is True
    # No cost in OpenAI-style decision replies: 100 tokens in at Jev's $0.04/M, for each of 2 rows × 4.
    assert finished["cost"] == pytest.approx(8 * 100 * 4e-08)


def test_a_run_whose_provider_was_deleted_fails_saying_so(client, dataset):
    provider = add(client, type="openrouter", api_key="sk-good").json()
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    created = start(client, job)
    assert client.delete(f"/v1/settings/providers/{provider['id']}").status_code == 204
    assert client.get("/v1/settings").json()["provider"] is None
    with pytest.raises(Exception, match="was deleted"):
        runs.process_next()
    failed = client.get(f"/v1/runs/{created['id']}").json()
    assert failed["status"] == "failed"
    assert "was deleted" in failed["error"]


def test_the_servers_key_wins(client, api_key, dataset, fake, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    assert client.get("/v1/settings").json()["provider"] == "server"
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    run(client, job)
    asked = {key for method, path, key, body in fake.calls if method == "POST"}
    assert asked == {"sk-env"}


def test_a_saved_openrouter_key_becomes_the_active_provider():
    sql = (db.MIGRATIONS_DIR / "006_providers.sql").read_text()
    backfill = sql[sql.index("INSERT INTO providers") :]
    with db.connect() as conn:
        conn.execute("DELETE FROM providers")
        conn.execute(
            "INSERT INTO settings (org_id, key, value) VALUES ('local', 'openrouter_api_key', 'k')"
        )
        for statement in backfill.split(";"):
            if statement.strip():
                conn.execute(statement)
    [provider] = model_providers.list_providers("local")
    assert (provider.type, provider.active) == ("openrouter", True)
    assert model_providers.for_run("local", None).api_key == "k"


def test_a_saved_key_goes_only_where_it_was_first_sent(client, fake):
    gateway = add(client, **GATEWAY).json()
    path = f"/v1/settings/providers/{gateway['id']}"
    moved = {**GATEWAY, "base_url": "https://elsewhere.example.net", "api_key": None}
    response = client.put(path, json=moved)
    assert response.status_code == 400
    assert response.json()["detail"] == "Enter the API key again to change the base URL."
    assert not any("elsewhere" in url for url in fake.urls)
    assert client.put(path, json={**moved, "type": "openrouter"}).status_code == 400
    # Renamed, with the key kept; or moved, with the key entered again.
    renamed = client.put(path, json={**GATEWAY, "name": "Homelab", "api_key": None})
    assert renamed.json()["name"] == "Homelab"
    assert client.put(path, json={**moved, "api_key": "sk-good"}).status_code == 200


def test_a_reply_that_cant_be_read_fails_its_answer_not_the_run(client, dataset, fake, monkeypatch):
    add(client, type="openrouter", api_key="sk-good")

    def odd(method, url, *, api_key, body=None, timeout=None):
        if method == "POST":
            fake.calls.append((method, url, api_key, body))
            return {"choices": "?", "usage": {"cost": 0.01}}
        return fake(method, url, api_key=api_key, body=body)

    monkeypatch.setattr(model_api, "_request", odd)
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [LLM_TASK]}
    finished = run(client, job)
    assert finished["status"] == "done"
    assert finished["costs"][0]["failed"] == 2
    # Paid for, so counted.
    assert finished["cost"] == pytest.approx(0.02)


def test_a_base_url_that_isnt_an_api_is_refused_on_save(client, monkeypatch):
    class Page:
        status_code, headers, is_error, is_redirect, text = 200, {}, False, False, "<html>"

        def json(self):
            raise ValueError("not JSON")

    monkeypatch.setattr(model_api, "_request", REAL_REQUEST)
    monkeypatch.setattr(model_api._client, "request", lambda *args, **kwargs: Page())
    response = add(client, **GATEWAY)
    assert response.status_code == 400
    assert "wasn't JSON" in response.json()["detail"]


def test_an_openai_decision_reply_missing_its_probabilities_fails_its_answer(
    client, dataset, fake, monkeypatch
):
    add(client, **GATEWAY)

    def partial(method, url, *, api_key, body=None, timeout=None):
        reply = fake(method, url, api_key=api_key, body=body)
        if url.endswith("/v1/decisions"):
            del reply["answers"][0]["probabilities"]
        return reply

    monkeypatch.setattr(model_api, "_request", partial)
    pick = {
        "template": "{{review}}",
        "type": "pick_one",
        "column": "team",
        "models": ["typesafe/jev-1.14"],
        "options": [{"name": "ops"}, {"name": "sales"}],
    }
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [pick]}
    finished = run(client, job)
    assert (finished["status"], finished["costs"][0]["failed"]) == ("done", 2)
    assert finished["cost"] > 0


def test_provider_names_are_unique_as_models_are_added_by_them(client, fake):
    assert add(client, type="openrouter", api_key="sk-good").status_code == 201
    second = add(client, type="openrouter", api_key="sk-good")
    assert second.json()["detail"] == (
        "A provider is already named OpenRouter. Give this one another name."
    )
    assert add(client, type="openrouter", name="Team", api_key="sk-good").status_code == 201


def test_a_litellm_provider_becomes_an_openai_one():
    sql = (db.MIGRATIONS_DIR / "009_models.sql").read_text()
    rename = sql[sql.index("UPDATE providers") : sql.index(";") + 1]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO providers (id, org_id, name, type, base_url, model_prefix, api_key,"
            " created_at) VALUES ('p', 'local', 'Gateway', 'litellm', 'https://g', '', 'k', '2026-11-16T00:00:00+00:00')"
        )
        conn.execute(rename)
    assert model_providers.get_provider("local", "p").type == "openai"


def test_an_agent_adds_a_gpu_and_moves_it_to_the_next_machine(client, api_key, fake):
    mcp = server.create_server()
    gpu = {"name": "gpu", "type": "systemone", "api_key": "sk-good"}
    added = call(mcp, "provider_add", **gpu, base_url="https://gpu-1.example.com")
    assert [p["name"] for p in call(mcp, "providers_list")] == ["gpu", "OpenRouter"]
    moved = call(
        mcp,
        "provider_move",
        provider="gpu",
        base_url="https://gpu-2.example.com",
        api_key="sk-good",
    )
    assert (moved["id"], moved["base_url"]) == (added["id"], "https://gpu-2.example.com")

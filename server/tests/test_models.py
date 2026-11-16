"""An organisation's own models: served where it chooses, asked like catalog models, and recording
for good what answered."""

import pytest
from helpers import NEGATIVE, call, run

from rowlab.core.providers import model_api
from rowlab.core.providers.model_api import ProviderError
from rowlab.mcp import server

pytestmark = pytest.mark.usefixtures("fake")

GPU = {
    "type": "systemone",
    "name": "gpu",
    "base_url": "https://gpu.example.com",
    "api_key": "sk-good",
}
KEV = {"id": "kev-base", "provider": "gpu", "upstream": "kev-latest", "note": "kev-4b @ 6cfce5c"}


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nLove it\nBroke on day one\n")
    return client.post("/v1/datasets", data={"source": str(path)}).json()


@pytest.fixture
def gpu(client, api_key):
    """OpenRouter, active for catalog models, and a GPU serving System One."""
    assert client.post("/v1/settings/providers", json=GPU).status_code == 201


def posts(fake):
    return [
        (url, call[3]) for url, call in zip(fake.urls, fake.calls, strict=True) if call[0] == "POST"
    ]


def test_an_own_model_answers_beside_catalog_models_in_one_run(client, gpu, dataset, fake):
    fake.calls.clear()
    fake.urls.clear()
    added = client.post("/v1/models", json=KEV)
    assert added.status_code == 201
    # Asked once first, by the name its server gives it.
    [(url, body)] = posts(fake)
    assert (url, body["model"]) == ("https://gpu.example.com/v1/systemone", "kev-latest")
    listed = client.get("/v1/models").json()
    assert listed[0]["id"] == "kev-base"
    assert (listed[0]["prompt_price"], listed[0]["note"]) == (None, "kev-4b @ 6cfce5c")

    task = {**NEGATIVE, "models": ["typesafe/jev-1.14", "kev-base"]}
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [task]}
    estimate = client.post(f"/v1/datasets/{dataset['id']}/estimate", json=job).json()
    assert (estimate["problem"], estimate["unpriced"]) == (None, ["kev-base"])
    fake.calls.clear()
    fake.urls.clear()
    finished = run(client, job)
    assert finished["status"] == "done"
    asked = {(url, body["model"]) for url, body in posts(fake)}
    assert asked == {
        ("https://openrouter.ai/api/alpha/decisions", "typesafe/jev-1.14"),
        ("https://gpu.example.com/v1/systemone", "kev-latest"),
    }
    # The run keeps what answered, and its column reads like a catalog model's.
    assert finished["models"]["kev-base"]["note"] == "kev-4b @ 6cfce5c"
    rows = client.post(f"/v1/datasets/{dataset['id']}/query", json={}).json()["rows"]
    broke = next(r for r in rows if r["review"] == "Broke on day one")
    assert (broke["negative__kev-base"], broke["negative__kev-base_proba"]) == (True, 0.9)
    # Only Jev is paid for: the GPU says no cost, and the model has no prices.
    by_model = {c["model"]: c["cost"] for c in finished["costs"]}
    assert by_model["kev-base"] == 0 and by_model["typesafe/jev-1.14"] > 0


def test_a_model_that_doesnt_answer_is_not_added(client, gpu):
    missing = client.post("/v1/models", json={**KEV, "upstream": "not-served"})
    assert missing.status_code == 400
    assert "not-served didn't answer through gpu" in missing.json()["detail"]
    nowhere = client.post("/v1/models", json={**KEV, "provider": "elsewhere"})
    assert "No provider is named elsewhere. The organisation's: OpenRouter, gpu." in nowhere.text
    for bad in ("Kev", "team/kev", ""):
        assert client.post("/v1/models", json={**KEV, "id": bad}).status_code == 400
    assert [m for m in client.get("/v1/models").json() if m["provider_id"]] == []


def test_what_answers_never_changes_and_an_id_never_goes_to_another_model(client, gpu, dataset):
    assert client.post("/v1/models", json=KEV).status_code == 201
    # Adding the same again is fine, so a script can run twice; other weights under its id aren't.
    taken = client.post("/v1/models", json={**KEV, "upstream": "kev-v2"})
    assert "is another model, with another served name" in taken.json()["detail"]
    changed = client.patch("/v1/models/kev-base", json={"note": "kev-4b", "prompt_price": 1e-7})
    assert (changed.json()["note"], changed.json()["prompt_price"]) == ("kev-4b", 1e-7)
    # Edited, it is still the same model to a script adding it again.
    assert client.post("/v1/models", json=KEV).json()["note"] == "kev-4b"

    assert client.delete("/v1/models/kev-base").status_code == 204
    assert "kev-base" not in {m["id"] for m in client.get("/v1/models").json()}
    job = {**NEGATIVE, "models": ["kev-base"]}
    refused = client.post(f"/v1/datasets/{dataset['id']}/runs", json={"tasks": [job]})
    assert "kev-base was deleted" in refused.json()["detail"]
    assert client.delete("/v1/models/kev-base").status_code == 404
    # Its id goes to no other model; the same model comes back.
    other = client.post("/v1/models", json={**KEV, "upstream": "kev-v2"})
    assert "was a model here before, with another served name" in other.json()["detail"]
    assert client.post("/v1/models", json=KEV).status_code == 201
    assert "kev-base" in {m["id"] for m in client.get("/v1/models").json()}


def test_checkpoints_served_under_one_name_never_share_replies(client, gpu, dataset, fake):
    for step in ("step-100", "step-200"):
        model = {"id": f"ft-{step}", "provider": "gpu", "upstream": "fallacy-ft"}
        assert client.post("/v1/models", json=model).status_code == 201
    asked = []
    for step in ("step-100", "step-200"):
        fake.calls.clear()
        fake.urls.clear()
        task = {**NEGATIVE, "models": [f"ft-{step}"]}
        job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [task]}
        assert run(client, job)["status"] == "done"
        asked.append(len(posts(fake)))
    assert asked == [2, 2]


def test_a_run_fails_when_its_models_server_is_down_and_resumes_once_up(
    client, gpu, dataset, fake, monkeypatch
):
    assert client.post("/v1/models", json=KEV).status_code == 201

    def down(method, url, *, api_key, body=None, timeout=None):
        if "gpu.example.com" in url:
            raise ProviderError("Could not reach gpu.example.com: refused", unreachable=True)
        return fake(method, url, api_key=api_key, body=body)

    monkeypatch.setattr(model_api, "_request", down)
    task = {**NEGATIVE, "models": ["typesafe/jev-1.14", "kev-base"]}
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [task]}
    with pytest.raises(Exception, match="Is the model's server up"):
        run(client, job)
    failed = client.get(f"/v1/datasets/{dataset['id']}/runs").json()[0]
    assert failed["status"] == "failed"
    assert "Is the model's server up" in failed["error"]

    # Back up, at a new address: the run asks only what it didn't get.
    monkeypatch.setattr(model_api, "_request", fake)
    providers = client.get("/v1/settings/providers").json()
    gpu_id = next(p["id"] for p in providers if p["name"] == "gpu")
    moved = {**GPU, "base_url": "https://gpu-2.example.com"}
    assert client.put(f"/v1/settings/providers/{gpu_id}", json=moved).status_code == 200
    fake.calls.clear()
    fake.urls.clear()
    finished = run(client, job)
    assert finished["status"] == "done"
    assert {url for url, _ in posts(fake)} == {"https://gpu-2.example.com/v1/systemone"}


def test_a_provider_is_deleted_only_once_its_models_are(client, gpu):
    assert client.post("/v1/models", json=KEV).status_code == 201
    gpu_id = next(
        p["id"] for p in client.get("/v1/settings/providers").json() if p["name"] == "gpu"
    )
    refused = client.delete(f"/v1/settings/providers/{gpu_id}")
    assert refused.json()["detail"] == "Delete its models first: kev-base."
    assert client.delete("/v1/models/kev-base").status_code == 204
    assert client.delete(f"/v1/settings/providers/{gpu_id}").status_code == 204


def test_members_add_models_through_providers_only_admins_add(hosted):
    ada = hosted("ada@example.com")
    openrouter = {"type": "openrouter", "name": "or", "api_key": "sk-good"}
    assert ada.post("/v1/settings/providers", json=openrouter).status_code == 201
    for email, role in (("bob@example.com", "member"), ("cy@example.com", "verifier")):
        ada.post("/v1/settings/invites", json={"email": email, "role": role})
    bob, cy = hosted("bob@example.com"), hosted("cy@example.com")
    assert bob.post("/v1/settings/providers", json={**openrouter, "name": "b"}).status_code == 403
    mine = {"id": "my-jev", "provider": "or", "upstream": "typesafe/jev-1.14"}
    assert cy.post("/v1/models", json=mine).status_code == 403
    assert bob.post("/v1/models", json=mine).status_code == 201


def test_an_agent_adds_a_checkpoint_over_mcp(client, gpu):
    added = call(server.create_server(), "model_add", **KEV)
    assert (added["id"], added["upstream"], added["note"]) == (
        "kev-base",
        "kev-latest",
        "kev-4b @ 6cfce5c",
    )
    found = call(server.create_server(), "models_list", search="kev")["models"]
    assert [m["id"] for m in found] == ["kev-base"]


def test_a_system_one_server_never_answers_for_rowlabs_catalog(client, dataset):
    created = client.post("/v1/settings/providers", json=GPU).json()
    assert created["active"] is False
    refused = client.post(f"/v1/settings/providers/{created['id']}/activate")
    assert "answers only the models added to it" in refused.json()["detail"]
    assert client.post("/v1/models", json=KEV).status_code == 201

    catalog_task = {**NEGATIVE, "models": ["typesafe/jev-1.14"]}
    job = {"sql": "SELECT * FROM data", "tasks": [catalog_task]}
    estimate = client.post(f"/v1/datasets/{dataset['id']}/estimate", json=job).json()
    assert estimate["problem"].startswith("Add OpenRouter, or a gateway")
    # Its own models run without a provider for the catalog.
    own = {"dataset_id": dataset["id"], **job, "tasks": [{**NEGATIVE, "models": ["kev-base"]}]}
    assert run(client, own)["status"] == "done"


def test_on_the_servers_key_own_models_still_go_to_their_own_provider(
    client, gpu, dataset, fake, monkeypatch
):
    assert client.post("/v1/models", json=KEV).status_code == 201
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    task = {**NEGATIVE, "models": ["typesafe/jev-1.14", "kev-base"]}
    fake.calls.clear()
    fake.urls.clear()
    job = {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [task]}
    assert run(client, job)["status"] == "done"
    sent = {(url.split("/")[2], c[2]) for url, c in zip(fake.urls, fake.calls) if c[0] == "POST"}
    assert sent == {("openrouter.ai", "sk-env"), ("gpu.example.com", "sk-good")}

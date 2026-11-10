"""Settings: the OpenRouter key, and the models it opens up."""

import pytest

pytestmark = pytest.mark.usefixtures("fake")


def test_saving_a_key_checks_it_and_never_returns_it(client):
    assert client.get("/v1/settings").json()["openrouter_key"] is None
    bad = client.put("/v1/settings/openrouter-key", json={"key": "sk-bad"})
    assert bad.status_code == 400
    assert "did not accept" in bad.json()["detail"]
    saved = client.put("/v1/settings/openrouter-key", json={"key": " sk-good "})
    assert saved.json()["openrouter_key"] == "saved"
    assert "sk-good" not in client.get("/v1/settings").text


def test_environment_key_wins(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    assert client.get("/v1/settings").json()["openrouter_key"] == "environment"


def test_lists_decision_models_then_llms_with_structured_outputs(client):
    models = client.get("/v1/utils/models").json()
    assert [(m["id"], m["kind"]) for m in models] == [
        ("a/cheap", "decision"),
        ("typesafe/jev-1.14", "decision"),
        ("anthropic/claude-haiku-5.5", "llm"),
        ("x/llm", "llm"),
    ]
    assert models[3]["prompt_price"] == 2e-06
    assert models[3]["completion_price"] == 1e-06

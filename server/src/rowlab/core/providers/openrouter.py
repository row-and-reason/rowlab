"""OpenRouter: what is particular to it, beside the chat completions every provider serves
(`model_api`).

- Its public catalog gives every model's current prices, whichever provider a run uses.
- Decisions API (alpha): `POST /api/alpha/decisions` with a `state` (the content to judge) and typed
  `questions`; returns one typed answer per question, by name, and its cost as `usage.cost`.
- A key is checked with `GET /api/v1/key`.
"""

from typing import Any

from rowlab.core.providers import model_api
from rowlab.core.providers.model_api import Request

BASE_URL = "https://openrouter.ai/api"
DECISIONS = "/alpha/decisions"


def prices() -> dict[str, tuple[float, float]]:
    """USD per input and output token, by model id, from OpenRouter's public catalog."""
    found = {}
    for path in ("/v1/models?output_modalities=decisions", "/v1/models"):
        for m in model_api.get(BASE_URL + path)["data"]:
            pricing = m.get("pricing") or {}
            found[m["id"]] = (
                float(pricing.get("prompt") or 0),
                float(pricing.get("completion") or 0),
            )
    return found


def check_key(base_url: str, api_key: str) -> None:
    """Raise ProviderError unless OpenRouter accepts the key."""
    model_api.get(base_url + "/v1/key", api_key)


def decision_request(model: str, state: str, questions: dict[str, Any]) -> Request:
    """Typed questions to a decision model about `state`."""
    return Request(
        path=DECISIONS,
        model=model,
        body={"model": model, "state": state, "questions": questions},
    )


def answers(reply: dict[str, Any]) -> dict[str, Any]:
    """A decision reply's answers, by question."""
    return reply["answers"]

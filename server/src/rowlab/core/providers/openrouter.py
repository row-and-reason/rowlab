"""OpenRouter: what is particular to it, beside the chat completions every provider serves
(`model_api`).

- Its public catalog lists the models rowlab can ask, beyond its own list, and every model's current
  prices, whichever provider a run uses.
- Decisions API (alpha): `POST /api/alpha/decisions` with a `state` (the content to judge) and typed
  `questions`; returns one typed answer per question, by name, and its cost as `usage.cost`.
- A key is checked with `GET /api/v1/key`.
"""

from typing import Any

from rowlab.core.providers import model_api
from rowlab.core.providers.model_api import Request

BASE_URL = "https://openrouter.ai/api"
DECISIONS = "/alpha/decisions"


def models() -> list[dict[str, Any]]:
    """The models rowlab can ask, from OpenRouter's public catalog: every decision model, and the
    LLMs that take a JSON schema for their reply (`structured_outputs`). Routers priced per call
    (negative prices) are left out: a run couldn't be estimated. Prices are USD per token."""
    found = {}
    decisions = model_api.get(BASE_URL + "/v1/models?output_modalities=decisions")["data"]
    llms = model_api.get(BASE_URL + "/v1/models")["data"]
    for kind, listed in (("llm", llms), ("decision", decisions)):
        for m in listed:
            pricing = m.get("pricing") or {}
            prompt, completion = (float(pricing.get(k) or 0) for k in ("prompt", "completion"))
            if prompt < 0 or completion < 0:
                continue
            if kind == "llm" and "structured_outputs" not in (m.get("supported_parameters") or []):
                continue
            found[m["id"]] = {
                "id": m["id"],
                "name": m.get("name") or m["id"],
                "kind": kind,
                "prompt_price": prompt,
                "completion_price": completion,
                "context_length": m.get("context_length") or 0,
            }
    return list(found.values())


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

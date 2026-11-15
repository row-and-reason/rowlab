"""LiteLLM, a gateway in front of other providers: what is particular to it, beside the chat
completions every provider serves (`model_api`).

- A gateway names models as its operator routes them, e.g. `openrouter/<vendor>/<model>`, so a
  provider can give a prefix for rowlab's model ids.
- A virtual key may list no models (a wildcard route), and may not read its own details, so a key is
  checked by listing models: 401 for a key LiteLLM doesn't know.
- Decisions: `POST /v1/decisions` in OpenAI's format: an `input` and a list of named questions
  (`predicate`, `choice` with `choices`, `score` with `levels`), answered in a list. rowlab asks in
  OpenRouter's terms (`noul`, `choice`, `score`, by name) and keeps replies in them, so this
  translates both ways. The reply's body has tokens but no cost, which is worked out from prices.
"""

from typing import Any

from rowlab.core.providers import model_api
from rowlab.core.providers.model_api import Request

DECISIONS = "/v1/decisions"


def check_key(base_url: str, api_key: str) -> None:
    """Raise ProviderError unless LiteLLM accepts the key."""
    model_api.get(base_url + "/v1/models", api_key)


def decision_request(model: str, name: str, state: str, questions: dict[str, Any]) -> Request:
    """Typed questions to a decision model about `state`, given as OpenRouter's (`decision_questions`).
    `name` is what the gateway calls the model."""
    return Request(
        path=DECISIONS,
        model=model,
        body={
            "model": name,
            "input": state,
            "questions": [_question(key, q) for key, q in questions.items()],
        },
    )


def answers(reply: dict[str, Any]) -> dict[str, Any]:
    """A decision reply's answers, by question, in OpenRouter's terms."""
    return {a.get("name"): _answer(a) for a in reply["answers"]}


def _question(name: str, question: dict[str, Any]) -> dict[str, Any]:
    asked = {"name": name, "instructions": question["instructions"]}
    if question["type"] == "noul":
        return {"type": "predicate", **asked}
    if question["type"] == "choice":
        choices = [{"value": v, "description": d} for v, d in question["criteria"].items()]
        return {"type": "choice", **asked, "choices": choices}
    levels = [{"label": label} for label in question["criteria"]]
    return {"type": "score", **asked, "levels": levels}


def _answer(answer: dict[str, Any]) -> dict[str, Any]:
    """A predicate's probability as `noul`; probabilities as a map, by choice or by level's index."""
    if answer["type"] == "predicate":
        return {"type": "noul", "noul": answer["probability"]}
    if answer["type"] in ("choice", "score"):
        probabilities = {str(p["value"]): p["probability"] for p in answer["probabilities"]}
        return {**answer, "probabilities": probabilities}
    return answer  # e.g. a refusal, which reading the answer reports

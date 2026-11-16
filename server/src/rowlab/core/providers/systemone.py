"""System One servers: decision models run where you choose, e.g. vLLM on a GPU, or a model's own
server (Kev's `kev.serve`, Laya's `laya-serve`).

- Decisions: `POST /v1/systemone`, in the format OpenRouter's Decisions API takes: a `state` and typed
  `questions` by name, answered by name. Dedicated decision models (Clef, D3, Kev, Laya) answer only
  this; vLLM answers it for generic models too, but on 0.33 without applying a LoRA adapter, which
  `openai`'s format does. The reply has no cost, which is worked out from prices, if the model has any.
- A key is checked by listing models. Not every server lists them (Laya has no `/v1/models`): a 404
  passes, and the first call to a model checks the key.
"""

from typing import Any

from rowlab.core.providers import model_api
from rowlab.core.providers.model_api import ProviderError, Request

DECISIONS = "/v1/systemone"


def check_key(base_url: str, api_key: str) -> None:
    """Raise ProviderError if the server refuses the key, or can't be reached."""
    try:
        model_api.get(base_url + "/v1/models", api_key)
    except ProviderError as e:
        if e.status != 404:
            raise


def decision_request(model: str, name: str, state: str, questions: dict[str, Any]) -> Request:
    """Typed questions to a decision model about `state`. `name` is what the server calls the model."""
    return Request(
        path=DECISIONS,
        model=model,
        body={"model": name, "state": state, "questions": questions},
    )


def answers(reply: dict[str, Any]) -> dict[str, Any]:
    """A decision reply's answers, by question."""
    return reply["answers"]

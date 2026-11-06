"""OpenRouter: the model catalog, decision calls and chat completions. Everything OpenRouter-specific
lives here.

- Decisions API (alpha): `POST /api/alpha/decisions` with a `state` (the content to judge) and typed
  `questions`; returns one typed answer per question.
- Chat completions: `POST /api/v1/chat/completions`, with `response_format` set to a JSON schema.

Both report their cost in USD as `usage.cost`.
"""

import hashlib
import json
import random
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from rowlab import __version__
from rowlab.core import db
from rowlab.core.errors import InvalidRequest

BASE_URL = "https://openrouter.ai/api"
CATALOG_TTL_SECONDS = 3600

# Per call: wait this long for an answer, and try this many times when the failure may pass.
TIMEOUT_SECONDS = 60
ATTEMPTS = 4
RETRY_BASE_SECONDS = 1.0


class Model(BaseModel):
    id: str
    name: str
    kind: Literal["decision", "llm"]
    prompt_price: float  # USD per input token
    completion_price: float  # USD per output token
    context_length: int


class Response(BaseModel):
    """A model's reply: the decision answers, or the chat message content."""

    data: Any
    cost: float
    cached: bool


class OpenRouterError(Exception):
    """A failed OpenRouter call, with OpenRouter's own message."""

    def __init__(
        self, message: str, *, status: int | None = None, retry_after: float | None = None
    ):
        super().__init__(message)
        self.status = status  # None when OpenRouter couldn't be reached or didn't answer in time
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Rate limits, server errors and timeouts may pass; anything else will fail again."""
        return self.status is None or self.status == 429 or self.status >= 500


_catalog: tuple[float, list[Model]] | None = None


def models() -> list[Model]:
    """Decision models, then LLMs that support structured outputs, each cheapest first. Cached for
    an hour."""
    global _catalog
    if _catalog is None or time.monotonic() - _catalog[0] > CATALOG_TTL_SECONDS:
        decision = _request("GET", "/v1/models?output_modalities=decisions", api_key=None)["data"]
        chat = _request("GET", "/v1/models", api_key=None)["data"]
        llms = [
            m
            for m in chat
            if "text" in m["architecture"]["output_modalities"]
            and "structured_outputs" in (m.get("supported_parameters") or [])
        ]
        found = [_model(m, "decision") for m in decision] + [_model(m, "llm") for m in llms]
        _catalog = (
            time.monotonic(),
            sorted(found, key=lambda m: (m.kind != "decision", m.prompt_price, m.name)),
        )
    return _catalog[1]


def model_kind(model_id: str) -> Literal["decision", "llm"]:
    for model in models():
        if model.id == model_id:
            return model.kind
    raise InvalidRequest(f"Unknown model: {model_id}")


def check_key(api_key: str) -> None:
    """Raise InvalidRequest unless OpenRouter accepts the key."""
    try:
        _request("GET", "/v1/key", api_key=api_key)
    except OpenRouterError as e:
        raise InvalidRequest(f"OpenRouter did not accept the key: {e}") from e


def decide(
    model: str, state: str, questions: dict[str, Any], *, api_key: str, fresh: bool = False
) -> Response:
    """Ask a decision model typed questions about `state`. `data` is the answers by question."""
    body = {"model": model, "state": state, "questions": questions}
    response, cached = _cached_post("/alpha/decisions", body, api_key, fresh=fresh)
    return Response(data=response["answers"], cost=response["usage"]["cost"], cached=cached)


def complete(
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    *,
    api_key: str,
    fresh: bool = False,
) -> Response:
    """Ask an LLM for a JSON reply matching `schema`. `data` is the reply's text."""
    body = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": schema},
        },
    }
    response, cached = _cached_post("/v1/chat/completions", body, api_key, fresh=fresh)
    content = (response.get("choices") or [{}])[0].get("message", {}).get("content")
    return Response(data=content, cost=response.get("usage", {}).get("cost", 0), cached=cached)


def _cached_post(
    path: str, body: dict[str, Any], api_key: str, *, fresh: bool = False
) -> tuple[dict[str, Any], bool]:
    """POST, unless the identical request was answered before: a paid call is never made twice.
    `fresh` asks again anyway, e.g. when the cached reply was unusable, and caches the new reply."""
    key = hashlib.sha256(
        json.dumps({"path": path, "body": body}, sort_keys=True).encode()
    ).hexdigest()
    with db.connect() as conn:
        row = conn.execute("SELECT response FROM responses WHERE key = ?", (key,)).fetchone()
    if row is not None and not fresh:
        return json.loads(row["response"]), True
    response = _post_with_retries(path, body, api_key)
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO responses (key, response, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(response), datetime.now(UTC).isoformat()),
        )
    return response, False


def _post_with_retries(path: str, body: dict[str, Any], api_key: str) -> dict[str, Any]:
    """POST, retrying failures that may pass, waiting longer each time (or as long as OpenRouter
    asks), with some randomness so parallel calls don't retry in step."""
    for attempt in range(ATTEMPTS):
        try:
            return _request("POST", path, api_key=api_key, body=body)
        except OpenRouterError as e:
            if not e.retryable or attempt == ATTEMPTS - 1:
                raise
            wait = e.retry_after or RETRY_BASE_SECONDS * 2**attempt * random.uniform(1, 1.5)
            time.sleep(wait)
    raise AssertionError("unreachable")


def _model(data: dict[str, Any], kind: Literal["decision", "llm"]) -> Model:
    pricing = data.get("pricing") or {}
    return Model(
        id=data["id"],
        name=data["name"],
        kind=kind,
        prompt_price=float(pricing.get("prompt") or 0),
        completion_price=float(pricing.get("completion") or 0),
        context_length=data.get("context_length") or 0,
    )


def _request(method: str, path: str, *, api_key: str | None, body: Any = None) -> dict[str, Any]:
    headers = {"User-Agent": f"rowlab/{__version__}", "X-Title": "rowlab"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.request(
            method, BASE_URL + path, headers=headers, json=body, timeout=TIMEOUT_SECONDS
        )
    except httpx.HTTPError as e:
        raise OpenRouterError(f"Could not reach OpenRouter: {e}") from e
    if response.is_error:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:200]
        retry_after = response.headers.get("retry-after")
        raise OpenRouterError(
            f"HTTP {response.status_code}: {message}",
            status=response.status_code,
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
        )
    return response.json()

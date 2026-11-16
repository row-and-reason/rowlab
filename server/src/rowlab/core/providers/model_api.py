"""Calls to a model provider's HTTP API, in the OpenAI style OpenRouter, LiteLLM and vLLM serve: a base
URL, a Bearer key, JSON in and out, and errors as `{"error": {"message": …}}`. What is particular to a
provider (its key check, its decisions API) is in its own module.

Chat completions: `POST {base}/v1/chat/completions`, with `response_format` set to a JSON schema. The
reply reports its tokens, and its cost in USD as `usage.cost` where the provider knows it.
"""

import random
import time
from typing import Any

import httpx
from pydantic import BaseModel

from rowlab import __version__
from rowlab.core import metrics

# Per call: wait this long for an answer, and try this many times when the failure may pass.
TIMEOUT_SECONDS = 60
ATTEMPTS = 4
RETRY_BASE_SECONDS = 1.0
# The longest wait before a retry, however long the provider asks for: a runner stopping must finish
# its calls in a few minutes.
RETRY_MAX_SECONDS = 30.0

COMPLETIONS = "/v1/chat/completions"

# One client for every call, so a runner's calls reuse connections instead of each making its own
# (DNS, TLS). Thread-safe; the runner's own pool caps how many calls are made at once. It follows no
# redirects, so a call goes only where its base URL was checked to point.
_client = httpx.Client(
    timeout=TIMEOUT_SECONDS,
    limits=httpx.Limits(max_connections=None, max_keepalive_connections=None),
)


class ProviderError(Exception):
    """A failed call, with the provider's own message."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        unreachable: bool = False,
    ):
        super().__init__(message)
        self.status = status  # None when the provider couldn't be reached or didn't answer in time
        self.retry_after = retry_after
        # No connection at all (refused, or no such host): not one slow call but a server that's down.
        self.unreachable = unreachable

    @property
    def retryable(self) -> bool:
        """Rate limits, server errors and timeouts may pass; anything else will fail again."""
        return self.status is None or self.status == 429 or self.status >= 500


class Request(BaseModel):
    """A call to make: where to, and what to send. `model` is rowlab's id for the model, which the
    body may name differently (e.g. with a gateway's prefix)."""

    path: str
    body: dict[str, Any]
    model: str


def completion_request(
    model: str, messages: list[dict[str, str]], schema: dict[str, Any], *, name: str | None = None
) -> Request:
    """Messages to an LLM, for a JSON reply matching `schema`. `name` is what the provider calls the
    model, if not rowlab's id."""
    return Request(
        path=COMPLETIONS,
        model=model,
        body={
            "model": name or model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            },
        },
    )


def message(reply: dict[str, Any]) -> Any:
    """A chat completion's text."""
    return (reply.get("choices") or [{}])[0].get("message", {}).get("content")


def usage(reply: dict[str, Any]) -> tuple[float | None, int, int]:
    """Cost (None if the provider doesn't say), input and output tokens, which APIs name differently."""
    found = reply.get("usage") or {}
    return (
        found.get("cost"),
        found.get("prompt_tokens") or found.get("input_tokens") or 0,
        found.get("completion_tokens") or found.get("output_tokens") or 0,
    )


def post(
    base_url: str,
    request: Request,
    api_key: str,
    *,
    attempts: int = ATTEMPTS,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Make a call, paid for, retrying failures that may pass, waiting longer each time (or as long
    as the provider asks), with some randomness so parallel calls don't retry in step."""
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            reply = _request(
                "POST", base_url + request.path, api_key=api_key, body=request.body, timeout=timeout
            )
            _timed(request.model, started, 200)
            return reply
        except ProviderError as e:
            _timed(request.model, started, e.status)
            if not e.retryable or attempt == attempts - 1:
                raise
            wait = e.retry_after or RETRY_BASE_SECONDS * 2**attempt * random.uniform(1, 1.5)
            time.sleep(min(wait, RETRY_MAX_SECONDS))
    raise AssertionError("unreachable")


def get(url: str, api_key: str | None = None) -> dict[str, Any]:
    """A GET, not retried."""
    return _request("GET", url, api_key=api_key)


def _timed(model: str, started: float, status: int | None) -> None:
    metrics.MODEL_CALL_SECONDS.labels(model, metrics.outcome(status)).observe(
        time.monotonic() - started
    )


def _request(
    method: str,
    url: str,
    *,
    api_key: str | None,
    body: Any = None,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    headers = {"User-Agent": f"rowlab/{__version__}", "X-Title": "rowlab"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = _client.request(method, url, headers=headers, json=body, timeout=timeout)
    except httpx.ConnectError as e:
        raise ProviderError(f"Could not reach {httpx.URL(url).host}: {e}", unreachable=True) from e
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach {httpx.URL(url).host}: {e}") from e
    if response.is_redirect:
        # Not followed: a call goes only where its base URL was checked to point.
        raise ProviderError(
            f"HTTP {response.status_code}: redirected to {response.headers.get('location')}."
            " Use that address as the base URL.",
            status=response.status_code,
        )
    if response.is_error:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:200]
        retry_after = response.headers.get("retry-after")
        raise ProviderError(
            f"HTTP {response.status_code}: {message}",
            status=response.status_code,
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
        )
    try:
        return response.json()
    except ValueError:
        raise ProviderError(
            f"HTTP {response.status_code}: the reply wasn't JSON. Is the base URL the API's?",
            status=response.status_code,
        ) from None

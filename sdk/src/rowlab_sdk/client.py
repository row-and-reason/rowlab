"""The HTTP client: where it connects, how it authenticates, and how replies become models or errors."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Self, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from .errors import ApiError, ConfigurationError, ResponseError, TransportError
from .resources import DatasetsResource, ModelsResource, RunsResource

T = TypeVar("T")

DEFAULT_URL = "https://app.rowlab.dev"
LOCALHOST = {"localhost", "127.0.0.1", "::1"}


def _options(base_url: str | None, timeout: float, api_key: str | None) -> dict:
    value = (base_url or os.environ.get("ROWLAB_API_URL") or DEFAULT_URL).strip()
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ConfigurationError("Provide a valid rowlab URL.") from None
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise ConfigurationError(
            "Provide an http(s) rowlab URL without credentials, query or fragment."
        )
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigurationError("timeout must be a positive finite number of seconds.")
    headers = {"accept": "application/json"}
    # A local server needs no key; a hosted one (app.rowlab.dev) does.
    key = api_key if api_key is not None else os.environ.get("ROWLAB_API_KEY", "")
    if key:
        if not key.startswith("rl_") or any(c.isspace() for c in key):
            raise ConfigurationError("A rowlab API key starts with `rl_`; create one in Settings.")
        if url.scheme != "https" and url.host not in LOCALHOST:
            raise ConfigurationError("API keys need HTTPS, except on localhost.")
        headers["authorization"] = f"Bearer {key}"
    return {
        "base_url": str(url).rstrip("/") + "/",
        "timeout": timeout,
        "headers": headers,
        "follow_redirects": False,
        "trust_env": False,
    }


def _message(detail: Any, status_code: int) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        lines = []
        for error in detail:
            if isinstance(error, dict):
                loc = list(error.get("loc", []))
                if loc and loc[0] in ("body", "query", "path"):
                    loc = loc[1:]
                lines.append(f"{'.'.join(map(str, loc))}: {error.get('msg', '')}")
        if lines:
            return "\n".join(lines)
    return f"rowlab request failed (HTTP {status_code})."


def _check(response: httpx.Response) -> None:
    """Raise `ApiError` unless the response is a success. The API's errors are `{"detail": ...}`."""
    if response.is_success:
        return
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    raise ApiError(
        _message(detail, response.status_code), status_code=response.status_code, detail=detail
    )


def _decode(response: httpx.Response, model: type[T]) -> T:
    _check(response)
    try:
        return TypeAdapter(model).validate_python(response.json())
    except (ValueError, ValidationError):
        raise ResponseError(
            "rowlab's reply didn't match this SDK version; upgrade rowlab-python-sdk."
        ) from None


class Client:
    """A rowlab client: `https://app.rowlab.dev` unless `base_url` or `ROWLAB_API_URL` says
    otherwise, signed in with `api_key` or `ROWLAB_API_KEY` (a local server needs none). Close it,
    or use it in a `with` block.

    `timeout` is in seconds, per request; uploading or exporting a very large file may need more."""

    datasets: DatasetsResource
    runs: RunsResource
    models: ModelsResource

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 300,
        _transport: httpx.BaseTransport | None = None,
    ):
        # `_transport` is for tests: it answers the requests instead of the network.
        self._http = httpx.Client(**_options(base_url, timeout, api_key), transport=_transport)
        self.datasets = DatasetsResource(self)
        self.runs = RunsResource(self)
        self.models = ModelsResource(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.RequestError:
            raise TransportError(
                "Could not complete the rowlab request; it may or may not have happened."
            ) from None

    def _request(self, method: str, path: str, model: type[T], **kwargs) -> T:
        return _decode(self._send(method, path, **kwargs), model)

    def _content(self, method: str, path: str, **kwargs) -> bytes:
        response = self._send(method, path, **kwargs)
        _check(response)
        return response.content

    def _download(self, path: str, to: Path, **kwargs) -> None:
        """Stream a GET's body into the file `to`."""
        try:
            with self._http.stream("GET", path, **kwargs) as response:
                if not response.is_success:
                    response.read()
                    _check(response)
                # Written next to `to` and moved there when complete, so a failure leaves no
                # truncated file behind.
                part = to.with_name(to.name + ".part")
                try:
                    with part.open("wb") as file:
                        for chunk in response.iter_bytes():
                            file.write(chunk)
                    part.replace(to)
                finally:
                    part.unlink(missing_ok=True)
        except httpx.RequestError:
            raise TransportError("Could not complete the rowlab download.") from None

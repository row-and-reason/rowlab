"""Where the client connects, how it signs in, and how the API's errors reach the caller. What the
API does with the requests is tested against the real server in `server/tests/test_sdk.py`."""

import httpx
import pytest

from rowlab_sdk import ApiError, Client, ConfigurationError
from rowlab_sdk.client import _options


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv("ROWLAB_API_URL", raising=False)
    monkeypatch.delenv("ROWLAB_API_KEY", raising=False)


def replying(status_code: int, body) -> Client:
    """A client whose every request gets this reply."""
    reply = httpx.MockTransport(lambda request: httpx.Response(status_code, json=body))
    return Client("http://localhost", _transport=reply)


def test_the_url_comes_from_the_argument_then_the_environment_then_rowlab_dev(monkeypatch):
    assert _options(None, 30, None)["base_url"] == "https://app.rowlab.dev/"
    monkeypatch.setenv("ROWLAB_API_URL", "http://localhost:8000")
    assert _options(None, 30, None)["base_url"] == "http://localhost:8000/"
    assert _options("https://rowlab.example.com/", 30, None)["base_url"] == (
        "https://rowlab.example.com/"
    )


def test_a_key_comes_from_the_argument_then_the_environment(monkeypatch):
    assert "authorization" not in _options(None, 30, None)["headers"]
    monkeypatch.setenv("ROWLAB_API_KEY", "rl_from_env")
    assert _options(None, 30, None)["headers"]["authorization"] == "Bearer rl_from_env"
    assert _options(None, 30, "rl_given")["headers"]["authorization"] == "Bearer rl_given"


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://app.rowlab.dev", "sk-or-not-rowlab"),
        ("https://app.rowlab.dev", "rl_with space"),
        ("http://rowlab.example.com", "rl_key"),
        ("https://user:pass@app.rowlab.dev", None),
        ("https://app.rowlab.dev?org=1", None),
        ("ftp://app.rowlab.dev", None),
    ],
)
def test_bad_settings_are_refused_before_anything_is_sent(url, key):
    with pytest.raises(ConfigurationError):
        Client(url, api_key=key)


def test_keys_go_over_https_or_to_localhost():
    for url in ["http://localhost:8000", "http://127.0.0.1:8000", "https://rowlab.example.com"]:
        assert _options(url, 30, "rl_key")["headers"]["authorization"] == "Bearer rl_key"


def test_an_invalid_request_says_what_is_wrong():
    detail = [
        {"loc": ["body", "tasks", 0, "type"], "msg": "Input should be 'yes_no'", "type": "x"},
        {"loc": ["query", "format"], "msg": "Field required", "type": "missing"},
    ]
    with replying(422, {"detail": detail}) as rl, pytest.raises(ApiError) as caught:
        rl.runs.get("r1")
    assert caught.value.status_code == 422
    assert caught.value.detail == detail
    assert str(caught.value) == "tasks.0.type: Input should be 'yes_no'\nformat: Field required"


def test_a_refusal_carries_the_apis_message():
    with replying(404, {"detail": "No dataset d1."}) as rl, pytest.raises(ApiError) as caught:
        rl.datasets.get("d1")
    assert (caught.value.status_code, str(caught.value)) == (404, "No dataset d1.")

"""Serving: told to stop, the server keeps answering while it says it isn't ready, then stops."""

import signal
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from rowlab.core import db, serving
from rowlab.core.config import config


@pytest.fixture(autouse=True)
def not_draining():
    yield
    serving._draining.clear()


@pytest.fixture
def drain_seconds(monkeypatch):
    def set_to(seconds):
        monkeypatch.setenv("ROWLAB_DRAIN_SECONDS", str(seconds))
        config.cache_clear()

    yield set_to
    config.cache_clear()


def test_ready_only_while_it_should_get_requests(client, monkeypatch):
    assert client.get("/v1/ready").json()["status"] == "ready"

    def away():
        raise OSError("connection refused")

    monkeypatch.setattr(db, "connect", away)
    response = client.get("/v1/ready")
    assert (response.status_code, response.json()["status"]) == (503, "database unreachable")
    # Liveness doesn't depend on the database: a restart wouldn't bring it back.
    assert client.get("/v1/health").status_code == 200


def test_draining_says_not_ready_while_still_alive(client):
    serving.drain()
    response = client.get("/v1/ready")
    assert (response.status_code, response.json()["status"]) == (503, "draining")
    assert client.get("/v1/health").status_code == 200


def test_sigterm_drains_while_serving_then_shuts_down(drain_seconds, monkeypatch):
    drain_seconds(0.5)
    monkeypatch.setenv("ROWLAB_NO_RUNNER", "1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = serving.Server(uvicorn.Config("rowlab.app:app", host="127.0.0.1", port=port))
    thread = threading.Thread(target=server.run)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert httpx.get(f"{url}/v1/ready").status_code == 200

    server.handle_exit(signal.SIGTERM, None)
    # Still serving, and saying it is stopping, so a load balancer stops sending requests.
    assert httpx.get(f"{url}/v1/health").status_code == 200
    assert httpx.get(f"{url}/v1/ready").status_code == 503
    assert not server.should_exit
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert server.should_exit


def test_without_a_drain_or_on_a_second_signal_it_stops_at_once(drain_seconds):
    drain_seconds(0)
    server = serving.Server(uvicorn.Config("rowlab.app:app"))
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit and not serving._draining.is_set()

    drain_seconds(30)
    server = serving.Server(uvicorn.Config("rowlab.app:app"))
    server.handle_exit(signal.SIGTERM, None)
    assert serving._draining.is_set() and not server.should_exit
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit

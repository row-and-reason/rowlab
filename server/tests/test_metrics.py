"""Metrics: what the Grafana dashboard reads, served apart from the API."""

import socket

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import NEGATIVE, run, start
from prometheus_client import REGISTRY

from rowlab.app import create_app
from rowlab.core import datasets, runs
from rowlab.core.config import config

pytestmark = pytest.mark.usefixtures("fake")


@pytest.fixture
def job(client):
    files = {"file": ("reviews.csv", b"review\nTerrible product\nLove it\nBroke after a day\n")}
    dataset = client.post("/v1/datasets", files=files).json()
    return {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}


def value(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0


MODEL = "typesafe/jev-1.14"


def test_runs_count_answers_cost_and_model_calls(client, job, api_key):
    before = {
        "answered": value("rowlab_answers_total", model=MODEL, result="answered"),
        "cached": value("rowlab_answers_total", model=MODEL, result="cached"),
        "cost": value("rowlab_model_cost_usd_total", model=MODEL),
        "tokens": value("rowlab_model_tokens_total", model=MODEL, kind="input"),
        "calls": value("rowlab_model_call_duration_seconds_count", model=MODEL, outcome="ok"),
        "done": value("rowlab_runs_finished_total", status="done"),
    }
    run(client, job)
    # The same question again, under another name: answered from the replies kept.
    run(client, {**job, "tasks": [{**NEGATIVE, "column": "again"}]})
    # The second run of the same rows is answered from the cache: no calls, no cost.
    assert value("rowlab_answers_total", model=MODEL, result="answered") - before["answered"] == 3
    assert value("rowlab_answers_total", model=MODEL, result="cached") - before["cached"] == 3
    assert value("rowlab_model_cost_usd_total", model=MODEL) - before["cost"] == pytest.approx(
        0.003
    )
    assert value("rowlab_model_tokens_total", model=MODEL, kind="input") - before["tokens"] == 300
    calls = value("rowlab_model_call_duration_seconds_count", model=MODEL, outcome="ok")
    assert calls - before["calls"] == 3
    assert value("rowlab_runs_finished_total", status="done") - before["done"] == 2
    assert value("rowlab_runner_calls_in_flight") == 0


def test_each_rate_limited_attempt_is_timed(client, job, api_key, fake):
    before = value("rowlab_model_call_duration_seconds_count", model=MODEL, outcome="rate_limited")
    fake.busy = 2
    assert run(client, job)["status"] == "done"
    after = value("rowlab_model_call_duration_seconds_count", model=MODEL, outcome="rate_limited")
    assert after - before == 2


@pytest.fixture
def served(monkeypatch):
    """An API serving its metrics on a port of their own, as in production: no runner. Returns the
    client and the metrics' URL."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("ROWLAB_METRICS_PORT", str(port))
    monkeypatch.setenv("ROWLAB_NO_RUNNER", "1")
    config.cache_clear()
    with TestClient(create_app()) as client:
        yield client, f"http://127.0.0.1:{port}/metrics"


def test_the_queue_is_read_from_the_database_even_with_no_runner(served, job, api_key):
    client, _ = served
    start(client, job)
    assert value("rowlab_runs", status="queued") == 1
    assert value("rowlab_run_queue_wait_seconds") >= 0
    while runs.process_next():
        pass
    assert value("rowlab_runs", status="queued") == 0
    assert value("rowlab_run_queue_wait_seconds") == 0


def test_requests_are_timed_by_route_template(client, job):
    route = "/v1/datasets/{dataset_id}"
    before = value(
        "rowlab_http_request_duration_seconds_count", method="GET", route=route, status="200"
    )
    client.get(f"/v1/datasets/{job['dataset_id']}")
    after = value(
        "rowlab_http_request_duration_seconds_count", method="GET", route=route, status="200"
    )
    assert after - before == 1


def test_errors_nothing_handles_are_timed_as_500s(job, monkeypatch):
    route = "/v1/datasets/{dataset_id}"
    before = value(
        "rowlab_http_request_duration_seconds_count", method="GET", route=route, status="500"
    )

    def broken(*args, **kwargs):
        raise RuntimeError("a bug")

    monkeypatch.setattr(datasets, "check_access", broken)
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get(f"/v1/datasets/{job['dataset_id']}").status_code == 500
    after = value(
        "rowlab_http_request_duration_seconds_count", method="GET", route=route, status="500"
    )
    assert after - before == 1


def test_metrics_are_served_on_their_own_port_only(served):
    client, url = served
    scraped = httpx.get(url)
    assert scraped.status_code == 200
    assert "rowlab_model_call_duration_seconds" in scraped.text
    assert "rowlab_runs{" in scraped.text
    # Never on the port people reach.
    assert "rowlab_" not in client.get("/metrics").text

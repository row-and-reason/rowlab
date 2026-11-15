"""Prometheus metrics, served on their own port (`ROWLAB_METRICS_PORT`) by the API and by runners, so
the address people reach never shows them. Nothing is served unless the port is set.

- `rowlab_http_request_duration_seconds{method, route, status}`: API requests, by route template.
- `rowlab_model_call_duration_seconds{model, outcome}`: every attempt at a paid model call, so a retry
  counts again. `outcome` is `ok`, `rate_limited` (429), `server_error` (5xx), `unreachable` (no
  answer in time, or none at all) or `refused` (any other 4xx).
- `rowlab_runner_calls_in_flight`, `rowlab_runner_call_slots`: a runner's call slots in use, a call
  waiting to be retried included, and how many it has.
- `rowlab_answers_total{model, result}`: answers given to runs, `answered` (paid for), `cached` (free)
  or `failed`. As in the usage, replies paid for in a chunk that is redone after a stop count again,
  as `cached`.
- `rowlab_model_cost_usd_total{model}`, `rowlab_model_tokens_total{model, kind}` (`input`, `output`):
  what the paid answers cost, as the provider bills it.
- `rowlab_runs_finished_total{status}`: runs `done` or `failed`.
- `rowlab_runs{status}` (`queued`, `running`, `stopping`) and `rowlab_run_queue_wait_seconds`, how long
  the run first in line has waited for its turn: read from the database at every scrape, so every
  process reports the same figures, even with no runner up; take their `max`.
"""

import logging
from datetime import UTC, datetime
from wsgiref.simple_server import WSGIServer

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily

from rowlab.core import db
from rowlab.core.config import config
from rowlab.core.usage import Spent

log = logging.getLogger(__name__)

# Uploads and URL imports take minutes; most requests a few milliseconds.
HTTP_REQUEST_SECONDS = Histogram(
    "rowlab_http_request_duration_seconds",
    "API requests, by route template.",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300, float("inf")),
)
# Model calls take from well under a second (decision models) to the 60 s timeout (long LLM replies).
MODEL_CALL_SECONDS = Histogram(
    "rowlab_model_call_duration_seconds",
    "Attempts at paid model calls, each retry on its own.",
    ["model", "outcome"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, float("inf")),
)
CALLS_IN_FLIGHT = Gauge(
    "rowlab_runner_calls_in_flight", "Call slots in use, calls waiting to be retried included."
)
CALL_SLOTS = Gauge("rowlab_runner_call_slots", "Model calls a runner makes at most at once.")
ANSWERS = Counter("rowlab_answers", "Answers given to runs.", ["model", "result"])
COST = Counter("rowlab_model_cost_usd", "USD paid for answers.", ["model"])
TOKENS = Counter("rowlab_model_tokens", "Tokens billed for answers.", ["model", "kind"])
RUNS_FINISHED = Counter("rowlab_runs_finished", "Runs finished.", ["status"])
# From 0, so a process's first finished run counts as an increase.
for _status in ("done", "failed"):
    RUNS_FINISHED.labels(_status)


_queue_registered = False


def serve() -> WSGIServer | None:
    """Serve the metrics on `ROWLAB_METRICS_PORT`, if it is set, with the run queue's."""
    if not config().metrics_port:
        return None
    global _queue_registered
    if not _queue_registered:
        REGISTRY.register(_Queue())
        _queue_registered = True
    server, _ = start_http_server(config().metrics_port)
    return server


def outcome(status: int | None) -> str:
    """A model call's outcome, from its HTTP status (None when there was no answer)."""
    if status is None:
        return "unreachable"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "refused" if status >= 400 else "ok"


def count_spent(spent: dict[tuple[str, str], Spent]) -> None:
    """Add what runs spent, by task and model, as `usage.add` records it."""
    for (_, model), this in spent.items():
        ANSWERS.labels(model, "answered").inc(this.answers - this.cached)
        ANSWERS.labels(model, "cached").inc(this.cached)
        ANSWERS.labels(model, "failed").inc(this.failed)
        COST.labels(model).inc(this.cost)
        TOKENS.labels(model, "input").inc(this.input_tokens)
        TOKENS.labels(model, "output").inc(this.output_tokens)


class _Queue:
    """The run queue as the database has it, read at every scrape."""

    def collect(self):
        runs = GaugeMetricFamily("rowlab_runs", "Runs with work to do.", labels=["status"])
        wait = GaugeMetricFamily(
            "rowlab_run_queue_wait_seconds", "How long the run first in line has waited."
        )
        try:
            with db.connect() as conn:
                found = conn.execute(
                    "SELECT status, count(*) AS n, min(queued_at) AS oldest FROM runs"
                    " WHERE status IN ('queued', 'running', 'stopping') GROUP BY status"
                ).fetchall()
        except Exception:
            # The other metrics are still served. (On Postgres, this waits for a connection first.)
            log.warning("Could not read the run queue for metrics", exc_info=True)
            return
        by_status = {row["status"]: row for row in found}
        for status in ("queued", "running", "stopping"):
            row = by_status.get(status)
            runs.add_metric([status], row["n"] if row else 0)
        oldest = by_status.get("queued") and by_status["queued"]["oldest"]
        waited = (
            (datetime.now(UTC) - datetime.fromisoformat(oldest)).total_seconds() if oldest else 0
        )
        wait.add_metric([], max(0.0, waited))
        yield runs
        yield wait

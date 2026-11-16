"""Whether this server should be sent requests, and stopping without refusing any.

`/v1/health` says the process is alive; `/v1/ready` says it should get traffic: the database answers,
with its migrations applied, and the server isn't draining.

A server told to stop (SIGTERM, as a pod being replaced is) first drains for
`ROWLAB_DRAIN_SECONDS`: it says it isn't ready, so a load balancer stops sending it requests, while
it keeps answering those that still arrive. Only then does uvicorn shut down, letting requests in
flight finish. Without the drain, a balancer that notices only by probing keeps sending requests to a
server no longer accepting them. A second signal, or Ctrl-C, stops at once.
"""

import logging
import signal
import threading
from types import FrameType

import uvicorn

from rowlab.core import db
from rowlab.core.config import config

log = logging.getLogger(__name__)

_draining = threading.Event()


def drain() -> None:
    """Say this server isn't ready any more, as it is about to stop."""
    _draining.set()


def not_ready() -> str | None:
    """Why this server shouldn't get requests, or None if it should."""
    if _draining.is_set():
        return "draining"
    try:
        # Opening the database applies its migrations, once per process.
        with db.connect() as conn:
            conn.execute("SELECT 1")
    # Whatever the failure (SQLite, Postgres, its pool, a migration), the answer is the same.
    except Exception as e:  # noqa: BLE001
        log.warning("Not ready: the database doesn't answer: %s", e)
        return "database unreachable"
    return None


class Server(uvicorn.Server):
    """uvicorn's server, draining for `ROWLAB_DRAIN_SECONDS` on SIGTERM before it shuts down."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        seconds = config().drain_seconds
        if sig != signal.SIGTERM or seconds <= 0 or _draining.is_set():
            super().handle_exit(sig, frame)
            return
        log.info("Draining for %s s before shutting down", seconds)
        drain()
        timer = threading.Timer(seconds, super().handle_exit, (sig, frame))
        timer.daemon = True
        timer.start()

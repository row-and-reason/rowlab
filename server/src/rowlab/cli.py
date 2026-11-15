import argparse
import json
import logging
import os
import signal
import sys

import uvicorn

from rowlab import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="rowlab")
    parser.add_argument("--version", action="version", version=f"rowlab {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the API and web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="Reload on code changes (development)")
    serve.add_argument(
        "--no-runner",
        action="store_true",
        help="Leave runs to separate `rowlab runner` processes (needs Postgres)",
    )

    commands.add_parser(
        "runner", help="Process queued runs (with Postgres, several can share them)"
    )

    commands.add_parser("mcp", help="Serve MCP over stdio, for an agent on this machine")

    commands.add_parser("openapi", help="Print the OpenAPI spec as JSON")

    migrate = commands.add_parser(
        "migrate",
        help="Fold datasets runs made into the datasets they were made from (once, runners stopped)",
    )
    migrate.add_argument("--dry-run", action="store_true", help="Only say what it would do")

    # `rowlab` alone serves, so `uvx rowlab` is all a first run needs.
    args = parser.parse_args(sys.argv[1:] or ["serve"])
    if args.command in ("serve", "runner", "mcp"):
        _check_migrated()
    if args.command == "serve":
        if args.no_runner:
            # Read by the app as it starts, also in the processes `--reload` starts.
            os.environ["ROWLAB_NO_RUNNER"] = "1"
        uvicorn.run("rowlab.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.command == "runner":
        from rowlab.core import metrics, runs

        logging.basicConfig(level=logging.INFO)
        metrics.serve()
        # A pod stopping, or Ctrl-C: finish the calls in flight and give the run back. (As PID 1 in
        # a container, Python would otherwise ignore SIGTERM until it is killed.)
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: runs.shut_down())
        runs.recover_interrupted_runs()
        runs.run_forever()
    elif args.command == "mcp":
        from rowlab.core import runs
        from rowlab.mcp.server import create_server

        # Runs made over stdio execute here too, as in `rowlab serve`.
        if not os.environ.get("ROWLAB_NO_RUNNER"):
            runs.start_runner()
        create_server().run(transport="stdio", show_banner=False)
    elif args.command == "openapi":
        from rowlab.app import app

        print(json.dumps(app.openapi(), indent=2))
    elif args.command == "migrate":
        from rowlab.core import migrate as migrate_core

        migrate_core.migrate(dry_run=args.dry_run)


def _check_migrated() -> None:
    """Refuse to start on datasets still in trees: runs would add answers where nothing reads them."""
    from rowlab.core import migrate

    pending = migrate.pending()
    if pending:
        sys.exit(
            f"{pending} dataset(s) were made by runs, in the layout before answers became columns. "
            "Stop every runner and run `rowlab migrate` first."
        )

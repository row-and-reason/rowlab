import argparse
import json
import logging
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="rowlab")
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

    args = parser.parse_args()
    if args.command == "serve":
        if args.no_runner:
            # Read by the app as it starts, also in the processes `--reload` starts.
            os.environ["ROWLAB_NO_RUNNER"] = "1"
        uvicorn.run("rowlab.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.command == "runner":
        from rowlab.core import runs

        logging.basicConfig(level=logging.INFO)
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

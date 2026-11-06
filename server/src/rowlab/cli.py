import argparse
import json

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="rowlab")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the API and web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="Reload on code changes (development)")

    commands.add_parser("openapi", help="Print the OpenAPI spec as JSON")

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("rowlab.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.command == "openapi":
        from rowlab.app import app

        print(json.dumps(app.openapi(), indent=2))

"""End-to-end smoke test of a running rowlab in local mode, through its public API only:
the web app and MCP answer, a file goes in, a query picks rows, a run answers them (only with
`OPENROUTER_API_KEY` set, since it costs money), and the result comes out as CSV, JSONL and Parquet.

    python3 scripts/smoke.py http://127.0.0.1:8001

Standard library only, so any Python runs it. `make smoke` and `make smoke-compose` start a rowlab
for it.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8001"

REVIEWS = b"""review,stars
"Arrived broken and support never answered.",1
"Works exactly as described, would buy again.",5
"Fine for the price.",3
"""


def request(method: str, path: str, body=None, headers=None) -> tuple[int, bytes]:
    headers = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(method: str, path: str, body=None, expect: int = 200):
    status, data = request(method, path, body)
    assert status == expect, f"{method} {path}: {status} {data[:500]!r}"
    return json.loads(data) if data else None


def upload(name: str, content: bytes) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: text/csv\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    status, data = request(
        "POST",
        "/v1/datasets",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert status == 201, f"upload: {status} {data[:500]!r}"
    return json.loads(data)


def step(text: str) -> None:
    print(f"· {text}", flush=True)


def main() -> None:
    health = call("GET", "/v1/health")
    step(f"rowlab {health['version']} at {BASE}")

    status, page = request("GET", "/")
    assert status == 200 and b"<html" in page, f"web app: {status}"
    step("the web app is served")

    status, _ = request(
        "POST",
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "1"},
            },
        },
        {"Accept": "application/json, text/event-stream"},
    )
    assert status == 200, f"MCP initialize: {status}"
    step("MCP answers")

    dataset = upload("reviews.csv", REVIEWS)
    assert dataset["row_count"] == 3, dataset
    step(f"added reviews.csv as {dataset['name']}: {dataset['row_count']} rows")

    picked = call(
        "POST",
        f"/v1/datasets/{dataset['id']}/query",
        {"sql": "SELECT review FROM data WHERE stars < 3"},
    )
    assert [row["review"] for row in picked["rows"]] == [
        "Arrived broken and support never answered."
    ], picked
    step("a query picks the right row")

    result = dataset
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        call("PUT", "/v1/settings/openrouter-key", {"key": key})
        run = call(
            "POST",
            f"/v1/datasets/{dataset['id']}/runs",
            {
                "tasks": [
                    {
                        "template": "Is this review negative? {{review}}",
                        "type": "yes_no",
                        "column": "negative",
                    }
                ]
            },
            expect=201,
        )
        deadline = time.monotonic() + 180
        while run["status"] in ("queued", "running"):
            assert time.monotonic() < deadline, f"run still {run['status']} after 3 minutes"
            time.sleep(2)
            run = call("GET", f"/v1/runs/{run['id']}")
        assert run["status"] == "done", f"run {run['status']}: {run['error']}"
        result = call("GET", f"/v1/datasets/{run['dataset_id']}")
        answers = call(
            "POST",
            f"/v1/datasets/{result['id']}/query",
            {"sql": "SELECT * FROM data ORDER BY stars"},
        )
        answer = next(c for c in answers["columns"] if c["name"].startswith("negative"))["name"]
        values = [row[answer] for row in answers["rows"]]
        assert values[0] is True and values[2] is False, values
        step(f"a run answered every row into {result['name']}.{answer}, for ${run['cost']:.6f}")
    else:
        step("no OPENROUTER_API_KEY: skipped the run")

    rows = result["row_count"]
    for fmt in ("csv", "jsonl", "parquet"):
        status, data = request("GET", f"/v1/datasets/{result['id']}/export?format={fmt}")
        assert status == 200, f"export {fmt}: {status} {data[:300]!r}"
        if fmt == "csv":
            assert len(data.decode().strip().splitlines()) == rows + 1, data
        elif fmt == "jsonl":
            assert len([json.loads(line) for line in data.decode().splitlines()]) == rows, data
        else:
            assert data[:4] == b"PAR1" and data[-4:] == b"PAR1", "not a Parquet file"
    step(f"{result['name']} exports as CSV, JSONL and Parquet")

    print("smoke test passed")


if __name__ == "__main__":
    main()

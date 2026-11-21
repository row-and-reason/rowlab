"""What the tests share besides fixtures: a stand-in for OpenRouter, an MCP client, and a look into
storage."""

import asyncio
import json

import duckdb
import httpx
from fastmcp import Client

from rowlab.core import runs, storage
from rowlab.core.config import config
from rowlab.core.providers import model_api, openrouter
from rowlab.core.providers.model_api import ProviderError

# Before the `fake` fixture replaces it: what a call really does with a reply.
REAL_REQUEST = model_api._request


def serving(reply):
    """An HTTP client whose every request gets `reply(request)`, an `httpx.Response`: for what a call
    really does with odd replies. Put in place of `model_api._client`, with `REAL_REQUEST`."""
    return httpx.Client(transport=httpx.MockTransport(reply))


def html_reply(status=200):
    """A reply that isn't the API's: an HTML page, as a proxy or tunnel gives, with `status`."""
    return lambda request: httpx.Response(status, text="<html>error code: 1033</html>")


def stored(dataset_id, *names):
    """Whether a dataset's file is in storage, local or S3, e.g. `stored(id, "data.parquet")`."""
    return storage.exists(storage.location(dataset_id, *names))


def stored_datasets():
    """The ids of the datasets with files in storage."""
    if not config().s3_storage:
        root = config().data_dir / "datasets"
        return {p.name for p in root.iterdir()} if root.exists() else set()
    bucket, prefix = storage._split(config().storage_url + "/")
    found = storage._s3().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    return {o["Key"].removeprefix(prefix).split("/")[0] for o in found}


# rowlab's own list, for the tests. OpenRouter (the fake) prices all but `x/unpriced`, and has more
# models besides.
CATALOG = """
[[models]]
id = "typesafe/jev-1.14"
name = "Jev"
kind = "decision"
tags = ["recommended"]
price_in = 0.05

[[models]]
id = "a/cheap"
name = "Cheap"
kind = "decision"
tags = ["budget"]

[[models]]
id = "anthropic/claude-haiku-5.5"
name = "Haiku"
kind = "llm"
tags = ["recommended"]

[[models]]
id = "x/llm"
name = "X"
kind = "llm"

[[models]]
id = "x/unpriced"
name = "Unpriced"
kind = "llm"
price_in = 3
price_out = 4
"""


def chat_model(id_, price, *, structured=True, endpoint="/api/v1/chat/completions"):
    return {
        "id": id_,
        "name": id_.title(),
        "pricing": {"prompt": price, "completion": "0.000001"},
        "supported_parameters": ["structured_outputs"] if structured else ["tools"],
        "endpoints": [endpoint],
    }


def decision_model(id_, price, **pricing):
    return {
        "id": id_,
        "name": id_.title(),
        "pricing": {"prompt": price, **pricing},
        "endpoints": ["/api/alpha/decisions"],
    }


class FakeOpenRouter:
    """Stands in for OpenRouter's HTTP API. Says yes when the prompt mentions a bad experience.

    `busy` makes the next calls fail with a rate limit; `crash_on` makes the call for that prompt
    fail once like a killed server would, with an error nothing catches; `flaky` prompts fail once,
    with an error that isn't retried."""

    def __init__(self):
        self.calls = []
        self.urls = []
        self.busy = 0
        self.crash_on = None
        self.flaky = set()
        self.reports_cost = True
        # Models in OpenRouter's catalog that aren't on rowlab's list; a test may take them out.
        self.unlisted_decisions = [decision_model("b/decider", "0.00000002")]
        self.unlisted_llms = [chat_model("y/other", "0.000003")]

    def __call__(self, method, url, *, api_key, body=None, timeout=None):
        # Paths as OpenRouter's under its `/api`, and as any other provider's under its host.
        path = url.removeprefix(openrouter.BASE_URL)
        if path == url:
            path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append((method, path, api_key, body))
        self.urls.append(url)
        if path in ("/v1/key", "/v1/models") and api_key and api_key != "sk-good":
            raise ProviderError("HTTP 401: Invalid key", status=401)
        if path == "/v1/key":
            return {"data": {}}
        if path == "/v1/models?output_modalities=decisions":
            return {
                "data": [
                    decision_model("typesafe/jev-1.14", "0.00000004"),
                    decision_model("a/cheap", "0.00000001"),
                    # Not on rowlab's list: one rowlab can ask, and one priced per request.
                    *self.unlisted_decisions,
                    decision_model("p/per-call", "0", request="0.001"),
                ]
            }
        if path == "/v1/models":
            return {
                "data": [
                    chat_model("x/llm", "0.000002"),
                    chat_model("anthropic/claude-haiku-5.5", "0.0000001"),
                    # Not on rowlab's list: one rowlab can ask, and ones it can't: without
                    # structured outputs, batch only, a router, and an alias.
                    *self.unlisted_llms,
                    chat_model("z/plain", "0.000001", structured=False),
                    chat_model("y/other:batch", "0.000001", endpoint="/api/v1/batches"),
                    chat_model("openrouter/free", "0"),
                    chat_model("~y/other-latest", "0.000003"),
                ]
            }
        if path == "/v1/chat/completions":
            prompt = body["messages"][1]["content"]
            schema = body["response_format"]["json_schema"]["schema"]
            content = json.dumps(_llm_reply(schema, prompt))
            usage = {"prompt_tokens": 1000, "completion_tokens": 100}
            if self.reports_cost:
                usage["cost"] = 0.01
            return {"choices": [{"message": {"content": content}}], "usage": usage}
        state = body.get("state", body.get("input"))
        if self.busy:
            self.busy -= 1
            raise ProviderError("HTTP 429: Rate limited", status=429)
        if state == self.crash_on:
            self.crash_on = None
            raise KeyboardInterrupt
        if state in self.flaky:
            self.flaky.remove(state)
            raise ProviderError("HTTP 400: Provider error", status=400)
        if state == "fail":
            raise ProviderError("HTTP 400: Provider error", status=400)
        if state == "no credits":
            raise ProviderError("HTTP 402: Insufficient credits", status=402)
        if body["model"] == "not-served":
            raise ProviderError("HTTP 404: The model `not-served` does not exist.", status=404)
        yes = 0.9 if _bad(state) else 0.1
        if path == "/v1/decisions":
            # OpenAI's format (LiteLLM, vLLM): a list of answers, by the questions' names, no cost.
            return {
                "answers": [_openai_answer(q, yes) for q in body["questions"]],
                "usage": {"input_tokens": 100, "output_tokens": 1},
            }
        answers = {"answers": {"answer": {"type": "noul", "noul": yes}}}
        if path == "/v1/systemone":
            # A server of your own, e.g. vLLM: OpenRouter's format, without a cost.
            return answers | {"usage": {"input_tokens": 100, "output_tokens": 1}}
        return answers | {"usage": {"input_tokens": 100, "output_tokens": 1, "cost": 0.001}}


def _openai_answer(question, yes):
    """Yes for a bad experience; the last choice; the top level, for certain."""
    name = question["name"]
    if question["type"] == "predicate":
        return {"type": "predicate", "name": name, "probability": yes}
    if question["type"] == "choice":
        values = [c["value"] for c in question["choices"]]
        probabilities = [
            {"value": v, "probability": 0.8 if v == values[-1] else 0.2} for v in values
        ]
        return {
            "type": "choice",
            "name": name,
            "choice": values[-1],
            "probabilities": probabilities,
        }
    levels = question["levels"]
    probabilities = [
        {"value": i, "label": level["label"], "probability": 1.0 if i == len(levels) - 1 else 0.0}
        for i, level in enumerate(levels)
    ]
    return {"type": "score", "name": name, "score": len(levels) - 1, "probabilities": probabilities}


def _llm_reply(schema, prompt):
    """A reply with the shape the schema asks for. Yes/no answers say whether the prompt is bad;
    answers from options are the prompt, when it is one."""
    reply = {}
    for name, prop in schema["properties"].items():
        if name == "answer":
            # A prompt that is one of the options is the answer, e.g. a scale's level.
            reply[name] = prompt if prompt in prop.get("enum", []) else _bad(prompt)
        elif name == "proba":
            reply[name] = 0.8
        elif name == "reason":
            reply[name] = "Because it says so."
        elif name == "text":
            reply[name] = f"In short: {prompt}"
        else:
            reply[name] = _fake_value(prop)
    return reply


def _fake_value(prop):
    types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
    if "array" in types:
        item = prop["items"]
        return [_llm_reply(item, "")] if item["type"] == "object" else ["red", "blue"]
    if "number" in types:
        return 4
    if "boolean" in types:
        return True
    return "2024-05-01" if prop.get("description") == "YYYY-MM-DD" else "Widget"


def _bad(text):
    return any(word in text for word in ["Terrible", "Broke"])


def call(mcp, tool_name, **arguments):
    """Call a tool as an agent would, in-process, and return its result."""

    async def go():
        async with Client(mcp) as client:
            result = (await client.call_tool(tool_name, arguments)).structured_content
            # A list or a bare value comes wrapped.
            return result["result"] if set(result) == {"result"} else result

    return asyncio.run(go())


def tools(mcp):
    async def go():
        async with Client(mcp) as client:
            return {t.name: t.description for t in await client.list_tools()}

    return asyncio.run(go())


def wide_dataset(client, tmp_path, monkeypatch):
    """A dataset of thousands of columns, as many as answer columns pile up to, and less memory for
    DuckDB than they take at once."""
    path = tmp_path / "wide.parquet"
    columns = ", ".join(f"random() AS c{i}" for i in range(3000))
    duckdb.sql(
        f"COPY (SELECT 'review ' || i AS review, {columns} FROM range(600) t(i)) TO '{path}'"
    )
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    monkeypatch.setenv("ROWLAB_DUCKDB_MEMORY", "32MB")
    config.cache_clear()
    return dataset


NEGATIVE = {"template": "Is this review negative? {{review}}", "column": "negative"}


def start(client, job):
    """Queue a run of the job, as the Run button does."""
    body = {"sql": job["sql"], "tasks": job["tasks"]}
    return client.post(f"/v1/datasets/{job['dataset_id']}/runs", json=body).json()


def run(client, job):
    """Queue a run and let the runner process it, as its thread would."""
    created = start(client, job)
    if "id" not in created:
        return created
    while runs.process_next():
        pass
    return client.get(f"/v1/runs/{created['id']}").json()

"""What the tests share besides fixtures: a stand-in for OpenRouter, an MCP client, and a look into
storage."""

import asyncio
import json

from fastmcp import Client

from rowlab.core import storage
from rowlab.core.config import config
from rowlab.core.providers import openrouter


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


def chat_model(id_, price, structured=True):
    return {
        "id": id_,
        "name": id_.title(),
        "pricing": {"prompt": price, "completion": "0.000001"},
        "architecture": {"output_modalities": ["text"]},
        "supported_parameters": ["structured_outputs"] if structured else [],
    }


class FakeOpenRouter:
    """Stands in for OpenRouter's HTTP API. Says yes when the prompt mentions a bad experience.

    `busy` makes the next calls fail with a rate limit; `crash_on` makes the call for that prompt
    fail once like a killed server would, with an error nothing catches; `flaky` prompts fail once,
    with an error that isn't retried."""

    def __init__(self):
        self.calls = []
        self.busy = 0
        self.crash_on = None
        self.flaky = set()

    def __call__(self, method, path, *, api_key, body=None):
        self.calls.append((method, path, api_key, body))
        if path == "/v1/key":
            if api_key != "sk-good":
                raise openrouter.OpenRouterError("HTTP 401: Invalid key", status=401)
            return {"data": {}}
        if path == "/v1/models?output_modalities=decisions":
            return {
                "data": [
                    {"id": "typesafe/jev-1.14", "name": "Jev", "pricing": {"prompt": "0.00000004"}},
                    {"id": "a/cheap", "name": "Cheap", "pricing": {"prompt": "0.00000001"}},
                ]
            }
        if path == "/v1/models":
            return {
                "data": [
                    chat_model("x/llm", "0.000002"),
                    chat_model("anthropic/claude-haiku-5.5", "0.0000001"),
                    chat_model("y/no-schema", "0.000001", structured=False),
                ]
            }
        if path == "/v1/chat/completions":
            prompt = body["messages"][1]["content"]
            schema = body["response_format"]["json_schema"]["schema"]
            content = json.dumps(_llm_reply(schema, prompt))
            return {"choices": [{"message": {"content": content}}], "usage": {"cost": 0.01}}
        if self.busy:
            self.busy -= 1
            raise openrouter.OpenRouterError("HTTP 429: Rate limited", status=429)
        if body["state"] == self.crash_on:
            self.crash_on = None
            raise KeyboardInterrupt
        if body["state"] in self.flaky:
            self.flaky.remove(body["state"])
            raise openrouter.OpenRouterError("HTTP 400: Provider error", status=400)
        if body["state"] == "fail":
            raise openrouter.OpenRouterError("HTTP 400: Provider error", status=400)
        if body["state"] == "no credits":
            raise openrouter.OpenRouterError("HTTP 402: Insufficient credits", status=402)
        return {
            "answers": {"answer": {"type": "noul", "noul": 0.9 if _bad(body["state"]) else 0.1}},
            "usage": {"input_tokens": 100, "output_tokens": 1, "cost": 0.001},
        }


def _llm_reply(schema, prompt):
    """A reply with the shape the schema asks for. Yes/no answers say whether the prompt is bad."""
    reply = {}
    for name, prop in schema["properties"].items():
        if name == "answer":
            reply[name] = _bad(prompt)
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

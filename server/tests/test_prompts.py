import json

import pytest

from rowlab.core.prompts import count_tokens, to_text

ROWS = [
    {
        "name": "Ada",
        "age": 36,
        "first name": "Ada",
        "actor": {"login": "ada", "id.x": 1},
        "tags": [],
    },
    {
        "name": "Alan",
        "age": None,
        "first name": "",
        "actor": {"login": "alan", "id.x": 2},
        "tags": ["a"],
    },
]


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "people.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in ROWS))
    response = client.post("/v1/datasets", data={"source": str(path)})
    assert response.status_code == 201, response.text
    return response.json()


def render(client, dataset, template, **body):
    response = client.post(
        f"/v1/datasets/{dataset['id']}/render", json={"template": template, **body}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_renders_fields_and_nested_paths(client, dataset):
    result = render(client, dataset, "{{name}} ({{ actor.login }}) is {{age}}: {{tags}}")
    assert result["warnings"] == ["`age` is empty in 1 of 2 sampled rows."]
    row = result["rows"][0]
    assert row["row_id"] == 0
    assert row["prompt"] == "Ada (ada) is 36: []"
    assert row["values"] == {"name": "Ada", "actor.login": "ada", "age": 36, "tags": []}
    assert row["tokens"] == count_tokens(row["prompt"])


def test_names_with_spaces_and_dots_need_no_quoting(client, dataset):
    result = render(client, dataset, "{{first name}} #{{actor.id.x}}")
    assert result["warnings"] == ["`first name` is empty in 1 of 2 sampled rows."]
    assert result["rows"][0]["prompt"] == "Ada #1"


def test_pages_through_rows(client, dataset):
    result = render(client, dataset, "{{name}}", offset=1, limit=5)
    assert [r["prompt"] for r in result["rows"]] == ["Alan"]


def test_lists_fields_including_struct_paths(client, dataset):
    paths = [f["path"] for f in render(client, dataset, "")["fields"]]
    assert paths == ["name", "age", "first name", "actor", "actor.login", "actor.id.x", "tags"]


def test_warns_about_unknown_and_empty_fields(client, dataset):
    result = render(client, dataset, "{{nmae}} {{age}} {{actor.nope}}")
    assert result["warnings"] == [
        "`nmae` is not a column. Did you mean `name`?",
        "`actor.nope` is not a column. Did you mean `actor.login`?",
        "`age` is empty in 1 of 2 sampled rows.",
    ]
    assert result["rows"][0]["prompt"] == " 36 "


def test_warns_when_no_fields_are_used(client, dataset):
    result = render(client, dataset, "Same for everyone")
    assert result["warnings"] == [
        "The template uses no columns, so every row gets the same prompt."
    ]
    assert render(client, dataset, "")["warnings"] == []


def test_token_estimate_covers_the_whole_dataset(client, dataset):
    tokens = render(client, dataset, "{{name}}")["tokens"]
    assert tokens["sample_size"] == 2
    assert tokens["min"] == tokens["max"] == 1
    assert tokens["total_estimate"] == 2


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        ("text", "text"),
        (36, "36"),
        (2.5, "2.5"),
        (True, "true"),
        ({"a": [1, "ü"]}, '{"a":[1,"ü"]}'),
    ],
)
def test_to_text(value, text):
    assert to_text(value) == text


def test_renders_only_the_rows_in_scope(client, dataset):
    result = render(client, dataset, "{{name}}", scope={"search": "alan", "filters": []})
    assert [r["prompt"] for r in result["rows"]] == ["Alan"]
    assert result["selected_rows"] == 1
    assert result["tokens"]["sample_size"] == 1
    assert result["tokens"]["total_estimate"] == 1

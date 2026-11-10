import json

import pytest

from rowlab.core import tasks
from rowlab.core.errors import InvalidRequest
from rowlab.core.tasks import AnswerFormatError, Option, Task

TEAMS = Task(
    template="Which team? {{text}}",
    type="pick_one",
    column="team",
    options=[Option(name="payments", description="Billing"), Option(name="frontend")],
)
TOPICS = Task(
    template="Which topics? {{text}}",
    type="pick_any",
    column="topic",
    options=[Option(name="price"), Option(name="speed")],
)
URGENCY = Task(
    template="How urgent? {{text}}",
    type="scale",
    column="urgency",
    options=[Option(name="low"), Option(name="medium"), Option(name="high", description="Act now")],
)


def test_checks_the_task():
    tasks.check(Task(template="Spam? {{text}}"))
    tasks.check(TEAMS)
    with pytest.raises(InvalidRequest, match="Write the prompt"):
        tasks.check(Task())
    with pytest.raises(InvalidRequest, match="Pick a model"):
        tasks.check(TEAMS.model_copy(update={"models": []}))
    with pytest.raises(InvalidRequest, match="same column name"):
        tasks.check(TEAMS.model_copy(update={"models": ["a/jev", "b/jev"]}))
    with pytest.raises(InvalidRequest, match="at least two levels"):
        tasks.check(URGENCY.model_copy(update={"options": [Option(name="1")]}))
    with pytest.raises(InvalidRequest, match="Name all options"):
        tasks.check(TEAMS.model_copy(update={"options": [Option(name="a"), Option(name=" ")]}))
    with pytest.raises(InvalidRequest, match="different names"):
        tasks.check(TOPICS.model_copy(update={"options": [Option(name="a"), Option(name="a")]}))
    with pytest.raises(InvalidRequest, match="Name the result column"):
        tasks.check(TEAMS.model_copy(update={"column": " "}))


def test_columns_are_named_after_each_model():
    assert tasks.result_columns(Task(column="spam")) == ["spam__jev-1.14"]
    two = TOPICS.model_copy(update={"models": ["typesafe/jev-1.14", "moonshotai/kimi-k3"]})
    assert tasks.result_columns(two) == [
        "topic_price__jev-1.14",
        "topic_speed__jev-1.14",
        "topic_price__kimi-k3",
        "topic_speed__kimi-k3",
    ]
    values = {
        "topic_price": True,
        "topic_price_proba": 0.9,
        "topic_speed": False,
        "topic_speed_proba": 0.8,
    }
    assert tasks.with_model(TOPICS, "moonshotai/kimi-k3", values) == {
        "topic_price__kimi-k3": True,
        "topic_price__kimi-k3_proba": 0.9,
        "topic_speed__kimi-k3": False,
        "topic_speed__kimi-k3_proba": 0.8,
    }


# Decision models


def test_decision_yes_no_gives_the_probability_of_the_answer():
    questions = tasks.decision_questions(Task(column="spam"))
    assert questions == {"answer": {"type": "noul", "instructions": tasks.INSTRUCTIONS}}
    yes = tasks.read_decision(Task(column="spam"), {"answer": {"type": "noul", "noul": 0.9}})
    assert yes == {"spam": True, "spam_proba": 0.9}
    no = tasks.read_decision(Task(column="spam"), {"answer": {"type": "noul", "noul": 0.2}})
    assert no == {"spam": False, "spam_proba": pytest.approx(0.8)}


def test_decision_pick_one():
    question = tasks.decision_questions(TEAMS)["answer"]
    assert question["type"] == "choice"
    assert question["criteria"] == {"payments": "Billing", "frontend": "frontend"}
    answer = {
        "type": "choice",
        "choice": "payments",
        "confidence": 0.7,
        "probabilities": {"payments": 0.84, "frontend": 0.16},
    }
    assert tasks.read_decision(TEAMS, {"answer": answer}) == {
        "team": "payments",
        "team_proba": 0.84,
    }


def test_decision_scale_picks_the_most_likely_level():
    question = tasks.decision_questions(URGENCY)["answer"]
    assert question["type"] == "score"
    assert question["criteria"] == ["low", "medium", "Act now"]
    answer = {"type": "score", "score": 1.4, "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}}
    assert tasks.read_decision(URGENCY, {"answer": answer}) == {
        "urgency": "high",
        "urgency_proba": 0.5,
    }


def test_decision_pick_any_asks_one_question_per_option():
    questions = tasks.decision_questions(TOPICS)
    assert list(questions) == ["option_0", "option_1"]
    assert questions["option_0"]["instructions"] == (
        'Is "price" a correct answer to the question in the text?'
    )
    reply = {"option_0": {"type": "noul", "noul": 0.7}, "option_1": {"type": "noul", "noul": 0.1}}
    assert tasks.read_decision(TOPICS, reply) == {
        "topic_price": True,
        "topic_price_proba": 0.7,
        "topic_speed": False,
        "topic_speed_proba": pytest.approx(0.9),
    }


def test_decision_refusal_is_an_error():
    with pytest.raises(AnswerFormatError, match="declined"):
        tasks.read_decision(Task(), {"answer": {"type": "refusal"}})


# LLMs


def test_llm_schema_fixes_the_reply_shape():
    assert tasks.llm_schema(Task())["properties"]["answer"] == {"type": "boolean"}
    assert tasks.llm_schema(TEAMS)["properties"]["answer"]["enum"] == ["payments", "frontend"]
    topics = tasks.llm_schema(TOPICS)["properties"]["answers"]
    assert topics["required"] == ["price", "speed"]
    assert topics["properties"]["price"]["required"] == ["answer", "proba"]


def test_llm_messages_list_the_options():
    system, user = tasks.llm_messages(URGENCY, "How urgent? Server down")
    assert "- high: Act now" in system["content"]
    assert "lowest to highest" in system["content"]
    assert user == {"role": "user", "content": "How urgent? Server down"}


def test_llm_replies_are_read_into_the_same_columns():
    reply = json.dumps({"answer": "payments", "proba": 0.9})
    assert tasks.read_llm(TEAMS, reply) == {"team": "payments", "team_proba": 0.9}
    reply = json.dumps(
        {
            "answers": {
                "price": {"answer": True, "proba": 1},
                "speed": {"answer": False, "proba": 0.6},
            }
        }
    )
    assert tasks.read_llm(TOPICS, reply) == {
        "topic_price": True,
        "topic_price_proba": 1.0,
        "topic_speed": False,
        "topic_speed_proba": 0.6,
    }


@pytest.mark.parametrize(
    ("task", "reply", "error"),
    [
        (Task(), "not json", "not JSON"),
        (Task(), '{"answer": "yes", "proba": 0.5}', "expected answer"),
        (Task(), '{"answer": true, "proba": 2}', "between 0 and 1"),
        (Task(), '{"answer": true, "proba": true}', "between 0 and 1"),
        (TEAMS, '{"answer": "shipping", "proba": 0.5}', "not one of the options"),
        (TOPICS, '{"answers": {"price": {"answer": true, "proba": 0.5}}}', "expected answer"),
    ],
)
def test_llm_replies_with_the_wrong_shape_are_errors(task, reply, error):
    with pytest.raises(AnswerFormatError, match=error):
        tasks.read_llm(task, reply)


INVOICE = Task(
    type="extract",
    template="{{text}}",
    column="invoice",
    fields=["company", "total:number", {"name": "due", "type": "date"}],
)


def test_extract_fields_have_a_short_form_and_may_be_empty():
    assert [(f.name, f.type) for f in INVOICE.fields] == [
        ("company", "text"),
        ("total", "number"),
        ("due", "date"),
    ]
    schema = tasks.llm_schema(INVOICE)["properties"]
    assert schema["total"] == {"type": ["number", "null"]}
    values = tasks.read_llm(INVOICE, '{"company": "ACME", "total": 12, "due": null}')
    assert values == {"company": "ACME", "total": 12.0, "due": None}


def test_extract_replies_are_checked_against_the_field_types():
    with pytest.raises(AnswerFormatError, match="total was not a number"):
        tasks.read_llm(INVOICE, '{"company": "ACME", "total": "12", "due": null}')
    with pytest.raises(AnswerFormatError, match="due was not a date"):
        tasks.read_llm(INVOICE, '{"company": "ACME", "total": 1, "due": "May 1st"}')


def test_a_task_gets_a_column_and_models_that_suit_its_type():
    write = Task.model_validate({"type": "write", "template": "Summarize: {{text}}"})
    assert (write.column, write.models) == ("text", [tasks.DEFAULT_LLM])
    picked = Task.model_validate({"type": "pick_one"})
    assert (picked.column, picked.models) == ("label", [tasks.DEFAULT_MODEL])


def test_a_preset_asks_for_the_same_reply_as_a_plain_write_task():
    task = Task(type="write", preset="translate", template="Use formal French: {{text}}")
    assert tasks.llm_schema(task) == tasks.llm_schema(Task(type="write"))


@pytest.mark.parametrize("field_type", ["text", "number", "boolean", "date"])
def test_single_value_extraction_accepts_scalars(field_type):
    task = Task(
        type="extract",
        extraction_mode="single",
        template="Extract the value from {{text}}",
        fields=[{"name": "value", "type": field_type}],
    )
    tasks.check(task)
    assert len(tasks.result_columns(task)) == 1


@pytest.mark.parametrize(
    "fields", [[], ["a", "b"], ["value:list"], [{"name": "value", "type": "items"}]]
)
def test_single_value_extraction_rejects_structures(fields):
    task = Task(
        type="extract", extraction_mode="single", template="Extract {{text}}", fields=fields
    )
    with pytest.raises(InvalidRequest, match="exactly one scalar"):
        tasks.check(task)

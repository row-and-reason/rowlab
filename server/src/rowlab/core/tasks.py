"""Tasks: what a job produces for each row, and how decision models and LLMs are asked for it.

A task is a prompt (the question, with the row's columns in it), an answer type, and the models that
answer it. Each model writes its own columns, named after it: `<column>__<model>` with the answer
and `<column>__<model>_proba` with the probability (0 to 1) that the answer is right, e.g.
`team__jev-1.14`. Pick any writes one such pair per option, `<column>_<option>__<model>`.

Decision models return probabilities; LLMs are asked for one as part of a JSON reply whose shape
is fixed by a schema and checked here.
"""

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rowlab.core.errors import InvalidRequest

AnswerType = Literal["yes_no", "pick_one", "pick_any", "scale"]

# Decision models take the content to judge (`state`) and instructions per question. The job's
# prompt holds both the question and the row's values, so it is sent as the state with this fixed
# instruction. Checked against several decision models: answers match asking the question separately.
INSTRUCTIONS = "Answer the question in the text."


class Option(BaseModel):
    name: str
    description: str = ""


DEFAULT_MODEL = "typesafe/jev-1.14"


class Task(BaseModel):
    # Responses always include every field, so the API schema marks them required there.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    template: str = Field("", description="The prompt, e.g. “Is this review negative? {{review}}”.")
    type: AnswerType = "yes_no"
    column: str = Field("answer", description="Base name of the result columns.")
    options: list[Option] = Field(
        [],
        description="The choices for pick one and pick any; the levels, lowest first, for scale.",
    )
    models: list[str] = Field(
        [DEFAULT_MODEL], description="Decision models or LLMs; see `GET /v1/models`."
    )


class AnswerFormatError(Exception):
    """A model's reply did not have the expected shape."""


def check(task: Task) -> None:
    """Raise InvalidRequest if the task can't be asked as configured."""
    if not task.template.strip():
        raise InvalidRequest("Write the prompt.")
    if not task.column.strip():
        raise InvalidRequest("Name the result column.")
    if not task.models:
        raise InvalidRequest("Pick a model.")
    slugs = [model_slug(m) for m in task.models]
    if len(set(slugs)) != len(slugs):
        raise InvalidRequest("Two of the models would get the same column name.")
    if task.type == "yes_no":
        return
    names = [o.name.strip() for o in task.options]
    what = "levels" if task.type == "scale" else "options"
    if len(names) < 2:
        raise InvalidRequest(f"Add at least two {what}.")
    if not all(names):
        raise InvalidRequest(f"Name all {what}.")
    if len(set(names)) != len(names):
        raise InvalidRequest(f"The {what} need different names.")


def model_slug(model: str) -> str:
    """How a model appears in column names: `typesafe/jev-1.14` → `jev-1.14`."""
    return model.rsplit("/", 1)[-1]


def base_columns(task: Task) -> list[str]:
    """The answer columns before the model is added to their names."""
    if task.type == "pick_any":
        return [f"{task.column}_{o.name}" for o in task.options]
    return [task.column]


def result_columns(task: Task) -> list[str]:
    """The answer columns a task writes, per model. Each also has a `_proba` column."""
    return [f"{base}__{model_slug(model)}" for model in task.models for base in base_columns(task)]


def with_model(task: Task, model: str, values: dict[str, Any]) -> dict[str, Any]:
    """Rename a model's answers from base columns to that model's columns."""
    renamed = {}
    for base in base_columns(task):
        column = f"{base}__{model_slug(model)}"
        renamed[column] = values[base]
        renamed[f"{column}_proba"] = values[f"{base}_proba"]
    return renamed


# Decision models


def decision_questions(task: Task) -> dict[str, Any]:
    if task.type == "yes_no":
        return {"answer": {"type": "noul", "instructions": INSTRUCTIONS}}
    if task.type == "pick_one":
        criteria = {o.name: o.description or o.name for o in task.options}
        return {"answer": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}}
    if task.type == "scale":
        criteria = [o.description or o.name for o in task.options]
        return {"answer": {"type": "score", "instructions": INSTRUCTIONS, "criteria": criteria}}
    return {
        f"option_{i}": {
            "type": "noul",
            "instructions": f"Is {_describe(o)} a correct answer to the question in the text?",
        }
        for i, o in enumerate(task.options)
    }


def read_decision(task: Task, answers: dict[str, Any]) -> dict[str, Any]:
    """Result columns from a decision model's answers."""
    if task.type == "pick_any":
        values = {}
        for i, column in enumerate(base_columns(task)):
            values |= _yes_no(column, _decision_answer(answers, f"option_{i}", "noul")["noul"])
        return values

    answer = _decision_answer(answers, "answer", _DECISION_TYPES[task.type])
    if task.type == "yes_no":
        return _yes_no(task.column, answer["noul"])
    probabilities = answer.get("probabilities") or {}
    if task.type == "pick_one":
        choice = answer["choice"]
        return {
            task.column: choice,
            f"{task.column}_proba": probabilities.get(choice, answer.get("confidence")),
        }
    # Scale: `score` is the expected level, a fraction; the answer is the most likely level.
    level, proba = max(probabilities.items(), key=lambda item: item[1])
    return {task.column: task.options[int(level)].name, f"{task.column}_proba": proba}


_DECISION_TYPES = {"yes_no": "noul", "pick_one": "choice", "scale": "score"}


def _decision_answer(answers: dict[str, Any], key: str, type_: str) -> dict[str, Any]:
    answer = answers.get(key) or {}
    if answer.get("type") == "refusal":
        raise AnswerFormatError("The model declined to answer.")
    if answer.get("type") != type_:
        raise AnswerFormatError(f"Expected a {type_} answer, got {answer.get('type')!r}.")
    return answer


def _yes_no(column: str, probability_yes: float) -> dict[str, Any]:
    yes = probability_yes >= 0.5
    return {column: yes, f"{column}_proba": probability_yes if yes else 1 - probability_yes}


# LLMs


def llm_messages(task: Task, prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _llm_instructions(task)},
        {"role": "user", "content": prompt},
    ]


def llm_schema(task: Task) -> dict[str, Any]:
    """JSON schema for the LLM's reply, enforced by structured outputs."""
    if task.type == "pick_any":
        properties = {o.name: _answer_schema({"type": "boolean"}) for o in task.options}
        return _object({"answers": _object(properties)})
    if task.type == "yes_no":
        return _answer_schema({"type": "boolean"})
    return _answer_schema({"type": "string", "enum": [o.name for o in task.options]})


def read_llm(task: Task, content: str | None) -> dict[str, Any]:
    """Result columns from an LLM's JSON reply, checked against the schema it was asked for."""
    try:
        reply = json.loads(content or "")
    except ValueError as e:
        raise AnswerFormatError("The model's reply was not JSON.") from e
    if task.type == "pick_any":
        answers = reply.get("answers") if isinstance(reply, dict) else None
        if not isinstance(answers, dict):
            raise AnswerFormatError("The model's reply had no answers.")
        values = {}
        for column, option in zip(base_columns(task), task.options):
            values |= _read_answer(column, answers.get(option.name), bool)
        return values
    if task.type == "yes_no":
        return _read_answer(task.column, reply, bool)
    allowed = {o.name for o in task.options}
    values = _read_answer(task.column, reply, str)
    if values[task.column] not in allowed:
        raise AnswerFormatError(
            f"The model answered {values[task.column]!r}, not one of the options."
        )
    return values


def _llm_instructions(task: Task) -> str:
    reply = (
        "Reply in JSON: `answer` is {answer}, and `proba` is the probability, from 0 to 1, that "
        "your answer is correct."
    )
    if task.type == "yes_no":
        return "Answer the yes/no question in the user's text.\n" + reply.format(
            answer="true for yes and false for no"
        )
    options = "\n".join(
        f"- {o.name}" + (f": {o.description}" if o.description else "") for o in task.options
    )
    if task.type == "pick_one":
        return (
            "Answer the question in the user's text by picking exactly one of these options.\n"
            + reply.format(answer="the option's name")
            + f"\n\nOptions:\n{options}"
        )
    if task.type == "scale":
        return (
            "Answer the question in the user's text by picking one level of this scale, listed "
            "from lowest to highest.\n"
            + reply.format(answer="the level's name")
            + f"\n\nLevels:\n{options}"
        )
    return (
        "Answer the question in the user's text: for each of these options, decide whether it is "
        "a correct answer. Any number of them may be, including none.\n"
        "Reply in JSON: `answers` has an entry per option, where `answer` is true or false and "
        "`proba` is the probability, from 0 to 1, that your true or false answer is correct."
        f"\n\nOptions:\n{options}"
    )


def _answer_schema(answer: dict[str, Any]) -> dict[str, Any]:
    return _object({"answer": answer, "proba": {"type": "number"}})


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _read_answer(column: str, reply: Any, type_: type) -> dict[str, Any]:
    if not isinstance(reply, dict) or not isinstance(reply.get("answer"), type_):
        raise AnswerFormatError("The model's reply did not have the expected answer.")
    proba = reply.get("proba")
    if isinstance(proba, bool) or not isinstance(proba, int | float) or not 0 <= proba <= 1:
        raise AnswerFormatError("The model's reply did not have a probability between 0 and 1.")
    return {column: reply["answer"], f"{column}_proba": float(proba)}


def _describe(option: Option) -> str:
    return f'"{option.name}"' + (f" ({option.description})" if option.description else "")

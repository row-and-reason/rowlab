"""Tasks: what a job produces for each row, and how decision models and LLMs are asked for it.

A task is a prompt (the question or instruction, with the row's columns in it), an answer type, and the
models that answer it. Answer types come in three families:

- **Classify** (yes/no, pick one, pick any, scale): puts the row in a known box. Any model; each answer
  comes with the probability (0 to 1) that it is right. Decision models return one; LLMs are asked for
  one as part of their reply.
- **Extract**: pulls typed facts (fields) out of the row. LLMs only. A field is empty when the text
  doesn't say.
- **Write**: produces new text from the row: a summary, a translation, a rewrite. LLMs only.

Each model writes its own columns, named after it: `<column>__<model>`, e.g. `team__jev-1.14`, with
`_proba` for Classify. Pick any writes one answer per option (`<column>_<option>__<model>`), Extract one
per field when there are several (`<column>_<field>__<model>`). With `reason`, an LLM also explains its
answer in `<column>__<model>_reason`.

LLM replies are JSON whose shape is fixed by a schema and checked here.
"""

import datetime
import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rowlab.core.errors import InvalidRequest
from rowlab.core.storage import sql_ident

AnswerType = Literal["yes_no", "pick_one", "pick_any", "scale", "extract", "write"]
GenerationPreset = Literal["summarize", "translate"]
FieldType = Literal["text", "number", "boolean", "date", "list", "items"]

CLASSIFY = ("yes_no", "pick_one", "pick_any", "scale")
# Answer types only LLMs can give.
LLM_ONLY = ("extract", "write")

DEFAULT_MODEL = "typesafe/jev-1.14"
DEFAULT_LLM = "anthropic/claude-haiku-5.5"

# Decision models take the content to judge (`state`) and instructions per question. The job's
# prompt holds both the question and the row's values, so it is sent as the state with this fixed
# instruction. Checked against several decision models: answers match asking the question separately.
INSTRUCTIONS = "Answer the question in the text."


class Option(BaseModel):
    name: str
    description: str = ""


class ExtractField(BaseModel):
    # Responses always include every field, so the API schema marks them required there.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    type: FieldType = "text"
    description: str = Field("", description="What to put in it, if the name doesn't say.")
    fields: list["ExtractField"] = Field(
        [], description="For `items`: the fields of each item, which can't be items themselves."
    )

    @model_validator(mode="before")
    @classmethod
    def _short_form(cls, value: Any) -> Any:
        """Accept `"amount:number"` for `{"name": "amount", "type": "number"}`."""
        if isinstance(value, str):
            name, _, type_ = value.partition(":")
            return {"name": name.strip(), "type": type_.strip() or "text"}
        return value


class Task(BaseModel):
    # Responses always include every field, so the API schema marks them required there.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    template: str = Field("", description="The prompt, e.g. “Is this review negative? {{review}}”.")
    type: AnswerType = "yes_no"
    preset: GenerationPreset | None = Field(
        None,
        description="Selected generation preset, for display. The template controls the output.",
    )
    column: str = Field(
        "answer", description="Base name of the result columns. Defaults to one for the type."
    )
    extraction_mode: Literal["single", "structure"] = Field(
        "structure", description="Extraction editor: one scalar value or named, typed fields."
    )
    options: list[Option] = Field(
        [],
        description="The choices for pick one and pick any; the levels, lowest first, for scale.",
    )
    fields: list[ExtractField] = Field(
        [],
        description='For extract: what to pull out. `"amount:number"` is short for '
        '`{"name": "amount", "type": "number"}`.',
    )
    reason: bool = Field(False, description="Also write why, from LLMs, for classify and extract.")
    models: list[str] = Field(
        [DEFAULT_MODEL],
        description="Decision models or LLMs; see `GET /v1/utils/models`. Defaults to one for the type.",
    )

    @model_validator(mode="before")
    @classmethod
    def _defaults_for_type(cls, value: Any) -> Any:
        """A column name and models that suit the type, unless given."""
        if isinstance(value, dict):
            info = _TYPES.get(value.get("type", "yes_no"))
            if info:
                value = {"column": info.column, "models": [info.model], **value}
        return value


class AnswerFormatError(Exception):
    """A model's reply did not have the expected shape."""


# The answer types, presets and field types, as the UI and API clients show them


class TypeInfo(BaseModel):
    id: AnswerType
    family: Literal["classify", "extract", "write"]
    label: str
    description: str
    column: str = Field(description="The result column a new task of this type gets.")
    model: str = Field(description="The model a new task of this type gets.")
    llm_only: bool


class Preset(BaseModel):
    """A starting point for a write task: its prompt, to finish by adding the row's columns."""

    id: GenerationPreset
    label: str
    column: str
    template: str


class FieldTypeInfo(BaseModel):
    id: FieldType
    label: str


class TaskTypes(BaseModel):
    types: list[TypeInfo] = Field(description="Classify, then extract, then write.")
    presets: list[Preset] = Field(description="Starting points for write tasks.")
    field_types: list[FieldTypeInfo]
    languages: list[str] = Field(description="Suggested target languages for translating.")


_TYPE_LIST = [
    TypeInfo(
        id="yes_no",
        family="classify",
        label="Yes / no",
        description="A yes or no question: filters, checks, flags.",
        column="answer",
        model=DEFAULT_MODEL,
        llm_only=False,
    ),
    TypeInfo(
        id="pick_one",
        family="classify",
        label="Pick one",
        description="Exactly one of your options: sentiment, intent, routing.",
        column="label",
        model=DEFAULT_MODEL,
        llm_only=False,
    ),
    TypeInfo(
        id="pick_any",
        family="classify",
        label="Pick any",
        description="Any number of your options: tags, topics.",
        column="tags",
        model=DEFAULT_MODEL,
        llm_only=False,
    ),
    TypeInfo(
        id="scale",
        family="classify",
        label="Scale",
        description="One level of a scale, lowest first: urgency, quality, rating.",
        column="level",
        model=DEFAULT_MODEL,
        llm_only=False,
    ),
    TypeInfo(
        id="extract",
        family="extract",
        label="Extract",
        description="Facts from the text, as typed fields: names, amounts, dates, line items.",
        column="extracted",
        model=DEFAULT_LLM,
        llm_only=True,
    ),
    TypeInfo(
        id="write",
        family="write",
        label="Write",
        description="New text from the row: a summary, a translation, a rewrite, a reply.",
        column="text",
        model=DEFAULT_LLM,
        llm_only=True,
    ),
]
_TYPES = {t.id: t for t in _TYPE_LIST}

PRESETS = [
    Preset(
        id="summarize",
        label="Summarize",
        column="summary",
        template="Summarize in one sentence:\n\n",
    ),
    Preset(
        id="translate",
        label="Translate",
        column="translation",
        template="Translate into English:\n\n",
    ),
]

_FIELD_TYPES = [
    FieldTypeInfo(id="text", label="Text"),
    FieldTypeInfo(id="number", label="Number"),
    FieldTypeInfo(id="boolean", label="True / false"),
    FieldTypeInfo(id="date", label="Date"),
    FieldTypeInfo(id="list", label="List of text"),
    FieldTypeInfo(id="items", label="Items, each with fields"),
]

LANGUAGES = [
    "English",
    "Spanish",
    "French",
    "German",
    "Portuguese",
    "Italian",
    "Dutch",
    "Swedish",
    "Finnish",
    "Polish",
    "Japanese",
    "Chinese",
    "Korean",
    "Arabic",
    "Hindi",
]


def task_types() -> TaskTypes:
    return TaskTypes(
        types=_TYPE_LIST, presets=PRESETS, field_types=_FIELD_TYPES, languages=LANGUAGES
    )


def check(task: Task, *, manual: bool = False) -> None:
    """Raise InvalidRequest if the task can't be asked as configured. Whether its models can give
    its type of answer is checked with the model catalog, in `runs.check`."""
    if not task.template.strip():
        raise InvalidRequest("Write the prompt.")
    if not task.column.strip():
        raise InvalidRequest("Name the result column.")
    if not manual and not task.models:
        raise InvalidRequest("Pick a model.")
    slugs = [model_slug(m) for m in task.models]
    if not manual and len(set(slugs)) != len(slugs):
        raise InvalidRequest("Two of the models would get the same column name.")
    if task.type == "write":
        if task.reason:
            raise InvalidRequest("Write tasks have no reason column.")
        return
    if task.type == "extract":
        if task.extraction_mode == "single" and (
            len(task.fields) != 1 or task.fields[0].type in ("list", "items")
        ):
            raise InvalidRequest("Single value extraction needs exactly one scalar field.")
        _check_fields(task.fields, "fields")
        return
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


def _check_fields(fields: list[ExtractField], what: str) -> None:
    if not fields:
        raise InvalidRequest(f"Add at least one of the {what}.")
    names = [f.name.strip() for f in fields]
    if not all(names):
        raise InvalidRequest(f"Name all {what}.")
    if len(set(names)) != len(names):
        raise InvalidRequest(f"The {what} need different names.")
    for f in fields:
        if f.type == "items":
            if any(sub.type == "items" for sub in f.fields):
                raise InvalidRequest(f"The items in {f.name} can't hold items themselves.")
            _check_fields(f.fields, f"fields of {f.name}")


def model_slug(model: str) -> str:
    """How a model appears in column names: `typesafe/jev-1.14` → `jev-1.14`."""
    return model.rsplit("/", 1)[-1]


def columns(task: Task, model: str) -> list[tuple[str, str]]:
    """The columns a model writes for a task, with their SQL types, the answer first."""
    return [(column, sql_type) for _, column, sql_type in _column_map(task, model)]


def result_columns(task: Task) -> list[str]:
    """The answer columns a task writes, for all its models, without their `_proba` and `_reason`
    columns."""
    return [
        column
        for model in task.models
        for key, column, _ in _column_map(task, model)
        if not key.endswith("_proba") and key != _REASON
    ]


def answer_columns(task: Task, *, manual: bool) -> list[str]:
    """The answer columns a run writes for a task: `result_columns`, or `manual_columns` by name."""
    return [name for name, _ in manual_columns(task)] if manual else result_columns(task)


def part_columns(task: Task, *, manual: bool) -> list[tuple[str, str]]:
    """Every column a run writes for a task, with its SQL type."""
    if manual:
        return manual_columns(task)
    return [column for model in task.models for column in columns(task, model)]


def with_model(task: Task, model: str, values: dict[str, Any]) -> dict[str, Any]:
    """A model's answers, read by `read_decision` or `read_llm`, as that model's columns."""
    return {column: values.get(key) for key, column, _ in _column_map(task, model)}


_REASON = "__reason"

_SQL_TYPES = {
    "text": "VARCHAR",
    "number": "DOUBLE",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "list": "VARCHAR[]",
}


def _column_map(task: Task, model: str) -> list[tuple[str, str, str]]:
    """(key in the answer values, column, SQL type) for each column a model writes."""
    slug = model_slug(model)
    mapped = []
    if task.type in CLASSIFY:
        answer_type = "BOOLEAN" if task.type in ("yes_no", "pick_any") else "VARCHAR"
        for base in _classify_columns(task):
            mapped.append((base, f"{base}__{slug}", answer_type))
            mapped.append((f"{base}_proba", f"{base}__{slug}_proba", "DOUBLE"))
    elif task.type == "extract":
        for f in task.fields:
            base = task.column if len(task.fields) == 1 else f"{task.column}_{f.name}"
            mapped.append((f.name, f"{base}__{slug}", _sql_type(f)))
    else:
        mapped.append(("text", f"{task.column}__{slug}", "VARCHAR"))
    if task.reason:
        mapped.append((_REASON, f"{task.column}__{slug}_reason", "VARCHAR"))
    return mapped


def _classify_columns(task: Task) -> list[str]:
    if task.type == "pick_any":
        return [f"{task.column}_{o.name}" for o in task.options]
    return [task.column]


def _sql_type(f: ExtractField) -> str:
    if f.type != "items":
        return _SQL_TYPES[f.type]
    members = ", ".join(f"{sql_ident(sub.name)} {_sql_type(sub)}" for sub in f.fields)
    return f"STRUCT({members})[]"


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
    """Answer values from a decision model's answers."""
    if task.type == "pick_any":
        values = {}
        for i, column in enumerate(_classify_columns(task)):
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
        {"role": "system", "content": llm_instructions(task)},
        {"role": "user", "content": prompt},
    ]


def llm_schema(task: Task) -> dict[str, Any]:
    """JSON schema for the LLM's reply, enforced by structured outputs. A reason comes first, so the
    model explains itself before it answers."""
    reason = {"reason": {"type": "string"}} if task.reason else {}
    if task.type == "write":
        return _object({"text": {"type": "string"}})
    if task.type == "extract":
        return _object(reason | {f.name: _field_schema(f) for f in task.fields})
    if task.type == "pick_any":
        properties = {o.name: _answer_schema({"type": "boolean"}) for o in task.options}
        return _object(reason | {"answers": _object(properties)})
    if task.type == "yes_no":
        return _object(reason | _answer_properties({"type": "boolean"}))
    enum = {"type": "string", "enum": [o.name for o in task.options]}
    return _object(reason | _answer_properties(enum))


def read_llm(task: Task, content: str | None) -> dict[str, Any]:
    """Answer values from an LLM's JSON reply, checked against the schema it was asked for."""
    try:
        reply = json.loads(content or "")
    except ValueError as e:
        raise AnswerFormatError("The model's reply was not JSON.") from e
    if not isinstance(reply, dict):
        raise AnswerFormatError("The model's reply was not a JSON object.")
    values = _read_reason(reply) if task.reason else {}
    if task.type == "write":
        if not isinstance(reply.get("text"), str):
            raise AnswerFormatError("The model's reply had no text.")
        return values | {"text": reply["text"]}
    if task.type == "extract":
        return values | {f.name: _read_field(f, reply.get(f.name)) for f in task.fields}
    if task.type == "pick_any":
        answers = reply.get("answers")
        if not isinstance(answers, dict):
            raise AnswerFormatError("The model's reply had no answers.")
        for column, option in zip(_classify_columns(task), task.options):
            values |= _read_answer(column, answers.get(option.name), bool)
        return values
    if task.type == "yes_no":
        return values | _read_answer(task.column, reply, bool)
    allowed = {o.name for o in task.options}
    values |= _read_answer(task.column, reply, str)
    if values[task.column] not in allowed:
        raise AnswerFormatError(
            f"The model answered {values[task.column]!r}, not one of the options."
        )
    return values


def llm_instructions(task: Task) -> str:
    """The system message for a task."""
    reason = (
        "\n`reason` briefly explains your answer; write it before deciding." if task.reason else ""
    )
    if task.type == "write":
        return (
            "Do what the user's text asks.\n"
            "Reply in JSON: `text` is the result itself, without any comments around it."
        )
    if task.type == "extract":
        return (
            "Extract these fields from the user's text. Use null for a field the text doesn't "
            "give; never guess or make one up.\n"
            "Reply in JSON with one entry per field."
            + reason
            + "\n\nFields:\n"
            + "\n".join(_describe_field(f) for f in task.fields)
        )
    reply = (
        "Reply in JSON: `answer` is {answer}, and `proba` is the probability, from 0 to 1, that "
        "your answer is correct." + reason
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
        + reason
        + f"\n\nOptions:\n{options}"
    )


_FIELD_DESCRIPTIONS = {
    "text": "text",
    "number": "a number",
    "boolean": "true or false",
    "date": "a date, as YYYY-MM-DD",
    "list": "a list of text",
}


def _describe_field(f: ExtractField, indent: str = "") -> str:
    what = (
        "a list of items, each with these fields:"
        if f.type == "items"
        else _FIELD_DESCRIPTIONS[f.type]
    )
    line = f"{indent}- {f.name}: {what}" + (f" — {f.description}" if f.description else "")
    subfields = (
        [_describe_field(sub, indent + "  ") for sub in f.fields] if f.type == "items" else []
    )
    return "\n".join([line, *subfields])


def _field_schema(f: ExtractField) -> dict[str, Any]:
    """Every field may be null: the text may not give it."""
    if f.type == "items":
        item = _object({sub.name: _field_schema(sub) for sub in f.fields})
        return {"type": ["array", "null"], "items": item}
    if f.type == "list":
        return {"type": ["array", "null"], "items": {"type": "string"}}
    if f.type == "date":
        return {"type": ["string", "null"], "description": "YYYY-MM-DD"}
    json_type = {"text": "string", "number": "number", "boolean": "boolean"}[f.type]
    return {"type": [json_type, "null"]}


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _read_field(f: ExtractField, value: Any) -> Any:
    """A field's value from the reply, checked against its type; None when the text didn't give it."""
    if value is None:
        return None
    wrong = AnswerFormatError(
        f"The model's {f.name} was not {_FIELD_DESCRIPTIONS.get(f.type, 'a list of items')}."
    )
    if f.type == "text":
        if not isinstance(value, str):
            raise wrong
        return value
    if f.type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise wrong
        return float(value)
    if f.type == "boolean":
        if not isinstance(value, bool):
            raise wrong
        return value
    if f.type == "date":
        try:
            if not isinstance(value, str) or not _DATE.fullmatch(value):
                raise ValueError
            return datetime.date.fromisoformat(value)
        except ValueError as e:
            raise wrong from e
    if f.type == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise wrong
        return value
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise wrong
    return [{sub.name: _read_field(sub, item.get(sub.name)) for sub in f.fields} for item in value]


def _answer_properties(answer: dict[str, Any]) -> dict[str, Any]:
    return {"answer": answer, "proba": {"type": "number"}}


def _answer_schema(answer: dict[str, Any]) -> dict[str, Any]:
    return _object(_answer_properties(answer))


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _read_reason(reply: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(reply.get("reason"), str):
        raise AnswerFormatError("The model's reply had no reason.")
    return {_REASON: reply["reason"]}


def _read_answer(column: str, reply: Any, type_: type) -> dict[str, Any]:
    if not isinstance(reply, dict) or not isinstance(reply.get("answer"), type_):
        raise AnswerFormatError("The model's reply did not have the expected answer.")
    proba = reply.get("proba")
    if isinstance(proba, bool) or not isinstance(proba, int | float) or not 0 <= proba <= 1:
        raise AnswerFormatError("The model's reply did not have a probability between 0 and 1.")
    return {column: reply["answer"], f"{column}_proba": float(proba)}


def _describe(option: Option) -> str:
    return f'"{option.name}"' + (f" ({option.description})" if option.description else "")


def manual_columns(task: Task) -> list[tuple[str, str]]:
    """Manual labels have the task's names and types, without model metadata."""
    if task.type in CLASSIFY:
        return [
            (name, "BOOLEAN" if task.type in ("yes_no", "pick_any") else "VARCHAR")
            for name in _classify_columns(task)
        ]
    if task.type == "extract":
        return [
            (task.column if len(task.fields) == 1 else f"{task.column}_{f.name}", _sql_type(f))
            for f in task.fields
        ]
    return [(task.column, "VARCHAR")]


def read_manual(task: Task, value: Any) -> dict[str, Any]:
    """Validate manually supplied values using the task's answer types. Null clears the answer."""
    names = [name for name, _ in manual_columns(task)]
    if value is None:
        return dict.fromkeys(names)
    if task.type == "yes_no":
        if type(value) is not bool:
            raise InvalidRequest("A yes/no label must be true or false.")
        return {task.column: value}
    if task.type in ("pick_one", "scale"):
        if not isinstance(value, str) or value not in [o.name for o in task.options]:
            raise InvalidRequest("Choose one of the task's options.")
        return {task.column: value}
    if task.type == "pick_any":
        if not isinstance(value, list) or any(
            not isinstance(v, str) or v not in [o.name for o in task.options] for v in value
        ):
            raise InvalidRequest("Supply a list of the task's option names.")
        return {name: option.name in value for name, option in zip(names, task.options)}
    if task.type == "write":
        if not isinstance(value, str):
            raise InvalidRequest("Supply text for this task.")
        return {task.column: value}
    if not isinstance(value, dict) or set(value) != {f.name for f in task.fields}:
        raise InvalidRequest("Supply an object with this task's field names.")
    try:
        return {name: _read_field(f, value[f.name]) for name, f in zip(names, task.fields)}
    except AnswerFormatError as e:
        raise InvalidRequest(str(e)) from e

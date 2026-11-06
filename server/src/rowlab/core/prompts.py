"""Prompt templates: `{{field}}` placeholders filled in from a dataset row.

A field is a column name, or a path into a struct column such as `{{actor.login}}`. Column names
are used as they are, so `{{first name}}` works without quoting.
"""

import difflib
import functools
import json
import re
from typing import Any

import tiktoken
from pydantic import BaseModel, Field

from rowlab.core import datasets, sql
from rowlab.core.datasets import ROW_ID

PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*\}\}")

# Rows sampled at random to estimate token counts for the whole dataset.
SAMPLE_SIZE = 200


class TemplateField(BaseModel):
    path: str
    type: str


class RenderedRow(BaseModel):
    row_id: int | None = Field(description="Empty if the query doesn't return `__row_id`.")
    prompt: str
    tokens: int
    values: dict[str, Any] = Field(description="The row's value for each field the template uses.")


class TokenStats(BaseModel):
    sample_size: int
    min: int
    avg: float
    max: int
    total_estimate: int = Field(description="Estimated tokens for all selected rows.")


class RenderRequest(BaseModel):
    template: str
    sql: str = Field(sql.ALL_ROWS, description="The rows to render for: a SELECT over `data`.")
    offset: int = Field(0, ge=0, description="First row to render, counting from 0.")
    limit: int = Field(1, ge=1, le=50)


class RenderResult(BaseModel):
    fields: list[TemplateField] = Field(description="Everything the template can use.")
    selected_rows: int = Field(description="Rows the query returns.")
    warnings: list[str]
    rows: list[RenderedRow]
    tokens: TokenStats


def render_dataset(dataset_id: str, request: RenderRequest) -> RenderResult:
    """Render a template for a page of the selected rows, with warnings, and token estimates from a
    sample of them."""
    fields = datasets.dataset_fields(dataset_id)
    keys = {path: field_keys for path, (_, field_keys) in fields.items()}
    used = list(dict.fromkeys(PLACEHOLDER.findall(request.template)))

    warnings = []
    for path in used:
        if path not in keys:
            close = difflib.get_close_matches(path, list(keys), n=1)
            hint = f" Did you mean `{close[0]}`?" if close else ""
            warnings.append(f"`{path}` is not a column.{hint}")
    if request.template.strip() and not used:
        warnings.append("The template uses no columns, so every row gets the same prompt.")

    page = sql.query(
        dataset_id, sql.QueryRequest(sql=request.sql, offset=request.offset, limit=request.limit)
    )
    rows = []
    for row in page.rows:
        prompt = render(request.template, row, keys)
        values = {path: _lookup(row, keys.get(path)) for path in used}
        rows.append(
            RenderedRow(
                row_id=row.get(ROW_ID), prompt=prompt, tokens=count_tokens(prompt), values=values
            )
        )

    sample = sql.sample(dataset_id, request.sql, SAMPLE_SIZE)
    counts = [count_tokens(render(request.template, row, keys)) for row in sample]
    for path in used:
        if path in keys:
            empty = sum(_is_empty(_lookup(row, keys[path])) for row in sample)
            if empty:
                warnings.append(f"`{path}` is empty in {empty} of {len(sample)} sampled rows.")

    avg = sum(counts) / len(counts) if counts else 0
    tokens = TokenStats(
        sample_size=len(sample),
        min=min(counts, default=0),
        avg=round(avg, 1),
        max=max(counts, default=0),
        total_estimate=round(avg * page.total),
    )
    return RenderResult(
        fields=[TemplateField(path=path, type=type_) for path, (type_, _) in fields.items()],
        selected_rows=page.total,
        warnings=warnings,
        rows=rows,
        tokens=tokens,
    )


def render(template: str, row: dict[str, Any], keys: dict[str, list[str]]) -> str:
    """Fill in each `{{field}}`. Unknown fields and empty values become an empty string."""
    return PLACEHOLDER.sub(lambda m: to_text(_lookup(row, keys.get(m.group(1)))), template)


def to_text(value: Any) -> str:
    """How a value appears in a prompt: text as is, everything else as compact JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def count_tokens(text: str) -> int:
    """An estimate: models differ, so this uses one common tokenizer (OpenAI's o200k)."""
    return len(_encoding().encode(text, disallowed_special=()))


@functools.cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def _lookup(row: dict[str, Any], keys: list[str] | None) -> Any:
    """The value at `keys` in a row, or None for unknown fields (`keys` is None)."""
    if keys is None:
        return None
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _is_empty(value: Any) -> bool:
    return value is None or value == ""

"""What runs asked of models (`usage` table): a row per run, task, model and day, added to as answers
come in, whoever's key paid. Summed up by month for Settings → Usage: an admin sees the organisation,
anyone else their own.
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.auth import Me, User
from rowlab.core.errors import InvalidRequest

PaidBy = Literal["organisation", "server"]


class Spent(BaseModel):
    """Spent by one task and model."""

    answers: int = 0
    cached: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0


class Total(BaseModel):
    answers: int = Field(description="Answers given, from the cache too.")
    cached: int = Field(description="Of those, from the cache, for free.")
    failed: int
    input_tokens: int
    output_tokens: int
    cost: float = Field(description="USD.")


class Day(Total):
    day: str = Field(description="e.g. `2026-11-07`, in UTC.")


class ByModel(Total):
    model: str


class ByPerson(Total):
    user: User | None = Field(description="Empty for runs started where nobody signs in.")


class Usage(BaseModel):
    month: str = Field(description="e.g. `2026-11`.")
    scope: Literal["organisation", "you"] = Field(
        description="An admin sees the organisation's usage; anyone else their own."
    )
    total: Total
    by_day: list[Day] = Field(description="Days with usage, in order.")
    by_model: list[ByModel] = Field(description="Most answers first.")
    by_person: list[ByPerson] = Field(description="Most answers first; the organisation's only.")
    storage_bytes: int = Field(description="The organisation's datasets, now.")


def add(
    conn: Any,
    *,
    org_id: str,
    user_id: str | None,
    run_id: str,
    paid_by: PaidBy,
    spent: dict[tuple[str, str], Spent],
) -> None:
    """Add what a run spent, by task and model, to today's usage."""
    day = datetime.now(UTC).date().isoformat()
    for (task_id, model), this in spent.items():
        conn.execute(
            "INSERT INTO usage (org_id, user_id, run_id, task_id, model, paid_by, day, answers,"
            " cached, failed, input_tokens, output_tokens, cost)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (run_id, task_id, model, paid_by, day) DO UPDATE SET"
            " answers = usage.answers + excluded.answers,"
            " cached = usage.cached + excluded.cached,"
            " failed = usage.failed + excluded.failed,"
            " input_tokens = usage.input_tokens + excluded.input_tokens,"
            " output_tokens = usage.output_tokens + excluded.output_tokens,"
            " cost = usage.cost + excluded.cost",
            (
                org_id,
                user_id,
                run_id,
                task_id,
                model,
                paid_by,
                day,
                this.answers,
                this.cached,
                this.failed,
                this.input_tokens,
                this.output_tokens,
                this.cost,
            ),
        )


_SUMS = (
    "sum(answers) AS answers, sum(cached) AS cached, sum(failed) AS failed,"
    " sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cost) AS cost"
)


def month_usage(me: Me, month: str | None = None) -> Usage:
    """A month's usage (this one by default): the organisation's for an admin, else the caller's."""
    month = month or datetime.now(UTC).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise InvalidRequest("Give the month as YYYY-MM, e.g. 2026-11.")
    year, number = int(month[:4]), int(month[5:])
    end = f"{year + number // 12:04d}-{number % 12 + 1:02d}"
    scope: Literal["organisation", "you"] = "organisation" if me.role == "admin" else "you"
    where = "u.org_id = ? AND u.day >= ? AND u.day < ?"
    params: list = [me.org.id, month, end]
    if scope == "you":
        where += " AND u.user_id = ?"
        params.append(me.user.id)
    with db.connect() as conn:
        total = conn.execute(f"SELECT {_SUMS} FROM usage u WHERE {where}", params).fetchone()
        days = conn.execute(
            f"SELECT u.day, {_SUMS} FROM usage u WHERE {where} GROUP BY u.day ORDER BY u.day",
            params,
        ).fetchall()
        models = conn.execute(
            f"SELECT u.model, {_SUMS} FROM usage u WHERE {where}"
            " GROUP BY u.model ORDER BY answers DESC, u.model",
            params,
        ).fetchall()
        people = []
        if scope == "organisation":
            people = conn.execute(
                f"SELECT u.user_id, p.email, p.name, {_SUMS} FROM usage u"
                f" LEFT JOIN users p ON p.id = u.user_id WHERE {where}"
                " GROUP BY u.user_id, p.email, p.name ORDER BY answers DESC",
                params,
            ).fetchall()
        storage = conn.execute(
            "SELECT coalesce(sum(size_bytes), 0) AS bytes FROM datasets WHERE org_id = ?",
            (me.org.id,),
        ).fetchone()["bytes"]
    return Usage(
        month=month,
        scope=scope,
        total=Total(**_sums(total)),
        by_day=[Day(day=row["day"], **_sums(row)) for row in days],
        by_model=[ByModel(model=row["model"], **_sums(row)) for row in models],
        by_person=[
            ByPerson(
                user=User(id=row["user_id"], email=row["email"], name=row["name"])
                if row["user_id"] and row["email"]
                else None,
                **_sums(row),
            )
            for row in people
        ],
        storage_bytes=storage,
    )


def _sums(row: dict) -> dict:
    """The sums of a row, as numbers: empty sums (no usage) are 0."""
    return {
        name: (float if name == "cost" else int)(row[name] or 0)
        for name in ("answers", "cached", "failed", "input_tokens", "output_tokens", "cost")
    }

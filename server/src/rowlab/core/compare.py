"""Comparing columns: how often two or more columns give the same value in each row.

The columns can be anything: several models' answers to one task, a model's answers against labels
someone already has, or two columns of the original data. With a reference column, the comparison also
says how often each other column matches it (its accuracy, if the reference is right). Every count
comes with SQL for its rows (`where`), to add to a query's WHERE clause: to look at them, or to ask
about them again.

Lists count as the same when they hold the same items; with a tolerance, numbers and dates count as the
same when they are no further apart. Empty values never count as a disagreement.
"""

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import sql
from rowlab.core.datasets import sql_ident, sql_string
from rowlab.core.errors import InvalidRequest

# Most common values listed (the rest are added up), and most common pairs in a crosstab.
TOP_VALUES = 20
TOP_CELLS = 50

_NUMBERS = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE")


class CompareRequest(BaseModel):
    columns: list[str] = Field(description="Two or more; or one, with a reference.")
    reference: str | None = Field(
        None, description="A column to measure the others against, e.g. labels known to be right."
    )
    tolerance: float | None = Field(
        None,
        description="For number and date columns: how far apart values may be (days for dates).",
    )
    sql: str = Field(sql.ALL_ROWS, description="The rows to compare: a SELECT over `data`.")


class Rows(BaseModel):
    rows: int
    where: str | None = Field(description="SQL picking these rows, for a query's WHERE clause.")


class Agreement(BaseModel):
    all_agree: Rows = Field(description="Every column has a value, and they are all the same.")
    disagree: Rows = Field(description="At least two values differ.")
    partly_answered: int = Field(description="Some columns are empty, and the others agree.")
    not_answered: int = Field(description="Every column is empty.")
    rate: float | None = Field(
        description="Of the rows that agree or disagree, the share that agree."
    )


class Pair(BaseModel):
    columns: list[str]
    compared: int = Field(description="Rows where both have a value.")
    agree: int
    rate: float | None
    disagree: str = Field(description="SQL picking the rows where the two differ.")


class ValueCounts(BaseModel):
    value: str | None = Field(
        description="None for all values past the most common ones, added up."
    )
    counts: dict[str, int] = Field(description="Rows with this value, by column.")


class Cell(BaseModel):
    values: list[str] = Field(description="The two columns' values, in the order compared.")
    rows: int
    where: str


class ValueAccuracy(BaseModel):
    value: str
    support: int = Field(
        description="Rows where the reference has this value (and the column one)."
    )
    predicted: int = Field(
        description="Rows where the column has this value (and the reference one)."
    )
    correct: int
    precision: float | None
    recall: float | None


class ReferenceAccuracy(BaseModel):
    column: str
    compared: int = Field(description="Rows where both the column and the reference have a value.")
    correct: int
    accuracy: float | None
    wrong: str = Field(
        description="SQL picking the rows where the column differs from the reference."
    )
    values: list[ValueAccuracy] = Field(
        description="For the reference's most common values; empty with a tolerance."
    )


class Comparison(BaseModel):
    rows: int = Field(description="Rows compared: those the query returns.")
    columns: list[str] = Field(description="The columns compared, with the reference last.")
    agreement: Agreement
    pairs: list[Pair] = Field(description="Every two of the columns.")
    values: list[ValueCounts] = Field(
        description="The most common values, and how often each column gives them."
    )
    crosstab: list[Cell] | None = Field(
        description="For exactly two columns: how often each pair of their values occurs."
    )
    reference: list[ReferenceAccuracy] | None = Field(
        description="With a reference: how often each other column matches it."
    )


def compare(dataset_id: str, request: CompareRequest) -> Comparison:
    columns = request.columns + ([request.reference] if request.reference else [])
    if len(columns) < 2:
        raise InvalidRequest("Compare two or more columns.")
    if len(set(columns)) != len(columns):
        raise InvalidRequest("Compare different columns.")

    with sql.connect(dataset_id) as con:
        query = sql.check(con, request.sql)
        types = {
            r[0]: r[1] for r in sql.execute(con, f"DESCRIBE SELECT * FROM ({query})").fetchall()
        }
        for c in columns:
            if c not in types:
                raise InvalidRequest(f"Unknown column: {c}")
        same = _Same(types, request.tolerance)
        source = f"FROM ({query}) AS t"

        def one(expressions: list[str]) -> tuple:
            return sql.execute(con, f"SELECT {', '.join(expressions)} {source}").fetchone()

        answered = " + ".join(f"({sql_ident(c)} IS NOT NULL)::INT" for c in columns)
        rows, all_agree, disagree, none = one(
            [
                "count(*)",
                f"count(*) FILTER ({same.agree(columns)})",
                f"count(*) FILTER ({same.disagree(columns)})",
                f"count(*) FILTER ({answered} = 0)",
            ]
        )

        pairs = []
        for i, a in enumerate(columns):
            for b in columns[i + 1 :]:
                compared, agree = one(
                    [
                        f"count(*) FILTER ({sql_ident(a)} IS NOT NULL AND {sql_ident(b)} IS NOT NULL)",
                        f"count(*) FILTER ({same.agree([a, b])})",
                    ]
                )
                pairs.append(
                    Pair(
                        columns=[a, b],
                        compared=compared,
                        agree=agree,
                        rate=_share(agree, compared),
                        disagree=same.disagree([a, b]),
                    )
                )

        values = _value_counts(con, columns, types, source)

        crosstab = None
        if len(columns) == 2:
            a, b = (_text(c, types[c]) for c in columns)
            cells = sql.execute(
                con,
                f"SELECT {a}, {b}, count(*) {source} WHERE {a} IS NOT NULL AND {b} IS NOT NULL"
                f" GROUP BY ALL ORDER BY count(*) DESC, 1, 2 LIMIT {TOP_CELLS}",
            ).fetchall()
            crosstab = [
                Cell(
                    values=[va, vb],
                    rows=count,
                    where=f"{a} = {sql_string(va)} AND {b} = {sql_string(vb)}",
                )
                for va, vb, count in cells
            ]

        reference = None
        if request.reference:
            reference = [
                _accuracy(con, column, request.reference, types, same, source)
                for column in request.columns
            ]

    return Comparison(
        rows=rows,
        columns=columns,
        agreement=Agreement(
            all_agree=Rows(rows=all_agree, where=same.agree(columns)),
            disagree=Rows(rows=disagree, where=same.disagree(columns)),
            partly_answered=rows - all_agree - disagree - none,
            not_answered=none,
            rate=_share(all_agree, all_agree + disagree),
        ),
        pairs=pairs,
        values=values,
        crosstab=crosstab,
        reference=reference,
    )


class _Same:
    """SQL for whether columns' values are the same, with the `agree` and `disagree` functions."""

    def __init__(self, types: dict[str, str], tolerance: float | None):
        self.types = types
        self.tolerance = tolerance

    def agree(self, columns: list[str]) -> str:
        return self._call("agree", columns)

    def disagree(self, columns: list[str]) -> str:
        return self._call("disagree", columns)

    def _call(self, function: str, columns: list[str]) -> str:
        if self.tolerance is None:
            return f"{function}([{', '.join(self._exact(columns))}])"
        values = ", ".join(self._number(c) for c in columns)
        return f"{function}_within([{values}], {float(self.tolerance)})"

    def _exact(self, columns: list[str]) -> list[str]:
        kinds = {self.types[c] for c in columns}
        # Columns of one type compare as they are, lists by their items; others as text.
        if len(kinds) == 1 and not kinds.pop().endswith("[]"):
            return [sql_ident(c) for c in columns]
        return [_text(c, self.types[c]) for c in columns]

    def _number(self, column: str) -> str:
        sql_type = self.types[column]
        if sql_type == "DATE":
            return f"date_diff('day', DATE '1970-01-01', {sql_ident(column)})"
        if sql_type in _NUMBERS or sql_type.startswith("DECIMAL"):
            return f"CAST({sql_ident(column)} AS DOUBLE)"
        raise InvalidRequest("A tolerance is only for number and date columns.")


def _text(column: str, sql_type: str) -> str:
    """A column's value as text, for comparing it with other columns: lists with the same items
    compare the same, whatever their order."""
    if sql_type == "VARCHAR":
        return sql_ident(column)
    if sql_type.endswith("[]"):
        return f"CAST(list_sort({sql_ident(column)}) AS VARCHAR)"
    return f"CAST({sql_ident(column)} AS VARCHAR)"


def _value_counts(
    con: duckdb.DuckDBPyConnection, columns: list[str], types: dict[str, str], source: str
) -> list[ValueCounts]:
    union = " UNION ALL ".join(
        f"SELECT {sql_string(c)} AS col, {_text(c, types[c])} AS value {source}" for c in columns
    )
    counted = sql.execute(
        con, f"SELECT col, value, count(*) FROM ({union}) WHERE value IS NOT NULL GROUP BY ALL"
    ).fetchall()
    totals: dict[str, int] = {}
    by_value: dict[str, dict[str, int]] = {}
    for column, value, count in counted:
        totals[value] = totals.get(value, 0) + count
        by_value.setdefault(value, {c: 0 for c in columns})[column] = count
    ordered = sorted(totals, key=lambda v: (-totals[v], v))
    result = [ValueCounts(value=v, counts=by_value[v]) for v in ordered[:TOP_VALUES]]
    if len(ordered) > TOP_VALUES:
        other = {c: sum(by_value[v][c] for v in ordered[TOP_VALUES:]) for c in columns}
        result.append(ValueCounts(value=None, counts=other))
    return result


def _accuracy(
    con: duckdb.DuckDBPyConnection,
    column: str,
    reference: str,
    types: dict[str, str],
    same: _Same,
    source: str,
) -> ReferenceAccuracy:
    both = f"{sql_ident(column)} IS NOT NULL AND {sql_ident(reference)} IS NOT NULL"
    compared, correct = sql.execute(
        con,
        f"SELECT count(*) FILTER ({both}), count(*) FILTER ({same.agree([column, reference])}) "
        f"{source}",
    ).fetchone()
    values = []
    if same.tolerance is None:
        c, r = _text(column, types[column]), _text(reference, types[reference])
        for value, support, predicted, hits in sql.execute(
            con,
            f"WITH v AS (SELECT {r} AS value, count(*) AS support {source} WHERE {both}"
            f" GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_VALUES})"
            f" SELECT v.value, v.support,"
            f" (SELECT count(*) {source} WHERE {both} AND {c} = v.value),"
            f" (SELECT count(*) {source} WHERE {both} AND {c} = v.value AND {r} = v.value)"
            f" FROM v ORDER BY v.support DESC, v.value",
        ).fetchall():
            values.append(
                ValueAccuracy(
                    value=value,
                    support=support,
                    predicted=predicted,
                    correct=hits,
                    precision=_share(hits, predicted),
                    recall=_share(hits, support),
                )
            )
    return ReferenceAccuracy(
        column=column,
        compared=compared,
        correct=correct,
        accuracy=_share(correct, compared),
        wrong=same.disagree([column, reference]),
        values=values,
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None

"""Comparing columns: how often two or more columns give the same value in each row.

The columns can be anything: several models' answers to one task, a model's answers against labels
someone already has, or two columns of the original data. With a reference column, the comparison also
says how often each other column matches it (its accuracy, if the reference is right). Every count
comes with the filter for its rows, to look at them (`query`) or to ask about them again (`runs`).

Lists count as the same when they hold the same items; with a tolerance, numbers and dates count as the
same when they are no further apart. Empty values never count as a disagreement.
"""

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets
from rowlab.core.datasets import Filter, RowSelection, agreement_sql, sql_string, value_text_sql
from rowlab.core.errors import InvalidRequest

# Most common values listed (the rest are added up), and most common pairs in a crosstab.
TOP_VALUES = 20
TOP_CELLS = 50


class CompareRequest(RowSelection):
    """Which columns to compare, on the rows the search and filters pick (all by default)."""

    columns: list[str] = Field(description="Two or more; or one, with a reference.")
    reference: str | None = Field(
        None, description="A column to measure the others against, e.g. labels known to be right."
    )
    tolerance: float | None = Field(
        None,
        description="For number and date columns: how far apart values may be (days for dates).",
    )


class Rows(BaseModel):
    rows: int
    filter: Filter | None = Field(description="Picks these rows, in a scope's `filters`.")


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
    disagree: Filter


class ValueCounts(BaseModel):
    value: str | None = Field(
        description="None for all values past the most common ones, added up."
    )
    counts: dict[str, int] = Field(description="Rows with this value, by column.")


class Cell(BaseModel):
    values: list[str] = Field(description="The two columns' values, in the order compared.")
    rows: int
    filters: list[Filter]


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
    wrong: Filter
    values: list[ValueAccuracy] = Field(
        description="For the reference's most common values; empty with a tolerance."
    )


class Comparison(BaseModel):
    rows: int = Field(description="Rows compared: those the search and filters pick.")
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
    types = datasets.column_types(dataset_id)
    columns = request.columns + ([request.reference] if request.reference else [])
    if len(set(columns)) != len(columns):
        raise InvalidRequest("Compare different columns.")
    answered, same = agreement_sql(columns, types, request.tolerance)
    where, params = datasets.where_sql(request, types)
    source = f"FROM {datasets.dataset_source(dataset_id)} AS t WHERE {where}"
    n = len(columns)
    group = {"columns": columns, "tolerance": request.tolerance}

    with duckdb.connect() as con:

        def one(sql: str) -> tuple:
            return con.execute(sql, params).fetchone()

        rows, all_agree, disagree, partly, none = one(
            f"SELECT count(*),"
            f" count(*) FILTER ({answered} = {n} AND {same}),"
            f" count(*) FILTER ({answered} >= 2 AND NOT {same}),"
            f" count(*) FILTER ({answered} BETWEEN 1 AND {n - 1} AND ({answered} < 2 OR {same})),"
            f" count(*) FILTER ({answered} = 0) {source}"
        )

        pairs = []
        for i, a in enumerate(columns):
            for b in columns[i + 1 :]:
                pair_answered, pair_same = agreement_sql([a, b], types, request.tolerance)
                compared, agree = one(
                    f"SELECT count(*) FILTER ({pair_answered} = 2),"
                    f" count(*) FILTER ({pair_answered} = 2 AND {pair_same}) {source}"
                )
                pairs.append(
                    Pair(
                        columns=[a, b],
                        compared=compared,
                        agree=agree,
                        rate=_share(agree, compared),
                        disagree=Filter(op="disagree", columns=[a, b], tolerance=request.tolerance),
                    )
                )

        values = _value_counts(con, columns, types, source, params)

        crosstab = None
        if n == 2:
            a, b = (value_text_sql(c, types[c]) for c in columns)
            cells = con.execute(
                f"SELECT {a}, {b}, count(*) {source} AND {a} IS NOT NULL AND {b} IS NOT NULL"
                f" GROUP BY ALL ORDER BY count(*) DESC, 1, 2 LIMIT {TOP_CELLS}",
                params,
            ).fetchall()
            crosstab = [
                Cell(
                    values=[va, vb],
                    rows=count,
                    filters=[
                        Filter(column=columns[0], op="eq", value=va),
                        Filter(column=columns[1], op="eq", value=vb),
                    ],
                )
                for va, vb, count in cells
            ]

        reference = None
        if request.reference:
            reference = [
                _accuracy(con, column, request.reference, types, request.tolerance, source, params)
                for column in request.columns
            ]

    return Comparison(
        rows=rows,
        columns=columns,
        agreement=Agreement(
            all_agree=Rows(rows=all_agree, filter=Filter(op="agree", **group)),
            disagree=Rows(rows=disagree, filter=Filter(op="disagree", **group)),
            partly_answered=partly,
            not_answered=none,
            rate=_share(all_agree, all_agree + disagree),
        ),
        pairs=pairs,
        values=values,
        crosstab=crosstab,
        reference=reference,
    )


def _value_counts(
    con: duckdb.DuckDBPyConnection,
    columns: list[str],
    types: dict[str, str],
    source: str,
    params: list,
) -> list[ValueCounts]:
    union = " UNION ALL ".join(
        f"SELECT {sql_string(c)} AS col, {value_text_sql(c, types[c])} AS value {source}"
        for c in columns
    )
    counted = con.execute(
        f"SELECT col, value, count(*) FROM ({union}) WHERE value IS NOT NULL GROUP BY ALL",
        params * len(columns),
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
    tolerance: float | None,
    source: str,
    params: list,
) -> ReferenceAccuracy:
    answered, same = agreement_sql([column, reference], types, tolerance)
    compared, correct = con.execute(
        f"SELECT count(*) FILTER ({answered} = 2), count(*) FILTER ({answered} = 2 AND {same}) "
        f"{source}",
        params,
    ).fetchone()
    values = []
    if tolerance is None:
        c, r = value_text_sql(column, types[column]), value_text_sql(reference, types[reference])
        both = f"{source} AND {c} IS NOT NULL AND {r} IS NOT NULL"
        for value, support, predicted, hits in con.execute(
            f"WITH v AS (SELECT {r} AS value, count(*) AS support {both} GROUP BY 1"
            f" ORDER BY 2 DESC, 1 LIMIT {TOP_VALUES})"
            f" SELECT v.value, v.support,"
            f" (SELECT count(*) {both} AND {c} = v.value),"
            f" (SELECT count(*) {both} AND {c} = v.value AND {r} = v.value)"
            f" FROM v ORDER BY v.support DESC, v.value",
            params * 3,
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
        wrong=Filter(op="disagree", columns=[column, reference], tolerance=tolerance),
        values=values,
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None

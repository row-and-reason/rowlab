"""Comparing columns: how often two or more columns give the same value in each row.

The columns can be anything: several models' answers to one task, a model's answers against labels
someone already has, or two columns of the original data. With a reference column, the comparison also
says how often each other column matches it (its accuracy, if the reference is right). Every count
comes with SQL for its rows (`where`), to add to a query's WHERE clause: to look at them, or to ask
about them again.

Lists count as the same when they hold the same items; with a tolerance, numbers and dates count as the
same when they are no further apart. Empty values never count as a disagreement.
"""

import itertools
import math
from typing import Literal

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import sql
from rowlab.core.datasets import sql_ident, sql_string
from rowlab.core.errors import InvalidRequest

# Bound display summaries; confusion cells prioritize differing values, then frequency.
TOP_VALUES = 20
TOP_CELLS = 50

_NUMBERS = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "FLOAT",
    "DOUBLE",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
)


class CompareRequest(BaseModel):
    columns: list[str] = Field(description="Two or more; or one, with a reference.")
    reference: str | None = Field(
        None, description="A column to measure the others against, e.g. labels known to be right."
    )
    tolerance: float | None = Field(
        None,
        ge=0,
        allow_inf_nan=False,
        description="For number and date columns: how far apart values may be (days for dates).",
    )
    ignore_case: bool = Field(
        False,
        description="Compare VARCHAR columns using Unicode lowercase (not full case folding).",
    )
    trim_whitespace: bool = Field(
        False,
        description="Trim ASCII space, tab, newline, carriage return, form feed and vertical tab in VARCHAR columns. Empty strings remain answers.",
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


class HistogramBin(Rows):
    lower: float
    upper: float
    matched: Rows
    different: Rows
    upper_inclusive: bool


class NumericSummary(BaseModel):
    matched: Rows
    different: Rows
    difference: str = Field(
        description="Human-readable signed difference; column minus reference when a reference exists, otherwise second minus first."
    )
    unit: str
    finite_pairs: int
    non_finite_pairs: int
    bias: float | None
    mean_absolute_difference: float | None
    p95_absolute_difference: float | None
    max_absolute_difference: float | None
    histogram: list[HistogramBin]


class Coverage(BaseModel):
    missing_left: Rows
    missing_right: Rows
    missing_both: Rows


class Completeness(BaseModel):
    total_groups: int
    shown_groups: int
    omitted_count: int
    count_unit: Literal["rows", "answers"] = "rows"
    truncated: bool


class Pair(BaseModel):
    columns: list[str]
    compared: int = Field(description="Rows where both have a value.")
    agree: int
    rate: float | None
    disagree: str = Field(description="SQL picking the rows where the two differ.")
    coverage: Coverage
    numeric: NumericSummary | None = None


class ValueCounts(BaseModel):
    where: dict[str, str] = Field(
        description="Exact row predicates by column, including Other values."
    )
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
    labels_completeness: Completeness
    macro_f1: float | None
    balanced_accuracy: float | None
    column: str
    compared: int = Field(description="Rows where both the column and the reference have a value.")
    correct: int
    accuracy: float | None
    wrong: str = Field(
        description="SQL picking the rows where the column differs from the reference."
    )
    values: list[ValueAccuracy] = Field(
        description="Up to 20 reference labels with lowest recall; aggregate metrics use all labels. Empty with a tolerance."
    )


class Comparison(BaseModel):
    ignore_case: bool
    trim_whitespace: bool
    tolerance: float | None
    values_completeness: Completeness
    crosstab_completeness: Completeness | None
    rows: int = Field(description="Rows compared: those the query returns.")
    columns: list[str] = Field(description="The columns compared, with the reference last.")
    agreement: Agreement
    pairs: list[Pair] = Field(description="Every two of the columns.")
    values: list[ValueCounts] = Field(
        description="The most common values, and how often each column gives them."
    )
    crosstab: list[Cell] | None = Field(
        description="For exactly two columns: up to 50 value combinations, differing values first then frequency."
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
        same = _Same(types, request.tolerance, request.ignore_case, request.trim_whitespace)
        if (request.ignore_case or request.trim_whitespace) and any(
            types[c] != "VARCHAR" for c in columns
        ):
            raise InvalidRequest("Text matching rules require text columns only.")
        if (
            request.tolerance is not None
            and any(types[c] == "DATE" for c in columns)
            and not all(types[c] == "DATE" for c in columns)
        ):
            raise InvalidRequest("Compare dates with dates, not with numbers.")
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
                        coverage=_coverage(con, a, b, source),
                        numeric=_numeric(con, a, b, same, source, request.reference),
                    )
                )

        values, values_completeness = _value_counts(con, columns, same, source)

        crosstab = None
        crosstab_completeness = None
        if len(columns) == 2:
            a, b = (same.text(c) for c in columns)
            cells = sql.execute(
                con,
                f"SELECT {a}, {b}, count(*) {source} WHERE {a} IS NOT NULL AND {b} IS NOT NULL"
                f" GROUP BY 1, 2 ORDER BY ({a} = {b}), count(*) DESC, 1, 2 LIMIT {TOP_CELLS}",
            ).fetchall()
            total_groups, paired = sql.execute(
                con,
                f"SELECT count(*), coalesce(sum(n), 0) FROM (SELECT count(*) n {source} WHERE {a} IS NOT NULL AND {b} IS NOT NULL GROUP BY {a}, {b})",
            ).fetchone()
            crosstab_completeness = Completeness(
                total_groups=total_groups,
                shown_groups=len(cells),
                omitted_count=paired - sum(c[2] for c in cells),
                truncated=total_groups > len(cells),
            )
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
                _accuracy(con, column, request.reference, same, source)
                for column in request.columns
            ]

    return Comparison(
        ignore_case=request.ignore_case,
        trim_whitespace=request.trim_whitespace,
        tolerance=request.tolerance,
        values_completeness=values_completeness,
        crosstab_completeness=crosstab_completeness,
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

    def __init__(
        self,
        types: dict[str, str],
        tolerance: float | None,
        ignore_case: bool = False,
        trim_whitespace: bool = False,
    ):
        self.types = types
        self.tolerance = tolerance
        self.ignore_case = ignore_case
        self.trim_whitespace = trim_whitespace

    def text(self, column: str) -> str:
        value = _text(column, self.types[column])
        if self.types[column] == "VARCHAR":
            if self.trim_whitespace:
                value = f"regexp_replace({value}, '^[\\x09-\\x0D ]+|[\\x09-\\x0D ]+$', '', 'g')"
            if self.ignore_case:
                value = f"lower({value})"
        return value

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
            return [self.text(c) if self.types[c] == "VARCHAR" else sql_ident(c) for c in columns]
        return [self.text(c) for c in columns]

    def _number(self, column: str) -> str:
        sql_type = self.types[column]
        if sql_type == "DATE":
            return f"date_diff('day', DATE '1970-01-01', {sql_ident(column)})"
        if sql_type in _NUMBERS or sql_type.startswith("DECIMAL"):
            return sql_ident(column)
        if sql_type.startswith("TIMESTAMP"):
            raise InvalidRequest(
                "Timestamp tolerance is not supported; cast to DATE for day-level comparison."
            )
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
    con: duckdb.DuckDBPyConnection, columns: list[str], same: _Same, source: str
) -> tuple[list[ValueCounts], Completeness]:
    union = " UNION ALL ".join(
        f"SELECT {sql_string(c)} AS col, {same.text(c)} AS value {source}" for c in columns
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
    result = [
        ValueCounts(
            value=v,
            counts=by_value[v],
            where={c: f"{same.text(c)} = {sql_string(v)}" for c in columns},
        )
        for v in ordered[:TOP_VALUES]
    ]
    if len(ordered) > TOP_VALUES:
        other = {c: sum(by_value[v][c] for v in ordered[TOP_VALUES:]) for c in columns}
        known = ", ".join(sql_string(v) for v in ordered[:TOP_VALUES])
        result.append(
            ValueCounts(
                value=None,
                counts=other,
                where={c: f"{same.text(c)} NOT IN ({known})" for c in columns},
            )
        )
    return result, Completeness(
        total_groups=len(ordered),
        shown_groups=min(len(ordered), TOP_VALUES),
        omitted_count=sum(totals[v] for v in ordered[TOP_VALUES:]),
        count_unit="answers",
        truncated=len(ordered) > TOP_VALUES,
    )


def _accuracy(
    con: duckdb.DuckDBPyConnection,
    column: str,
    reference: str,
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
        c, r = same.text(column), same.text(reference)
        for value, support, predicted, hits in sql.execute(
            con,
            f"WITH paired AS (SELECT {c} prediction, {r} reference {source} WHERE {both}),"
            " refs AS (SELECT reference value, count(*) support FROM paired GROUP BY 1),"
            " preds AS (SELECT prediction value, count(*) predicted FROM paired GROUP BY 1),"
            " hits AS (SELECT reference value, count(*) correct FROM paired WHERE prediction=reference GROUP BY 1)"
            " SELECT refs.value, support, coalesce(predicted,0), coalesce(correct,0)"
            " FROM refs LEFT JOIN preds USING(value) LEFT JOIN hits USING(value)",
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
    total_labels = len(values)
    balanced = sum(v.recall or 0 for v in values) / total_labels if total_labels else None
    # Include predicted-only labels in macro F1 (their score is zero).
    predicted_only = 0
    if same.tolerance is None:
        predicted_only = sql.execute(
            con,
            f"SELECT count(DISTINCT {c}) {source} WHERE {both} AND {c} NOT IN (SELECT {r} {source} WHERE {both})",
        ).fetchone()[0]
    label_union = total_labels + predicted_only
    macro_f1 = (
        sum(2 * v.correct / (v.support + v.predicted) for v in values) / label_union
        if label_union
        else None
    )
    shown = sorted(
        values, key=lambda v: (v.recall if v.recall is not None else 2, -v.support, v.value)
    )[:TOP_VALUES]
    return ReferenceAccuracy(
        labels_completeness=Completeness(
            total_groups=total_labels,
            shown_groups=len(shown),
            omitted_count=sum(v.support for v in values) - sum(v.support for v in shown),
            truncated=total_labels > len(shown),
        ),
        macro_f1=macro_f1,
        balanced_accuracy=balanced,
        column=column,
        compared=compared,
        correct=correct,
        accuracy=_share(correct, compared),
        wrong=same.disagree([column, reference]),
        values=shown,
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _coverage(con, a: str, b: str, source: str) -> Coverage:
    predicates = {
        "missing_left": f"{sql_ident(a)} IS NULL AND {sql_ident(b)} IS NOT NULL",
        "missing_right": f"{sql_ident(b)} IS NULL AND {sql_ident(a)} IS NOT NULL",
        "missing_both": f"{sql_ident(a)} IS NULL AND {sql_ident(b)} IS NULL",
    }
    counts = sql.execute(
        con, f"SELECT {', '.join(f'count(*) FILTER ({v})' for v in predicates.values())} {source}"
    ).fetchone()
    return Coverage(
        **{key: Rows(rows=n, where=predicates[key]) for key, n in zip(predicates, counts)}
    )


def _numeric(
    con, a: str, b: str, same: _Same, source: str, reference: str | None
) -> NumericSummary | None:
    kinds = [same.types[c] for c in (a, b)]
    days = all(k == "DATE" for k in kinds)
    if not days and not all(k in _NUMBERS or k.startswith("DECIMAL") for k in kinds):
        return None
    left, right = (b, a) if b == reference else (a, b)
    # Subtract in the source type first to retain integer/decimal differences before chart conversion.
    x, y = same._number(right), same._number(left)
    # Reversing unsigned subtraction preserves a negative small difference exactly.
    # Only differences outside the source type's range need floating subtraction.
    delta = f"coalesce(TRY(CAST(({x} - {y}) AS DOUBLE)), -TRY(CAST(({y} - {x}) AS DOUBLE)), CAST({x} AS DOUBLE) - CAST({y} AS DOUBLE))"
    finite = f"isfinite({same._number(a)}) AND isfinite({same._number(b)}) AND isfinite({delta})"
    paired = f"{sql_ident(a)} IS NOT NULL AND {sql_ident(b)} IS NOT NULL"
    n, excluded, low, high = sql.execute(
        con,
        f"SELECT count(*) FILTER ({finite}), count(*) FILTER ({paired} AND NOT coalesce(({finite}), false)), "
        f"min({delta}) FILTER ({finite}), max({delta}) FILTER ({finite}) {source}",
    ).fetchone()
    bias = mae = p95 = maximum = None
    if n:
        maximum = max(abs(low), abs(high))
        scale = maximum or 1
        # Scale before accumulation/interpolation so finite extreme inputs do not overflow.
        scaled = f"({delta} / {scale!r})"
        bias, mae, p95 = sql.execute(
            con,
            f"SELECT avg({scaled}), avg(abs({scaled})), quantile_cont(abs({scaled}), 0.95) {source} WHERE {finite}",
        ).fetchone()
        bias, mae, p95 = [
            v * scale if v is not None and math.isfinite(v * scale) else None
            for v in (bias, mae, p95)
        ]
    bins = []
    if n:
        edges = sorted(
            {
                low,
                high,
                *[low * (1 - i / 12) + high * (i / 12) for i in range(1, 12)],
            }
        )
        edges = [v for v in edges if math.isfinite(v)]
        if len(edges) == 1:
            edges.append(edges[0])
        predicates = [
            f"({finite}) AND {delta} >= {lo!r} AND {delta} {'<=' if i == len(edges) - 2 else '<'} {hi!r}"
            for i, (lo, hi) in enumerate(itertools.pairwise(edges))
        ]
        matching = same.agree([a, b])
        match_predicates = [f"({where}) AND ({matching})" for where in predicates]
        different_predicates = [f"({where}) AND NOT ({matching})" for where in predicates]
        counts = sql.execute(
            con,
            f"SELECT {', '.join(f'count(*) FILTER ({v})' for v in predicates + match_predicates)} {source}",
        ).fetchone()
        bins = [
            HistogramBin(
                lower=lo,
                upper=hi,
                upper_inclusive=i == len(edges) - 2,
                rows=counts[i],
                where=where,
                matched=Rows(rows=counts[i + len(predicates)], where=match_predicates[i]),
                different=Rows(
                    rows=counts[i] - counts[i + len(predicates)], where=different_predicates[i]
                ),
            )
            for i, (lo, hi, where) in enumerate(zip(edges, edges[1:], predicates))
        ]
    matching = same.agree([a, b])
    return NumericSummary(
        matched=Rows(rows=sum(b.matched.rows for b in bins), where=f"({finite}) AND ({matching})"),
        different=Rows(
            rows=sum(b.different.rows for b in bins), where=f"({finite}) AND NOT ({matching})"
        ),
        difference=f"{right} − {left}",
        unit="days" if days else "value",
        finite_pairs=n,
        non_finite_pairs=excluded,
        bias=bias,
        mean_absolute_difference=mae,
        p95_absolute_difference=p95,
        max_absolute_difference=maximum,
        histogram=bins,
    )

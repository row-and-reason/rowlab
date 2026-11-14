"""Comparing columns: how often two or more columns give the same value in each row.

The columns can be anything: several models' answers to one task, a model's answers against labels
someone already has, or two columns of the original data. With a reference column, the comparison also
says how often each other column matches it (its accuracy, if the reference is right). Every count
comes with SQL for its rows (`where`), to add to a query's WHERE clause: to look at them, or to ask
about them again.

Lists count as the same when they hold the same items; with a tolerance, numbers and dates count as the
same when they are no further apart. Empty values never count as a disagreement.

Beyond raw agreement: Cohen's κ for each pair and Krippendorff's α across all the columns correct for
the agreement chance alone would give; rates come with Wilson 95% intervals; a column's `_proba`
column is checked against the reference (calibration); and columns a run wrote come with what they cost.
"""

import itertools
import math
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import datasets, runs, sql, tasks
from rowlab.core.errors import InvalidRequest, NotFound
from rowlab.core.storage import sql_ident, sql_string

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

# z for a two-sided 95% interval.
_Z = 1.959963984540054

# Calibration bins: equal-width over 0 to 1.
_CALIBRATION_BINS = 10


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


class Interval(BaseModel):
    low: float
    high: float


class Agreement(BaseModel):
    all_agree: Rows = Field(description="Every column has a value, and they are all the same.")
    disagree: Rows = Field(description="At least two values differ.")
    partly_answered: int = Field(description="Some columns are empty, and the others agree.")
    not_answered: int = Field(description="Every column is empty.")
    rate: float | None = Field(
        description="Of the rows that agree or disagree, the share that agree."
    )
    rate_ci: Interval | None = Field(description="Wilson 95% interval of the rate.")
    alpha: float | None = Field(
        description="Krippendorff's α across all the columns: 1 is full agreement, 0 what chance "
        "would give. Rows with fewer than two values are left out. Empty when every value is the same."
    )
    alpha_level: Literal["nominal", "ordinal", "interval"] = Field(
        description="How α weighs a difference: interval for numbers and dates (in days, ignoring "
        "the tolerance), ordinal when a column was written by a scale task (by its levels' order), "
        "nominal otherwise."
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
    rate_ci: Interval | None = Field(description="Wilson 95% interval of the rate.")
    kappa: float | None = Field(
        description="Cohen's κ: agreement beyond what chance would give, 1 for full agreement and 0 "
        "for chance. Empty for numbers and dates, and when every value is the same."
    )
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


class CalibrationBin(Rows):
    lower: float
    upper: float = Field(description="Exclusive, except for the last bin, which ends at 1.")
    mean_probability: float
    accuracy: float = Field(description="The share of the bin's rows the column has right.")


class Calibration(BaseModel):
    probability_column: str
    rows: int = Field(
        description="Rows with an answer, a reference and a probability between 0 and 1."
    )
    brier: float | None = Field(
        description="Mean squared difference between the probability and being right (1) or "
        "wrong (0): 0 is perfect."
    )
    ece: float | None = Field(
        description="Expected calibration error: how far the probability is from the accuracy, "
        "averaged over the bins by their rows."
    )
    auroc: float | None = Field(
        description="How well the probability tells right answers from wrong ones: 1 always ranks "
        "right ones higher, 0.5 is chance. Empty when every answer is right, or every one wrong."
    )
    bins: list[CalibrationBin] = Field(
        description="Ten equal-width bins of the probability; empty bins are left out."
    )


class ReferenceAccuracy(BaseModel):
    labels_completeness: Completeness
    macro_f1: float | None
    balanced_accuracy: float | None
    column: str
    compared: int = Field(description="Rows where both the column and the reference have a value.")
    correct: int
    accuracy: float | None
    accuracy_ci: Interval | None = Field(description="Wilson 95% interval of the accuracy.")
    calibration: Calibration | None = Field(
        description="With a `{column}_proba` column: how well the model's probability that its "
        "answer is right matches how often it is."
    )
    usd_per_correct: float | None = Field(
        description="For a column a run wrote: its USD per answered row, divided by the accuracy."
    )
    wrong: str = Field(
        description="SQL picking the rows where the column differs from the reference."
    )
    values: list[ValueAccuracy] = Field(
        description="Up to 20 reference labels with lowest recall; aggregate metrics use all labels. Empty with a tolerance."
    )


class ColumnCost(BaseModel):
    column: str
    run_id: str
    task_id: str
    model: str
    usd: float = Field(
        description="What the run spent on this task and model, for all its rows; cached answers are "
        "free. Columns of one task and model share it."
    )
    answered: int = Field(description="The run's rows with an answer from the model.")
    usd_per_1k_rows: float | None = Field(
        description="USD per 1,000 answered rows. Answered rows include cached ones, which cost "
        "nothing, so this can look cheaper than a fresh run would be."
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
    costs: list[ColumnCost] = Field(
        description="For each column a model wrote in a run, what it cost. Uploaded and manual "
        "columns have none."
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
                        rate_ci=_wilson(agree, compared),
                        kappa=_kappa(con, a, b, same, source),
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

        sources = _column_sources(dataset_id)
        costs = [cost for c in columns if c in sources and (cost := _cost(c, *sources[c]))]
        alpha, alpha_level = _alpha(con, columns, same, source, sources)

        reference = None
        if request.reference:
            spend = {c.column: c for c in costs}
            reference = [
                _accuracy(con, column, request.reference, same, source, spend.get(column))
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
            rate_ci=_wilson(all_agree, all_agree + disagree),
            alpha=alpha,
            alpha_level=alpha_level,
        ),
        pairs=pairs,
        values=values,
        crosstab=crosstab,
        reference=reference,
        costs=costs,
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
        return self.normalize(value) if self.types[column] == "VARCHAR" else value

    def normalize(self, value: str) -> str:
        """A text expression as the matching rules see it: trimmed and lowercased if asked."""
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
        values = ", ".join(self.number(c) for c in columns)
        return f"{function}_within([{values}], {float(self.tolerance)})"

    def _exact(self, columns: list[str]) -> list[str]:
        kinds = {self.types[c] for c in columns}
        # Columns of one type compare as they are, lists by their items; others as text.
        if len(kinds) == 1 and not kinds.pop().endswith("[]"):
            return [self.text(c) if self.types[c] == "VARCHAR" else sql_ident(c) for c in columns]
        return [self.text(c) for c in columns]

    def number(self, column: str) -> str:
        sql_type = self.types[column]
        if sql_type == "DATE":
            return f"date_diff('day', DATE '1970-01-01', {sql_ident(column)})"
        if _is_number(sql_type):
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
    cost: ColumnCost | None,
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
        accuracy_ci=_wilson(correct, compared),
        calibration=_calibration(con, column, reference, same, source),
        # The cost of an answer, over the share of answers that are right.
        usd_per_correct=cost.usd * compared / (cost.answered * correct)
        if cost and cost.answered and correct
        else None,
        wrong=same.disagree([column, reference]),
        values=shown,
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _wilson(part: int, whole: int) -> Interval | None:
    """The Wilson score interval of `part / whole`, at 95%."""
    if not whole:
        return None
    p = part / whole
    z2 = _Z * _Z / whole
    center = (p + z2 / 2) / (1 + z2)
    half = _Z / (1 + z2) * math.sqrt(p * (1 - p) / whole + z2 / (4 * whole))
    return Interval(low=max(0.0, center - half), high=min(1.0, center + half))


def _is_number(sql_type: str) -> bool:
    return sql_type in _NUMBERS or sql_type.startswith("DECIMAL")


def _is_number_or_date(sql_type: str) -> bool:
    return _is_number(sql_type) or sql_type == "DATE"


def _kappa(con, a: str, b: str, same: _Same, source: str) -> float | None:
    """Cohen's κ over the rows where both columns have a value; numbers and dates have none."""
    if all(_is_number_or_date(same.types[c]) for c in (a, b)):
        return None
    x, y = same.text(a), same.text(b)
    cells = sql.execute(
        con,
        f"SELECT {x}, {y}, count(*) {source} WHERE {x} IS NOT NULL AND {y} IS NOT NULL GROUP BY 1, 2",
    ).fetchall()
    n = sum(count for _, _, count in cells)
    left: dict[str, int] = {}
    right: dict[str, int] = {}
    for va, vb, count in cells:
        left[va] = left.get(va, 0) + count
        right[vb] = right.get(vb, 0) + count
    observed = sum(count for va, vb, count in cells if va == vb) / n if n else 0
    expected = sum(left[v] * right.get(v, 0) for v in left) / (n * n) if n else 1
    return (observed - expected) / (1 - expected) if expected < 1 else None


def _alpha(
    con, columns: list[str], same: _Same, source: str, sources: dict[str, tuple]
) -> tuple[float | None, Literal["nominal", "ordinal", "interval"]]:
    """Krippendorff's α across the columns, over the rows with two or more values."""
    kinds = [same.types[c] for c in columns]
    if all(_is_number(k) for k in kinds) or all(k == "DATE" for k in kinds):
        # Interval: the squared differences of every ordered pair of m values add up to
        # 2·m·Σ(v − mean)², within a row (observed) and across all values (expected). Taken around
        # the mean, so large values (epoch seconds) don't cancel out.
        values = ", ".join(f"CAST({same.number(c)} AS DOUBLE)" for c in columns)
        observed, n, expected = sql.execute(
            con,
            "WITH units AS (SELECT v, len(v) m, list_avg(v) a"
            f" FROM (SELECT list_filter([{values}], lambda x: isfinite(x)) v {source})"
            " WHERE len(v) >= 2),"
            " overall AS (SELECT sum(m * a) / sum(m) mean FROM units)"
            " SELECT sum(2 * m * list_sum(list_transform(v, lambda x: (x - a) ** 2)) / (m - 1)),"
            " sum(m), 2 * sum(m) * sum(list_sum(list_transform(v, lambda x: (x - mean) ** 2)))"
            " FROM units, overall",
        ).fetchone()
        alpha = 1 - (n - 1) * observed / expected if expected else None
        return alpha, "interval"

    values = ", ".join(same.text(c) for c in columns)
    units = sql.execute(
        con,
        f"SELECT list_sort(v), count(*) FROM (SELECT list_filter([{values}], lambda x: x IS NOT NULL) v"
        f" {source}) WHERE len(v) >= 2 GROUP BY 1",
    ).fetchall()
    counts: dict[str, int] = {}
    for unit, weight in units:
        for value in unit:
            counts[value] = counts.get(value, 0) + weight
    n = sum(counts.values())

    level: Literal["nominal", "ordinal"] = "nominal"
    rank = {}
    for column in columns:
        task = sources[column][1] if column in sources else None
        if task and task.type == "scale":
            levels = ", ".join(same.normalize(sql_string(o.name)) for o in task.options)
            names = sql.execute(con, f"SELECT [{levels}]").fetchone()[0]
            rank = {name: i for i, name in enumerate(names)}
            if all(value in rank for value in counts):
                level = "ordinal"
            break

    if level == "ordinal":
        # The values seen between two levels, both counted half: Krippendorff's ordinal distance.
        ordered = sorted(counts, key=rank.__getitem__)
        position = {value: i for i, value in enumerate(ordered)}
        before = list(itertools.accumulate([0] + [counts[v] for v in ordered]))

        def distance(c: str, k: str) -> float:
            i, j = sorted((position[c], position[k]))
            return (before[j + 1] - before[i] - (counts[c] + counts[k]) / 2) ** 2

        expected = sum(counts[c] * counts[k] * distance(c, k) for c in counts for k in counts)
    else:

        def distance(c: str, k: str) -> float:
            return float(c != k)

        expected = n * n - sum(count * count for count in counts.values())

    observed = sum(
        weight / (len(unit) - 1) * sum(distance(c, k) for c in unit for k in unit)
        for unit, weight in units
    )
    alpha = 1 - (n - 1) * observed / expected if expected > 0 else None
    return alpha, level


def _calibration(con, column: str, reference: str, same: _Same, source: str) -> Calibration | None:
    """How well `{column}_proba`, the model's probability that its answer is right, matches how
    often the answer matches the reference."""
    proba = f"{column}_proba"
    if proba not in same.types or not _is_number(same.types[proba]):
        return None
    p = sql_ident(proba)
    paired = (
        f"{sql_ident(column)} IS NOT NULL AND {sql_ident(reference)} IS NOT NULL"
        f" AND {p} BETWEEN 0 AND 1"
    )
    right = f"({same.agree([column, reference])})::INT"
    edges = [i / _CALIBRATION_BINS for i in range(_CALIBRATION_BINS + 1)]
    predicates = [
        f"{paired} AND {p} >= {lo!r} AND {p} {'<=' if hi == 1 else '<'} {hi!r}"
        for lo, hi in itertools.pairwise(edges)
    ]
    aggregates = [
        f"count(*) FILTER ({w}), avg({p}) FILTER ({w}), avg({right}) FILTER ({w})"
        for w in predicates
    ]
    found = sql.execute(con, f"SELECT {', '.join(aggregates)} {source}").fetchone()
    rows, brier, positives, ranks = sql.execute(
        con,
        f"SELECT count(*), avg(({p} - y) ** 2), sum(y), sum(r) FILTER (y = 1) FROM ("
        f" SELECT {p}, {right} y, rank() OVER (ORDER BY {p})"
        f" + (count(*) OVER (PARTITION BY {p}) - 1) / 2 r {source} WHERE {paired})",
    ).fetchone()
    bins = [
        CalibrationBin(
            lower=lo,
            upper=hi,
            rows=count,
            mean_probability=mean,
            accuracy=accuracy,
            where=where,
        )
        for lo, hi, where, (count, mean, accuracy) in zip(
            edges,
            edges[1:],
            predicates,
            itertools.batched(found, 3),
        )
        if count
    ]
    negatives = rows - (positives or 0)
    auroc = None
    if positives and negatives:
        # Mann–Whitney: the chance a right answer's probability is above a wrong one's.
        auroc = (ranks - positives * (positives + 1) / 2) / (positives * negatives)
    return Calibration(
        probability_column=proba,
        rows=rows,
        brier=brier,
        ece=sum(b.rows * abs(b.mean_probability - b.accuracy) for b in bins) / rows
        if rows
        else None,
        auroc=auroc,
        bins=bins,
    )


def _column_sources(dataset_id: str) -> dict[str, tuple[runs.Run, tasks.Task, str]]:
    """The run, task and model that wrote each column of a dataset, from its own run and its
    ancestors' (a made dataset keeps the columns of the one it was made from)."""
    sources: dict[str, tuple[runs.Run, tasks.Task, str]] = {}
    next_id: str | None = dataset_id
    while next_id:
        try:
            dataset = datasets.get_dataset(next_id)
            run = dataset.run and runs.get_run(dataset.run.id)
        except NotFound:
            break  # An ancestor was deleted; the datasets made from it stay.
        if run:
            for task in run.config.tasks:
                for model in task.models:
                    for _, column, _ in tasks._column_map(task, model):
                        # The nearest run wins.
                        sources.setdefault(column, (run, task, model))
        next_id = dataset.parent_id
    return sources


def _cost(column: str, run: runs.Run, task: tasks.Task, model: str) -> ColumnCost | None:
    """What a run spent on a column's task and model, once it has done a chunk of rows."""
    spent = next((c for c in run.costs if c.task_id == task.id and c.model == model), None)
    if spent is None:
        return None
    answered = min(run.next_chunk * runs.CHUNK_ROWS, run.row_count) - spent.failed
    return ColumnCost(
        column=column,
        run_id=run.id,
        task_id=task.id,
        model=model,
        usd=spent.cost,
        answered=answered,
        usd_per_1k_rows=spent.cost * 1000 / answered if answered else None,
    )


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
    if not days and not all(_is_number(k) for k in kinds):
        return None
    left, right = (b, a) if b == reference else (a, b)
    # Subtract in the source type first to retain integer/decimal differences before chart conversion.
    x, y = same.number(right), same.number(left)
    # Reversing unsigned subtraction preserves a negative small difference exactly.
    # Only differences outside the source type's range need floating subtraction.
    delta = f"coalesce(TRY(CAST(({x} - {y}) AS DOUBLE)), -TRY(CAST(({y} - {x}) AS DOUBLE)), CAST({x} AS DOUBLE) - CAST({y} AS DOUBLE))"
    finite = f"isfinite({same.number(a)}) AND isfinite({same.number(b)}) AND isfinite({delta})"
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


def compact_comparison(result: Comparison) -> dict[str, Any]:
    """Agent summary: retain metrics and per-class scores; omit repeated drill-down details."""
    data = result.model_dump()
    data.pop("values")
    data.pop("values_completeness")
    data.pop("crosstab", None)
    data.pop("crosstab_completeness", None)
    for accuracy in data["reference"] or []:
        if accuracy["calibration"] is not None:
            for bucket in accuracy["calibration"]["bins"]:
                bucket.pop("where")
    for pair in data["pairs"]:
        pair["coverage"] = {key: value["rows"] for key, value in pair["coverage"].items()}
        if pair["numeric"] is not None:
            pair["numeric"].pop("histogram")
    return data

"""Comparing columns: agreement across any number of columns, pairs, values, and a reference."""

import pytest
from helpers import NEGATIVE, run

# Three "models" and a known answer for six rows. Row 5 has an empty answer.
CSV = """city,a,b,c,truth,price_a,price_b
Paris,Europe,Europe,Europe,Europe,10.0,10.4
Tokyo,Asia,Asia,Europe,Asia,5.0,5.0
Lima,Americas,Europe,Americas,Americas,3.0,9.0
Oslo,Europe,Europe,Europe,Europe,1.0,1.2
Cairo,Africa,Africa,Africa,Asia,2.0,2.0
Quito,Americas,,Americas,Americas,,
"""


@pytest.fixture
def dataset(client, tmp_path):
    path = tmp_path / "cities.csv"
    path.write_text(CSV)
    return client.post("/v1/datasets", data={"source": str(path)}).json()


def compare(client, dataset, **body):
    response = client.post(f"/v1/datasets/{dataset['id']}/compare", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def rows(client, dataset, where):
    body = {"sql": f"SELECT * FROM data WHERE {where}"}
    response = client.post(f"/v1/datasets/{dataset['id']}/query", json=body)
    assert response.status_code == 200, response.text
    return [r["city"] for r in response.json()["rows"]]


def test_agreement_across_three_columns_with_sql_for_each_count(client, dataset):
    result = compare(client, dataset, columns=["a", "b", "c"])
    agreement = result["agreement"]
    assert agreement["all_agree"]["rows"] == 3  # Paris, Oslo, Cairo
    assert agreement["disagree"]["rows"] == 2  # Tokyo, Lima
    # Quito: b is empty, a and c agree. Not a disagreement.
    assert (agreement["partly_answered"], agreement["not_answered"]) == (1, 0)
    assert agreement["rate"] == pytest.approx(3 / 5)
    assert rows(client, dataset, agreement["disagree"]["where"]) == ["Tokyo", "Lima"]
    assert rows(client, dataset, agreement["all_agree"]["where"]) == ["Paris", "Oslo", "Cairo"]

    pairs = {tuple(p["columns"]): (p["compared"], p["agree"]) for p in result["pairs"]}
    assert pairs == {("a", "b"): (5, 4), ("a", "c"): (6, 5), ("b", "c"): (5, 3)}
    europe = next(v for v in result["values"] if v["value"] == "Europe")
    assert europe["counts"] == {"a": 2, "b": 3, "c": 3}
    # Only two columns get a crosstab.
    assert result["crosstab"] is None


def test_two_columns_get_a_crosstab_whose_cells_filter_to_their_rows(client, dataset):
    result = compare(client, dataset, columns=["a", "c"])
    cells = {tuple(c["values"]): c for c in result["crosstab"]}
    assert cells[("Asia", "Europe")]["rows"] == 1
    assert rows(client, dataset, cells[("Asia", "Europe")]["where"]) == ["Tokyo"]


def test_a_reference_gives_accuracy_and_the_wrong_rows(client, dataset):
    result = compare(client, dataset, columns=["a", "b"], reference="truth")
    accuracy = {r["column"]: r for r in result["reference"]}
    assert (accuracy["a"]["compared"], accuracy["a"]["correct"]) == (6, 5)
    assert rows(client, dataset, accuracy["a"]["wrong"]) == ["Cairo"]
    asia = next(v for v in accuracy["b"]["values"] if v["value"] == "Asia")
    # The truth says Asia twice (Tokyo, Cairo); b says Asia once, rightly.
    assert (asia["support"], asia["predicted"], asia["correct"]) == (2, 1, 1)
    assert (asia["precision"], asia["recall"]) == (1.0, 0.5)


def test_numbers_compare_within_a_tolerance(client, dataset):
    exact = compare(client, dataset, columns=["price_a", "price_b"])
    assert exact["agreement"]["all_agree"]["rows"] == 2  # Tokyo, Cairo
    close = compare(client, dataset, columns=["price_a", "price_b"], tolerance=0.5)
    assert close["agreement"]["all_agree"]["rows"] == 4  # and Paris, Oslo
    assert rows(client, dataset, close["agreement"]["disagree"]["where"]) == ["Lima"]


def test_lists_compare_by_their_items(client, tmp_path):
    path = tmp_path / "tags.jsonl"
    path.write_text(
        '{"a": ["x", "y"], "b": ["y", "x"]}\n{"a": ["x"], "b": ["z"]}\n{"a": [], "b": []}\n'
    )
    tags = client.post("/v1/datasets", data={"source": str(path)}).json()
    result = compare(client, tags, columns=["a", "b"])
    # ["x", "y"] and ["y", "x"] hold the same items.
    assert (result["agreement"]["all_agree"]["rows"], result["agreement"]["disagree"]["rows"]) == (
        2,
        1,
    )


def test_compare_explains_what_it_cant_do(client, dataset):
    def problem(**body):
        response = client.post(f"/v1/datasets/{dataset['id']}/compare", json=body)
        assert response.status_code == 400
        return response.json()["detail"]

    assert problem(columns=["a"]) == "Compare two or more columns."
    assert problem(columns=["a", "nope"]) == "Unknown column: nope"
    assert problem(columns=["a", "a"]) == "Compare different columns."
    assert problem(columns=["a", "b"], tolerance=1) == (
        "A tolerance is only for number and date columns."
    )


def test_agree_and_disagree_are_sql_functions(client, dataset):
    where = "disagree([a, b, c]) AND city = 'Lima'"
    assert rows(client, dataset, where) == ["Lima"]
    assert rows(client, dataset, "agree([a, c]) AND NOT agree([a, b])") == ["Lima", "Quito"]
    assert rows(client, dataset, "disagree_within([price_a, price_b], 0.5)") == ["Lima"]


def test_compares_the_rows_a_query_returns(client, dataset):
    result = compare(
        client, dataset, columns=["a", "b"], sql="SELECT * FROM data WHERE city <> 'Lima'"
    )
    assert (result["rows"], result["agreement"]["disagree"]["rows"]) == (5, 0)


def test_text_rules_reconcile_metrics_groups_and_predicates(client, tmp_path):
    path = tmp_path / "text.jsonl"
    path.write_text(
        '{"city":"a","a":" Bug ","b":"bug"}\n{"city":"b","a":"BUG","b":"bug"}\n{"city":"c","a":"\\tBug\\n","b":"Bug"}\n{"city":"d","a":"   ","b":""}\n{"city":"e","a":null,"b":"bug"}'
    )
    dataset = client.post("/v1/datasets", data={"source": str(path)}).json()
    exact = compare(client, dataset, columns=["a"], reference="b")
    assert exact["pairs"][0]["agree"] == 0
    case = compare(client, dataset, columns=["a"], reference="b", ignore_case=True)
    assert case["pairs"][0]["agree"] == 1
    normalized = compare(
        client, dataset, columns=["a"], reference="b", ignore_case=True, trim_whitespace=True
    )
    assert normalized["pairs"][0]["agree"] == 4
    assert normalized["reference"][0]["accuracy"] == 1
    assert normalized["reference"][0]["macro_f1"] == 1
    for cell in normalized["crosstab"]:
        assert len(rows(client, dataset, cell["where"])) == cell["rows"]
    assert normalized["pairs"][0]["coverage"]["missing_left"]["rows"] == 1
    bug = next(v for v in normalized["values"] if v["value"] == "bug")
    assert bug["counts"] == {"a": 3, "b": 4}
    for value in normalized["values"]:
        for column in ("a", "b"):
            assert len(rows(client, dataset, value["where"][column])) == value["counts"][column]


def test_numeric_diagnostics_and_histogram_are_exact_drilldowns(client, dataset):
    result = compare(client, dataset, columns=["price_a"], reference="price_b", tolerance=0.5)
    numeric = result["pairs"][0]["numeric"]
    assert numeric["difference"] == "price_a − price_b"
    assert numeric["finite_pairs"] == 5
    assert numeric["bias"] == pytest.approx(-1.32)
    assert numeric["mean_absolute_difference"] == pytest.approx(1.32)
    assert sum(b["rows"] for b in numeric["histogram"]) == 5
    found = []
    for bucket in numeric["histogram"]:
        members = rows(client, dataset, bucket["where"])
        assert len(members) == bucket["rows"]
        found.extend(members)
    assert len(set(found)) == len(found) == 5
    scoped = compare(
        client, dataset, columns=["price_a", "price_b"], sql="SELECT * FROM data WHERE city='Tokyo'"
    )
    assert scoped["pairs"][0]["numeric"]["histogram"][0]["rows"] == 1


def test_tolerance_boundary_and_validation(client, dataset):
    invalid = client.post(
        f"/v1/datasets/{dataset['id']}/compare",
        json={"columns": ["price_a", "price_b"], "tolerance": -1},
    )
    assert invalid.status_code == 422
    invalid = client.post(
        f"/v1/datasets/{dataset['id']}/compare",
        json={"columns": ["price_a", "price_b"], "ignore_case": True},
    )
    assert invalid.status_code == 400
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        tolerance=0.1,
        sql="SELECT city, 0.3::DOUBLE a, 0.4::DOUBLE b FROM data",
    )
    assert result["pairs"][0]["agree"] == 6
    outside = compare(
        client,
        dataset,
        columns=["a", "b"],
        tolerance=0.1,
        sql="SELECT city, 0.3::DOUBLE a, 0.40000001::DOUBLE b FROM data",
    )
    assert outside["pairs"][0]["agree"] == 0
    exact = compare(
        client,
        dataset,
        columns=["a", "b"],
        tolerance=0,
        sql="SELECT city, 0.3::DOUBLE a, 0.30000000000000004::DOUBLE b FROM data",
    )
    assert exact["pairs"][0]["agree"] == 0


def test_complete_label_metrics_despite_display_limit(client, dataset):
    result = compare(
        client,
        dataset,
        columns=["a"],
        reference="b",
        sql="SELECT i::VARCHAR a, i::VARCHAR b FROM range(30) t(i)",
    )
    reference = result["reference"][0]
    assert reference["macro_f1"] == reference["balanced_accuracy"] == 1
    assert reference["labels_completeness"] == {
        "total_groups": 30,
        "shown_groups": 20,
        "omitted_count": 10,
        "count_unit": "rows",
        "truncated": True,
    }
    assert result["values_completeness"]["truncated"]
    assert result["crosstab_completeness"]["total_groups"] == 30


def test_numeric_empty_nonfinite_large_integer_and_dates(client, dataset):
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        sql="SELECT 9007199254740992::BIGINT a, 9007199254740993::BIGINT b",
    )
    assert result["pairs"][0]["numeric"]["bias"] == 1
    result = compare(
        client, dataset, columns=["a", "b"], sql="SELECT NULL::DOUBLE a, NULL::DOUBLE b"
    )
    assert result["pairs"][0]["numeric"]["histogram"] == []
    assert result["pairs"][0]["numeric"]["bias"] is None
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        sql="SELECT 'Infinity'::DOUBLE a, 1::DOUBLE b",
        tolerance=0.1,
    )
    assert result["pairs"][0]["numeric"]["non_finite_pairs"] == 1
    assert result["pairs"][0]["agree"] == 0
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        tolerance=1,
        sql="SELECT DATE '2026-01-01' a, DATE '2026-01-02' b",
    )
    assert result["pairs"][0]["numeric"]["unit"] == "days"
    assert result["pairs"][0]["agree"] == 1
    response = client.post(
        f"/v1/datasets/{dataset['id']}/compare",
        json={"columns": ["a", "b"], "tolerance": 1, "sql": "SELECT DATE '2026-01-01' a, 1 b"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("code", [9, 10, 11, 12, 13, 32, 160])
def test_ascii_trim_contract(client, dataset, code):
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        trim_whitespace=True,
        sql=f"SELECT chr({code}) || 'bug' || chr({code}) a, 'bug' b",
    )
    assert result["pairs"][0]["agree"] == (0 if code == 160 else 1)


def test_histogram_extremes_and_tolerance_classification(client, dataset):
    for query, tolerance in [
        (
            "SELECT * FROM (VALUES (0::DOUBLE,-1e308::DOUBLE),(0::DOUBLE,1e308::DOUBLE)) t(a,b)",
            None,
        ),
        (
            "SELECT * FROM (VALUES (0.3::DOUBLE,0.4::DOUBLE),(0.3::DOUBLE,0.40001::DOUBLE),(0.4::DOUBLE,0.3::DOUBLE)) t(a,b)",
            0.1,
        ),
    ]:
        result = compare(client, dataset, columns=["a", "b"], sql=query, tolerance=tolerance)
        pair = result["pairs"][0]
        numeric = pair["numeric"]
        bins = numeric["histogram"]
        assert sum(b["rows"] for b in bins) == numeric["finite_pairs"]
        assert sum(b["matched"]["rows"] for b in bins) == pair["agree"]
        for b in bins:
            for subset in [b, b["matched"], b["different"]]:
                q = f"SELECT count(*) n FROM ({query}) WHERE {subset['where']}"
                count = client.post(f"/v1/datasets/{dataset['id']}/query", json={"sql": q}).json()[
                    "rows"
                ][0]["n"]
                assert count == subset["rows"]
        if tolerance is None:
            assert numeric["bias"] == 0
            assert numeric["mean_absolute_difference"] == 1e308


def test_unsigned_differences_keep_their_sign_and_precision(client, dataset):
    result = compare(
        client,
        dataset,
        columns=["a", "b"],
        tolerance=1,
        sql="SELECT 9007199254740993::UBIGINT a, 9007199254740992::UBIGINT b",
    )
    assert result["pairs"][0]["numeric"]["bias"] == -1
    assert result["pairs"][0]["agree"] == 1


@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN", "1e400"])
def test_nonfinite_json_tolerance_returns_validation_error(client, dataset, literal):
    response = client.post(
        f"/v1/datasets/{dataset['id']}/compare",
        content='{"columns":["price_a","price_b"],"tolerance":' + literal + "}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "tolerance"]
    assert error["type"] == "finite_number"
    assert "input" not in error


def values_sql(columns, rows):
    """A SELECT of literal rows, e.g. `values_sql("a, b", ["(1, 2)", "(3, NULL)"])`."""
    return f"SELECT * FROM (VALUES {', '.join(rows)}) t({columns})"


def test_kappa_corrects_a_pairs_agreement_for_chance(client, dataset):
    # Both yes 20, yes/no 5, no/yes 10, both no 15: agreement 0.7, by chance 0.5.
    cells = [("yes", "yes", 20), ("yes", "no", 5), ("no", "yes", 10), ("no", "no", 15)]
    query = " UNION ALL ".join(f"SELECT '{a}' a, '{b}' b FROM range({n})" for a, b, n in cells)
    pair = compare(client, dataset, columns=["a", "b"], sql=query)["pairs"][0]
    assert pair["rate"] == pytest.approx(0.7)
    assert pair["kappa"] == pytest.approx(0.4, abs=1e-3)


# Krippendorff's worked example: four coders, twelve units, values missing.
KRIPPENDORFF_ROWS = [
    "(1, 1, NULL, 1)",
    "(2, 2, 3, 2)",
    "(3, 3, 3, 3)",
    "(3, 3, 3, 3)",
    "(2, 2, 2, 2)",
    "(1, 2, 3, 4)",
    "(4, 4, 4, 4)",
    "(1, 1, 2, 1)",
    "(2, 2, 2, 2)",
    "(NULL, 5, 5, 5)",
    "(NULL, NULL, 1, 1)",
    "(NULL, 3, NULL, NULL)",
]
KRIPPENDORFF = values_sql("a, b, c, d", KRIPPENDORFF_ROWS)


def test_alpha_is_krippendorffs_across_all_columns(client, dataset):
    columns = ["a", "b", "c", "d"]
    as_text = KRIPPENDORFF.replace(
        "SELECT *", "SELECT a::VARCHAR a, b::VARCHAR b, c::VARCHAR c, d::VARCHAR d"
    )
    nominal = compare(client, dataset, columns=columns, sql=as_text)["agreement"]
    assert nominal["alpha_level"] == "nominal"
    assert nominal["alpha"] == pytest.approx(0.743, abs=1e-3)
    interval = compare(client, dataset, columns=columns, sql=KRIPPENDORFF)["agreement"]
    assert interval["alpha_level"] == "interval"
    assert interval["alpha"] == pytest.approx(0.849, abs=1e-3)


def test_alpha_is_ordinal_for_a_scale_tasks_levels(client, tmp_path, api_key):
    # Krippendorff's example again, with coder d a model asked a scale task: it answers the level
    # in its prompt. Unit 12, with one value, isn't asked.
    path = tmp_path / "coders.csv"
    lines = ["a,b,c,d"]
    for row in KRIPPENDORFF_ROWS:
        lines.append(row.strip("()").replace("NULL", "").replace(" ", ""))
    path.write_text("\n".join(lines) + "\n")
    source = client.post("/v1/datasets", data={"source": str(path)}).json()
    scale = {
        "template": "{{d}}",
        "type": "scale",
        "column": "level",
        "options": [{"name": str(i)} for i in range(1, 6)],
        "models": ["x/llm"],
    }
    job = {
        "dataset_id": source["id"],
        "sql": "SELECT * FROM data WHERE d IS NOT NULL",
        "tasks": [scale],
    }
    made = run(client, job)
    result = compare(client, {"id": made["dataset_id"]}, columns=["a", "b", "c", "level__llm"])
    assert result["agreement"]["alpha_level"] == "ordinal"
    assert result["agreement"]["alpha"] == pytest.approx(0.815, abs=1e-3)


def test_interval_alpha_holds_for_large_values(client, dataset):
    rows = ["(0, 0)", "(60, 60)", "(120, 130)", "(180, 170)", "(240, 260)"]
    small = compare(client, dataset, columns=["a", "b"], sql=values_sql("a, b", rows))
    for offset in (1_700_000_000, 1e12):
        query = f"SELECT a::DOUBLE + {offset} a, b::DOUBLE + {offset} b FROM ({values_sql('a, b', rows)})"
        large = compare(client, dataset, columns=["a", "b"], sql=query)
        assert large["agreement"]["alpha"] == pytest.approx(small["agreement"]["alpha"], abs=1e-3)


def test_dates_and_numbers_together_are_nominal(client, dataset):
    query = "SELECT DATE '2026-01-01' + i::INT a, i b, i::VARCHAR c FROM range(3) t(i)"
    result = compare(client, dataset, columns=["a", "b"], sql=query)
    assert result["agreement"]["alpha_level"] == "nominal"
    # A number paired with text has a κ: the values are labels.
    assert compare(client, dataset, columns=["b", "c"], sql=query)["pairs"][0]["kappa"] == 1


def test_rates_come_with_wilson_intervals(client, dataset):
    query = "SELECT 'x' a, CASE WHEN i < 8 THEN 'x' ELSE 'y' END b FROM range(10) t(i)"
    result = compare(client, dataset, columns=["a"], reference="b", sql=query)
    for interval in (
        result["agreement"]["rate_ci"],
        result["pairs"][0]["rate_ci"],
        result["reference"][0]["accuracy_ci"],
    ):
        assert interval["low"] == pytest.approx(0.490, abs=1e-3)
        assert interval["high"] == pytest.approx(0.943, abs=1e-3)


def test_calibration_checks_the_probability_against_the_reference(client, dataset):
    # Right answers are sure (0.9), wrong ones unsure (0.3): ranked perfectly. Of the 0.9s 3 of 4
    # are right, of the 0.3s none: ECE = (4·|0.9 − 0.75| + 2·|0.3 − 0|) / 6.
    query = values_sql(
        "city, answer, answer_proba, truth",
        [
            "('a', 'x', 0.9, 'x')",
            "('b', 'x', 0.9, 'x')",
            "('c', 'x', 0.9, 'x')",
            "('d', 'y', 0.9, 'x')",
            "('e', 'y', 0.3, 'x')",
            "('f', 'y', 0.3, 'x')",
        ],
    )
    calibration = compare(client, dataset, columns=["answer"], reference="truth", sql=query)[
        "reference"
    ][0]["calibration"]
    assert calibration["rows"] == 6
    assert calibration["ece"] == pytest.approx((4 * 0.15 + 2 * 0.3) / 6, abs=1e-3)
    assert calibration["brier"] == pytest.approx((3 * 0.01 + 0.81 + 2 * 0.09) / 6, abs=1e-3)
    # 9 right-wrong pairs: 6 ranked right, 3 tied at 0.9 counting half.
    assert calibration["auroc"] == pytest.approx(7.5 / 9, abs=1e-3)
    separated = query.replace("('d', 'y', 0.9, 'x')", "('d', 'y', 0.2, 'x')")
    result = compare(client, dataset, columns=["answer"], reference="truth", sql=separated)
    calibration = result["reference"][0]["calibration"]
    assert calibration["auroc"] == pytest.approx(1)
    for bucket in calibration["bins"]:
        q = f"SELECT count(*) n FROM ({separated}) WHERE {bucket['where']}"
        found = client.post(f"/v1/datasets/{dataset['id']}/query", json={"sql": q}).json()
        assert found["rows"][0]["n"] == bucket["rows"]


def test_a_runs_columns_come_with_their_cost(client, tmp_path, api_key):
    path = tmp_path / "reviews.csv"
    path.write_text("review,truth\nTerrible product,true\nLove it,true\nBroke after a day,true\n")
    source = client.post("/v1/datasets", data={"source": str(path)}).json()
    job = {"dataset_id": source["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    made = run(client, job)
    result = compare(client, {"id": made["dataset_id"]}, columns=made["columns"], reference="truth")
    assert [(c["column"], c["run_id"]) for c in result["costs"]] == [
        ("negative__jev-1.14", made["id"])
    ]
    cost = result["costs"][0]
    assert cost["usd"] == pytest.approx(made["cost"])
    assert cost["usd_per_1k_rows"] == pytest.approx(made["cost"] * 1000 / 3)
    accuracy = result["reference"][0]
    assert accuracy["correct"] == 2
    assert accuracy["usd_per_correct"] == pytest.approx(made["cost"] / 2)
    assert accuracy["calibration"]["rows"] == 3

    # A column the lab uploaded, and a column labelled by hand in a run made from this one, cost nothing.
    manual = client.post(
        f"/v1/datasets/{made['dataset_id']}/runs",
        json={"method": "manual", "tasks": [{"template": "{{review}}", "column": "label"}]},
    ).json()
    result = compare(
        client,
        {"id": manual["dataset_id"]},
        columns=["label", "negative__jev-1.14"],
        reference="truth",
    )
    assert [c["column"] for c in result["costs"]] == ["negative__jev-1.14"]
    assert result["reference"][0]["usd_per_correct"] is None


def test_compare_works_after_the_source_dataset_is_deleted(client, tmp_path, api_key):
    path = tmp_path / "reviews.csv"
    path.write_text("review,truth\nTerrible product,true\nLove it,false\n")
    source = client.post("/v1/datasets", data={"source": str(path)}).json()
    made = run(
        client, {"dataset_id": source["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    )
    assert client.delete(f"/v1/datasets/{source['id']}").status_code == 204
    result = compare(client, {"id": made["dataset_id"]}, columns=made["columns"], reference="truth")
    assert result["reference"][0]["accuracy"] == 1
    assert [c["column"] for c in result["costs"]] == made["columns"]

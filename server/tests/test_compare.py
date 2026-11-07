"""Comparing columns: agreement across any number of columns, pairs, values, and a reference."""

import pytest

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

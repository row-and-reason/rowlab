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

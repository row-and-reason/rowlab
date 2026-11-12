"""Usage: what runs asked and paid for, and how much the organisation stores."""

import pytest
from helpers import NEGATIVE, run, start

from rowlab.core import db, runs

pytestmark = pytest.mark.usefixtures("fake")


@pytest.fixture
def job(client):
    files = {"file": ("reviews.csv", b"review\nTerrible product\nLove it\nBroke after a day\n")}
    dataset = client.post("/v1/datasets", files=files).json()
    return {"dataset_id": dataset["id"], "sql": "SELECT * FROM data", "tasks": [NEGATIVE]}


def test_usage_adds_up_what_runs_asked(client, job, api_key, fake):
    run(client, job)
    run(client, job)
    used = client.get("/v1/settings/usage").json()
    assert used["scope"] == "organisation"
    # Two runs of the same three rows: the second is answered from the cache, for free.
    assert used["total"]["answers"] == 6
    assert used["total"]["cached"] == 3
    assert used["total"]["cost"] == pytest.approx(0.003)
    assert used["total"]["input_tokens"] == 300
    assert [m["model"] for m in used["by_model"]] == ["typesafe/jev-1.14"]
    assert len(used["by_day"]) == 1
    assert used["by_person"] == [
        {**used["total"], "user": None},
    ]
    assert used["storage_bytes"] > 0
    with db.connect() as conn:
        assert {r["paid_by"] for r in conn.execute("SELECT paid_by FROM usage").fetchall()} == {
            "organisation"
        }


def test_usage_by_month(client, job, api_key, fake):
    run(client, job)
    assert (
        client.get("/v1/settings/usage", params={"month": "2020-01"}).json()["total"]["answers"]
        == 0
    )
    assert client.get("/v1/settings/usage", params={"month": "2026-13"}).status_code == 400


def test_admins_see_everyones_usage_and_others_their_own(hosted, fake, tmp_path):
    ada = hosted("ada@example.com")
    ada.post("/v1/settings/invites", json={"email": "bob@example.com"})
    bob = hosted("bob@example.com")
    assert ada.put("/v1/settings/openrouter-key", json={"key": "sk-good"}).status_code == 200
    dataset = ada.post(
        "/v1/datasets", files={"file": ("reviews.csv", b"review\nTerrible product\nLove it\n")}
    ).json()
    body = {"sql": "SELECT * FROM data", "tasks": [NEGATIVE]}
    assert bob.post(f"/v1/datasets/{dataset['id']}/runs", json=body).status_code == 201
    while runs.process_next():
        pass

    mine = bob.get("/v1/settings/usage").json()
    assert (mine["scope"], mine["total"]["answers"], mine["by_person"]) == ("you", 2, [])
    assert ada.get("/v1/settings/usage").json()["total"]["answers"] == 2
    [person] = ada.get("/v1/settings/usage").json()["by_person"]
    assert person["user"]["email"] == "bob@example.com"
    # Ada started nothing herself; as an admin she sees the organisation's anyway.
    assert ada.get("/v1/settings/usage").json()["scope"] == "organisation"


# Storage is organisation-wide and current, even when run activity is personal or historical.
def test_storage_is_current_org_scoped_and_shared_by_members(hosted):
    admin = hosted("admin@example.com")
    admin.post("/v1/settings/invites", json={"email": "member@example.com"})
    member = hosted("member@example.com")
    other = hosted("other@example.com")
    dataset = admin.post("/v1/datasets", files={"file": ("data.csv", b"name\nAda\nBob\n")}).json()
    other_dataset = other.post(
        "/v1/datasets", files={"file": ("other.csv", b"name\nSomeone else\n")}
    ).json()
    for caller in (admin, member):
        for month in (None, "2020-01"):
            usage = caller.get(
                "/v1/settings/usage", params={"month": month} if month else {}
            ).json()
            assert usage["storage_bytes"] == dataset["size_bytes"]
    assert member.get("/v1/settings/usage").json()["scope"] == "you"
    assert admin.delete(f"/v1/datasets/{dataset['id']}").status_code == 204
    assert (
        member.get("/v1/settings/usage", params={"month": "2020-01"}).json()["storage_bytes"] == 0
    )
    assert other.get("/v1/settings/usage").json()["storage_bytes"] == other_dataset["size_bytes"]


def test_usage_counts_what_was_paid_for_in_a_chunk_cut_off_mid_way(client, job, api_key, fake):
    fake.crash_on = "Is this review negative? Love it"  # one chunk of three rows; the second
    created = start(client, job)
    with pytest.raises(KeyboardInterrupt):
        runs.process_next()
    runs.recover_interrupted_runs(stale_after=0)
    while runs.process_next():
        pass
    assert client.get(f"/v1/runs/{created['id']}").json()["status"] == "done"
    # The answers paid for before the crash were redone from the cache: each paid once, counted once.
    total = client.get("/v1/settings/usage").json()["total"]
    assert total["cost"] == pytest.approx(0.003)
    assert total["input_tokens"] == 300

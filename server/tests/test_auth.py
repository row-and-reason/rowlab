import re

import pytest
from fastapi.testclient import TestClient

from rowlab.api.auth import SESSION_COOKIE, STATE_COOKIE
from rowlab.app import create_app
from rowlab.core.config import config
from rowlab.core.providers import workos
from rowlab.core.providers.workos import SignedIn

CSV = b"name,age\nAda,36\nAlan,41\n"


def upload(client: TestClient) -> dict:
    response = client.post("/v1/datasets", files={"file": ("people.csv", CSV)})
    assert response.status_code == 201, response.text
    return response.json()


def test_locally_everyone_is_the_one_admin(client, monkeypatch):
    # No analytics locally, token or not.
    monkeypatch.setenv("ROWLAB_POSTHOG_TOKEN", "phc_test")
    config.cache_clear()
    me = client.get("/v1/me").json()
    assert me == {
        "user": None,
        "org": {"id": "local", "name": "Local"},
        "role": "admin",
        "analytics": None,
    }
    assert client.get("/v1/settings/api-keys").status_code == 400
    upload(client)
    assert len(client.get("/v1/datasets").json()) == 1


def test_hosted_the_api_needs_sign_in(hosted):
    client = TestClient(create_app())
    paths = create_app().openapi()["paths"]
    assert len(paths) > 20
    for path, methods in paths.items():
        if path == "/v1/health":
            continue
        for method in methods:
            response = client.request(method, re.sub(r"{\w+}", "x", path))
            assert response.status_code == 401, f"{method} {path}"
    assert client.get("/v1/health").status_code == 200


def test_first_sign_in_makes_an_organisation(hosted):
    ada = hosted("Ada@example.com")
    me = ada.get("/v1/me").json()
    assert me["user"]["email"] == "ada@example.com"
    assert me["org"]["name"] == "Ada's organisation"
    assert me["role"] == "admin"
    # Signing in again keeps the same organisation.
    assert hosted("ada@example.com").get("/v1/me").json()["org"] == me["org"]


def test_hosted_analytics_only_with_a_token(hosted, monkeypatch):
    assert hosted("ada@example.com").get("/v1/me").json()["analytics"] is None
    monkeypatch.setenv("ROWLAB_POSTHOG_TOKEN", "phc_test")
    config.cache_clear()
    analytics = hosted("ada@example.com").get("/v1/me").json()["analytics"]
    assert analytics == {"token": "phc_test", "host": "https://eu.i.posthog.com"}


def test_organisations_dont_see_each_others_things(hosted):
    ada, alan = hosted("ada@example.com"), hosted("alan@example.com")
    dataset = upload(ada)
    assert alan.get("/v1/datasets").json() == []
    for response in (
        alan.get(f"/v1/datasets/{dataset['id']}"),
        alan.post(f"/v1/datasets/{dataset['id']}/query", json={"sql": "SELECT * FROM data"}),
        alan.delete(f"/v1/datasets/{dataset['id']}"),
    ):
        assert response.status_code == 404

    connection = ada.post(
        "/v1/settings/connections",
        json={"name": "Lake", "access_key_id": "id", "secret_access_key": "secret"},
    ).json()
    assert alan.get("/v1/settings/connections").json() == []
    used = alan.post(
        "/v1/datasets", data={"source": "s3://bucket/file.csv", "connection_id": connection["id"]}
    )
    assert used.status_code == 404


def test_invited_people_join_with_their_role(hosted):
    ada = hosted("ada@example.com")
    dataset = upload(ada)
    invite = ada.post("/v1/settings/invites", json={"email": "Bob@example.com", "role": "verifier"})
    assert invite.status_code == 201
    assert ada.get("/v1/settings/members").json()["invites"][0]["email"] == "bob@example.com"

    bob = hosted("bob@example.com")
    me = bob.get("/v1/me").json()
    assert me["org"] == ada.get("/v1/me").json()["org"]
    assert me["role"] == "verifier"
    members = ada.get("/v1/settings/members").json()
    assert [m["role"] for m in members["members"]] == ["admin", "verifier"]
    assert members["invites"] == []

    # A verifier reads, but doesn't add, run or export.
    assert bob.get(f"/v1/datasets/{dataset['id']}").status_code == 200
    assert bob.post("/v1/datasets", files={"file": ("people.csv", CSV)}).status_code == 403
    assert bob.get(f"/v1/datasets/{dataset['id']}/export?format=csv").status_code == 403
    assert bob.put("/v1/settings/openrouter-key", json={"key": "x"}).status_code == 403


def test_people_in_an_organisation_cant_be_invited_elsewhere(hosted):
    ada = hosted("ada@example.com")
    hosted("alan@example.com")
    response = ada.post("/v1/settings/invites", json={"email": "alan@example.com"})
    assert response.status_code == 400
    assert "another organisation" in response.json()["detail"]


def test_an_organisation_keeps_an_admin(hosted):
    ada = hosted("ada@example.com")
    ada.post("/v1/settings/invites", json={"email": "bob@example.com"})
    bob = hosted("bob@example.com")
    ada_id = ada.get("/v1/me").json()["user"]["id"]
    bob_id = bob.get("/v1/me").json()["user"]["id"]

    response = ada.put(f"/v1/settings/members/{ada_id}", json={"role": "member"})
    assert response.status_code == 400
    assert "needs an admin" in response.json()["detail"]
    assert ada.delete(f"/v1/settings/members/{ada_id}").status_code == 400

    assert bob.put(f"/v1/settings/members/{bob_id}", json={"role": "admin"}).status_code == 403
    assert ada.put(f"/v1/settings/members/{bob_id}", json={"role": "admin"}).status_code == 200
    assert ada.put(f"/v1/settings/members/{ada_id}", json={"role": "member"}).status_code == 200
    assert ada.get("/v1/me").json()["role"] == "member"


def test_removed_members_are_signed_out(hosted):
    ada = hosted("ada@example.com")
    ada.post("/v1/settings/invites", json={"email": "bob@example.com"})
    bob = hosted("bob@example.com")
    key = bob.post("/v1/settings/api-keys", json={"name": "script"}).json()["key"]
    bob_id = bob.get("/v1/me").json()["user"]["id"]

    assert ada.delete(f"/v1/settings/members/{bob_id}").status_code == 204
    assert bob.get("/v1/me").status_code == 401
    by_key = TestClient(create_app()).get("/v1/me", headers={"Authorization": f"Bearer {key}"})
    assert by_key.status_code == 401


def test_api_keys_act_as_their_maker(hosted):
    ada = hosted("ada@example.com")
    dataset = upload(ada)
    made = ada.post("/v1/settings/api-keys", json={"name": "notebook"})
    assert made.status_code == 201
    key = made.json()["key"]
    assert key.startswith("rl_")

    api = TestClient(create_app(), headers={"Authorization": f"Bearer {key}"})
    assert api.get("/v1/me").json()["user"]["email"] == "ada@example.com"
    assert [d["id"] for d in api.get("/v1/datasets").json()] == [dataset["id"]]
    [listed] = ada.get("/v1/settings/api-keys").json()
    assert listed["name"] == "notebook"
    assert listed["last_used_at"] is not None
    assert "key" not in listed

    assert ada.delete(f"/v1/settings/api-keys/{listed['id']}").status_code == 204
    assert api.get("/v1/me").status_code == 401
    wrong = TestClient(create_app()).get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


@pytest.fixture
def fake_workos(monkeypatch):
    """WorkOS, answering the code `good` with Ada."""
    monkeypatch.setattr(workos, "sign_in_url", lambda state: f"https://authkit.test/?state={state}")
    monkeypatch.setattr(
        workos, "sign_out_url", lambda session: f"https://authkit.test/out/{session}"
    )

    def authenticate(code: str) -> SignedIn:
        assert code == "good"
        return SignedIn(
            workos_id="user_ada",
            email="ada@example.com",
            name="Ada",
            email_verified=True,
            session_id="session_ada",
        )

    monkeypatch.setattr(workos, "authenticate", authenticate)


def test_signing_in_and_out_in_a_browser(hosted, fake_workos):
    browser = TestClient(create_app(), follow_redirects=False)
    start = browser.get("/auth/sign-in")
    assert start.status_code == 307
    state = browser.cookies[STATE_COOKIE]
    assert start.headers["location"] == f"https://authkit.test/?state={state}"

    # Only this browser's sign-in counts.
    assert browser.get("/auth/callback?code=good&state=other").status_code == 401
    done = browser.get(f"/auth/callback?code=good&state={state}")
    assert done.headers["location"] == "/"
    assert browser.get("/v1/me").json()["user"]["email"] == "ada@example.com"

    out = browser.post("/auth/sign-out")
    assert out.headers["location"] == "https://authkit.test/out/session_ada"
    assert SESSION_COOKIE not in browser.cookies
    assert browser.get("/v1/me").status_code == 401


def test_unverified_email_addresses_cant_sign_in(hosted, monkeypatch):
    monkeypatch.setattr(
        workos,
        "authenticate",
        lambda code: SignedIn(
            workos_id="u", email="eve@example.com", name="Eve", email_verified=False
        ),
    )
    browser = TestClient(create_app(), follow_redirects=False)
    browser.cookies.set(STATE_COOKIE, "s")
    response = browser.get("/auth/callback?code=x&state=s")
    assert response.status_code == 401
    assert "Verify" in response.json()["detail"]

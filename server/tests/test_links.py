import pytest
from fastapi.testclient import TestClient

from rowlab.app import create_app
from rowlab.core import links
from rowlab.core.errors import InvalidRequest

CSV = b"review\nTerrible product\nLove it\n"


def path_of(link):
    """The link's path, for the test client; its URL is on ROWLAB_URL."""
    assert link.url.startswith("http://testserver/v1/links/")
    return link.url.removeprefix("http://testserver")


def test_an_upload_link_adds_a_dataset_without_signing_in(hosted):
    ada = hosted("ada@example.com")
    org_id = ada.get("/v1/me").json()["org"]["id"]
    link = links.upload_link(org_id)
    assert "curl" in link.command and link.url in link.command

    anyone = TestClient(create_app())
    added = anyone.post(path_of(link), files={"file": ("reviews.csv", CSV)})
    assert added.status_code == 201
    assert added.json()["name"] == "reviews"
    # It is Ada's organisation's.
    assert [d["id"] for d in ada.get("/v1/datasets").json()] == [added.json()["id"]]


def test_a_download_link_gives_the_file_without_signing_in(hosted):
    ada = hosted("ada@example.com")
    dataset = ada.post("/v1/datasets", files={"file": ("reviews.csv", CSV)}).json()
    link = links.download_link(
        dataset["id"], "csv", include_row_id=False, query="SELECT * FROM data LIMIT 1"
    )
    assert "-o 'reviews.csv'" in link.command

    reply = TestClient(create_app()).get(path_of(link))
    assert reply.status_code == 200
    assert reply.text.splitlines() == ["review", "Terrible product"]


def test_links_that_are_forged_expired_or_for_something_else_are_refused(hosted, monkeypatch):
    ada = hosted("ada@example.com")
    dataset = ada.post("/v1/datasets", files={"file": ("reviews.csv", CSV)}).json()
    download = path_of(links.download_link(dataset["id"], "csv", include_row_id=False))
    anyone = TestClient(create_app())

    assert anyone.get("/v1/links/forged").status_code == 401
    assert anyone.post("/v1/links/forged", files={"file": ("x.csv", CSV)}).status_code == 401
    # A download link isn't an upload link.
    assert anyone.post(download, files={"file": ("x.csv", CSV)}).status_code == 401
    monkeypatch.setattr(links, "LINK_SECONDS", -1)
    expired = anyone.get(download)
    assert expired.status_code == 401
    assert "expired" in expired.json()["detail"]


def test_a_download_link_checks_its_query_when_made(hosted):
    ada = hosted("ada@example.com")
    dataset = ada.post("/v1/datasets", files={"file": ("reviews.csv", CSV)}).json()
    with pytest.raises(InvalidRequest):
        links.download_link(dataset["id"], "csv", include_row_id=False, query="SELECT nope")


def test_links_are_for_hosted_rowlab(client):
    with pytest.raises(InvalidRequest, match="locally, give a path"):
        links.upload_link("any")

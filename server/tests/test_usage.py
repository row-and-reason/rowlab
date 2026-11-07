"""Storage is organization-wide and current, even when run activity is personal or historical."""


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

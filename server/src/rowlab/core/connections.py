"""Connections: named credentials for S3-compatible storage (AWS S3, Cloudflare R2, MinIO, …).

Datasets are read from `s3://bucket/key` sources and exported to `s3://` paths with DuckDB, using a
connection when one is given, or else the usual AWS credentials (environment variables, `~/.aws`).
"""

import uuid
from datetime import UTC, datetime

import duckdb
from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.errors import InvalidRequest, NotFound


class ConnectionInput(BaseModel):
    name: str
    endpoint: str = Field(
        "",
        description="Empty for AWS S3. Otherwise the storage's address, e.g. "
        "`https://<account>.r2.cloudflarestorage.com` or `http://localhost:9000` for MinIO.",
    )
    region: str = Field("us-east-1", description="`auto` for Cloudflare R2.")
    access_key_id: str
    secret_access_key: str | None = Field(
        None, description="Required for a new connection; leave out to keep the saved one."
    )


class Connection(BaseModel):
    """A connection as the API shows it: without its secret key."""

    id: str
    name: str
    endpoint: str
    region: str
    access_key_id: str
    created_at: datetime


def is_s3(location: str) -> bool:
    return location.startswith("s3://")


def list_connections(org_id: str) -> list[Connection]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM connections WHERE org_id = ? ORDER BY name", (org_id,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def get_connection(org_id: str, connection_id: str) -> Connection:
    return _from_row(_row(org_id, connection_id))


def create_connection(org_id: str, data: ConnectionInput) -> Connection:
    _check(data)
    if not data.secret_access_key:
        raise InvalidRequest("Enter the secret access key.")
    connection_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO connections (id, org_id, name, endpoint, region, access_key_id,"
            " secret_access_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                connection_id,
                org_id,
                data.name.strip(),
                data.endpoint.strip(),
                data.region.strip(),
                data.access_key_id.strip(),
                data.secret_access_key.strip(),
                datetime.now(UTC).isoformat(),
            ),
        )
    return get_connection(org_id, connection_id)


def update_connection(org_id: str, connection_id: str, data: ConnectionInput) -> Connection:
    saved = _row(org_id, connection_id)
    secret = data.secret_access_key or saved["secret_access_key"]
    _check(data)
    with db.connect() as conn:
        conn.execute(
            "UPDATE connections SET name = ?, endpoint = ?, region = ?, access_key_id = ?,"
            " secret_access_key = ? WHERE id = ?",
            (
                data.name.strip(),
                data.endpoint.strip(),
                data.region.strip(),
                data.access_key_id.strip(),
                secret.strip(),
                connection_id,
            ),
        )
    return get_connection(org_id, connection_id)


def delete_connection(org_id: str, connection_id: str) -> None:
    _row(org_id, connection_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))


def configure(con: duckdb.DuckDBPyConnection, org_id: str, connection_id: str | None) -> None:
    """Let a DuckDB connection read and write `s3://` paths: with the organisation's connection's
    keys, or else with whatever AWS credentials the environment has (none for public buckets)."""
    if connection_id is None:
        try:
            con.execute("CREATE TEMPORARY SECRET (TYPE s3, PROVIDER credential_chain)")
        except duckdb.Error:
            pass  # No credentials around: public buckets still work.
        return
    row = _row(org_id, connection_id)
    endpoint = row["endpoint"]
    options = {
        "KEY_ID": row["access_key_id"],
        "SECRET": row["secret_access_key"],
        "REGION": row["region"],
    }
    if endpoint:
        options["ENDPOINT"] = endpoint.removeprefix("https://").removeprefix("http://").rstrip("/")
        # Storage other than AWS is addressed by path: `endpoint/bucket/key`.
        options["URL_STYLE"] = "path"
        options["USE_SSL"] = not endpoint.startswith("http://")
    settings = ", ".join(
        f"{key} {value}"
        if isinstance(value, bool)
        else f"{key} '{value.replace(chr(39), chr(39) * 2)}'"
        for key, value in options.items()
    )
    con.execute(f"CREATE TEMPORARY SECRET (TYPE s3, {settings})")


def _check(data: ConnectionInput) -> None:
    if not data.name.strip():
        raise InvalidRequest("Name the connection.")
    if not data.access_key_id.strip():
        raise InvalidRequest("Enter the access key ID.")
    if not data.region.strip():
        raise InvalidRequest("Enter the region, e.g. us-east-1, or auto for Cloudflare R2.")


def _row(org_id: str, connection_id: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM connections WHERE id = ? AND org_id = ?", (connection_id, org_id)
        ).fetchone()
    if row is None:
        raise NotFound(f"Connection {connection_id} not found")
    return row


def _from_row(row) -> Connection:
    return Connection(
        id=row["id"],
        name=row["name"],
        endpoint=row["endpoint"],
        region=row["region"],
        access_key_id=row["access_key_id"],
        created_at=row["created_at"],
    )

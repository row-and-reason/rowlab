"""Who is calling, in which organisation, with which role.

Locally there is no sign-in: every call is the one implicit admin of the organisation `local`. Hosted,
a call is signed in one of two ways, each acting as one person in one organisation:

- A browser session, made when someone signs in with WorkOS (`sign_in`), kept in a cookie.
- An API key (`rl_…`) someone made, sent as `Authorization: Bearer rl_…`.
- A WorkOS access token, which MCP clients get by signing in with WorkOS (`me_for_workos_user`).

Roles, each allowed what the one before it is: a verifier reads (and, later, labels by hand); a member
also adds, runs and exports; an admin also changes settings, connections and members.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.config import config
from rowlab.core.errors import Forbidden, InvalidRequest, NotFound, Unauthorized
from rowlab.core.providers.workos import SignedIn

Role = Literal["verifier", "member", "admin"]
ROLES: list[Role] = ["verifier", "member", "admin"]

LOCAL_ORG = "local"
SESSION_DAYS = 30
API_KEY_PREFIX = "rl_"


class Org(BaseModel):
    id: str
    name: str


class User(BaseModel):
    id: str
    email: str
    name: str


class Me(BaseModel):
    """Who is calling."""

    user: User | None = Field(description="Empty locally, where nobody signs in.")
    org: Org
    role: Role


LOCAL = Me(user=None, org=Org(id=LOCAL_ORG, name="Local"), role="admin")


class ApiKey(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None


class NewApiKey(BaseModel):
    api_key: ApiKey
    key: str = Field(description="The key itself, `rl_…`. It is shown only this once.")


def authenticate(session: str | None, bearer: str | None) -> Me:
    """Who is calling, from a session cookie's token or an API key."""
    if config().mode == "local":
        return LOCAL
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        if bearer and bearer.startswith(API_KEY_PREFIX):
            row = _caller(conn, "api_keys", "t.hash = ?", (_hash(bearer),))
            if row is not None:
                conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        elif bearer:
            raise Unauthorized("That isn't a rowlab API key (`rl_…`).")
        elif session:
            row = _caller(conn, "sessions", "t.id = ? AND t.expires_at > ?", (_hash(session), now))
        else:
            raise Unauthorized("Sign in, or send an API key: `Authorization: Bearer rl_…`.")
    if row is None:
        raise Unauthorized("That API key or session isn't valid (any more).")
    return Me(
        user=User(id=row["user_id"], email=row["email"], name=row["user_name"]),
        org=Org(id=row["org_id"], name=row["org_name"]),
        role=row["role"],
    )


def _caller(conn: Any, table: str, where: str, params: tuple) -> dict[str, Any] | None:
    """The session or API key, with who it acts as: only while they are still a member of its
    organisation."""
    return conn.execute(
        "SELECT t.*, u.email, u.name AS user_name, o.name AS org_name, m.role"
        f" FROM {table} t JOIN members m ON m.org_id = t.org_id AND m.user_id = t.user_id"
        " JOIN users u ON u.id = t.user_id JOIN orgs o ON o.id = t.org_id"
        f" WHERE {where}",
        params,
    ).fetchone()


def require(me: Me, role: Role) -> None:
    """Raise Forbidden unless the caller's role is `role` or above."""
    if ROLES.index(me.role) < ROLES.index(role):
        raise Forbidden(f"That needs the {role} role; you are a {me.role}.")


def sign_in(person: SignedIn) -> str:
    """Start a session for someone WorkOS signed in, and return its token, for a cookie. The first
    time, they join the organisation that invited them, or else get one of their own, as its admin."""
    if not person.email_verified:
        raise Unauthorized("Verify your email address first.")
    email = person.email.lower()
    now = datetime.now(UTC)
    with db.connect() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE workos_id = ? OR email = ?", (person.workos_id, email)
        ).fetchone()
        if user is None:
            user_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO users (id, workos_id, email, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, person.workos_id, email, person.name, now.isoformat()),
            )
        else:
            user_id = user["id"]
            conn.execute(
                "UPDATE users SET workos_id = ?, email = ?, name = ? WHERE id = ?",
                (person.workos_id, email, person.name, user_id),
            )
        org_id = _org_of(conn, user_id) or _join(conn, user_id, email, person.name, now)
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (id, user_id, org_id, workos_session_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                _hash(token),
                user_id,
                org_id,
                person.session_id,
                now.isoformat(),
                (now + timedelta(days=SESSION_DAYS)).isoformat(),
            ),
        )
    return token


def me_for_workos_user(workos_id: str) -> Me:
    """Who a WorkOS access token's user is: for MCP clients, which sign in with WorkOS. They must
    have signed in to rowlab in a browser before, which is where organisations are joined."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.id AS user_id, u.email, u.name AS user_name, m.org_id, o.name AS org_name,"
            " m.role FROM users u JOIN members m ON m.user_id = u.id JOIN orgs o ON o.id = m.org_id"
            " WHERE u.workos_id = ? ORDER BY m.created_at LIMIT 1",
            (workos_id,),
        ).fetchone()
    if row is None:
        raise Unauthorized("Sign in to rowlab in a browser first, then connect again.")
    return Me(
        user=User(id=row["user_id"], email=row["email"], name=row["user_name"]),
        org=Org(id=row["org_id"], name=row["org_name"]),
        role=row["role"],
    )


def sign_out(session: str) -> str | None:
    """End a session. Returns the WorkOS session to end too, if there is one."""
    with db.connect() as conn:
        row = conn.execute(
            "DELETE FROM sessions WHERE id = ? RETURNING workos_session_id", (_hash(session),)
        ).fetchone()
    return row["workos_session_id"] if row and row["workos_session_id"] else None


def list_api_keys(me: Me) -> list[ApiKey]:
    """The caller's own API keys, newest first."""
    _need_user(me)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM api_keys WHERE user_id = ? AND org_id = ? ORDER BY created_at DESC",
            (me.user.id, me.org.id),
        ).fetchall()
    return [ApiKey(**row) for row in rows]


def create_api_key(me: Me, name: str) -> NewApiKey:
    """An API key acting as the caller, in their organisation, with their role at the time of use."""
    _need_user(me)
    if not name.strip():
        raise InvalidRequest("Name the key, e.g. after where it is used.")
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    api_key = ApiKey(
        id=uuid.uuid4().hex, name=name.strip(), created_at=datetime.now(UTC), last_used_at=None
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO api_keys (id, hash, user_id, org_id, name, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                api_key.id,
                _hash(key),
                me.user.id,
                me.org.id,
                api_key.name,
                api_key.created_at.isoformat(),
            ),
        )
    return NewApiKey(api_key=api_key, key=key)


def delete_api_key(me: Me, api_key_id: str) -> None:
    _need_user(me)
    with db.connect() as conn:
        row = conn.execute(
            "DELETE FROM api_keys WHERE id = ? AND user_id = ? RETURNING id",
            (api_key_id, me.user.id),
        ).fetchone()
    if row is None:
        raise NotFound(f"API key {api_key_id} not found")


def _need_user(me: Me) -> None:
    if me.user is None:
        raise InvalidRequest("Locally nobody signs in, so the API needs no key.")


def _org_of(conn: Any, user_id: str) -> str | None:
    """The organisation someone is in. One for now; the tables allow several."""
    row = conn.execute(
        "SELECT org_id FROM members WHERE user_id = ? ORDER BY created_at LIMIT 1", (user_id,)
    ).fetchone()
    return row["org_id"] if row else None


def _join(conn: Any, user_id: str, email: str, name: str, now: datetime) -> str:
    """Add someone to the organisation that invited them, or else to a new one of their own."""
    invite = conn.execute(
        "SELECT * FROM invites WHERE email = ? ORDER BY created_at LIMIT 1", (email,)
    ).fetchone()
    if invite is not None:
        org_id, role = invite["org_id"], invite["role"]
        conn.execute("DELETE FROM invites WHERE id = ?", (invite["id"],))
    else:
        org_id, role = uuid.uuid4().hex, "admin"
        conn.execute(
            "INSERT INTO orgs (id, name, created_at) VALUES (?, ?, ?)",
            (org_id, f"{name}'s organisation", now.isoformat()),
        )
    conn.execute(
        "INSERT INTO members (org_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
        (org_id, user_id, role, now.isoformat()),
    )
    return org_id


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

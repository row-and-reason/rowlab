"""The people in an organisation, and the ones invited to it. An organisation always keeps an admin.

Nobody is emailed: an admin invites an address, and its owner joins the first time they sign in.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from rowlab.core import db
from rowlab.core.auth import Me, Role, User
from rowlab.core.config import config
from rowlab.core.errors import InvalidRequest, NotFound


class Member(BaseModel):
    user: User
    role: Role
    created_at: datetime = Field(description="When they joined.")


class Invite(BaseModel):
    id: str
    email: str
    role: Role
    created_at: datetime


class Members(BaseModel):
    members: list[Member]
    invites: list[Invite]


class InviteRequest(BaseModel):
    email: str
    role: Role = "member"


class RoleChange(BaseModel):
    role: Role


def list_members(me: Me) -> Members:
    with db.connect() as conn:
        members = conn.execute(
            "SELECT m.*, u.email, u.name FROM members m JOIN users u ON u.id = m.user_id"
            " WHERE m.org_id = ? ORDER BY u.name",
            (me.org.id,),
        ).fetchall()
        invites = conn.execute(
            "SELECT * FROM invites WHERE org_id = ? ORDER BY created_at", (me.org.id,)
        ).fetchall()
    return Members(
        members=[_member(row) for row in members], invites=[Invite(**r) for r in invites]
    )


def invite(me: Me, request: InviteRequest) -> Invite:
    """Invite an email address, or change the role of an invite already made."""
    if config().mode == "local":
        raise InvalidRequest("Locally nobody signs in, so nobody can be invited.")
    email = request.email.strip().lower()
    if "@" not in email:
        raise InvalidRequest("Enter an email address.")
    with db.connect() as conn:
        member = conn.execute(
            "SELECT m.org_id FROM members m JOIN users u ON u.id = m.user_id WHERE u.email = ?",
            (email,),
        ).fetchone()
        if member is not None:
            raise InvalidRequest(
                f"{email} is already in this organisation."
                if member["org_id"] == me.org.id
                else f"{email} already belongs to another organisation."
            )
        row = conn.execute(
            "INSERT INTO invites (id, org_id, email, role, created_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (org_id, email) DO UPDATE SET role = excluded.role RETURNING *",
            (uuid.uuid4().hex, me.org.id, email, request.role, datetime.now(UTC).isoformat()),
        ).fetchone()
    return Invite(**row)


def delete_invite(me: Me, invite_id: str) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "DELETE FROM invites WHERE id = ? AND org_id = ? RETURNING id", (invite_id, me.org.id)
        ).fetchone()
    if row is None:
        raise NotFound(f"Invite {invite_id} not found")


def change_role(me: Me, user_id: str, change: RoleChange) -> Member:
    with db.connect() as conn:
        _row(conn, me, user_id)
        conn.execute(
            "UPDATE members SET role = ? WHERE org_id = ? AND user_id = ?",
            (change.role, me.org.id, user_id),
        )
        _keep_an_admin(conn, me)
        return _member(_row(conn, me, user_id))


def remove(me: Me, user_id: str) -> None:
    """Remove someone, with their API keys and sessions in this organisation."""
    with db.connect() as conn:
        _row(conn, me, user_id)
        for table in ("members", "api_keys", "sessions"):
            conn.execute(
                f"DELETE FROM {table} WHERE org_id = ? AND user_id = ?", (me.org.id, user_id)
            )
        _keep_an_admin(conn, me)


def _keep_an_admin(conn: Any, me: Me) -> None:
    """Raise, undoing the change, if it left the organisation without an admin."""
    row = conn.execute(
        "SELECT count(*) AS admins FROM members WHERE org_id = ? AND role = 'admin'", (me.org.id,)
    ).fetchone()
    if row["admins"] == 0:
        raise InvalidRequest("An organisation needs an admin: make someone else admin first.")


def _row(conn: Any, me: Me, user_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT m.*, u.email, u.name FROM members m JOIN users u ON u.id = m.user_id"
        " WHERE m.org_id = ? AND m.user_id = ?",
        (me.org.id, user_id),
    ).fetchone()
    if row is None:
        raise NotFound(f"Member {user_id} not found")
    return row


def _member(row: dict[str, Any]) -> Member:
    return Member(
        user=User(id=row["user_id"], email=row["email"], name=row["name"]),
        role=row["role"],
        created_at=row["created_at"],
    )

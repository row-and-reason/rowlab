from fastapi import APIRouter

from rowlab.api.auth import CanAdmin, CanRead
from rowlab.core import members
from rowlab.core.members import Invite, InviteRequest, Member, Members, RoleChange

router = APIRouter(prefix="/v1/settings", tags=["settings"])


@router.get("/members", operation_id="listMembers")
def list_members(me: CanRead) -> Members:
    """The organisation's members, and the people invited to it."""
    return members.list_members(me)


@router.put("/members/{user_id}", operation_id="changeRole")
def change_role(user_id: str, change: RoleChange, me: CanAdmin) -> Member:
    """Make someone an admin, member or verifier. The organisation always keeps an admin."""
    return members.change_role(me, user_id, change)


@router.delete("/members/{user_id}", operation_id="removeMember", status_code=204)
def remove_member(user_id: str, me: CanAdmin) -> None:
    """Remove someone from the organisation, with their API keys."""
    members.remove(me, user_id)


@router.post("/invites", operation_id="inviteMember", status_code=201)
def invite_member(request: InviteRequest, me: CanAdmin) -> Invite:
    """Invite an email address. Nobody is emailed: they join when they first sign in."""
    return members.invite(me, request)


@router.delete("/invites/{invite_id}", operation_id="deleteInvite", status_code=204)
def delete_invite(invite_id: str, me: CanAdmin) -> None:
    members.delete_invite(me, invite_id)

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from rowlab.core import auth
from rowlab.core.auth import Me
from rowlab.core.config import config
from rowlab.core.errors import Unauthorized
from rowlab.core.providers import workos

SESSION_COOKIE = "rowlab_session"
STATE_COOKIE = "rowlab_sign_in"

_bearer = HTTPBearer(auto_error=False, description="An API key, `rl_…`. Hosted only.")
_session = APIKeyCookie(
    name=SESSION_COOKIE, auto_error=False, description="Set by signing in. Hosted only."
)


def _me(
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[str | None, Depends(_session)],
) -> Me:
    return auth.authenticate(session, bearer.credentials if bearer else None)


def _member(me: Annotated[Me, Depends(_me)]) -> Me:
    auth.require(me, "member")
    return me


def _admin(me: Annotated[Me, Depends(_me)]) -> Me:
    auth.require(me, "admin")
    return me


# What an endpoint needs: any role reads; members also add, run and export; admins change settings.
CanRead = Annotated[Me, Depends(_me)]
CanEdit = Annotated[Me, Depends(_member)]
CanAdmin = Annotated[Me, Depends(_admin)]

router = APIRouter(tags=["auth"])


@router.get("/v1/me", operation_id="getMe")
def get_me(me: CanRead) -> Me:
    """Who is calling: their organisation and role. Locally, always the one implicit admin."""
    return me


# Signing in and out, in a browser. Not part of the API.


@router.get("/auth/sign-in", include_in_schema=False)
def sign_in() -> RedirectResponse:
    if config().mode == "local":
        return RedirectResponse("/")
    state = secrets.token_urlsafe(16)
    response = RedirectResponse(workos.sign_in_url(state))
    response.set_cookie(STATE_COOKIE, state, max_age=600, **_cookie())
    return response


@router.get("/auth/callback", include_in_schema=False)
def callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    # The state proves this browser started the sign-in.
    if not code or not state or state != request.cookies.get(STATE_COOKIE):
        raise Unauthorized("The sign-in didn't come from this browser. Sign in again.")
    token = auth.sign_in(workos.authenticate(code))
    response = RedirectResponse("/")
    response.delete_cookie(STATE_COOKIE)
    response.set_cookie(SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, **_cookie())
    return response


@router.post("/auth/sign-out", include_in_schema=False)
def sign_out(request: Request) -> RedirectResponse:
    session = request.cookies.get(SESSION_COOKIE)
    workos_session = auth.sign_out(session) if session else None
    response = RedirectResponse(
        workos.sign_out_url(workos_session) if workos_session else "/", status_code=303
    )
    response.delete_cookie(SESSION_COOKIE)
    return response


def _cookie() -> dict:
    # Lax: sent when following a link here, not with other sites' requests (no CSRF).
    return {"httponly": True, "samesite": "lax", "secure": config().url.startswith("https://")}

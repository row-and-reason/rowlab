"""WorkOS AuthKit, which people sign in with in `hosted` mode: its sign-in page, then a code exchanged
for who signed in."""

from typing import Any

from pydantic import BaseModel

from rowlab.core.config import config
from rowlab.core.errors import Unauthorized


class SignedIn(BaseModel):
    """Who signed in, as WorkOS says."""

    workos_id: str
    email: str
    name: str
    email_verified: bool
    session_id: str = ""  # WorkOS's own session, ended when they sign out of rowlab


def sign_in_url(state: str) -> str:
    """AuthKit's sign-in page, which sends people back to `/auth/callback` with a code."""
    return _client().user_management.get_authorization_url(
        provider="authkit", redirect_uri=f"{config().url}/auth/callback", state=state
    )


def authenticate(code: str) -> SignedIn:
    """Who signed in, from the code AuthKit sent back."""
    import jwt  # Both only needed hosted: `pip install rowlab[hosted]`.
    from workos import WorkOSError

    try:
        response = _client().user_management.authenticate_with_code(code=code)
    except WorkOSError as e:
        raise Unauthorized(f"WorkOS did not accept the sign-in: {e}") from e
    user = response.user
    # The token comes straight from WorkOS, so it is only read, not verified.
    claims = jwt.decode(response.access_token, options={"verify_signature": False})
    return SignedIn(
        workos_id=user.id,
        email=user.email,
        name=" ".join(n for n in (user.first_name, user.last_name) if n) or user.email,
        email_verified=user.email_verified,
        session_id=claims.get("sid", ""),
    )


def sign_out_url(session_id: str) -> str:
    """WorkOS's sign-out, which ends its session too, then sends people back to rowlab."""
    return _client().user_management.get_logout_url(
        session_id=session_id, return_to=f"{config().url}/"
    )


def _client() -> Any:
    from workos import WorkOSClient

    return WorkOSClient(api_key=config().workos_api_key, client_id=config().workos_client_id)

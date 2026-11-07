class NotFound(Exception):
    """The requested object does not exist. The API returns 404."""


class InvalidRequest(Exception):
    """The request cannot be fulfilled as given, e.g. an unreadable file. The API returns 400."""


class Unauthorized(Exception):
    """Nobody is signed in, or the credentials are wrong. The API returns 401."""


class Forbidden(Exception):
    """The caller's role doesn't allow this. The API returns 403."""

class NotFound(Exception):
    """The requested object does not exist. The API returns 404."""


class InvalidRequest(Exception):
    """The request cannot be fulfilled as given, e.g. an unreadable file. The API returns 400."""

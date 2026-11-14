"""What the client raises. Everything is a `RowlabError`."""

from typing import Any


class RowlabError(Exception):
    """Base SDK error."""


class ConfigurationError(RowlabError, ValueError):
    """The URL, API key or timeout given to `Client` is invalid."""


class TransportError(RowlabError):
    """rowlab could not be reached. Nothing is retried: a request that creates data or costs money
    may or may not have happened."""


class ResponseError(RowlabError):
    """rowlab replied with something this SDK version doesn't understand."""


class ApiError(RowlabError):
    """rowlab refused the request. `detail` is the API's `detail` as sent: a message, or for an
    invalid request (422) the list of what's wrong with it."""

    def __init__(self, message: str, *, status_code: int, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail

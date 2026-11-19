"""Exception hierarchy for gradescope-cli."""

from __future__ import annotations


class GradescopeError(Exception):
    """Base class for all errors raised by gradescope-cli."""


class ConfigError(GradescopeError):
    """Missing or invalid local configuration (e.g. credentials)."""


class AuthError(GradescopeError):
    """Authentication with Gradescope failed, or the session expired."""


class APIError(GradescopeError):
    """A request to Gradescope failed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class NotFoundError(APIError):
    """The requested course/assignment/submission does not exist (HTTP 404)."""


class ParseError(GradescopeError):
    """A Gradescope page could not be parsed."""


class AutograderTimeoutError(GradescopeError):
    """The autograder did not finish within the allotted time."""

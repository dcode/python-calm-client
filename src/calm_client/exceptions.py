"""Custom exceptions for the Calm Client."""

from __future__ import annotations


class CalmError(Exception):
    """Base exception for Calm Client."""


class CalmAuthError(CalmError):
    """Raised when authentication fails (401/403)."""


class CalmAPIError(CalmError):
    """Raised when the API returns an error or cannot be reached.

    Attributes:
        status: The HTTP status Calm answered with, or None when no response arrived.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        """Create the error with the HTTP status, if there was a response."""
        super().__init__(message)
        self.status = status


class CalmNotFoundError(CalmAPIError):
    """Raised when the requested content does not exist (HTTP 404, or a guide missing from its program)."""


class CalmConnectionError(CalmAPIError):
    """Raised when Calm cannot be reached: a connection error, a timeout or a broken response."""


class CalmRateLimitError(CalmAPIError):
    """Raised when Calm rate-limits the client (HTTP 429).

    Attributes:
        retry_after: Seconds Calm asked the client to wait, if it said so as a number.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Create the error with the wait Calm asked for, if any."""
        super().__init__(message, status=429)
        self.retry_after = retry_after

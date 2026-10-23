"""Custom exceptions for the Calm Client."""


class CalmError(Exception):
    """Base exception for Calm Client."""

    pass


class CalmAuthError(CalmError):
    """Raised when authentication fails (401/403)."""

    pass


class CalmAPIError(CalmError):
    """Raised when API returns an error."""

    pass


class CalmRateLimitError(CalmAPIError):
    """Raised when Calm rate-limits the client (HTTP 429).

    Attributes:
        retry_after: Seconds Calm asked the client to wait, if it said so as a number.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Create the error with the wait Calm asked for, if any."""
        super().__init__(message)
        self.retry_after = retry_after

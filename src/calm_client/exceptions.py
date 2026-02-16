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

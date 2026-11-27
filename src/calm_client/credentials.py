"""Credential management for Calm Client.

Stores the full OAuth2 token set from Auth0 as a Pydantic model, tracks
expiry, and supports automatic refresh using the refresh token.

Inspired by ``google.oauth2.credentials.Credentials``.
"""

from __future__ import annotations

import json
import time
import typing
import uuid

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .exceptions import CalmAuthError, CalmConnectionError


class Credentials(BaseModel):
    """OAuth2 credentials from Auth0.

    Can be constructed directly from an Auth0 ``/oauth/token`` response::

        creds = Credentials(**auth0_response_json)

    Or from a raw pasted token::

        creds = Credentials.from_token("eyJ...")
    """

    model_config = ConfigDict(populate_by_name=True)

    token: str = Field(alias="access_token")
    refresh_token: str | None = None
    id_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float | None = None
    scope: str = ""
    session_token: str | None = None
    device_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @model_validator(mode="before")
    @classmethod
    def _compute_expiry(cls, values: dict) -> dict:
        """Convert ``expires_in`` (seconds) → ``expires_at`` (timestamp)."""
        if isinstance(values, dict) and "expires_in" in values and "expires_at" not in values:
            expires_in = values.pop("expires_in")
            if expires_in is not None:
                values["expires_at"] = time.time() + int(expires_in)
        return values

    # ------------------------------------------------------------------
    # Token lifecycle properties
    # ------------------------------------------------------------------

    # Buffer (seconds) to refresh *before* actual expiry to avoid races.
    _EXPIRY_BUFFER: int = 60

    @property
    def expired(self) -> bool:
        """True if the access token has expired (or will within 60 s)."""
        if self.expires_at is None:
            return False  # No expiry info → assume valid (e.g. pasted tokens)
        return time.time() >= (self.expires_at - self._EXPIRY_BUFFER)

    @property
    def valid(self) -> bool:
        """True if there is a token and it is not expired."""
        return bool(self.token) and not self.expired

    @property
    def can_refresh(self) -> bool:
        """True if a refresh token is available."""
        return bool(self.refresh_token)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def refresh(self, session: aiohttp.ClientSession, *, user_agent: str | None = None) -> None:
        """Use the refresh token to obtain a new access token.

        Mutates this instance in-place with the new token data.

        Args:
            session: The aiohttp session to send the refresh request with.
            user_agent: A User-Agent for this request; None keeps the session's own.

        Raises:
            CalmAuthError: If there is no refresh token or Auth0 rejects it.
            CalmConnectionError: If Auth0 cannot be reached.
        """
        if not self.refresh_token:
            raise CalmAuthError("Cannot refresh: no refresh_token available. Please login again.")

        from .constants import AUTH0_CLIENT_ID, AUTH0_TOKEN_URL

        payload = {
            "grant_type": "refresh_token",
            "client_id": AUTH0_CLIENT_ID,
            "refresh_token": self.refresh_token,
        }
        headers = {"Content-Type": "application/json"}
        if user_agent is not None:
            headers["User-Agent"] = user_agent

        try:
            async with session.post(AUTH0_TOKEN_URL, json=payload, headers=headers) as response:
                status = response.status
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise CalmConnectionError(f"Network error during token refresh: {e}") from e

        if status != 200:
            raise CalmAuthError(f"Token refresh failed: {_auth0_error(text)}")

        data = _json_object(text)
        new_token = data.get("access_token")
        if not new_token:
            raise CalmAuthError("Refresh response missing access_token.")

        # Update fields in-place
        self.token = new_token
        self.id_token = data.get("id_token", self.id_token)
        self.scope = data.get("scope", self.scope)

        expires_in = data.get("expires_in")
        if expires_in:
            self.expires_at = time.time() + int(expires_in)

        # Auth0 may rotate the refresh token
        if "refresh_token" in data:
            self.refresh_token = data["refresh_token"]

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_token(cls, token: str) -> Credentials:
        """Create a Credentials instance from a raw token string (e.g. pasted).

        These credentials have no refresh capability and no expiry tracking.
        """
        return cls(token=token)

    def __repr__(self) -> str:
        """Return a safe repr that does not leak the token."""
        status = "valid" if self.valid else "expired"
        refresh = "yes" if self.can_refresh else "no"
        return f"<Credentials status={status} refresh={refresh}>"


def _json_object(text: str) -> dict[str, typing.Any]:
    """Parse a JSON object body, or return an empty dict when it is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _auth0_error(text: str) -> str:
    """Return the description from an Auth0 error body, or the start of the raw body."""
    err = _json_object(text)
    if err:
        return str(err.get("error_description", err.get("error", "Unknown error")))
    return text[:200]

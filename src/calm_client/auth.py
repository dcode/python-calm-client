"""Authentication strategies for Calm Client.

Implements the ``AuthStrategy`` protocol with concrete strategies for
Bearer token (Auth0 JWT) and legacy cookie-based authentication.
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    import collections.abc

    from .credentials import Credentials


class AuthStrategy(typing.Protocol):
    """Protocol defining how authentication credentials are injected.

    Called by ``CalmClient._request()`` immediately before every request.
    Implementations can check token expiry and refresh here.
    """

    def before_request(
        self,
        headers: collections.abc.MutableMapping[str, str | bytes],
    ) -> None:
        """Inject credentials into the request headers.

        Args:
            headers: The dictionary of headers to modify in-place.
        """
        ...


# Common headers for all strategies
_COMMON_HEADERS: dict[str, str] = {
    "x-calm-platform": "web",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),

}


class BearerAuth:
    """Injects ``Authorization: Bearer <token>`` header from Credentials.

    Use for APIs that accept standard OAuth2 Bearer tokens (e.g.
    ``api.calm.com`` directly).  Not used for the web proxy.
    """

    def __init__(self, credentials: Credentials) -> None:
        """Initialize with a Credentials instance."""
        self.credentials = credentials

    def before_request(
        self,
        headers: collections.abc.MutableMapping[str, str | bytes],
    ) -> None:
        """Add common headers and Bearer token."""
        headers.update(_COMMON_HEADERS)
        if self.credentials.token:
            headers["Authorization"] = f"Bearer {self.credentials.token}"


class CookieAuth:
    """Injects ``calm-user-token`` cookie via headers.

    The Calm web proxy (``www.calm.com/webapi/authproxy``) authenticates
    via the ``calm-user-token`` cookie.  Auth0 JWTs and legacy tokens
    are both stored in this cookie by the web app.

    Holds a reference to ``Credentials`` so the token stays in sync
    after auto-refresh.
    """

    def __init__(self, credentials: Credentials) -> None:
        """Initialize with a Credentials instance."""
        self.credentials = credentials

    def before_request(
        self,
        headers: collections.abc.MutableMapping[str, str | bytes],
    ) -> None:
        """Add common headers and calm-user-token cookie."""
        headers.update(_COMMON_HEADERS)

        # Prefer session token if available (required for some endpoints like favorites)
        if self.credentials.session_token:
            token = self.credentials.session_token
            headers["Cookie"] = f"calm-user-token={token}"
            headers["x-session-token"] = token
        # Fallback to JWT/legacy token
        elif self.credentials.token:
            headers["Cookie"] = f"calm-user-token={self.credentials.token}"

        if self.credentials.device_id:
            headers["x-device-id"] = self.credentials.device_id


def auth_for(credentials: Credentials) -> AuthStrategy:
    """Factory: pick the right auth strategy for the Calm API.

    The Calm web proxy authenticates via the ``calm-user-token`` cookie,
    regardless of whether the token is a JWT or a legacy token.
    ``BearerAuth`` is available for direct API access but is not the
    default.
    """
    return CookieAuth(credentials)

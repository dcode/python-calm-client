"""Main client module for Calm API interaction."""

from __future__ import annotations

from typing import Any

import httpx

from calm_client.auth import AuthStrategy, auth_for
from calm_client.credentials import Credentials
from calm_client.exceptions import CalmAPIError, CalmAuthError
from calm_client.logging import logger as logger
from calm_client.models import Feed, FeedResponse, PackItem, Program, ProgramResponse, SearchResponse

DEFAULT_CATEGORIES: list[tuple[str, str, str]] = [
    # (api_slug, emoji, display_name)
    ("home", "🏠", "Home"),
    ("sleep", "🌙", "Sleep"),
    ("meditate", "◎", "Meditate"),
    ("music", "♫", "Music"),
    ("work", "☕", "For Work"),
    ("wisdom", "💡", "Wisdom"),
    ("kids", "🧒", "Kids"),
    ("movement", "🏃", "Movement"),
    ("breathe", "🌬️", "Breathe"),
]


class CalmClient:
    """Async client for interacting with Calm.com internal API.

    Accepts either a ``Credentials`` object (full token lifecycle) or a raw
    token string (simple, no auto-refresh).

    Examples:
        Using a raw token::

            async with CalmClient("eyJ...") as client:
                feed = await client.get_feed("sleep")

        Using Credentials with auto-refresh::

            creds = Credentials.model_validate(saved_data)
            async with CalmClient(creds) as client:
                feed = await client.get_feed("sleep")  # auto-refreshes if expired
    """

    BASE_URL = "https://www.calm.com/webapi/authproxy"

    @staticmethod
    def resolve_image_url(url: str | None, width: int = 0, height: int = 0) -> str:
        """Resolve an image URL with optional resizing (for Contentful)."""
        if not url:
            return ""
        if "ctfassets.net" in url and (width or height):
            params = []
            if width:
                params.append(f"w={width}")
            if height:
                params.append(f"h={height}")
            # Check if url already has params
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}{'&'.join(params)}"
        return url

    def __init__(
        self,
        credentials: Credentials | str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        """Initialize the client.

        Args:
            credentials: A ``Credentials`` instance, a raw token string, or
                None for unauthenticated operations (e.g. login flow).
            client: An optional pre-configured ``httpx.AsyncClient``.
        """
        # Normalise input to a Credentials object
        if isinstance(credentials, str):
            self._credentials = Credentials.from_token(credentials)
        elif credentials is not None:
            self._credentials = credentials
        else:
            self._credentials = Credentials(token="")

        self._auth: AuthStrategy = auth_for(self._credentials)
        self._client = client or httpx.AsyncClient()

    @property
    def credentials(self) -> Credentials:
        """The current credentials (may have been refreshed)."""
        return self._credentials

    async def login(self, email: str, password: str) -> Credentials:
        """Login with email and password via Auth0 ROPC flow.

        Posts to Auth0's /oauth/token endpoint using the Resource Owner
        Password Grant with realm support. Returns full ``Credentials``
        including a refresh token (if granted).

        Raises:
            CalmAuthError: If Auth0 rejects the credentials or ROPC is disabled.
        """
        from .constants import (
            AUTH0_AUDIENCE,
            AUTH0_CLIENT_ID,
            AUTH0_CONNECTION,
            AUTH0_GRANT_TYPE,
            AUTH0_SCOPE,
            AUTH0_TOKEN_URL,
        )

        payload = {
            "grant_type": AUTH0_GRANT_TYPE,
            "client_id": AUTH0_CLIENT_ID,
            "username": email,
            "password": password,
            "realm": AUTH0_CONNECTION,
            "audience": AUTH0_AUDIENCE,
            "scope": AUTH0_SCOPE,
        }
        logger.debug(
            "login()|http_request",
            method="POST",
            url=AUTH0_TOKEN_URL,
            body=payload,
        )
        try:
            response = await self._client.post(
                AUTH0_TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise CalmAuthError(f"Network error during login: {e}") from e

        logger.debug(
            "login()|http_response",
            method="POST",
            url=AUTH0_TOKEN_URL,
            status=response.status_code,
            body=response.text[:200],
        )

        if response.status_code != 200:
            logger.error(
                "login()|http_response",
                method="POST",
                url=AUTH0_TOKEN_URL,
                status=response.status_code,
                body=response.text[:200],
            )
            try:
                err = response.json()
                desc = err.get("error_description", err.get("error", "Unknown error"))
            except Exception:
                desc = response.text[:200]
            raise CalmAuthError(f"Auth0 login failed: {desc}")

        data = response.json()
        if "access_token" not in data:
            raise CalmAuthError("Auth0 response did not contain an access_token.")

        # Preserve device_id if present in existing credentials
        existing_device_id = self._credentials.device_id if self._credentials else None

        # Construct Credentials directly from Auth0 response
        creds = Credentials(**data)

        if existing_device_id:
            creds.device_id = existing_device_id

        # Update internal state
        self._credentials = creds
        self._auth = auth_for(creds)

        # Attempt to get session token via web proxy
        await self._session_handshake(creds)

        return creds

    async def _session_handshake(self, credentials: Credentials) -> None:
        """Exchange Auth0 token for session token via web proxy."""
        # 1. Register device (best effort)
        try:
            # x-device-id is injected by AuthStrategy based on credentials.device_id
            await self._request("POST", "device")
        except Exception as e:
            logger.warning("device_registration_failed", error=str(e))

        # 2. Fetch session token from v2/me
        try:
            # We need to explicitly use Bearer auth to get the session token
            # (CookieAuth defaults to sending the JWT as a cookie, which might fail or be insufficient)
            headers = {"Authorization": f"Bearer {credentials.token}"}
            data = await self._request("GET", "v2/me", headers=headers)

            if token := data.get("token"):
                credentials.session_token = token
                logger.info("session_token_retrieved")
            else:
                logger.warning("v2_me_missing_token", response_keys=list(data.keys()))

        except Exception as e:
            logger.error("session_handshake_failed", error=str(e))
            # Non-fatal: user can still use basic features, but favorites won't work

    async def _ensure_valid_token(self) -> None:
        """Refresh the access token if expired and a refresh token exists."""
        if not self._credentials.valid and self._credentials.can_refresh:
            await self._credentials.refresh(self._client)
            self._auth = auth_for(self._credentials)

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        url = f"{self.BASE_URL}/{endpoint}"

        # Auto-refresh if needed
        await self._ensure_valid_token()

        # Build headers via auth strategy
        headers: dict[str, Any] = {}
        self._auth.before_request(headers)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        # Handle per-request cookies: only pass if explicitly provided
        cookies = kwargs.pop("cookies", None)

        try:
            request_kwargs: dict = {}
            if cookies:
                request_kwargs["cookies"] = cookies

            logger.debug(
                "http_request",
                method=method,
                url=url,
                headers=headers,
                body=kwargs.get("json") or kwargs.get("data"),
            )
            response = await self._client.request(
                method,
                url,
                headers=headers,
                **request_kwargs,
                **kwargs,
            )

            logger.debug(
                "http_response",
                method=method,
                url=url,
                status=response.status_code,
                body=response.text[:200],
            )

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.debug(
                "http_error",
                method=method,
                url=url,
                status=e.response.status_code,
                body=e.response.text[:200],
            )
            if e.response.status_code == 401:
                raise CalmAuthError("Invalid or expired token") from e
            raise CalmAPIError(f"API Error: {e}") from e

    async def get_feed(self, category: str) -> Feed:
        """Fetch a category feed (sleep, meditate, music, wisdom)."""
        logger.info("get_feed", category=category)
        data = await self._request("GET", f"packs/feeds/{category}")
        if "feed" in data:
            return Feed(**data["feed"])
        return Feed(**data)

    async def get_program(self, program_id: str) -> Program:
        """Fetch detailed program information."""
        logger.info("get_program", program_id=program_id)
        data = await self._request("GET", f"content/programs/{program_id}")
        response = ProgramResponse(**data)
        return response.program

    async def search(self, query: str) -> SearchResponse:
        """Search the catalog for the given query."""
        logger.info("search", query=query)
        data = await self._request("GET", "search/v2", params={"query": query})
        if "pack" in data:
            return SearchResponse(**data["pack"])
        return SearchResponse(**data)

    async def get_category_feed(self, category: str) -> FeedResponse:
        """Fetch the full category feed with all packs and items."""
        logger.info("get_category_feed", category=category)
        data = await self._request("GET", f"packs/feeds/{category}")
        if "feed" in data:
            return FeedResponse(**data["feed"])
        return FeedResponse(**data)

    async def get_favorites(self) -> list[PackItem]:
        """Aggregate all favorited items from across the platform."""
        logger.info("get_favorites")
        data = await self._request("GET", "packs/class/faves-hydrated")
        if "pack" not in data:
            return []

        from .models import Pack

        pack = Pack(**data["pack"])
        return pack.items

    async def close(self) -> None:
        """Close the underlying http client."""
        await self._client.aclose()

    async def aclose(self) -> None:
        """Alias for close."""
        await self.close()

    async def __aenter__(self) -> CalmClient:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the async context manager and close the client."""
        await self.close()

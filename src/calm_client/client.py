"""Main client module for Calm API interaction."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import aiohttp

from calm_client.auth import AuthStrategy, auth_for
from calm_client.constants import DEFAULT_USER_AGENT
from calm_client.credentials import Credentials, _auth0_error, _json_object
from calm_client.exceptions import (
    CalmAPIError,
    CalmAuthError,
    CalmConnectionError,
    CalmNotFoundError,
    CalmRateLimitError,
)
from calm_client.logging import logger as logger
from calm_client.models import (
    Feed,
    FeedResponse,
    Guide,
    GuideSummary,
    Pack,
    PackItem,
    Playlist,
    Program,
    ProgramResponse,
    SearchItem,
    SearchResponse,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_CATEGORIES: list[tuple[str, str, str]] = [
    # (api_slug, emoji, display_name)
    ("home", "🏠", "Home"),
    ("sleep", "🌙", "Sleep"),
    # every icon is a double-width emoji, so labels line up in a terminal
    ("meditate", "🧘", "Meditate"),
    ("music", "🎵", "Music"),
    # the app's "For Work"/"Kids" are the richer collection feeds, not the bare work/kids feeds
    ("collection-calm-for-work", "☕", "For Work"),
    ("wisdom", "💡", "Wisdom"),
    ("collection-calm-for-kids", "🧒", "Kids"),
    ("movement", "🏃", "Movement"),
    # "breathe" is omitted: its feed holds only breathe-bubble exercises, which have no audio to play
]

# Timeout for the session calm-client opens itself; a caller's session keeps its own.
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


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

        Sharing an application's aiohttp session::

            client = CalmClient(creds, session=app_session, user_agent="MyApp/1.0")
            feed = await client.get_feed("sleep")
            await client.close()  # leaves app_session open
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
        *,
        session: aiohttp.ClientSession | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            credentials: A ``Credentials`` instance, a raw token string, or
                None for unauthenticated operations (e.g. login flow).
            session: An aiohttp session to send requests with, such as an
                application's shared session. The caller owns it: ``close()``
                leaves it open. Without one, the client opens its own session on
                the first request and closes it in ``close()``.
            user_agent: The User-Agent to send. With a caller's session, None keeps
                that session's own User-Agent; without one, None sends
                ``DEFAULT_USER_AGENT``.
        """
        # Normalise input to a Credentials object
        if isinstance(credentials, str):
            self._credentials = Credentials.from_token(credentials)
        elif credentials is not None:
            self._credentials = credentials
        else:
            self._credentials = Credentials(token="")

        self._auth: AuthStrategy = auth_for(self._credentials)
        self._session = session
        self._owns_session = session is None
        self._user_agent = user_agent

    @property
    def session(self) -> aiohttp.ClientSession:
        """The aiohttp session requests go through, opened on first use when the client owns it."""
        if self._session is None:
            # created lazily: aiohttp needs a running event loop to build a session
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": self._user_agent or DEFAULT_USER_AGENT},
                timeout=DEFAULT_TIMEOUT,
            )
        return self._session

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Build per-request headers, adding the User-Agent only when the caller set one."""
        headers = dict(extra or {})
        if self._user_agent is not None:
            headers["User-Agent"] = self._user_agent
        return headers

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
            CalmConnectionError: If Auth0 cannot be reached.
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
            async with self.session.post(
                AUTH0_TOKEN_URL,
                json=payload,
                headers=self._headers({"Content-Type": "application/json"}),
            ) as response:
                status = response.status
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise CalmConnectionError(f"Network error during login: {e}") from e

        logger.debug(
            "login()|http_response",
            method="POST",
            url=AUTH0_TOKEN_URL,
            status=status,
            body=text[:200],
        )

        if status != 200:
            logger.error(
                "login()|http_response",
                method="POST",
                url=AUTH0_TOKEN_URL,
                status=status,
                body=text[:200],
            )
            raise CalmAuthError(f"Auth0 login failed: {_auth0_error(text)}")

        data = _json_object(text)
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
            await self._credentials.refresh(self.session, user_agent=self._user_agent)
            self._auth = auth_for(self._credentials)

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Send an authenticated request to the web proxy and return its JSON body.

        Raises:
            CalmAuthError: On HTTP 401, or when the token refresh is rejected.
            CalmNotFoundError: On HTTP 404.
            CalmRateLimitError: On HTTP 429.
            CalmAPIError: On any other HTTP error status.
            CalmConnectionError: When Calm cannot be reached or sends a body that is not JSON.
        """
        url = f"{self.BASE_URL}/{endpoint}"

        # Auto-refresh if needed
        await self._ensure_valid_token()

        # Build headers via auth strategy
        headers: dict[str, Any] = {}
        self._auth.before_request(headers)
        headers.update(self._headers(kwargs.pop("headers", None)))

        # Handle per-request cookies: only pass if explicitly provided
        cookies = kwargs.pop("cookies", None)
        if cookies:
            kwargs["cookies"] = cookies

        logger.debug(
            "http_request",
            method=method,
            url=url,
            headers=headers,
            body=kwargs.get("json") or kwargs.get("data"),
        )
        try:
            async with self.session.request(method, url, headers=headers, **kwargs) as response:
                status = response.status
                text = await response.text()
                retry_after = _retry_after(response.headers)
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.debug("http_transport_error", method=method, url=url, error=repr(e))
            raise CalmConnectionError(f"Network error on {method} {endpoint}: {e!r}") from e

        logger.debug("http_response", method=method, url=url, status=status, body=text[:200])

        if status >= 400:
            message = f"API Error: HTTP {status} on {method} {endpoint}"
            if status == 401:
                raise CalmAuthError("Invalid or expired token")
            if status == 404:
                raise CalmNotFoundError(message, status=status)
            if status == 429:
                raise CalmRateLimitError(message, retry_after=retry_after)
            raise CalmAPIError(message, status=status)

        try:
            return json.loads(text)
        except ValueError as e:
            raise CalmConnectionError(f"Invalid JSON from {method} {endpoint}: {text[:200]!r}", status=status) from e

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

    async def search(self, query: str, *, category: str | None = None, duration: str | None = None) -> SearchResponse:
        """Search the catalog, optionally scoped by one category and/or duration.

        ``category`` and ``duration`` take a single option id from ``search/v2/config``
        (e.g. ``narrators_artists``, ``soundscapes``; ``ten_min``, ``sixty_plus_min``).
        The API ignores an unknown value and rejects multiple, so only one of each is
        supported. Results are a single ranked page (~200 max); there is no pagination.
        """
        logger.info("search", query=query, category=category, duration=duration)
        params = {"query": query}
        if category:
            params["category"] = category
        if duration:
            params["duration"] = duration
        data = await self._request("GET", "search/v2", params=params)
        if "pack" in data:
            return SearchResponse(**data["pack"])
        return SearchResponse(**data)

    async def list_narrators(self, query: str = "") -> list[SearchItem]:
        """Search narrators and artists, scoped to the ``narrators_artists`` category.

        Calm has no narrator index. An empty query returns the "Narrators & Artists"
        catalog, but search is capped (~200 hits, alphabetical), so it is a starter set,
        not the whole roster — pass a name to find anyone. Each item is a ``FOLDER``
        whose ``path`` opens the narrator's feed; tell narrators from artists by
        ``content_type``.
        """
        logger.info("list_narrators", query=query)
        results = await self.search(query, category="narrators_artists")
        return [item for item in results.items if item.item_type == "narrator"]

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

        pack = Pack(**data["pack"])
        return pack.items

    async def get_pack(self, pack_class: str) -> Pack:
        """Fetch a pack (e.g. a row of a feed) with all of its items."""
        logger.info("get_pack", pack_class=pack_class)
        data = await self._request("GET", f"packs/class/{pack_class}")
        return Pack.model_validate(data.get("pack", data))

    async def get_playlists(self) -> list[Playlist]:
        """Fetch the user's playlists ("My Collections"). Requires authentication."""
        logger.info("get_playlists")
        data = await self._request("GET", "content/playlist")
        return [Playlist.model_validate(p) for p in data]

    async def add_fave(
        self,
        *,
        guide_id: str | None = None,
        program_id: str | None = None,
        feed_id: str | None = None,
        pack_class: str | None = None,
        content_id: str | None = None,
    ) -> None:
        """Favorite a guide, program, feed, pack or content item. Pass exactly one id."""
        await self._fave("POST", guide_id, program_id, feed_id, pack_class, content_id)

    async def remove_fave(
        self,
        *,
        guide_id: str | None = None,
        program_id: str | None = None,
        feed_id: str | None = None,
        pack_class: str | None = None,
        content_id: str | None = None,
    ) -> None:
        """Remove a favorite. Pass exactly one id, matching ``add_fave``."""
        await self._fave("DELETE", guide_id, program_id, feed_id, pack_class, content_id)

    async def _fave(
        self,
        method: str,
        guide_id: str | None,
        program_id: str | None,
        feed_id: str | None,
        pack_class: str | None,
        content_id: str | None,
    ) -> None:
        """Add or remove a favorite via the endpoint that matches the content type."""
        body = {
            k: v
            for k, v in (
                ("guide_id", guide_id),
                ("program_id", program_id),
                ("feed_id", feed_id),
                ("pack_class", pack_class),
                ("content_id", content_id),
            )
            if v is not None
        }
        if len(body) != 1:
            raise ValueError("Pass exactly one of guide_id, program_id, feed_id, pack_class, content_id")
        logger.info("fave", method=method, **body)
        # guides have a dedicated path (no body); everything else uses the generic /faves
        if guide_id is not None:
            await self._request(method, f"programs/guides/{guide_id}/faves")
        else:
            await self._request(method, "faves", json=body)

    async def get_guide_summary(self, guide_id: str) -> GuideSummary:
        """Fetch a guide's summary: the program it belongs to and its lock flags."""
        logger.info("get_guide_summary", guide_id=guide_id)
        data = await self._request("GET", f"programs/guides/{guide_id}")
        return GuideSummary.model_validate(data)

    async def get_guide(self, guide_id: str) -> tuple[Guide, Program]:
        """Fetch a guide with its assets, together with the program it belongs to.

        Program detail responses carry no lock flags, so the guide summary's flags are
        copied onto the returned program; check playability with
        ``is_available(guide, program)``.

        Raises:
            CalmNotFoundError: If the guide does not exist, or is not part of the program
                Calm names for it.
        """
        summary = await self.get_guide_summary(guide_id)
        program = await self.get_program(summary.program_id or summary.id)
        for flag in ("is_unlocked", "is_free"):
            if flag in summary.model_fields_set:
                setattr(program, flag, getattr(summary, flag))
        for guide in program.guides:
            if guide.id == guide_id:
                return guide, program
        raise CalmNotFoundError(f"Guide {guide_id} not found in program {program.id}")

    async def browse(self, path: str = "") -> list[PackItem]:
        """List the entries at a browse path, as a tree any integration can walk.

        - ``""``: the categories in ``DEFAULT_CATEGORIES``, as feed entries
        - ``"feed/<feed_id>"``: the feed's packs that hold guides or programs, then its tags
        - ``"pack/<pack_class>"``: the pack's items

        Guides and programs come back as they are; sub-feeds and sub-packs have a
        ``path`` to browse next. Check each entry's ``media_type``.

        Raises:
            ValueError: If the path is not one of the forms above.
        """
        kind, _, ident = path.partition("/")
        if not path:
            return [PackItem(type="feed", feed_id=slug, title=name) for slug, _, name in DEFAULT_CATEGORIES]
        if kind == "feed" and ident:
            feed = await self.get_category_feed(ident)
            entries = [
                PackItem(type="pack", pack_class=pack.pack_class, title=pack.title)
                for pack in feed.packs
                if pack.pack_class and pack.title and pack.has_playable_items
            ]
            for tag in feed.tags:
                if tag.title and tag.feed_id:
                    entries.append(PackItem(type="feed", feed_id=tag.feed_id, title=tag.title))
                elif tag.title and tag.pack_class:
                    entries.append(PackItem(type="pack", pack_class=tag.pack_class, title=tag.title))
            return entries
        if kind == "pack" and ident:
            return (await self.get_pack(ident)).items
        raise ValueError(f"Not a Calm browse path: {path!r}")

    async def close(self) -> None:
        """Close the HTTP session if the client opened it; a caller's session stays open."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

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


def _retry_after(headers: Mapping[str, str]) -> float | None:
    """Return the ``Retry-After`` wait in seconds, or None when absent or not a number."""
    try:
        return max(0.0, float(headers["Retry-After"]))
    except (KeyError, ValueError):
        return None

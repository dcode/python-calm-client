"""Main client module for Calm API interaction."""

from __future__ import annotations

from typing import Any

import httpx

from calm_client.auth import AuthStrategy, auth_for
from calm_client.credentials import Credentials
from calm_client.exceptions import CalmAPIError, CalmAuthError
from calm_client.logging import logger as logger
from calm_client.models import (
    CalmAlbum,
    CalmBaseItem,
    CalmFeed,
    CalmFolder,
    CalmTrack,
    ProgramResponse,
    SearchResponse,
)


class CalmClient:
    """Async client for interacting with Calm.com internal API."""

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
        """Initialize the client."""
        # Normalize input to a Credentials object
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
        """Login with email and password via Auth0 ROPC flow."""
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
        try:
            response = await self._client.post(
                AUTH0_TOKEN_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise CalmAuthError(f"Network error during login: {e}") from e

        if response.status_code != 200:
            try:
                err = response.json()
                desc = err.get("error_description", err.get("error", "Unknown error"))
            except Exception:
                desc = response.text[:200]
            raise CalmAuthError(f"Auth0 login failed: {desc}")

        data = response.json()
        if "access_token" not in data:
            raise CalmAuthError("Auth0 response did not contain an access_token.")

        existing_device_id = self._credentials.device_id if self._credentials else None
        creds = Credentials(**data)
        if existing_device_id:
            creds.device_id = existing_device_id

        self._credentials = creds
        self._auth = auth_for(creds)
        await self._session_handshake(creds)
        return creds

    async def _session_handshake(self, credentials: Credentials) -> None:
        """Exchange Auth0 token for session token via web proxy."""
        try:
            await self._request("POST", "device")
        except Exception:
            pass

        try:
            headers = {"Authorization": f"Bearer {credentials.token}"}
            data = await self._request("GET", "v2/me", headers=headers)
            if token := data.get("token"):
                credentials.session_token = token
        except Exception:
            pass

    async def _ensure_valid_token(self) -> None:
        """Refresh the access token if expired."""
        if not self._credentials.valid and self._credentials.can_refresh:
            await self._credentials.refresh(self._client)
            self._auth = auth_for(self._credentials)

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        url = f"{self.BASE_URL}/{endpoint}"
        await self._ensure_valid_token()
        headers: dict[str, Any] = {}
        self._auth.before_request(headers)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        cookies = kwargs.pop("cookies", None)
        try:
            request_kwargs: dict = {}
            if cookies:
                request_kwargs["cookies"] = cookies
            response = await self._client.request(
                method, url, headers=headers, **request_kwargs, **kwargs
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise CalmAuthError("Invalid or expired token") from e
            raise CalmAPIError(f"API Error: {e}") from e

    async def get_home_feed(self) -> CalmFeed:
        """Fetch the root home feed."""
        data = await self._request("GET", "packs/feeds/home")
        if "feed" in data:
            return CalmFeed.model_validate(data["feed"])
        return CalmFeed.model_validate(data)

    async def get_feed(self, category: str) -> CalmFeed:
        """Fetch a category feed."""
        data = await self._request("GET", f"packs/feeds/{category}")
        if "feed" in data:
            return CalmFeed.model_validate(data["feed"])
        return CalmFeed.model_validate(data)

    async def get_program(self, program_id: str) -> CalmAlbum:
        """Fetch detailed program/album information."""
        data = await self._request("GET", f"content/programs/{program_id}")
        return ProgramResponse(**data).program

    async def get_guide_program(self, guide_id: str) -> CalmAlbum:
        """Fetch the program containing a specific guide."""
        data = await self._request("GET", f"content/programs/guides/{guide_id}")
        return ProgramResponse(**data).program

    async def search(self, query: str) -> SearchResponse:
        """Search the catalog."""
        data = await self._request("GET", "search/v2", params={"query": query})
        if "pack" in data:
            return SearchResponse.model_validate(data["pack"])
        return SearchResponse.model_validate(data)

    async def get_favorites(self) -> list[CalmTrack | CalmAlbum]:
        """Aggregate all favorited items."""
        data = await self._request("GET", "packs/class/faves-hydrated")
        if "pack" not in data:
            return []
        folder = CalmFolder.model_validate(data["pack"])
        return [i for i in folder.items if isinstance(i, (CalmTrack, CalmAlbum))]

    async def get_pack(self, pack_id: str) -> CalmFolder:
        """Fetch a specific pack by ID."""
        data = await self._request("GET", f"packs/class/{pack_id}")
        if "pack" in data:
            return CalmFolder.model_validate(data["pack"])
        return CalmFolder.model_validate(data)

    async def browse(self, path: str = "") -> list[CalmTrack | CalmAlbum | CalmFolder | CalmBaseItem]:
        """Browse the Calm catalog hierarchies."""
        if not path:
            home = await self.get_home_feed()
            results = []
            # Dailies
            for pack in home.packs:
                if pack.pack_class == "top-of-home-carousel":
                    results.extend(pack.items)
            # Folders
            results.append(CalmFolder(id="categories", title="Categories", type="feed"))
            results.append(CalmFolder(id="recommendations", title="Recommendations", type="feed"))
            results.append(CalmFolder(id="favorites", title="Favorites", type="feed"))
            return results

        if path == "categories":
            home = await self.get_home_feed()
            for pack in home.packs:
                if pack.pack_class == "quick-nav":
                    items = []
                    for it in pack.items:
                        # Prefix feed IDs to differentiate them in browse
                        it.id = f"feed:{it.id}"
                        items.append(it)
                    return items
            return []

        if path == "recommendations":
            home = await self.get_home_feed()
            exclude = {"top-of-home-carousel", "quick-nav", "recently-completed", "faves", "faves-collections"}
            items = []
            for pack in home.packs:
                if pack.pack_class not in exclude:
                    pack.id = f"pack:{pack.id}"
                    items.append(pack)
            return items

        if path == "favorites":
            return await self.get_favorites()

        if path.startswith("feed:"):
            slug = path.split(":", 1)[1]
            feed = await self.get_feed(slug)
            items = []
            for pack in feed.packs:
                pack.id = f"pack:{pack.id}"
                items.append(pack)
            return items

        if path.startswith("pack:"):
            pack_id = path.split(":", 1)[1]
            pack = await self.get_pack(pack_id)
            return pack.items

        return []

    async def close(self) -> None:
        """Close the client."""
        await self._client.aclose()

    async def aclose(self) -> None:
        """Alias for close."""
        await self.close()

    async def __aenter__(self) -> CalmClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.close()

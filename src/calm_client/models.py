"""Pydantic models for Calm API entities."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Asset(BaseModel):
    """Represents a media asset (audio/video file)."""

    url: str
    content_type: str
    duration: float


class Guide(BaseModel):
    """Represents a guide or track within a program."""

    id: str
    title: str
    assets: list[Asset] = Field(default_factory=list)

    @property
    def stream_url(self) -> str | None:
        """Return the URL of the first available asset (preferring audio/m4a or wav)."""
        # Simple heuristic: take the first one.
        # In production, we might want to filter by content_type.
        if not self.assets:
            return None
        return self.assets[0].url


class Program(BaseModel):
    """Represents a full program or album."""

    id: str
    title: str
    description: str | None = None
    guides: list[Guide] = Field(default_factory=list)

    @property
    def first_stream_url(self) -> str | None:
        """Return the stream URL of the first guide in the program."""
        if not self.guides:
            return None
        return self.guides[0].stream_url


class FeedItem(BaseModel):
    """Represents an item in a content feed."""

    id: str
    title: str
    subtitle: str | None = None
    image_url: str | None = None
    item_type: str = Field(alias="type")  # e.g., 'program', 'single'


class Feed(BaseModel):
    """Represents a category feed (Sleep, Meditate, etc.).

    Current feeds group their content in ``packs``; older responses listed ``items``
    directly. Both are accepted.
    """

    items: list[FeedItem] = Field(default_factory=list)
    packs: list[Pack] = Field(default_factory=list)
    next_page_url: str | None = None


class ProgramResponse(BaseModel):
    """API Response for a generic program request."""

    program: Program


class SearchItem(BaseModel):
    """Represents an item in search results."""

    model_config = ConfigDict(populate_by_name=True)

    program_id: str | None = None
    title: str
    subtitle: str | None = None
    item_type: str = Field(default="unknown", alias="type")
    search_category: str | None = None
    content_type: str | None = None
    content_id: str | None = None
    narrator_name: str | None = None
    is_new: bool = False
    is_unlocked: bool = False


class SearchResponse(BaseModel):
    """API Response for search/v2 results.

    The API returns ``{pack: {items: [...], total_item_number: N, ...}}``.
    """

    items: list[SearchItem] = Field(default_factory=list)
    total_item_number: int = 0
    has_more: bool = False


# ------------------------------------------------------------------
# Feed / Browse models
# ------------------------------------------------------------------


class ImageAsset(BaseModel):
    """Image metadata returned inline on feed items."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = ""
    width: int = 0
    height: int = 0


class PackItemAsset(BaseModel):
    """An audio/video asset attached to a pack item."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = ""
    content_type: str = ""
    duration: float = 0.0


class PackItem(BaseModel):
    """A single content item inside a Pack (guide, program, etc.)."""

    model_config = ConfigDict(populate_by_name=True)

    guide_id: str | None = None
    program_id: str | None = None
    title: str = ""
    subtitle: str | None = None
    item_type: str = Field(default="unknown", alias="type")
    search_category: str | None = None
    narrator_name: str | None = None
    content_id: str | None = None
    image: ImageAsset | None = None
    assets: list[PackItemAsset] = Field(default_factory=list)
    is_new: bool = False
    is_unlocked: bool = False

    @property
    def display_id(self) -> str:
        """Return the best available identifier for display."""
        return self.program_id or self.guide_id or self.content_id or ""

    @property
    def duration_str(self) -> str:
        """Return a human-readable duration string."""
        if not self.assets:
            return ""
        secs = self.assets[0].duration
        if secs <= 0:
            return ""
        mins = int(secs // 60)
        if mins >= 60:
            return f"{mins // 60}h {mins % 60}m"
        return f"{mins}m"


class Pack(BaseModel):
    """A named group of items within a category feed."""

    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    pack_class: str = ""
    display_type: str | None = None
    items: list[PackItem] = Field(default_factory=list)
    has_more: bool = False
    total_item_number: int = 0
    is_faveable: bool = False


class FeedResponse(BaseModel):
    """Full category feed as returned by ``packs/feeds/<category>``."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    title: str = ""
    subtitle: str | None = None
    packs: list[Pack] = Field(default_factory=list)


Feed.model_rebuild()

Track = Guide

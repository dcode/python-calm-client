"""Pydantic models for Calm API entities."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MediaType(StrEnum):
    """Media types aligned with Music Assistant and Calm concepts."""

    TRACK = "track"
    ALBUM = "album"
    PLAYLIST = "playlist"
    FOLDER = "folder"
    FEED = "feed"
    UNKNOWN = "unknown"


class CalmImage(BaseModel):
    """Image metadata returned by the Calm API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    url: str
    width: int | None = None
    height: int | None = None
    content_type: str | None = None
    dominant_colors: list[str] = Field(default_factory=list)


class CalmAsset(BaseModel):
    """Audio/Video asset attached to a track or guide."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    url: str
    content_type: str
    duration: float = 0.0
    size: int | None = None


class CalmBaseItem(BaseModel):
    """Base representation of any item in the Calm catalog."""

    model_config = ConfigDict(populate_by_name=True)

    # Calm uses 'content_id', 'id', 'guide_id', 'program_id', 'feed_id' etc.
    id: str = Field(validation_alias=AliasChoices("content_id", "id", "guide_id", "program_id", "feed_id"))
    title: str = Field(default="")
    subtitle: str | None = None
    item_type: str = Field(alias="type", default="unknown")
    image: CalmImage | None = None
    is_new: bool = False
    is_unlocked: bool = True
    search_category: str | None = None

    @property
    def media_type(self) -> MediaType:
        """Heuristic to determine the media type for external consumers."""
        if self.item_type == "guide":
            return MediaType.TRACK
        if self.item_type == "program":
            return MediaType.ALBUM
        if self.item_type in ("feed", "pack", "collection"):
            return MediaType.FOLDER
        return MediaType.UNKNOWN


class CalmTrack(CalmBaseItem):
    """A single playable piece of content (often a 'guide')."""

    item_type: Literal["guide", "single"] = Field(alias="type", default="guide")
    guide_id: str | None = None
    program_id: str | None = None
    narrator_name: str | None = None
    duration: float = 0.0
    assets: list[CalmAsset] = Field(default_factory=list)
    content_type: str | None = None

    @property
    def stream_url(self) -> str | None:
        """Return the best available stream URL."""
        if not self.assets:
            return None
        for asset in self.assets:
            if "m4a" in asset.url or asset.content_type == "audio/mp4":
                return asset.url
        return self.assets[0].url

    @property
    def duration_str(self) -> str:
        """Return a human-readable duration string."""
        if self.duration <= 0:
            return ""
        mins = int(self.duration // 60)
        if mins >= 60:
            return f"{mins // 60}h {mins % 60}m"
        return f"{mins}m"


class CalmAlbum(CalmBaseItem):
    """A collection of tracks (often a 'program')."""

    item_type: Literal["program"] = Field(alias="type", default="program")
    program_id: str | None = None
    description: str | None = None
    narrator_name: str | None = None
    content_type: str | None = None
    guides: list[CalmTrack] = Field(default_factory=list)

    @property
    def media_type(self) -> MediaType:
        """Heuristic for programs."""
        if self.content_type in ("Playlist", "Music"):
            return MediaType.PLAYLIST
        if len(self.guides) == 1 and self.content_type not in ("Course", "Series"):
            return MediaType.TRACK
        return MediaType.ALBUM


class CalmFolder(CalmBaseItem):
    """A container for other items (often a 'pack' or 'feed')."""

    item_type: Literal["feed", "pack", "unknown"] = Field(alias="type", default="unknown")
    pack_class: str | None = None
    items: list[Union[CalmTrack, CalmAlbum, CalmFolder, CalmBaseItem]] = Field(default_factory=list)
    total_item_number: int = 0
    has_more: bool = False
    next_page_url: str | None = None

    @property
    def media_type(self) -> MediaType:
        return MediaType.FOLDER


class CalmFeed(BaseModel):
    """The root structure of a category or home feed."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    title: str | None = None
    subtitle: str | None = None
    packs: list[CalmFolder] = Field(default_factory=list)


class ProgramResponse(BaseModel):
    """API Response for a program request."""

    program: CalmAlbum


class SearchResponse(BaseModel):
    """API Response for search results."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[Union[CalmTrack, CalmAlbum, CalmBaseItem]] = Field(default_factory=list)
    total_item_number: int = 0
    has_more: bool = False


def parse_item(data: dict[str, Any]) -> CalmTrack | CalmAlbum | CalmFolder | CalmBaseItem:
    """Polymorphic parser for Calm items."""
    item_type = data.get("type")
    if item_type in ("guide", "single"):
        return CalmTrack.model_validate(data)
    if item_type == "program":
        return CalmAlbum.model_validate(data)
    if item_type in ("feed", "pack"):
        return CalmFolder.model_validate(data)
    return CalmBaseItem.model_validate(data)

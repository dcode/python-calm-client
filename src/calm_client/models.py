"""Pydantic models for Calm API entities."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable


class MediaType(StrEnum):
    """What a catalog entry is, in terms an integration can map to its own types."""

    TRACK = "track"  # a guide: one playable session or song
    ALBUM = "album"  # a program: an ordered set of guides
    FOLDER = "folder"  # a sub-feed or sub-pack: more entries to browse
    UNKNOWN = "unknown"  # promos, links, check-ins and other entries without audio


# preferred audio formats, compressed first to save bandwidth
_AUDIO_PREFERENCE = {"audio/mp4": 0, "audio/mpeg": 1, "audio/ogg": 2, "audio/wav": 3}


class Lockable(BaseModel):
    """Calm's per-account lock flags; some responses spell them ``unlocked``/``free``."""

    model_config = ConfigDict(populate_by_name=True)

    is_unlocked: bool = Field(default=False, validation_alias=AliasChoices("is_unlocked", "unlocked"))
    is_free: bool = Field(default=False, validation_alias=AliasChoices("is_free", "free"))

    @property
    def is_available(self) -> bool:
        """Return whether Calm reports this entry as playable for the account."""
        return is_available(self)


def is_available(*sources: Lockable) -> bool:
    """Return whether the content described by ``sources`` is playable for the account.

    Pass a guide together with its program: either being unlocked or free is enough.
    Program detail responses carry no lock flags at all, so content counts as
    available when no source reported ``is_unlocked``.
    """
    if any(source.is_unlocked or source.is_free for source in sources):
        return True
    return not any("is_unlocked" in source.model_fields_set for source in sources)


class ImageAsset(BaseModel):
    """Image metadata returned inline on feed items."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = ""
    width: int = 0
    height: int = 0


class Asset(BaseModel):
    """Represents a media asset (audio/video file)."""

    url: str
    content_type: str = ""
    duration: float = 0.0


def _best_audio[T: (Asset, PackItemAsset)](assets: Iterable[T]) -> T | None:
    """Return the preferred audio asset, ignoring video and assets without a URL."""
    audio = [a for a in assets if a.url and a.content_type.startswith("audio/")]
    return min(audio, key=lambda a: _AUDIO_PREFERENCE.get(a.content_type, 9), default=None)


def _duration[T: (Asset, PackItemAsset)](assets: Iterable[T]) -> float:
    """Return the length in seconds of the preferred audio asset, else of the first asset."""
    assets = list(assets)
    if audio := _best_audio(assets):
        return audio.duration
    return assets[0].duration if assets else 0.0


class Guide(Lockable):
    """Represents a guide or track within a program."""

    id: str
    title: str
    position: int = 0
    narrator_id: str | None = None
    narrator_name: str | None = None
    assets: list[Asset] = Field(default_factory=list)

    @property
    def audio_asset(self) -> Asset | None:
        """Return the preferred audio asset (compressed formats over wav, never video)."""
        return _best_audio(self.assets)

    @property
    def stream_url(self) -> str | None:
        """Return the URL of the preferred audio asset, else of the first asset."""
        if asset := self.audio_asset:
            return asset.url
        if not self.assets:
            return None
        return self.assets[0].url

    @property
    def duration(self) -> float:
        """Return the length in seconds (the preferred audio asset's), 0.0 when unknown."""
        return _duration(self.assets)

    @property
    def artist(self) -> Narrator | None:
        """Return the narrator or composer credited on the guide, if any."""
        if not self.narrator_name:
            return None
        return Narrator(id=self.narrator_id, name=self.narrator_name)


class Narrator(BaseModel):
    """The narrator or composer credited on a program."""

    id: str | None = None
    name: str
    headshot: ImageAsset | None = None

    @property
    def image_url(self) -> str | None:
        """Return the headshot URL, if there is one."""
        return self.headshot.url if self.headshot and self.headshot.url else None


class Program(Lockable):
    """Represents a full program or album.

    Program detail responses carry no lock flags; ``CalmClient.get_guide`` copies them
    over from the guide summary.
    """

    id: str
    title: str
    description: str | None = None
    narrator: Narrator | str | None = None
    narrator_id: str | None = None
    cell_image: ImageAsset | None = None
    untitled_cell_image: ImageAsset | None = None
    image: ImageAsset | None = None
    background_image: ImageAsset | None = None
    guides: list[Guide] = Field(default_factory=list)

    @property
    def first_stream_url(self) -> str | None:
        """Return the stream URL of the first guide in the program."""
        if not self.guides:
            return None
        return self.guides[0].stream_url

    @property
    def narrator_name(self) -> str | None:
        """Return the narrator's name, whether the response gave an object or a string."""
        if isinstance(self.narrator, Narrator):
            return self.narrator.name
        return self.narrator or None

    @property
    def artist(self) -> Narrator | None:
        """Return the narrator or composer, whether the response gave an object or a string."""
        if isinstance(self.narrator, Narrator):
            return self.narrator
        if self.narrator:
            return Narrator(id=self.narrator_id, name=self.narrator)
        return None

    @property
    def image_url(self) -> str | None:
        """Return the best cover image URL, if any."""
        for image in (self.cell_image, self.untitled_cell_image, self.image, self.background_image):
            if image and image.url:
                return image.url
        return None

    @property
    def sorted_guides(self) -> list[Guide]:
        """Return the guides in position order."""
        return sorted(self.guides, key=lambda guide: guide.position)


class GuideSummary(Lockable):
    """Calm's per-guide summary (``programs/guides/<id>``): its program and lock flags."""

    id: str
    program_id: str | None = None
    title: str | None = None


class FeedItem(BaseModel):
    """Represents an item in a content feed."""

    id: str
    title: str
    subtitle: str | None = None
    image_url: str | None = None
    item_type: str = Field(alias="type")  # e.g., 'program', 'single'


class FeedTag(BaseModel):
    """A link from a feed to a sub-feed or pack (e.g. "Sleep Stories" under Sleep)."""

    title: str = ""
    feed_id: str | None = None
    pack_class: str | None = None

    @property
    def path(self) -> str | None:
        """Return the ``CalmClient.browse`` path this tag leads to."""
        if self.feed_id:
            return f"feed/{self.feed_id}"
        if self.pack_class:
            return f"pack/{self.pack_class}"
        return None


class Feed(BaseModel):
    """Represents a category feed (Sleep, Meditate, etc.).

    Current feeds group their content in ``packs``; older responses listed ``items``
    directly. Both are accepted.
    """

    items: list[FeedItem] = Field(default_factory=list)
    packs: list[Pack] = Field(default_factory=list)
    tags: list[FeedTag] = Field(default_factory=list)
    next_page_url: str | None = None


class ProgramResponse(BaseModel):
    """API Response for a generic program request."""

    program: Program


# ------------------------------------------------------------------
# Feed / Browse models
# ------------------------------------------------------------------


class PackItemAsset(BaseModel):
    """An audio/video asset attached to a pack item."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = ""
    content_type: str = ""
    duration: float = 0.0


class PackItem(Lockable):
    """A single content item inside a Pack: a guide, program, sub-pack or sub-feed."""

    guide_id: str | None = None
    program_id: str | None = None
    feed_id: str | None = None
    pack_class: str | None = None
    narrator_id: str | None = None
    title: str = ""
    subtitle: str | None = None
    item_type: str = Field(default="unknown", alias="type")
    search_category: str | None = None
    narrator_name: str | None = None
    content_id: str | None = None
    content_type: str | None = None
    image: ImageAsset | None = None
    assets: list[PackItemAsset] = Field(default_factory=list)
    is_new: bool = False

    @property
    def display_id(self) -> str:
        """Return the best available identifier for display."""
        return self.program_id or self.guide_id or self.content_id or self.pack_class or self.feed_id or ""

    @property
    def media_type(self) -> MediaType:
        """Classify the item; an entry missing the id its type needs counts as unknown."""
        if self.item_type == "guide" and self.guide_id:
            return MediaType.TRACK
        if self.item_type == "program" and self.program_id:
            return MediaType.ALBUM
        if self.path:
            return MediaType.FOLDER
        return MediaType.UNKNOWN

    @property
    def path(self) -> str | None:
        """Return the ``CalmClient.browse`` path of a sub-feed, sub-pack or narrator item."""
        if self.item_type == "feed" and self.feed_id:
            return f"feed/{self.feed_id}"
        if self.item_type == "pack" and self.pack_class:
            return f"pack/{self.pack_class}"
        # a narrator/artist is browsable as the feed packs/feeds/narrator-<id>
        if self.item_type == "narrator" and self.narrator_id:
            return f"feed/narrator-{self.narrator_id}"
        return None

    @property
    def audio_asset(self) -> PackItemAsset | None:
        """Return the preferred audio asset (compressed formats over wav, never video)."""
        return _best_audio(self.assets)

    @property
    def image_url(self) -> str | None:
        """Return the cover image URL, if the item has one."""
        return self.image.url if self.image and self.image.url else None

    @property
    def artist(self) -> Narrator | None:
        """Return the narrator or composer credited on the item, if any."""
        if not self.narrator_name:
            return None
        return Narrator(id=self.narrator_id, name=self.narrator_name)

    @property
    def display_subtitle(self) -> str:
        """Return the line to show under the title: the narrator, else the subtitle."""
        return self.narrator_name or self.subtitle or ""

    @property
    def duration(self) -> float:
        """Return the length in seconds (the preferred audio asset's), 0.0 when unknown."""
        return _duration(self.assets)

    @property
    def duration_str(self) -> str:
        """Return a human-readable duration string."""
        secs = self.duration
        if secs <= 0:
            return ""
        mins = int(secs // 60)
        if mins >= 60:
            return f"{mins // 60}h {mins % 60}m"
        return f"{mins}m"


class SearchItem(PackItem):
    """Represents an item in search results (the same shape as a pack item)."""

    title: str


class SearchResponse(BaseModel):
    """API Response for search/v2 results.

    The API returns ``{pack: {items: [...], total_item_number: N, ...}}``.
    """

    items: list[SearchItem] = Field(default_factory=list)
    total_item_number: int = 0
    has_more: bool = False


class Pack(BaseModel):
    """A named group of items within a category feed.

    A pack embedded in a feed holds only a preview of its items (about 10); when
    ``has_more`` is set, fetch the rest with ``CalmClient.get_pack(pack_class)``.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    pack_class: str = ""
    content_description: str | None = None
    display_type: str | None = None
    # "client" packs (favorites, recently played, collections) arrive empty: apps fill them in
    evaluation_type: str | None = None
    items: list[PackItem] = Field(default_factory=list)
    has_more: bool = False
    total_item_number: int = 0
    is_faveable: bool = False

    @property
    def has_playable_items(self) -> bool:
        """Return whether the pack holds guides or programs (rather than only promos)."""
        return any(item.media_type in (MediaType.TRACK, MediaType.ALBUM) for item in self.items)

    @property
    def has_content(self) -> bool:
        """Return whether the pack holds anything to open: a guide, program or sub-folder.

        Rows that are only links, breathe bubbles or text (e.g. "Resources") have none.
        """
        return any(item.media_type is not MediaType.UNKNOWN for item in self.items)


class FeedResponse(BaseModel):
    """Full category feed as returned by ``packs/feeds/<category>``."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    title: str = ""
    subtitle: str | None = None
    packs: list[Pack] = Field(default_factory=list)
    tags: list[FeedTag] = Field(default_factory=list)


class PlaylistItem(BaseModel):
    """An entry in a user playlist: a reference to a guide, not a hydrated item.

    Playlists store only ids; use ``CalmClient.get_guide`` to resolve titles and audio.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: str = "guide"
    guide_id: str | None = None
    program_id: str | None = None


class Playlist(BaseModel):
    """A user-created playlist ("My Collections" in the apps)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str = ""
    items: list[PlaylistItem] = Field(default_factory=list)
    user_id: str | None = None
    cover_image_asset_id: str | None = None
    image: ImageAsset | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def image_url(self) -> str | None:
        """Return the cover image URL, if the playlist has one."""
        return self.image.url if self.image and self.image.url else None


Feed.model_rebuild()

Track = Guide

"""Interactive TUI for browsing the Calm catalog.

Launched via ``calm browse``.  Uses `textual` for the full-screen interface.
Provides a catalog-style grid with thumbnail cards, drill-down navigation,
and an inline audio player with playback controls.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from rich.cells import cell_len
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, ProgressBar, Static

from .client import DEFAULT_CATEGORIES
from .models import FeedResponse, Guide, MediaType, Pack, PackItem, PackItemAsset, Playlist, Program, SearchItem

if TYPE_CHECKING:
    from .client import CalmClient
    from .player import CalmPlayer

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Categories available in the Calm API
# ------------------------------------------------------------------

CATEGORIES = DEFAULT_CATEGORIES
# the feed pack the apps fill with the account's favorites
FAVES_PACK = "faves"


def _wrap(text: str, width: int, *, max_lines: int) -> list[str]:
    """Wrap text to at most max_lines, ellipsizing the last line when it overflows."""
    width = max(width, 4)
    lines = textwrap.wrap(text, width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last[: width - 1].rstrip() + "…") if len(last) >= width - 1 else last + "…"
    return lines


# the feed pack the apps fill with the user's playlists ("My Collections")
COLLECTIONS_PACK = "faves-collections"
# sentinel pack_class prefix for a single playlist's track listing
PLAYLIST_PREFIX = "playlist:"

# Emoji fallbacks for items without images
TYPE_EMOJI: dict[str, str] = {
    "sleep": "🌙",
    "music": "🎵",
    "meditation": "🧘",
    "meditations": "🧘",
    "wisdom": "📖",
    "soundscapes": "🌊",
    "programs": "📋",
    "program": "📋",
    "guide": "🎧",
    "narrator": "🎤",
    "sleep stories": "🌙",
    "body": "🏃",
    "kids": "👶",
}

# ------------------------------------------------------------------
# Album art helpers
# ------------------------------------------------------------------

_ART_AVAILABLE = False
try:
    from PIL import Image as PILImage
    from rich_pixels import Pixels

    _ART_AVAILABLE = True
except ImportError:
    pass


def _resize_image(data: bytes, width: int = 16, height: int = 16) -> object | None:
    """Resize image bytes and return a ``Pixels`` renderable, or None."""
    if not _ART_AVAILABLE:
        return None
    try:
        img: PILImage.Image = PILImage.open(io.BytesIO(data))
        img = img.convert("RGBA")
        img = img.resize((width, height), PILImage.Resampling.LANCZOS)
        return Pixels.from_image(img)  # type: ignore[no-any-return]
    except Exception:
        return None


# ------------------------------------------------------------------
# Custom widgets
# ------------------------------------------------------------------


class CategoryItem(ListItem):
    """A selectable category in the sidebar."""

    def __init__(self, slug: str, emoji: str, name: str) -> None:
        """Initialise with category metadata."""
        super().__init__()
        self.slug = slug
        self.cat_name = name
        self.emoji = emoji

    def compose(self) -> ComposeResult:
        """Render the category label."""
        # centre the icon in a fixed two-cell column so the names line up
        icon = self.emoji.center(2) if cell_len(self.emoji) < 2 else self.emoji
        yield Label(f" {icon}  {self.cat_name}")


class CatalogCard(Static):
    """A clickable card in the catalog grid with optional thumbnail."""

    can_focus = True

    @dataclass
    class Selected(Message):
        """Fired when a card is clicked or Enter is pressed."""

        card: CatalogCard

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        emoji: str = "📋",
        *,
        pack: Pack | None = None,
        item: PackItem | None = None,
    ) -> None:
        """Initialise with display info and optional data references."""
        super().__init__()
        self.card_title = title
        self.card_subtitle = subtitle
        self.card_emoji = emoji
        self.card_pack = pack
        self.card_item = item
        self._art_renderable: object | None = None

    def set_art(self, renderable: object) -> None:
        """Set an album art renderable and re-render."""
        self._art_renderable = renderable
        if self.is_mounted:
            self._render_card()

    def compose(self) -> ComposeResult:
        """Initial render."""
        yield Label("", id="card-content")

    def on_mount(self) -> None:
        """Render card content after mount."""
        self._render_card()

    def _render_card(self) -> None:
        """Update the card label content."""
        try:
            label = self.query_one("#card-content", Label)
        except Exception:
            return  # Card removed from DOM before art arrived
        # wrap to the card's inner width; fall back before the first layout pass
        width = self.content_size.width or 18
        title = "\n".join(_wrap(self.card_title, width, max_lines=2))
        parts = [self.card_emoji] if not self._art_renderable else []
        parts.append(f"[bold]{title}[/bold]")
        if self.card_subtitle:
            sub = "\n".join(_wrap(self.card_subtitle, width, max_lines=1))
            parts.append(f"[dim]{sub}[/dim]")
        label.update("\n".join(parts))

    def on_resize(self) -> None:
        """Re-wrap card text when the column width changes."""
        self._render_card()

    def on_click(self) -> None:
        """Handle click on the card."""
        self.post_message(self.Selected(self))

    def on_key(self, event: object) -> None:
        """Handle Enter key."""
        if hasattr(event, "key") and event.key == "enter":  # type: ignore[union-attr]
            self.post_message(self.Selected(self))


class TrackItem(ListItem):
    """A track in the track listing view."""

    def __init__(self, guide: Guide, index: int, *, is_current: bool = False) -> None:
        """Initialise with a Guide model."""
        super().__init__()
        self.guide = guide
        self.track_index = index
        self._is_current = is_current

    def compose(self) -> ComposeResult:
        """Render the track entry."""
        marker = "▶ " if self._is_current else "  "
        dur = ""
        if self.guide.assets:
            secs = int(self.guide.assets[0].duration)
            m, s = divmod(secs, 60)
            dur = f" · {m}:{s:02d}"
        yield Label(f"{marker}{self.track_index + 1}. {self.guide.title}{dur}")


# ------------------------------------------------------------------
# Now Playing widgets
# ------------------------------------------------------------------


class NowPlayingBar(Static):
    """Compact one-line player bar docked to the bottom."""

    track_title: reactive[str] = reactive("")
    program_title: reactive[str] = reactive("")
    narrator: reactive[str] = reactive("")
    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)
    paused: reactive[bool] = reactive(False)

    def render(self) -> str:
        """Render the bar content."""
        icon = "⏸" if self.paused else "▶"
        pos = self._fmt(self.position)
        dur = self._fmt(self.duration)

        parts = [f" {icon}  [bold]{self.track_title}[/bold]"]
        if self.program_title:
            parts.append(f" · {self.program_title}")
        if self.narrator:
            parts.append(f" · [dim]{self.narrator}[/dim]")

        # Progress fraction
        frac = ""
        if self.duration > 0:
            pct = min(100, int(self.position / self.duration * 100))
            bar_w = 15
            filled = int(bar_w * pct / 100)
            frac = f"  [dim]{'━' * filled}{'─' * (bar_w - filled)}[/dim]  {pos} / {dur}"

        return "".join(parts) + frac

    @staticmethod
    def _fmt(seconds: float) -> str:
        """Format seconds as M:SS."""
        if seconds <= 0:
            return "0:00"
        total = int(seconds)
        m, s = divmod(total, 60)
        return f"{m}:{s:02d}"


# ------------------------------------------------------------------
# Main TUI App
# ------------------------------------------------------------------


BROWSE_CSS = """
#browse-container {
    layout: horizontal;
    height: 1fr;
}

#category-sidebar {
    width: 22;
    border-right: solid $accent;
    background: $surface;
}

#category-sidebar > ListView {
    height: 1fr;
}

#category-sidebar .sidebar-title {
    text-style: bold;
    color: $accent;
    padding: 1 1;
    text-align: center;
}

/* ---- Catalog grid ---- */

#catalog-panel {
    width: 1fr;
}

#catalog-header {
    height: 3;
    padding: 0 2;
}

#catalog-header .panel-title {
    text-style: bold;
    color: $text;
    padding: 1 1 0 1;
}

#search-input {
    display: none;
    dock: top;
    margin: 0 1;
}

#catalog-grid {
    layout: grid;
    grid-size: 4;
    grid-gutter: 1;
    grid-rows: auto;
    padding: 0 1;
    height: 1fr;
    overflow-y: auto;
}

CatalogCard {
    height: 7;
    padding: 1;
    border: round $surface-darken-2;
    background: $surface;
    text-align: center;
}

CatalogCard:focus {
    border: round $accent;
    background: $accent 15%;
}

/* ---- Track listing ---- */

#track-panel {
    display: none;
    width: 1fr;
}

#narrator-panel {
    display: none;
    width: 1fr;
}

#narrator-title {
    padding: 1 2;
    background: $surface;
    border-bottom: solid $surface-darken-2;
}

#narrator-filter {
    margin: 0 1;
}

#narrator-list {
    height: 1fr;
}

.narrator-header {
    color: $accent;
    text-style: bold;
}

#track-header {
    height: auto;
    max-height: 14;
    padding: 1 2;
    background: $surface;
    border-bottom: solid $surface-darken-2;
}

#track-art {
    width: auto;
    height: auto;
    margin-right: 2;
}

#track-info {
    width: 1fr;
}

#track-list {
    height: 1fr;
}

.back-btn {
    margin: 0 1;
    color: $accent;
}

/* ---- Now Playing ---- */

#now-playing-bar {
    dock: bottom;
    height: 3;
    display: none;
    background: $surface;
    border-top: solid $accent;
    padding: 0 1;
    content-align: left middle;
}

#now-playing-expanded {
    dock: bottom;
    height: 24;
    display: none;
    background: $surface;
    border-top: solid $accent;
    padding: 1 2;
}

#expanded-art-row {
    height: auto;
    max-height: 14;
}

#expanded-art {
    width: 24;
    min-width: 24;
    max-width: 24;
    height: auto;
    margin-right: 2;
    overflow: hidden;
}

#expanded-info {
    width: 1fr;
    min-width: 30;
    height: auto;
    padding: 1 1;
}

#expanded-progress {
    width: 100%;
    margin: 1 0;
}

#expanded-timer {
    text-align: center;
    color: $text-muted;
}

#expanded-tracks {
    height: 1fr;
    margin-top: 1;
    border-top: solid $surface-darken-2;
}

/* ---- Maximized player ---- */

#maximized-player {
    display: none;
    width: 100%;
    height: 100%;
    background: $surface;
    padding: 2 4;
}

#max-art-container {
    height: auto;
    width: 100%;
    content-align: center middle;
    margin-bottom: 1;
}

#max-title {
    text-align: center;
    text-style: bold;
    margin-bottom: 1;
}

#max-track {
    text-align: center;
    color: $text-muted;
}

#max-narrator {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

#max-progress {
    width: 80%;
    margin: 1 4;
}

#max-timer {
    text-align: center;
    color: $text-muted;
}

#max-tracks {
    height: 1fr;
    margin-top: 1;
    border-top: solid $surface-darken-2;
}

ListView > ListItem.--highlight {
    background: $accent 30%;
}
"""


class BrowseApp(App):
    """Interactive Calm catalog browser with grid layout and inline player."""

    CSS = BROWSE_CSS
    TITLE = "Calm Browser"
    SUB_TITLE = "Browse the catalog"

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "back", "Back"),
        Binding("f", "show_favorites", "Favorites"),
        Binding("slash", "search", "Search"),
        Binding("p", "play_item", "Play"),
        Binding("s", "stop_playback", "Stop"),
        Binding("space", "toggle_pause", "⏯"),
        Binding("n", "next_track", "Next"),
        Binding("shift+n", "prev_track", "Prev"),
        Binding("m", "maximize_player", "Max"),
    ]

    def __init__(self, client: CalmClient) -> None:
        """Initialise with an authenticated CalmClient."""
        super().__init__()
        self._client = client
        self._feed_cache: dict[str, FeedResponse] = {}
        # full packs by pack_class; feeds only embed a preview (about 10 items) of each pack
        self._pack_cache: dict[str, Pack] = {}
        # resolved guides by id, so playlist hydration doesn't refetch
        self._guide_cache: dict[str, tuple[Guide, Program]] = {}
        # narrators/artists, fetched once and filtered in-memory
        self._narrators: list[SearchItem] = []
        # cap concurrent album-art downloads so a big grid doesn't fire hundreds at once
        self._art_semaphore = asyncio.Semaphore(6)
        self._current_category: str = ""
        self._current_pack: Pack | None = None
        self._current_item: PackItem | None = None

        # Player state
        self._player: CalmPlayer | None = None
        self._current_program: Program | None = None
        self._current_track_index: int = 0
        self._player_mode: str = "hidden"  # hidden | bar | expanded | maximized
        self._update_timer: object | None = None

        # Art cache: url -> Pixels renderable
        self._art_cache: dict[str, object] = {}

        # Navigation: "grid" | "tracks"
        self._view: str = "grid"

    def compose(self) -> ComposeResult:
        """Build the layout."""
        yield Header()

        # Main browse area
        with Horizontal(id="browse-container"):
            with Vertical(id="category-sidebar"):
                yield Static("☁ Calm", classes="sidebar-title")
                yield ListView(
                    *[CategoryItem(slug, emoji, name) for slug, emoji, name in CATEGORIES],
                    CategoryItem("narrators", "🎙", "Narrators"),
                    id="category-list",
                )

            # Catalog grid view
            with Vertical(id="catalog-panel"):
                with Horizontal(id="catalog-header"):
                    yield Static("Select a category", classes="panel-title", id="catalog-title")
                yield Input(placeholder="Search...", id="search-input")
                yield ScrollableContainer(id="catalog-grid")

            # Narrators & Artists view (hidden initially)
            with Vertical(id="narrator-panel"):
                yield Static("🎙  Narrators & Artists", classes="panel-title", id="narrator-title")
                yield Input(placeholder="Filter by name...", id="narrator-filter")
                yield ListView(id="narrator-list")

            # Track listing view (hidden initially)
            with Vertical(id="track-panel"):
                with Horizontal(id="track-header"):
                    yield Static("", id="track-art")
                    with Vertical(id="track-info"):
                        yield Label("← Back", classes="back-btn", id="back-btn")
                        yield Label("", id="track-program-title")
                        yield Label("", id="track-narrator")
                        yield Label("", id="track-description")
                yield ListView(id="track-list")

        # Now Playing bar (collapsed)
        yield NowPlayingBar(id="now-playing-bar")

        # Now Playing expanded drawer
        with Vertical(id="now-playing-expanded"):
            with Horizontal(id="expanded-art-row"):
                yield Static("", id="expanded-art")
                with Vertical(id="expanded-info"):
                    yield Label("", id="expanded-title")
                    yield Label("", id="expanded-track")
                    yield Label("", id="expanded-narrator")
            yield ProgressBar(total=100, show_eta=False, id="expanded-progress")
            yield Label("0:00 / 0:00", id="expanded-timer")
            yield ListView(id="expanded-tracks")

        # Maximized player (hidden initially)
        with Vertical(id="maximized-player"):
            yield Center(Static("", id="max-art"), id="max-art-container")
            yield Label("", id="max-title")
            yield Label("", id="max-track")
            yield Label("", id="max-narrator")
            yield Center(ProgressBar(total=100, show_eta=False, id="max-progress"))
            yield Label("0:00 / 0:00", id="max-timer")
            yield ListView(id="max-tracks")

        yield Footer()

    def on_mount(self) -> None:
        """Focus the category list on startup."""
        self.query_one("#category-list", ListView).focus()

    def on_unmount(self) -> None:
        """Clean up resources."""
        if self._player:
            self._player.stop()
            self._player.shutdown()

    async def action_quit(self) -> None:
        """Quit the application."""
        if self._player:
            self._player.stop()
            self._player.shutdown()
        await self._client.aclose()
        self.exit()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _switch_to_grid(self) -> None:
        """Show the catalog grid, hide the other panels."""
        self._view = "grid"
        self.query_one("#catalog-panel").styles.display = "block"
        self.query_one("#track-panel").styles.display = "none"
        self.query_one("#narrator-panel").styles.display = "none"

    def _switch_to_tracks(self) -> None:
        """Show the track panel, hide the catalog grid."""
        self._view = "tracks"
        self.query_one("#catalog-panel").styles.display = "none"
        self.query_one("#narrator-panel").styles.display = "none"
        self.query_one("#track-panel").styles.display = "block"

    def _switch_to_narrators(self) -> None:
        """Show the narrators panel, hide the others."""
        self._view = "narrators"
        self.query_one("#catalog-panel").styles.display = "none"
        self.query_one("#track-panel").styles.display = "none"
        self.query_one("#narrator-panel").styles.display = "block"

    async def action_back(self) -> None:
        """Navigate back based on current state."""
        # Maximized player → expanded
        if self._player_mode == "maximized":
            self._show_player_expanded()
            return

        # Expanded player → bar
        if self._player_mode == "expanded":
            self._show_player_bar()
            return

        # Narrators → back to the sidebar/grid
        if self._view == "narrators":
            self._switch_to_grid()
            self.query_one("#category-list", ListView).focus()
            return

        # Track listing → grid
        if self._view == "tracks":
            self._switch_to_grid()
            grid = self.query_one("#catalog-grid", ScrollableContainer)
            # Try to focus first card
            cards = grid.query(CatalogCard)
            if cards:
                cards[0].focus()
            return

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection in any ListView."""
        item = event.item
        if isinstance(item, CategoryItem):
            if item.slug == "search":
                self._show_search_input()
            elif item.slug == "narrators":
                self._load_narrators()
            else:
                self._load_category(item.slug, item.cat_name)
        elif isinstance(item, TrackItem) and self._current_program:
            self._play_track(item.track_index)
        elif isinstance(pack_item := getattr(item, "item", None), PackItem):
            self._open_item(pack_item)

    def on_catalog_card_selected(self, event: CatalogCard.Selected) -> None:
        """Handle card selection — drill into packs or items."""
        card = event.card
        if card.card_pack:
            self._drill_into_pack(card.card_pack)
        elif card.card_item:
            self._open_item(card.card_item)

    def _open_item(self, item: PackItem) -> None:
        """Open a folder (sub-feed, sub-pack or narrator), or play a guide or program."""
        # folders carry a browse path: feed/<id>, pack/<class>, or feed/narrator-<id>
        if path := item.path:
            kind, _, ident = path.partition("/")
            if kind == "feed":
                self._load_category(ident, item.title)
            else:
                self._drill_into_pack(Pack(title=item.title, pack_class=ident, has_more=True))
        elif item.media_type in (MediaType.TRACK, MediaType.ALBUM):
            self._current_item = item
            self._play_selected_item()
        else:
            # breathe bubbles, link cards, and other non-audio entries aren't playable here
            self.notify(f"'{item.title}' has no audio to play", severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        if event.input.id == "search-input":
            self._perform_search(event.value)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def action_search(self) -> None:
        """Activate the search input."""
        self._show_search_input()

    def _show_search_input(self) -> None:
        """Show the search input and focus it."""
        self._current_category = "search"
        self._switch_to_grid()
        grid = self.query_one("#catalog-grid", ScrollableContainer)
        grid.query(CatalogCard).remove()
        title = self.query_one("#catalog-title", Static)
        title.update("Search")
        self.sub_title = "Search the catalog"

        search_input = self.query_one("#search-input", Input)
        search_input.display = True
        search_input.value = ""
        search_input.focus()

    @work(exclusive=True, group="search")
    async def _perform_search(self, query: str) -> None:
        """Execute search and display results as cards."""
        if not query.strip():
            return

        title = self.query_one("#catalog-title", Static)
        title.update(f"Searching '{query}'...")

        try:
            results = await self._client.search(query)
            if not results.items:
                title.update(f"No results for '{query}'")
                return

            # Hide search input
            self.query_one("#search-input", Input).display = False
            title.update(f"Results: {query} ({len(results.items)})")

            # Build cards from results
            grid = self.query_one("#catalog-grid", ScrollableContainer)
            grid.query(CatalogCard).remove()

            for res in results.items:
                # res is a SearchItem (a PackItem), so pass it straight through — this keeps
                # guide_id, narrator_id, image, etc. so guides, programs and narrators all open
                emoji = TYPE_EMOJI.get((res.search_category or "").lower(), "🔍")
                card = CatalogCard(
                    title=res.title,
                    subtitle=res.narrator_name or res.subtitle or "",
                    emoji=emoji,
                    item=res,
                )
                await grid.mount(card)
                if res.image and res.image.url:
                    self._fetch_card_art(card, res.image.url)

        except Exception as e:
            title.update(f"Error: {e}")

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def action_show_favorites(self) -> None:
        """Load and display favorites."""
        self._load_all_favorites()

    @work(exclusive=True, group="faves-load")
    async def _load_all_favorites(self) -> None:
        """Fetch favorites and display as cards."""
        self._switch_to_grid()
        title = self.query_one("#catalog-title", Static)
        grid = self.query_one("#catalog-grid", ScrollableContainer)
        grid.query(CatalogCard).remove()
        title.update("⏳ Loading Favorites...")
        self.sub_title = "Your favorites"

        try:
            favorites = await self._client.get_favorites()
        except Exception as e:
            self.notify(f"Error loading favorites: {e}", severity="error")
            title.update("Error loading favorites")
            return

        if not favorites:
            self.notify("No favorites found", severity="warning")
            title.update("Favorites (Empty)")
            return

        favorites.sort(key=lambda x: x.title)
        title.update(f"★ Favorites ({len(favorites)})")

        for fav in favorites:
            emoji = TYPE_EMOJI.get((fav.search_category or fav.item_type or "").lower(), "⭐")
            card = CatalogCard(
                title=fav.title,
                subtitle=fav.narrator_name or fav.subtitle or "",
                emoji=emoji,
                item=fav,
            )
            await grid.mount(card)
            # Fetch art in background
            if fav.image and fav.image.url:
                self._fetch_card_art(card, fav.image.url)

    @work(exclusive=True, group="collections-load")
    async def _load_collections(self) -> None:
        """Fetch the user's playlists and display them as cards."""
        self._switch_to_grid()
        title = self.query_one("#catalog-title", Static)
        grid = self.query_one("#catalog-grid", ScrollableContainer)
        grid.query(CatalogCard).remove()
        title.update("⏳ Loading My Collections...")
        self.sub_title = "Your playlists"

        try:
            playlists = await self._client.get_playlists()
        except Exception as e:
            self.notify(f"Error loading collections: {e}", severity="error")
            title.update("Error loading collections")
            return

        if not playlists:
            title.update("My Collections (Empty)")
            self.notify("No playlists yet", severity="warning")
            return

        title.update(f"≡ My Collections ({len(playlists)})")
        for playlist in playlists:
            pack = self._playlist_pack(playlist)
            self._pack_cache[pack.pack_class] = pack
            card = CatalogCard(
                title=playlist.name or "Untitled",
                subtitle=f"{len(playlist.items)} items",
                emoji="≡",
                pack=pack,
            )
            await grid.mount(card)
            if playlist.image_url:
                self._fetch_card_art(card, playlist.image_url)

        cards = grid.query(CatalogCard)
        if cards:
            cards[0].focus()

    @staticmethod
    def _playlist_pack(playlist: Playlist) -> Pack:
        """Represent a playlist as a Pack of (unhydrated) guide items."""
        return Pack(
            title=playlist.name or "Untitled",
            pack_class=f"{PLAYLIST_PREFIX}{playlist.id}",
            items=[
                PackItem(type="guide", guide_id=i.guide_id, program_id=i.program_id)
                for i in playlist.items
                if i.guide_id
            ],
        )

    @work(exclusive=True, group="playlist-hydrate")
    async def _hydrate_playlist(self, pack: Pack) -> None:
        """Fill in titles, narrators and durations for a playlist's guide items."""
        changed = False
        for item in pack.items:
            if item.title or not item.guide_id:
                continue
            if item.guide_id in self._guide_cache:
                guide, program = self._guide_cache[item.guide_id]
            else:
                try:
                    guide, program = await self._client.get_guide(item.guide_id)
                except Exception:
                    continue
                self._guide_cache[item.guide_id] = (guide, program)
            item.title = guide.title
            item.narrator_name = guide.narrator_name or program.narrator_name
            item.assets = [
                PackItemAsset(url=a.url, content_type=a.content_type, duration=a.duration) for a in guide.assets
            ]
            changed = True
        if changed and self._view == "tracks" and self._current_pack is pack:
            self._show_pack(pack)

    @work(exclusive=True, group="narrators-load")
    async def _load_narrators(self) -> None:
        """Fetch the narrators/artists catalog and show it as a filterable name list."""
        self._switch_to_narrators()
        title = self.query_one("#narrator-title", Static)
        listview = self.query_one("#narrator-list", ListView)
        await listview.clear()
        self.query_one("#narrator-filter", Input).value = ""
        title.update("⏳ Loading Narrators & Artists...")

        if not self._narrators:
            try:
                self._narrators = await self._client.list_narrators()
            except Exception as e:
                self.notify(f"Error loading narrators: {e}", severity="error")
                title.update("Error loading narrators")
                return

        title.update(f"🎙  Narrators & Artists ({len(self._narrators)})")
        self._populate_narrators("")
        with contextlib.suppress(Exception):
            self.query_one("#narrator-filter", Input).focus()

    def _populate_narrators(self, query: str) -> None:
        """Fill the narrator list, filtered by name, with A/B/C section headers."""
        listview = self.query_one("#narrator-list", ListView)
        listview.clear()
        needle = query.strip().lower()
        matches = [n for n in self._narrators if needle in n.title.lower()]
        current_letter = ""
        for narrator in matches:
            first = narrator.title[:1].upper()
            letter = first if first.isalpha() else "#"
            if letter != current_letter:
                current_letter = letter
                header = ListItem(Label(f"— {letter} —", classes="narrator-header"))
                header.disabled = True  # a non-selectable section divider
                self.call_after_refresh(listview.append, header)
            row = ListItem(Label(narrator.title))
            row.item = narrator  # type: ignore[attr-defined]
            self.call_after_refresh(listview.append, row)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the narrator list as the user types."""
        if event.input.id == "narrator-filter":
            self._populate_narrators(event.value)

    # ------------------------------------------------------------------
    # Category loading
    # ------------------------------------------------------------------

    @work(exclusive=True, group="feed-load")
    async def _load_category(self, slug: str, name: str) -> None:
        """Fetch and display a category's feed as catalog cards."""
        self._current_category = slug
        self._current_pack = None
        self._switch_to_grid()

        title = self.query_one("#catalog-title", Static)
        grid = self.query_one("#catalog-grid", ScrollableContainer)

        # Hide search input
        self.query_one("#search-input", Input).display = False

        grid.query(CatalogCard).remove()
        title.update(f"⏳ Loading {name}...")

        try:
            if slug in self._feed_cache:
                feed = self._feed_cache[slug]
            else:
                feed = await self._client.get_category_feed(slug)
                self._feed_cache[slug] = feed

            title.update(feed.title or name)
            self.sub_title = feed.subtitle or f"Browse {name}"

            # Packs the apps fill in themselves arrive empty; of those, favorites and
            # collections have endpoints the client can load (recently played does not)
            client_packs = (FAVES_PACK, COLLECTIONS_PACK)
            # keep only rows with playable content; drop link-only rows like "Resources"
            packs = [p for p in feed.packs if p.pack_class in client_packs or p.has_content]
            # favorites first, then collections, as in the apps
            order = {FAVES_PACK: 0, COLLECTIONS_PACK: 1}
            packs.sort(key=lambda p: order.get(p.pack_class, 2))
            emoji = TYPE_EMOJI.get(slug, "📋")

            for pack in packs:
                # untitled packs (the navigation row, today's Daily Calm banner) only describe themselves
                pack.title = pack.title or pack.content_description or ""
                # Use first item's image if available
                img_url = ""
                if pack.items:
                    for pi in pack.items:
                        if pi.image and pi.image.url:
                            img_url = pi.image.url
                            break

                count = len(pack.items) if pack.items else pack.total_item_number
                card = CatalogCard(
                    title=pack.title,
                    # the feed only previews the pack; the full count is known once it's opened
                    subtitle=(
                        "Your favorites"
                        if pack.pack_class == FAVES_PACK
                        else "Your playlists"
                        if pack.pack_class == COLLECTIONS_PACK
                        else f"{count}+ items"
                        if pack.has_more and pack.items
                        else f"{count} items"
                    ),
                    emoji=emoji,
                    pack=pack,
                )
                await grid.mount(card)

                # Fetch thumbnail in background
                if img_url:
                    self._fetch_card_art(card, img_url)

            # Focus first card
            cards = grid.query(CatalogCard)
            if cards:
                cards[0].focus()

        except Exception as e:
            title.update(f"Error: {e}")

    # ------------------------------------------------------------------
    # Drill-down into pack → track listing
    # ------------------------------------------------------------------

    def _drill_into_pack(self, pack: Pack) -> None:
        """Switch to track listing view for a pack.

        Feeds embed only a preview of each pack, so the preview is shown straight away
        and the full pack is loaded in the background.
        """
        if pack.pack_class == FAVES_PACK:
            self._load_all_favorites()
            return
        if pack.pack_class == COLLECTIONS_PACK:
            self._load_collections()
            return
        full = self._pack_cache.get(pack.pack_class)
        self._show_pack(full or pack)
        if pack.pack_class.startswith(PLAYLIST_PREFIX):
            # playlist items carry only ids; fill in titles and durations
            self._hydrate_playlist(full or pack)
        elif full is None and pack.has_more and pack.pack_class:
            self._load_full_pack(pack)

    def _append_pack_item(self, track_list: ListView, item: ListItem, pack: Pack) -> None:
        """Append a deferred track row, unless another pack has been shown since."""
        if self._current_pack is pack:
            track_list.append(item)

    @work(exclusive=True, group="pack-load")
    async def _load_full_pack(self, preview: Pack) -> None:
        """Fetch every item of a pack and redisplay it if it's still open."""
        try:
            full = await self._client.get_pack(preview.pack_class)
        except Exception as e:
            self.notify(f"Could not load all of {preview.title}: {e}", severity="warning")
            return
        if not full.items:
            return
        full.title = full.title or preview.title
        self._pack_cache[preview.pack_class] = full
        if self._view == "tracks" and self._current_pack is preview:
            self._show_pack(full)

    def _show_pack(self, pack: Pack) -> None:
        """Display a pack's items in the track listing view."""
        self._current_pack = pack
        self._switch_to_tracks()

        # Update header info
        program_title = self.query_one("#track-program-title", Label)
        narrator_label = self.query_one("#track-narrator", Label)
        desc_label = self.query_one("#track-description", Label)

        program_title.update(f"[bold]{pack.title}[/bold]")

        # Get narrator from first item
        narrator = ""
        if pack.items:
            for pi in pack.items:
                if pi.narrator_name:
                    narrator = pi.narrator_name
                    break
        narrator_label.update(f"[dim]{narrator}[/dim]" if narrator else "")
        desc_label.update(f"[dim]{len(pack.items) if pack.items else 0} items[/dim]")

        # Fetch album art for the header
        art_widget = self.query_one("#track-art", Static)
        art_widget.update("")
        if pack.items:
            for pi in pack.items:
                if pi.image and pi.image.url:
                    self._fetch_header_art(art_widget, pi.image.url)
                    break

        # Populate track list as content items
        track_list = self.query_one("#track-list", ListView)
        track_list.clear()
        if pack.items:
            for i, item in enumerate(pack.items):
                dur = item.duration_str or ""
                narrator_str = f" · {item.narrator_name}" if item.narrator_name else ""
                li = ListItem(Label(f"  {i + 1}. {item.title}{narrator_str}  {dur}"))
                li.item = item  # type: ignore[attr-defined]
                self.call_after_refresh(self._append_pack_item, track_list, li, pack)

        track_list.focus()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def action_play_item(self) -> None:
        """Play the focused item."""
        # If on a card, try to play it
        focused = self.focused
        if isinstance(focused, CatalogCard) and focused.card_item:
            self._open_item(focused.card_item)
        elif isinstance(focused, CatalogCard) and focused.card_pack:
            # Drill into the pack first
            self._drill_into_pack(focused.card_pack)
        elif self._view == "tracks" and self._current_pack:
            # Get selected track from list
            track_list = self.query_one("#track-list", ListView)
            if track_list.highlighted_child is not None:
                li = track_list.highlighted_child
                if hasattr(li, "item"):
                    self._open_item(li.item)  # type: ignore[attr-defined]

    @work(exclusive=True, group="playback")
    async def _play_selected_item(self) -> None:
        """Fetch a program and start playing."""
        item = self._current_item
        if not item:
            self.notify("No item selected", severity="warning")
            return

        # only program_id resolves to a playable program; content_id can be a non-program
        # ref (e.g. a breathe bubble), which 404s the program endpoint
        program_id = item.program_id
        if not program_id:
            self.notify(f"'{item.title}' has no audio to play", severity="warning")
            return

        self.notify(f"Loading {item.title}...", severity="information")

        try:
            program = await self._client.get_program(program_id)
        except Exception as e:
            self.notify(f"Failed: {e}", severity="error")
            return

        if not program.guides:
            self.notify("No audio tracks found", severity="warning")
            return

        # a guide entry (e.g. today's Daily Calm) starts at that guide, not the program's first
        index = next((i for i, g in enumerate(program.guides) if g.id == item.guide_id), 0)
        self._current_program = program
        self._current_track_index = index

        # Fetch art for the player
        if item.image and item.image.url:
            self._fetch_player_art(item.image.url)

        self._play_track(index)

    def _play_track(self, index: int) -> None:
        """Play a specific track from the current program."""
        if not self._current_program or not self._current_program.guides:
            return

        if index < 0 or index >= len(self._current_program.guides):
            return

        # Stop current playback
        if self._player:
            self._player.stop()
            self._player.shutdown()
            self._player = None

        track = self._current_program.guides[index]
        url = track.stream_url
        if not url:
            self.notify("No stream URL available", severity="error")
            return

        try:
            from .player import CalmPlayer

            self._player = CalmPlayer()
        except RuntimeError as e:
            self.notify(str(e), severity="error")
            return

        self._current_track_index = index
        self._player.play(url)

        # Register end-of-track callback for auto-advance
        self._player.on_end(self._on_track_end)

        # Show the player bar
        self._show_player_bar()

        # Start progress timer
        if self._update_timer is None:
            self._update_timer = self.set_interval(0.5, self._update_player_ui)

        # Update bar content immediately
        narrator = ""
        if self._current_item and self._current_item.narrator_name:
            narrator = self._current_item.narrator_name

        bar = self.query_one("#now-playing-bar", NowPlayingBar)
        bar.track_title = track.title
        bar.program_title = self._current_program.title
        bar.narrator = narrator
        bar.paused = False

        self.sub_title = f"Playing: {track.title}"
        self.notify(f"▶ {track.title}", severity="information")

        # Update track lists in expanded/maximized views
        self._refresh_track_lists()

    def _on_track_end(self) -> None:
        """Auto-advance to the next track when current ends."""
        if not self._current_program:
            return
        next_idx = self._current_track_index + 1
        if next_idx < len(self._current_program.guides):
            # Use call_from_thread since mpv callback is on a different thread
            self.call_from_thread(self._play_track, next_idx)
        else:
            # End of playlist
            self.call_from_thread(self._stop_playback)

    def action_next_track(self) -> None:
        """Skip to the next track."""
        if self._current_program:
            self._play_track(self._current_track_index + 1)

    def action_prev_track(self) -> None:
        """Skip to the previous track."""
        if self._current_program:
            self._play_track(self._current_track_index - 1)

    def action_toggle_pause(self) -> None:
        """Pause or resume playback."""
        if self._player:
            self._player.pause()
            bar = self.query_one("#now-playing-bar", NowPlayingBar)
            bar.paused = self._player.is_paused

    def action_stop_playback(self) -> None:
        """Stop playback and hide the player."""
        self._stop_playback()

    def _stop_playback(self) -> None:
        """Internal stop and cleanup."""
        if self._player:
            self._player.stop()
            self._player.shutdown()
            self._player = None

        self._current_program = None
        self._current_track_index = 0
        self._player_mode = "hidden"

        # Hide all player widgets
        self.query_one("#now-playing-bar").styles.display = "none"
        self.query_one("#now-playing-expanded").styles.display = "none"
        self.query_one("#maximized-player").styles.display = "none"
        self.query_one("#browse-container").styles.display = "block"

        self.sub_title = "Browse the catalog"

    # ------------------------------------------------------------------
    # Player UI modes
    # ------------------------------------------------------------------

    def _show_player_bar(self) -> None:
        """Show collapsed now-playing bar."""
        self._player_mode = "bar"
        self.query_one("#now-playing-bar").styles.display = "block"
        self.query_one("#now-playing-expanded").styles.display = "none"
        self.query_one("#maximized-player").styles.display = "none"
        self.query_one("#browse-container").styles.display = "block"

    def _show_player_expanded(self) -> None:
        """Show expanded now-playing drawer."""
        self._player_mode = "expanded"
        self.query_one("#now-playing-bar").styles.display = "none"
        self.query_one("#now-playing-expanded").styles.display = "block"
        self.query_one("#maximized-player").styles.display = "none"
        self.query_one("#browse-container").styles.display = "block"
        self._update_expanded_content()

    def _show_player_maximized(self) -> None:
        """Show full-screen maximized player."""
        self._player_mode = "maximized"
        self.query_one("#now-playing-bar").styles.display = "none"
        self.query_one("#now-playing-expanded").styles.display = "none"
        self.query_one("#maximized-player").styles.display = "block"
        self.query_one("#browse-container").styles.display = "none"
        self._update_maximized_content()

    def action_maximize_player(self) -> None:
        """Toggle between maximized and previous player mode."""
        if self._player_mode == "maximized":
            self._show_player_expanded()
        elif self._player_mode in ("bar", "expanded") and self._player:
            self._show_player_maximized()

    def on_now_playing_bar_click(self) -> None:
        """Expand the player bar when clicked."""
        if self._player_mode == "bar":
            self._show_player_expanded()

    def on_key(self, event: object) -> None:
        """Handle Enter on now-playing bar to expand."""
        # Let the default handling work for most keys
        pass

    # ------------------------------------------------------------------
    # Player UI updates
    # ------------------------------------------------------------------

    def _update_player_ui(self) -> None:
        """Update all visible player widgets with current position/duration."""
        if not self._player:
            return

        pos = self._player.position
        dur = self._player.duration

        # Update bar
        bar = self.query_one("#now-playing-bar", NowPlayingBar)
        bar.position = pos
        bar.duration = dur
        bar.paused = self._player.is_paused

        # Update expanded view if visible
        if self._player_mode == "expanded":
            self._update_expanded_progress(pos, dur)

        # Update maximized view if visible
        if self._player_mode == "maximized":
            self._update_maximized_progress(pos, dur)

    def _update_expanded_content(self) -> None:
        """Update the expanded drawer with current program info."""
        if not self._current_program:
            return

        track = self._current_program.guides[self._current_track_index]
        narrator = ""
        if self._current_item and self._current_item.narrator_name:
            narrator = self._current_item.narrator_name

        self.query_one("#expanded-title", Label).update(f"[bold]{self._current_program.title}[/bold]")
        self.query_one("#expanded-track", Label).update(track.title)
        self.query_one("#expanded-narrator", Label).update(f"[dim]{narrator}[/dim]" if narrator else "")

        self._refresh_track_lists()

    def _update_expanded_progress(self, pos: float, dur: float) -> None:
        """Update progress in expanded view."""
        progress = self.query_one("#expanded-progress", ProgressBar)
        progress.total = dur if dur > 0 else 100
        progress.progress = pos
        timer = self.query_one("#expanded-timer", Label)
        timer.update(f"{NowPlayingBar._fmt(pos)} / {NowPlayingBar._fmt(dur)}")

    def _update_maximized_content(self) -> None:
        """Update the maximized player with current program info."""
        if not self._current_program:
            return

        track = self._current_program.guides[self._current_track_index]
        narrator = ""
        if self._current_item and self._current_item.narrator_name:
            narrator = self._current_item.narrator_name

        self.query_one("#max-title", Label).update(f"[bold]{self._current_program.title}[/bold]")
        self.query_one("#max-track", Label).update(track.title)
        self.query_one("#max-narrator", Label).update(f"[dim]{narrator}[/dim]" if narrator else "")

        self._refresh_track_lists()

    def _update_maximized_progress(self, pos: float, dur: float) -> None:
        """Update progress in maximized view."""
        progress = self.query_one("#max-progress", ProgressBar)
        progress.total = dur if dur > 0 else 100
        progress.progress = pos
        timer = self.query_one("#max-timer", Label)
        timer.update(f"{NowPlayingBar._fmt(pos)} / {NowPlayingBar._fmt(dur)}")

    def _refresh_track_lists(self) -> None:
        """Update track listing in expanded and maximized views."""
        if not self._current_program:
            return

        for list_id in ("#expanded-tracks", "#max-tracks"):
            with contextlib.suppress(Exception):
                track_list = self.query_one(list_id, ListView)
                track_list.clear()
                for i, guide in enumerate(self._current_program.guides):
                    is_current = i == self._current_track_index
                    self.call_after_refresh(
                        lambda tl=track_list, g=guide, idx=i, cur=is_current: tl.append(
                            TrackItem(g, idx, is_current=cur)
                        )
                    )

    # ------------------------------------------------------------------
    # Album art fetching
    # ------------------------------------------------------------------

    @work(group="art")
    async def _fetch_card_art(self, card: CatalogCard, url: str) -> None:
        """Download and set thumbnail on a catalog card."""
        pixels = await self._get_art(url, width=16, height=16)
        if pixels:
            card.set_art(pixels)

    @work(group="art")
    async def _fetch_header_art(self, widget: Static, url: str) -> None:
        """Download and display larger art in the track header."""
        pixels = await self._get_art(url, width=24, height=24)
        if pixels:
            widget.update(pixels)  # type: ignore[arg-type]

    @work(group="art")
    async def _fetch_player_art(self, url: str) -> None:
        """Download art for expanded/maximized player views."""
        # Medium for expanded
        pixels_med = await self._get_art(url, width=20, height=20)
        if pixels_med:
            with contextlib.suppress(Exception):
                self.query_one("#expanded-art", Static).update(pixels_med)  # type: ignore[arg-type]

        # Large for maximized
        pixels_lg = await self._get_art(url, width=36, height=36)
        if pixels_lg:
            with contextlib.suppress(Exception):
                self.query_one("#max-art", Static).update(pixels_lg)  # type: ignore[arg-type]

    async def _get_art(self, url: str, width: int = 16, height: int = 16) -> object | None:
        """Fetch an image URL and return a Pixels renderable."""
        cache_key = f"{url}:{width}x{height}"
        if cache_key in self._art_cache:
            return self._art_cache[cache_key]

        try:
            import httpx

            # bound concurrency: a 200+ item grid otherwise opens that many sockets at once
            async with self._art_semaphore, httpx.AsyncClient() as http:
                resp = await http.get(url, timeout=10, follow_redirects=True)
                resp.raise_for_status()
                pixels = _resize_image(resp.content, width=width, height=height)
                if pixels:
                    self._art_cache[cache_key] = pixels
                return pixels
        except Exception:
            log.debug("Failed to fetch art from %s", url, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Search (legacy category-sidebar trigger)
    # ------------------------------------------------------------------

    def _show_search(self) -> None:
        """Legacy: called when Search category is selected."""
        self._show_search_input()


def run_browse(client: CalmClient) -> None:
    """Launch the browse TUI with the given authenticated client."""
    app = BrowseApp(client)
    app.run()

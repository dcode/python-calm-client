"""Interactive TUI for browsing the Calm catalog."""

from __future__ import annotations

import contextlib
import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, ProgressBar, Static

from calm_client.models import CalmAlbum, CalmBaseItem, CalmFolder, CalmTrack
from .player import CalmPlayer

# Emoji fallbacks
TYPE_EMOJI: dict[str, str] = {
    "sleep": "🌙",
    "music": "🎵",
    "meditation": "🧘",
    "wisdom": "📖",
    "soundscapes": "🌊",
    "program": "📋",
    "guide": "🎧",
    "feed": "📁",
    "pack": "📦",
}

_ART_AVAILABLE = False
try:
    from PIL import Image as PILImage
    from rich_pixels import Pixels
    _ART_AVAILABLE = True
except ImportError:
    pass

def _resize_image(data: bytes, width: int = 16, height: int = 16) -> object | None:
    if not _ART_AVAILABLE: return None
    try:
        img: PILImage.Image = PILImage.open(io.BytesIO(data))
        img = img.convert("RGBA").resize((width, height), PILImage.Resampling.LANCZOS)
        return Pixels.from_image(img)
    except Exception: return None

class CatalogCard(Static):
    can_focus = True
    @dataclass
    class Selected(Message):
        card: CatalogCard

    def __init__(self, item: CalmBaseItem, emoji: str = "📋") -> None:
        super().__init__()
        self.item = item
        self.card_emoji = emoji
        self._art_renderable: object | None = None

    def set_art(self, renderable: object) -> None:
        self._art_renderable = renderable
        if self.is_mounted: self._render_card()

    def compose(self) -> ComposeResult:
        yield Label("", id="card-content")

    def on_mount(self) -> None:
        self._render_card()

    def _render_card(self) -> None:
        try:
            label = self.query_one("#card-content", Label)
        except Exception: return
        title = self.item.title[:20]
        sub = f"\n[dim]{self.item.subtitle[:20]}[/dim]" if self.item.subtitle else ""
        emoji = f"\n{self.card_emoji}" if not self._art_renderable else ""
        label.update(f"{emoji}\n[bold]{title}[/bold]{sub}")

    def on_click(self) -> None:
        self.post_message(self.Selected(self))

    def on_key(self, event: Any) -> None:
        if event.key == "enter":
            self.post_message(self.Selected(self))

class TrackItem(ListItem):
    def __init__(self, track: CalmTrack, index: int, *, is_current: bool = False) -> None:
        super().__init__()
        self.track = track
        self.track_index = index
        self._is_current = is_current

    def compose(self) -> ComposeResult:
        marker = "▶ " if self._is_current else "  "
        yield Label(f"{marker}{self.track_index + 1}. {self.track.title} · {self.track.duration_str}")

class NowPlayingBar(Static):
    track_title: reactive[str] = reactive("")
    program_title: reactive[str] = reactive("")
    paused: reactive[bool] = reactive(False)
    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)

    def render(self) -> str:
        icon = "⏸" if self.paused else "▶"
        pos = self._fmt(self.position)
        dur = self._fmt(self.duration)
        return f" {icon}  [bold]{self.track_title}[/bold] · {self.program_title}  {pos} / {dur}"

    @staticmethod
    def _fmt(seconds: float) -> str:
        if seconds <= 0: return "0:00"
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

class BrowseApp(App):
    CSS_PATH = None # We'll use the one from previous read or inline it
    TITLE = "Calm Browser"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "back", "Back"),
        Binding("slash", "search", "Search"),
        Binding("space", "toggle_pause", "⏯"),
    ]

    def __init__(self, client: CalmClient) -> None:
        super().__init__()
        self._client = client
        self._history: list[str] = [""]
        self._player: CalmPlayer | None = None
        self._current_album: CalmAlbum | None = None
        self._current_track_idx: int = 0
        self._art_cache: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="browse-container"):
            with Vertical(id="catalog-panel"):
                yield Static("Home", id="catalog-title")
                yield Input(placeholder="Search...", id="search-input")
                yield ScrollableContainer(id="catalog-grid")
            with Vertical(id="track-panel"):
                yield Label("← Back", id="back-btn")
                yield Label("", id="track-program-title")
                yield ListView(id="track-list")
        yield NowPlayingBar(id="now-playing-bar")
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_path("")

    async def action_back(self) -> None:
        if self.query_one("#track-panel").display:
            self.query_one("#track-panel").display = False
            self.query_one("#catalog-panel").display = True
            return
        if len(self._history) > 1:
            self._history.pop()
            await self._load_path(self._history[-1], push=False)

    def action_search(self) -> None:
        inp = self.query_one("#search-input", Input)
        inp.display = True
        inp.value = ""
        inp.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.display = False
        self._perform_search(event.value)

    @work(exclusive=True)
    async def _perform_search(self, query: str) -> None:
        self.query_one("#catalog-title", Static).update(f"Search: {query}")
        res = await self._client.search(query)
        await self._display_items(res.items)

    async def _load_path(self, path: str, push: bool = True) -> None:
        if push and (not self._history or self._history[-1] != path):
            self._history.append(path)
        
        self.query_one("#catalog-title", Static).update(path or "Home")
        items = await self._client.browse(path)
        await self._display_items(items)

    async def _display_items(self, items: list[CalmBaseItem]) -> None:
        grid = self.query_one("#catalog-grid", ScrollableContainer)
        grid.query(CatalogCard).remove()
        for item in items:
            emoji = TYPE_EMOJI.get(item.item_type, "📋")
            card = CatalogCard(item, emoji)
            await grid.mount(card)
            if item.image: self._fetch_art(card, item.image.url)
        
        cards = grid.query(CatalogCard)
        if cards:
            cards[0].focus()

    @work(group="art")
    async def _fetch_art(self, card: CatalogCard, url: str) -> None:
        if url in self._art_cache:
            card.set_art(self._art_cache[url])
            return
        async with httpx.AsyncClient() as c:
            r = await c.get(url)
            pixels = _resize_image(r.content)
            if pixels:
                self._art_cache[url] = pixels
                card.set_art(pixels)

    async def on_catalog_card_selected(self, event: CatalogCard.Selected) -> None:
        item = event.card.item
        if isinstance(item, CalmFolder):
            await self._load_path(item.id)
        elif isinstance(item, CalmAlbum):
            await self._show_album(item)
        elif isinstance(item, CalmTrack):
            await self._play_track_item(item)

    async def _show_album(self, album: CalmAlbum) -> None:
        # Load full album if needed
        if not album.guides:
            album = await self._client.get_program(album.id)
        
        self.query_one("#catalog-panel").display = False
        self.query_one("#track-panel").display = True
        self.query_one("#track-program-title").update(album.title)
        
        lst = self.query_one("#track-list", ListView)
        lst.clear()
        for i, track in enumerate(album.guides):
            lst.append(TrackItem(track, i))
        self._current_album = album

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, TrackItem):
            await self._play_album_track(event.item.track_index)

    async def _play_track_item(self, track: CalmTrack) -> None:
        # If it's a standalone track, we might need its program to get the full album context if it's part of one
        # but for now just play it.
        self._current_album = None
        await self._start_playback(track)

    async def _play_album_track(self, index: int) -> None:
        if not self._current_album: return
        self._current_track_idx = index
        track = self._current_album.guides[index]
        await self._start_playback(track)

    async def _start_playback(self, track: CalmTrack) -> None:
        if self._player: self._player.stop()
        self._player = CalmPlayer()
        url = track.stream_url
        if not url: return
        self._player.play(url)
        
        bar = self.query_one("#now-playing-bar", NowPlayingBar)
        bar.display = True
        bar.track_title = track.title
        bar.program_title = self._current_album.title if self._current_album else ""
        
        self.set_interval(1.0, self._update_ui)

    def _update_ui(self) -> None:
        if not self._player: return
        bar = self.query_one("#now-playing-bar", NowPlayingBar)
        bar.position = self._player.position
        bar.duration = self._player.duration
        bar.paused = self._player.is_paused

    def action_toggle_pause(self) -> None:
        if self._player: self._player.pause()

import httpx
def run_browse(client: CalmClient) -> None:
    BrowseApp(client).run()

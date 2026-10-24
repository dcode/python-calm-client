"""Textual app for the 'calm play' command."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.widgets import Footer, Header, Label, ProgressBar

from .models import AudioQuality
from .player import CalmPlayer, format_time

if TYPE_CHECKING:
    from .models import Guide, Program


class PlayApp(App):
    """Textual app for playing a single track with controls."""

    CSS = """
    Screen {
        align: center middle;
    }

    #player-container {
        width: 80%;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }

    .title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    .track {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }

    ProgressBar {
        width: 100%;
        margin: 1 0;
    }

    #timer {
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("space", "toggle_pause", "Pause/Resume"),
        Binding("right", "seek_forward", "+10s"),
        Binding("left", "seek_backward", "-10s"),
    ]

    def __init__(self, program: Program, guide_index: int, quality: AudioQuality = AudioQuality.COMPACT) -> None:
        """Initialise with program and track index."""
        super().__init__()
        self.program = program
        self.guide_index = guide_index
        self._player: CalmPlayer | None = None
        self._track: Guide = program.guides[guide_index]
        self._quality = quality

    def compose(self) -> ComposeResult:
        """Render the player UI."""
        yield Header(show_clock=True)
        yield Center(
            Vertical(
                Label(self.program.title, classes="title"),
                Label(self._track.title, classes="track"),
                ProgressBar(total=100, show_eta=False, id="progress"),
                Label("0:00 / 0:00", id="timer"),
                id="player-container",
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        """Start playback on mount."""
        self._start_playback()

    def on_unmount(self) -> None:
        """Clean up on exit."""
        if self._player:
            self._player.stop()
            self._player.shutdown()

    @work(exclusive=True, group="playback")
    async def _start_playback(self) -> None:
        """Initialize player and start streaming."""
        stream_url = self._track.stream_url_for(self._quality)
        if not stream_url:
            self.notify("No audio URL for this track", severity="error")
            self.exit()
            return

        try:
            self._player = CalmPlayer()
            self._player.play(stream_url)
            self.set_interval(0.5, self._update_progress)
        except RuntimeError as e:
            self.notify(str(e), severity="error")
            self.exit()

    def _update_progress(self) -> None:
        """Update progress bar and timer."""
        if not self._player:
            return

        pos = self._player.position
        dur = self._player.duration

        # Update labels
        timer = self.query_one("#timer", Label)
        timer.update(f"{format_time(pos)} / {format_time(dur)}")

        # Update progress bar
        progress = self.query_one("#progress", ProgressBar)
        progress.total = dur if dur > 0 else 100
        progress.progress = pos

    def action_toggle_pause(self) -> None:
        """Pause or resume playback."""
        if self._player:
            self._player.pause()
            status = "Paused" if self._player.is_paused else "Playing"
            self.notify(status)

    def action_seek_forward(self) -> None:
        """Seek forward 10s."""
        if self._player:
            self._player.seek(10)

    def action_seek_backward(self) -> None:
        """Seek backward 10s."""
        if self._player:
            self._player.seek(-10)


def run_play(program: Program, guide_index: int, quality: AudioQuality = AudioQuality.COMPACT) -> None:
    """Launch the play TUI."""
    app = PlayApp(program, guide_index, quality)
    app.run()

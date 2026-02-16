"""Audio playback via mpv.

Provides a thin wrapper around ``python-mpv`` to stream audio from URLs.
Used by both ``calm play`` and the browse TUI.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


from calm_client.logging import logger

def _check_mpv() -> None:
    """Raise a helpful error if ``mpv`` is not installed on the system."""
    try:
        import mpv as _mpv  # noqa: F401
    except ImportError:
        msg = (
            "The 'python-mpv' package is required for audio playback.\n"
            "Install it with:\n"
            "  pip install 'calm-client[player]'\n"
            "  # or: pipx inject calm-client python-mpv"
        )
        logger.error("mpv_python_missing")
        raise RuntimeError(msg) from None

    if shutil.which("mpv") is None:
        msg = (
            "mpv is required for audio playback but was not found.\n"
            "Install it with:\n"
            "  Ubuntu/Debian: sudo apt install mpv\n"
            "  macOS:         brew install mpv\n"
            "  Arch:          sudo pacman -S mpv"
        )
        logger.error("mpv_binary_missing")
        raise RuntimeError(msg)


class CalmPlayer:
    """Stream audio from Calm asset URLs via mpv."""

    def __init__(self) -> None:
        """Initialise the mpv player instance."""
        _check_mpv()
        import mpv  # type: ignore[import-untyped]

        logger.debug("player_init")
        self._player = mpv.MPV(
            video=False,  # audio only
            terminal=False,  # don't hijack the terminal
            input_terminal=False,
        )
        self._player.observe_property("time-pos", self._on_time_pos)
        self._player.observe_property("duration", self._on_duration)
        self._lock = threading.Lock()
        self._duration: float = 0.0
        self._position: float = 0.0
        self._on_progress: Callable[[float, float], None] | None = None
        self._on_end: Callable[[], None] | None = None

        @self._player.event_callback("end-file")
        def _on_end_file(event: mpv.MpvEvent) -> None:
            if self._on_end:
                self._on_end()

    @property
    def duration(self) -> float:
        """Total duration in seconds."""
        return self._duration

    @property
    def position(self) -> float:
        """Current position in seconds."""
        return self._position

    @property
    def is_playing(self) -> bool:
        """Whether audio is currently playing (not paused/stopped)."""
        try:
            return not self._player.pause and self._player.filename is not None
        except Exception:
            return False

    @property
    def is_paused(self) -> bool:
        """Whether playback is paused."""
        try:
            return bool(self._player.pause) and self._player.filename is not None
        except Exception:
            return False

    def play(self, url: str) -> None:
        """Start streaming audio from a URL."""
        if self._player:
            logger.info("player_play", url=url)
            self._player.play(url)

    def pause(self) -> None:
        """Toggle pause/resume."""
        if self._player:
            logger.info("player_toggle_pause", was_paused=self._player.pause)
            self._player.pause = not self._player.pause

    def stop(self) -> None:
        """Stop playback and clear callbacks to prevent deadlocks."""
        # Clear callbacks first to prevent on_end from firing during teardown
        logger.info("player_stop")
        self._on_end = None
        self._on_progress = None
        if self._player:
            with contextlib.suppress(Exception):
                self._player.stop()

    def seek(self, seconds: float) -> None:
        """Seek forward/backward by the given number of seconds."""
        if self._player:
            logger.debug("player_seek", seconds=seconds)
            self._player.seek(seconds, reference="relative")

    def set_volume(self, volume: int) -> None:
        """Set volume (0-100)."""
        if self._player:
            logger.debug("player_set_volume", volume=volume)
            self._player.volume = max(0, min(100, volume))

    def on_progress(self, callback: Callable[[float, float], None]) -> None:
        """Register a callback for playback progress: ``callback(position, duration)``."""
        self._on_progress = callback

    def on_end(self, callback: Callable[[], None]) -> None:
        """Register a callback for when playback ends."""
        self._on_end = callback

    def wait_for_playback(self) -> None:
        """Block until the current track finishes."""
        if self._player:
            self._player.wait_for_playback()

    def shutdown(self) -> None:
        """Clean up the mpv instance.

        Runs ``terminate()`` in a background thread with a timeout
        to avoid deadlocking when called while mpv callbacks are active.
        """
        logger.debug("player_shutdown")
        self._on_end = None
        self._on_progress = None
        if hasattr(self, "_player") and self._player:
            player = self._player
            self._player = None  # Prevent further access
            t = threading.Thread(target=self._terminate_player, args=(player,), daemon=True)
            t.start()
            t.join(timeout=2.0)  # Don't block forever

    @staticmethod
    def _terminate_player(player: object) -> None:
        """Terminate an mpv player instance, suppressing errors."""
        with contextlib.suppress(Exception):
            player.terminate()  # type: ignore[union-attr]

    def _on_time_pos(self, _name: str, value: float | None) -> None:
        """Handle time-pos property change from mpv."""
        if value is not None:
            self._position = value
            if self._on_progress and self._duration > 0:
                self._on_progress(self._position, self._duration)

    def _on_duration(self, _name: str, value: float | None) -> None:
        """Handle duration property change from mpv."""
        if value is not None:
            self._duration = value

    def __del__(self) -> None:
        """Clean up on garbage collection."""
        self.shutdown()


def format_time(seconds: float) -> str:
    """Format seconds as ``MM:SS`` or ``H:MM:SS``."""
    if seconds <= 0:
        return "0:00"
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

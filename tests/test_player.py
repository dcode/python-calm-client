import sys
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from calm_client.player import CalmPlayer, _check_mpv, format_time


class TestCalmPlayer:
    @pytest.fixture(autouse=True)
    def mock_dependencies(self) -> Generator[None]:
        """Mock external dependencies for all tests."""
        # Create a mock mpv module and inject it into sys.modules
        # so that `import mpv` inside CalmPlayer.__init__ picks it up.
        self.mock_mpv_module = MagicMock()
        self.mock_player_instance = MagicMock()
        self.mock_mpv_module.MPV.return_value = self.mock_player_instance

        with (
            patch.dict(sys.modules, {"mpv": self.mock_mpv_module}),
            patch("shutil.which", return_value="/usr/bin/mpv"),
        ):
            yield

    def _make_player(self) -> CalmPlayer:
        """Create a CalmPlayer with mocked dependencies."""
        return CalmPlayer()

    def test_check_mpv_installed(self) -> None:
        _check_mpv()

    def test_check_mpv_missing(self) -> None:
        with patch("shutil.which", return_value=None), pytest.raises(RuntimeError, match="mpv is required"):
            _check_mpv()

    def test_check_python_mpv_missing(self) -> None:
        # a None entry in sys.modules makes `import mpv` raise ImportError
        with patch.dict(sys.modules, {"mpv": None}), pytest.raises(RuntimeError, match=r"'player' extra"):
            _check_mpv()

    def test_check_libmpv_missing(self) -> None:
        real_import = __import__

        def failing_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "mpv":
                raise OSError("Cannot find libmpv in the usual places.")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        sys.modules.pop("mpv", None)
        with patch("builtins.__import__", side_effect=failing_import), pytest.raises(RuntimeError, match="libmpv"):
            _check_mpv()

    def test_init(self) -> None:
        player = self._make_player()

        # Verify MPV instantiated
        self.mock_mpv_module.MPV.assert_called()
        assert player._player is self.mock_player_instance

        # Verify property observers
        self.mock_player_instance.observe_property.assert_any_call("time-pos", player._on_time_pos)
        self.mock_player_instance.observe_property.assert_any_call("duration", player._on_duration)

    def test_playback_controls(self) -> None:
        player = self._make_player()

        player.play("http://example.com/stream.mp3")
        self.mock_player_instance.play.assert_called_with("http://example.com/stream.mp3")

        player.pause()
        # Verify pause property access
        # player._player.pause = not player._player.pause
        assert self.mock_player_instance.pause is False

        player.stop()
        self.mock_player_instance.stop.assert_called()

        player.seek(30)
        self.mock_player_instance.seek.assert_called_with(30, reference="relative")

        player.set_volume(50)
        assert self.mock_player_instance.volume == 50

    def test_is_playing_paused(self) -> None:
        player = self._make_player()

        self.mock_player_instance.pause = False
        self.mock_player_instance.filename = "stream.mp3"

        assert player.is_playing is True
        assert player.is_paused is False

        self.mock_player_instance.pause = True
        assert player.is_playing is False
        assert player.is_paused is True

        self.mock_player_instance.filename = None
        assert player.is_playing is False
        assert player.is_paused is False

    def test_callbacks(self) -> None:
        player = self._make_player()

        prog_cb = MagicMock()
        player.on_progress(prog_cb)

        player._on_duration("duration", 100.0)
        player._on_time_pos("time-pos", 10.0)

        prog_cb.assert_called_with(10.0, 100.0)

        # Check event registration
        self.mock_player_instance.event_callback.assert_called_with("end-file")

    def test_shutdown(self) -> None:
        player = self._make_player()
        player.shutdown()
        self.mock_player_instance.terminate.assert_called()
        assert player._player is None

    def test_format_time(self) -> None:
        assert format_time(0) == "0:00"
        assert format_time(65) == "1:05"
        assert format_time(3600) == "1:00:00"

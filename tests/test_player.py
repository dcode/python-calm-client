import sys
from collections.abc import Generator
from unittest.mock import MagicMock, PropertyMock, patch

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

    def test_end_file_event_runs_on_end_callback(self) -> None:
        player = self._make_player()
        # @player.event_callback("end-file") registered the handler on the decorator mock
        handler = self.mock_player_instance.event_callback.return_value.call_args.args[0]

        handler(MagicMock())  # no callback registered yet: nothing happens
        on_end = MagicMock()
        player.on_end(on_end)
        handler(MagicMock())
        on_end.assert_called_once_with()

    def test_position_and_duration_tracking(self) -> None:
        player = self._make_player()
        progress = MagicMock()
        player.on_progress(progress)

        player._on_time_pos("time-pos", 5.0)  # duration unknown yet: no progress callback
        player._on_time_pos("time-pos", None)
        player._on_duration("duration", None)
        progress.assert_not_called()
        assert player.position == 5.0
        assert player.duration == 0.0

        player._on_duration("duration", 60.0)
        assert player.duration == 60.0

    def test_state_errors_report_not_playing(self) -> None:
        player = self._make_player()
        # mpv raises once the player is torn down
        type(self.mock_player_instance).pause = PropertyMock(side_effect=RuntimeError("gone"))
        try:
            assert player.is_playing is False
            assert player.is_paused is False
        finally:
            del type(self.mock_player_instance).pause

    def test_volume_is_clamped(self) -> None:
        player = self._make_player()
        player.set_volume(150)
        assert self.mock_player_instance.volume == 100
        player.set_volume(-5)
        assert self.mock_player_instance.volume == 0

    def test_stop_clears_callbacks_and_ignores_errors(self) -> None:
        player = self._make_player()
        player.on_end(MagicMock())
        player.on_progress(MagicMock())
        self.mock_player_instance.stop.side_effect = RuntimeError("mpv gone")
        player.stop()
        assert player._on_end is None
        assert player._on_progress is None

    def test_wait_for_playback(self) -> None:
        player = self._make_player()
        player.wait_for_playback()
        self.mock_player_instance.wait_for_playback.assert_called_once_with()

    def test_controls_are_noops_after_shutdown(self) -> None:
        player = self._make_player()
        player.shutdown()
        self.mock_player_instance.reset_mock()

        player.play("u")
        player.pause()
        player.stop()
        player.seek(5)
        player.set_volume(10)
        player.wait_for_playback()
        player.shutdown()  # second shutdown is harmless

        assert not self.mock_player_instance.method_calls

    def test_terminate_errors_are_suppressed(self) -> None:
        broken = MagicMock()
        broken.terminate.side_effect = RuntimeError("already dead")
        CalmPlayer._terminate_player(broken)
        broken.terminate.assert_called_once_with()

    def test_shutdown(self) -> None:
        player = self._make_player()
        player.shutdown()
        self.mock_player_instance.terminate.assert_called()
        assert player._player is None

    def test_format_time(self) -> None:
        assert format_time(0) == "0:00"
        assert format_time(65) == "1:05"
        assert format_time(3600) == "1:00:00"

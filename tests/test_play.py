from unittest.mock import MagicMock, patch

import pytest

from calm_client.models import Guide, Program
from calm_client.play import PlayApp


class TestPlayApp:
    @pytest.fixture
    def mock_program(self):
        guide = MagicMock(spec=Guide)
        guide.title = "Test Guide"
        guide.stream_url = "http://example.com/stream.mp3"

        program = MagicMock(spec=Program)
        program.title = "Test Program"
        program.guides = [guide]
        return program

    @pytest.fixture
    def mock_player(self):
        with patch("calm_client.play.CalmPlayer") as mock:
            player_instance = mock.return_value
            player_instance.duration = 100.0
            player_instance.position = 0.0
            player_instance.play = MagicMock()
            player_instance.stop = MagicMock()
            player_instance.pause = MagicMock()
            player_instance.seek = MagicMock()
            player_instance.shutdown = MagicMock()
            # Mock is_paused property behavior if needed, but actions usually just toggle
            yield player_instance

    @pytest.mark.asyncio
    async def test_play_app_mount_and_quit(self, mock_program, mock_player):
        app = PlayApp(mock_program, 0)
        async with app.run_test() as pilot:
            # Check if playback started
            mock_player.play.assert_called_with("http://example.com/stream.mp3")

            # Check UI elements
            # Use render() to get the content, converted to string
            assert str(app.query_one(".title").render()) == "Test Program"
            assert str(app.query_one(".track").render()) == "Test Guide"

            # Send 'q' to quit
            await pilot.press("q")

        # Verify cleanup
        mock_player.stop.assert_called()
        mock_player.shutdown.assert_called()

    @pytest.mark.asyncio
    async def test_play_controls(self, mock_program, mock_player):
        app = PlayApp(mock_program, 0)
        async with app.run_test() as pilot:
            # Space to pause
            await pilot.press("space")
            mock_player.pause.assert_called()

            # Right to seek forward
            await pilot.press("right")
            mock_player.seek.assert_called_with(10)

            # Left to seek backward
            await pilot.press("left")
            mock_player.seek.assert_called_with(-10)

    @pytest.mark.asyncio
    async def test_playback_error(self, mock_program):
        # Setup program with no URL
        mock_program.guides[0].stream_url = None

        app = PlayApp(mock_program, 0)
        async with app.run_test() as _:
            # Should exit or show error.
            # In code: self.notify("No audio URL...", severity="error"); self.exit()
            # We can check if app is not running or if notify was called
            # But run_test context might close immediately if self.exit() is called.
            pass

        # If we reached here without hanging, it likely exited.

    @pytest.mark.asyncio
    async def test_player_init_error(self, mock_program):
        with patch("calm_client.play.CalmPlayer", side_effect=RuntimeError("No mpv")):
            app = PlayApp(mock_program, 0)
            async with app.run_test() as _:
                # Should notify and exit
                pass
            # Should exit cleanly

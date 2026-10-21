import sys
from unittest.mock import patch

import pytest

from calm_client._entry import main


def test_entry_explains_missing_cli_extra(capsys: pytest.CaptureFixture[str]) -> None:
    # a None entry in sys.modules makes `from calm_client.cli import app` raise ImportError
    with patch.dict(sys.modules, {"calm_client.cli": None}), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "calm-client[player]" in err
    assert "calm-client[cli]" in err


def test_entry_runs_cli() -> None:
    with patch("calm_client.cli.app") as app:
        main()
    app.meta.assert_called_once_with()

"""Entry point for the ``calm`` command.

The CLI's dependencies are an optional extra, so a library-only install still gets the
``calm`` script; this reports what to install instead of failing with an ImportError.
"""

from __future__ import annotations

import sys

INSTALL_HINT = (
    "The calm command line needs extra packages ({missing} is not installed).\n"
    "Install them with one of:\n"
    "  pipx install 'calm-client[player]'   # CLI, TUI browser and audio playback\n"
    "  pipx install 'calm-client[cli]'      # CLI and TUI browser only\n"
)


def main() -> None:
    """Run the CLI, or explain which extra is missing."""
    try:
        from calm_client.cli import app
    except ImportError as err:
        sys.stderr.write(INSTALL_HINT.format(missing=err.name or "a dependency"))
        raise SystemExit(1) from None
    app.meta()

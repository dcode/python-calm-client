"""Fail when any source file's coverage is below a minimum.

coverage.py only enforces a total (``fail_under``); this adds a per-file floor.
Under GitHub Actions, each file below the floor is also reported as an ``::error``
annotation on that file.

    uv run coverage json -o coverage.json
    uv run python scripts/check_coverage.py coverage.json --min-file 85
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    """Check per-file coverage from a ``coverage json`` report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path, help="coverage JSON report")
    parser.add_argument("--min-file", type=float, default=85.0, help="minimum coverage per file (percent)")
    args = parser.parse_args()

    files = json.loads(args.report.read_text())["files"]
    below = {
        name: data["summary"]["percent_covered"]
        for name, data in files.items()
        if data["summary"]["percent_covered"] < args.min_file
    }
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for name, percent in sorted(below.items()):
        message = f"{percent:.1f}% < {args.min_file:.0f}%"
        print(f"{name}: {message}")
        if annotate:
            print(f"::error file={name},title=Coverage below {args.min_file:.0f}%::{name} has {message} coverage")
    if below:
        return 1
    print(f"All {len(files)} files have at least {args.min_file:.0f}% coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

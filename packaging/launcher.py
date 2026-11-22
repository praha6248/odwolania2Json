"""PyInstaller entry point.

The window executable opens the interface when started without arguments and runs the CLI with arguments; the
console executable (odwolania2json-cli) always runs the CLI, so its output stays in the terminal.
"""

import sys
from pathlib import Path

from odwolania2json.desktop import ensure_streams

ensure_streams()  # a window executable has no console: send output to a log file before anything logs

from odwolania2json.cli import main as cli_main  # noqa: E402
from odwolania2json.desktop import main as desktop_main  # noqa: E402

if __name__ == "__main__":
    console = Path(sys.executable).stem.lower().endswith("-cli")
    raise SystemExit(cli_main() if console or len(sys.argv) > 1 else desktop_main())

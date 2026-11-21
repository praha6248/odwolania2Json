"""PyInstaller entry point.

The window executable opens the interface when started without arguments and runs the CLI with arguments; the
console executable (odwolania2json-cli) always runs the CLI, so its output stays in the terminal.
"""

import sys
from pathlib import Path

from odwolania2json.cli import main as cli_main
from odwolania2json.desktop import main as desktop_main

if __name__ == "__main__":
    console = Path(sys.executable).stem.lower().endswith("-cli")
    raise SystemExit(cli_main() if console or len(sys.argv) > 1 else desktop_main())

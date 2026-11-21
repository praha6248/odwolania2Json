"""PyInstaller entry point: GUI when started without arguments, CLI otherwise."""

import sys

from odwolania2json.cli import main as cli_main
from odwolania2json.desktop import main as desktop_main

if __name__ == "__main__":
    raise SystemExit(cli_main() if len(sys.argv) > 1 else desktop_main())

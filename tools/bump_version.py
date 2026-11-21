"""Keep the version one patch above the newest release: v0.3.2 released -> 0.3.3.

The bump workflow runs it after each push to main with the newest release tag. Pushes between two releases share one
version, so numbers are not used up. A version raised by hand (higher major or minor) is kept for the next release.

Usage: python tools/bump_version.py <latest-tag-or-empty>   prints the new version when the file changed
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "odwolania2json" / "__init__.py"
PATTERN = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"', re.M)


def parse(text: str) -> tuple[int, int, int] | None:
    """Parse 'v1.2.3' or '1.2.3' into a tuple."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", text.strip())
    return tuple(int(n) for n in match.groups()) if match else None


def target(current: tuple[int, int, int], latest: tuple[int, int, int] | None) -> tuple[int, int, int]:
    """Return the version that should follow the latest release."""
    if latest is None or current[:2] > latest[:2]:
        return current if latest is None or current > latest else (latest[0], latest[1], latest[2] + 1)
    return (latest[0], latest[1], latest[2] + 1)


def main(argv: list[str]) -> int:
    """Rewrite the version file when needed and print the new version."""
    text = FILE.read_text(encoding="utf-8")
    match = PATTERN.search(text)
    if not match:
        sys.exit(f"No version in {FILE}")
    current = tuple(int(n) for n in match.groups())
    wanted = target(current, parse(argv[1]) if len(argv) > 1 and argv[1] else None)
    if wanted == current:
        return 0
    version = ".".join(map(str, wanted))
    FILE.write_text(PATTERN.sub(f'__version__ = "{version}"', text), encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

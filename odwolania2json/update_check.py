"""Check whether a newer release is published on GitHub.

Any failure (no internet, rate limit, unexpected answer) simply means "no update known"; nothing is downloaded here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Any

from . import __version__

log = logging.getLogger(__name__)

GITHUB_REPO = os.environ.get("O2J_UPDATE_REPO", "praha6248/odwolania2Json")
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DOWNLOAD_PAGE_URL = f"https://{GITHUB_REPO.split('/')[0].lower()}.github.io/{GITHUB_REPO.split('/')[1]}/"
TIMEOUT_S = 6
_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+){0,3})")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """Turn 'v1.2.3' into (1, 2, 3); None when the text is not a version."""
    match = _VERSION_RE.match(text or "")
    return tuple(int(n) for n in match.group(1).split(".")) if match else None


def is_newer(candidate: str | None, current: str) -> bool:
    """Tell whether candidate is a strictly higher version than current."""
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def check_for_update(current: str = __version__) -> dict[str, Any]:
    """Ask the GitHub API for the latest release and report whether it is newer than the running version."""
    if os.environ.get("O2J_NO_UPDATE_CHECK"):
        return {"available": False, "current": current}
    try:
        request = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "odwolania2json-update-check"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            release = json.loads(response.read().decode())
    except Exception as exc:
        log.debug("Update check failed: %s", exc)
        return {"available": False, "current": current}
    tag = release.get("tag_name")
    return {
        "available": is_newer(tag, current),
        "current": current,
        "latest": (tag or "").lstrip("v"),
        "url": release.get("html_url") or DOWNLOAD_PAGE_URL,
        "assets": [{"name": a.get("name"), "url": a.get("browser_download_url"), "size": a.get("size")} for a in release.get("assets", [])],
    }

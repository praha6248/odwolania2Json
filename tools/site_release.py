"""Write site/release.json: the latest GitHub release with SHA-256 sums, served next to the download page.

The download page and the in-app update check read this file from GitHub Pages first, so they do not depend on the
unauthenticated GitHub API limit of 60 requests per hour per IP address. The file keeps the API field names.

Usage (in the pages workflow): GH_TOKEN=... python tools/site_release.py owner/repo site/release.json
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    """GET a URL, authenticated with GH_TOKEN when it is set."""
    headers = {"Accept": accept, "User-Agent": "odwolania2json-site"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return response.read()


def main(repo: str, target: Path) -> int:
    """Fetch the latest release and write its public fields with checksums."""
    try:
        release = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        target.write_text("{}\n", encoding="utf-8")
        print("No release published yet")
        return 0
    sums = {}
    for asset in release.get("assets", []):
        if asset["name"].endswith(".sha256"):
            text = get(asset["url"], "application/octet-stream").decode("utf-8", "replace")
            sums[asset["name"].removesuffix(".sha256")] = text.split()[0] if text.split() else ""
    data = {
        "tag_name": release.get("tag_name"),
        "name": release.get("name"),
        "published_at": release.get("published_at"),
        "html_url": release.get("html_url"),
        "zipball_url": release.get("zipball_url"),
        "body": release.get("body") or "",
        "assets": [
            {"name": a["name"], "size": a["size"], "browser_download_url": a["browser_download_url"], "sha256": sums.get(a["name"])}
            for a in release.get("assets", [])
        ],
    }
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{data['tag_name']}: {len(data['assets'])} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2])))

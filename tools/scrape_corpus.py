"""Collect public documents for robustness testing (local use only, never committed).

Sources:
    --kio START END COUNT   KIO rulings from the official UZP database (orzeczenia.uzp.gov.pl), sampled evenly between
                            two ids; they share the vocabulary of appeals and are used as look-alike negatives and to
                            study real phrasing of challenged acts
    --urls FILE             one URL per line (e.g. appeals published in public information bulletins)

Every request checks robots.txt of its host, honours Crawl-delay (at least --delay seconds between requests to the
same host) and identifies itself with a descriptive User-Agent. Files go to data_real/<category>/.

Usage: python tools/scrape_corpus.py --kio 5000 36000 60 --urls seeds.txt
"""

from __future__ import annotations

import argparse
import hashlib
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

USER_AGENT = "Odwolania2JSON-research-crawler/1.0 (HackNation 2026 test corpus; low rate)"
KIO_URL = "https://orzeczenia.uzp.gov.pl/Home/PdfContent/{id}?Kind=KIO"


class PoliteFetcher:
    """HTTP client that obeys robots.txt and per-host delays."""

    def __init__(self, delay: float) -> None:
        """Create a fetcher with a minimum delay between requests to one host."""
        self.delay = delay
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.last: dict[str, float] = {}

    def _robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """Load and cache robots.txt of the URL's host."""
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.robots:
            parser = urllib.robotparser.RobotFileParser(f"{host}/robots.txt")
            try:
                request = urllib.request.Request(f"{host}/robots.txt", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read().decode("utf-8", "replace")
                parser.parse(body.splitlines() if "user-agent" in body.lower() else [])
            except Exception:
                parser.parse([])
            self.robots[host] = parser
        return self.robots[host]

    def allowed(self, url: str) -> bool:
        """Tell whether robots.txt allows fetching the URL."""
        parser = self._robots(url)
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> bytes | None:
        """Fetch a URL if allowed, waiting for the host's crawl delay."""
        if not self.allowed(url):
            print(f"  robots.txt disallows {url}")
            return None
        host = urllib.parse.urlsplit(url).netloc
        parser = self._robots(url)
        wait = max(self.delay, float((parser.crawl_delay(USER_AGENT) if parser else 0) or 0))
        elapsed = time.monotonic() - self.last.get(host, 0)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self.last[host] = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            print(f"  failed {url}: {exc}")
            return None


def save(data: bytes | None, folder: Path, name: str) -> bool:
    """Store a PDF unless it is not a PDF or already present."""
    if not data or not data.startswith(b"%PDF"):
        return False
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return True


def main(argv: list[str] | None = None) -> int:
    """Collect the requested documents."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kio", nargs=3, type=int, metavar=("START", "END", "COUNT"))
    parser.add_argument("--urls", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data_real"))
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args(argv)
    fetcher = PoliteFetcher(args.delay)
    saved = 0
    if args.kio:
        start, end, count = args.kio
        step = max(1, (end - start) // max(1, count))
        for ruling_id in range(start, end, step):
            target = args.out / "orzeczenia" / f"kio_{ruling_id}.pdf"
            if target.exists():
                continue
            saved += save(fetcher.get(KIO_URL.format(id=ruling_id)), target.parent, target.name)
    if args.urls:
        for url in [u.strip() for u in args.urls.read_text(encoding="utf-8").splitlines() if u.strip() and not u.startswith("#")]:
            name = hashlib.sha1(url.encode()).hexdigest()[:12] + ".pdf"
            saved += save(fetcher.get(url), args.out / "urls", name)
    print(f"Saved {saved} new PDF(s) under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

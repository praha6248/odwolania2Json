"""Test the application on real documents published on the internet.

    python -I tools/real_world_test.py fetch     download the documents listed in tools/real_world_seeds.yaml
    python -I tools/real_world_test.py run       process them (batch pipeline + web API) and write a report

The PDFs go to data_real/real_world/ (git-ignored, never committed). The report lists, for every document:
the recognised type against the expected one, the extracted JSON, crashes, slow processing, values that fail
sanity checks (NIP/REGON/KRS checksums, impossible dates, values not present in the text, run-away strings) and
hand-checked values from the seed file that differ. The web part uploads all documents into one application
instance and calls every read-only endpoint (cases, exports, page images, field location, anonymisation, search).

Downloads reuse the polite fetcher of tools/scrape_corpus.py (robots.txt, crawl delay, descriptive User-Agent).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import yaml  # noqa: E402

SEEDS = ROOT / "tools" / "real_world_seeds.yaml"
DATA = ROOT / "data_real" / "real_world"
SLOW_SECONDS = 20.0


def load_seeds() -> list[dict[str, Any]]:
    """Return the seed entries from the YAML file, plus an even sample of KIO rulings when configured."""
    from scrape_corpus import KIO_URL

    config = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    seeds = list(config["documents"])
    sample = config.get("kio_sample")
    if sample:
        step = max(1, (sample["end"] - sample["start"]) // max(1, sample["count"]))
        for ruling_id in range(sample["start"], sample["end"], step):
            seeds.append({"id": f"kio_{ruling_id}", "url": KIO_URL.format(id=ruling_id), "expect": "none"})
    return seeds


def pdf_path(seed: dict[str, Any]) -> Path:
    """Local path of a seed document."""
    return DATA / "pdf" / seed["expect"] / f"{seed['id']}.pdf"


def fetch(seeds: list[dict[str, Any]], delay: float) -> int:
    """Download every seed that is not present yet."""
    from scrape_corpus import PoliteFetcher

    fetcher = PoliteFetcher(delay)
    missing = 0
    for seed in seeds:
        target = pdf_path(seed)
        if target.exists():
            continue
        data = fetcher.get(seed["url"])
        if not data or not data.startswith(b"%PDF"):
            print(f"  not a PDF / unavailable: {seed['id']}")
            missing += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"  saved {target.relative_to(ROOT)} ({len(data) // 1024} kB)")
    return missing


# --- sanity checks of extracted values (no ground truth needed) ---------------------------------------------------

def nip_ok(value: str) -> bool:
    """Validate a NIP checksum."""
    d = [int(c) for c in value]
    return len(d) == 10 and sum(w * x for w, x in zip((6, 5, 7, 2, 3, 4, 5, 6, 7), d)) % 11 == d[9]


def regon_ok(value: str) -> bool:
    """Validate a 9 or 14 digit REGON checksum."""
    d = [int(c) for c in value]
    weights = {9: (8, 9, 2, 3, 4, 5, 6, 7), 14: (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)}.get(len(d))
    return bool(weights) and sum(w * x for w, x in zip(weights, d)) % 11 % 10 == d[-1]


def pesel_ok(value: str) -> bool:
    """Validate a PESEL checksum."""
    d = [int(c) for c in value]
    return len(d) == 11 and (10 - sum(w * x for w, x in zip((1, 3, 7, 9, 1, 3, 7, 9, 1, 3), d)) % 10) % 10 == d[10]


def squash(text: str) -> str:
    """Lowercase text without whitespace and punctuation, for presence checks."""
    return re.sub(r"[\W_]+", "", text).lower()


def walk(data: Any, prefix: str = ""):
    """Yield (path, value) for every leaf of a JSON structure."""
    if isinstance(data, dict):
        for k, v in data.items():
            yield from walk(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, data


def sanity(data: dict[str, Any] | None, text: str) -> list[str]:
    """Flag extracted values that are very likely wrong."""
    problems: list[str] = []
    if not data:
        return problems
    plain = squash(text)
    today = dt.date.today()
    for path, value in walk(data):
        leaf = path.rsplit(".", 1)[-1]
        if value is None or value == "":
            continue
        if isinstance(value, str):
            if "\n" in value:
                problems.append(f"{path}: contains a line break: {value!r}")
            if len(value) > 300:
                problems.append(f"{path}: {len(value)} characters long (run-away match?)")
            if leaf == "nip" and not (value.isdigit() and nip_ok(value)):
                problems.append(f"{path}: invalid NIP {value!r}")
            if leaf == "regon" and not (value.isdigit() and regon_ok(value)):
                problems.append(f"{path}: invalid REGON {value!r}")
            if leaf == "krs" and not re.fullmatch(r"\d{10}", value):
                problems.append(f"{path}: invalid KRS {value!r}")
            if leaf == "pesel" and not (value.isdigit() and pesel_ok(value)):
                problems.append(f"{path}: invalid PESEL {value!r}")
            if leaf == "mail" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", value, re.I):
                problems.append(f"{path}: invalid e-mail {value!r}")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    day = dt.date.fromisoformat(value)
                    if not dt.date(2010, 1, 1) <= day <= today + dt.timedelta(days=60):
                        problems.append(f"{path}: implausible date {value}")
                except ValueError:
                    problems.append(f"{path}: impossible date {value}")
            if leaf in {"nazwa", "imie_nazwisko", "tytul", "numer_postepowania", "miejscowosc"}:
                if squash(value) and squash(value) not in plain and leaf not in {"imie_nazwisko", "miejscowosc"}:
                    problems.append(f"{path}: value not found in the text: {value!r}")
                if re.search(r"(?i)(?:\bul\s?\.|\b(?:nip|regon|krs|tel|e-mail|adres)\b|\b\d{2}-\d{3}\b)", value):
                    problems.append(f"{path}: contains address/identifier words: {value!r}")
                if len(value) < 3:
                    problems.append(f"{path}: suspiciously short {value!r}")
    return problems


def compare(expected: dict[str, Any] | None, data: dict[str, Any] | None) -> tuple[int, list[str]]:
    """Compare hand-checked values (keyed by JSON path) with the output; return (matching count, differences)."""
    from difflib import SequenceMatcher

    leaves = dict(walk(data or {}))
    matching, diffs = 0, []
    for path, want in (expected or {}).items():
        got = leaves.get(path)
        if isinstance(want, str) and want.startswith("sha256:"):
            same = isinstance(got, str) and hashlib.sha256(got.encode("utf-8")).hexdigest()[:16] == want[7:]
            if same:
                matching += 1
            else:
                diffs.append(f"{path}: expected the value with {want}, got {got!r}")
            continue
        same = got == want
        if not same and isinstance(want, str) and isinstance(got, str) and len(want) > 30:
            same = SequenceMatcher(None, want.lower(), got.lower()).ratio() >= 0.8
        if same:
            matching += 1
        else:
            diffs.append(f"{path}: expected {want!r}, got {got!r}")
    return matching, diffs


# --- running the application ---------------------------------------------------------------------------------------

def run_pipeline(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Process every downloaded document with the batch processor."""
    from odwolania2json.pipeline import Processor, write_json

    processor = Processor(use_llm=False)
    rows = []
    for seed in seeds:
        path = pdf_path(seed)
        if not path.exists():
            continue
        row: dict[str, Any] = {"id": seed["id"], "expect": seed["expect"], "url": seed["url"]}
        try:
            result = processor.process_pdf(path)
        except Exception:
            row["crash"] = traceback.format_exc()
            rows.append(row)
            continue
        got = result.doc_type or "none"
        matching, diffs = compare(seed.get("values"), result.data)
        row.update(
            got=got,
            classified_ok=got == seed["expect"],
            scores=result.classification.scores,
            seconds=round(result.seconds, 2),
            chars=len(result.text),
            ocr=result.ocr,
            error=result.error,
            data=result.data,
            sanity=sanity(result.data, result.text),
            checked=len(seed.get("values") or {}),
            matching=matching,
            diffs=diffs,
            empty=[f["field"] for f in result.fields if f["value"] in (None, [], "")],
        )
        (DATA / "text").mkdir(parents=True, exist_ok=True)
        (DATA / "text" / f"{seed['id']}.txt").write_text(result.text, encoding="utf-8")
        write_json(DATA / "json" / f"{seed['id']}.json", result.data if result.data is not None else {})
        write_json(DATA / "trace" / f"{seed['id']}.trace.json", result.trace())
        rows.append(row)
        print(f"  {seed['id']:<40} expect={seed['expect']:<14} got={got:<14} {row['seconds']:>6}s"
              f"{'  SANITY ' + str(len(row['sanity'])) if row['sanity'] else ''}")
    return rows


def run_web(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upload all documents into one web application and call its endpoints; return failures."""
    os.environ["O2J_NO_UPDATE_CHECK"] = "1"
    from fastapi.testclient import TestClient

    from odwolania2json.web.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    failures: list[dict[str, Any]] = []

    def call(method: str, url: str, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            response = client.request(method, url, **kwargs)
        except Exception:
            failures.append({"call": f"{method} {url}", "error": traceback.format_exc()})
            return None
        took = time.perf_counter() - started
        if response.status_code >= 400 and response.status_code not in (404, 409):
            failures.append({"call": f"{method} {url}", "status": response.status_code, "body": response.text[:500]})
        if took > SLOW_SECONDS:
            failures.append({"call": f"{method} {url}", "slow": round(took, 1)})
        return response

    docs = []
    for seed in seeds:
        path = pdf_path(seed)
        if not path.exists():
            continue
        response = call("POST", "/api/documents", files=[("files", (path.name, path.read_bytes(), "application/pdf"))])
        if response is not None and response.status_code == 200:
            docs.extend(response.json())
    call("GET", "/api/documents")
    call("GET", "/api/cases")
    call("GET", "/api/export.xlsx")
    call("GET", "/api/export.csv")
    call("POST", "/api/search", json={"question": "zarzut naruszenia art. 226 ust. 1 pkt 5 Pzp"})
    for doc in docs:
        base = f"/api/documents/{doc['id']}"
        call("GET", base)
        call("GET", f"{base}/json")
        pages = call("GET", f"{base}/pages")
        if pages is not None and pages.status_code == 200:
            call("GET", f"{base}/pages/1.png")
        if doc.get("doc_type"):
            for field in doc.get("fields") or []:
                if field.get("value") not in (None, [], ""):
                    call("GET", f"{base}/locate/{field['field']}")
            if not doc.get("ocr"):  # anonymisation of scanned pages is refused by design (HTTP 400)
                call("GET", f"{base}/anonymized.pdf")
            call("GET", f"/api/types/sample/{doc['id']}")
    return failures


def run_batch() -> list[str]:
    """Run the CLI batch mode over the downloaded tree and check that every PDF got a JSON file."""
    from odwolania2json.pipeline import Processor

    out = DATA / "batch_output"
    results = Processor(use_llm=False).process_tree(DATA / "pdf", out)
    missing = [str(r.path.name) for r in results if not (out / r.path.relative_to(DATA / "pdf")).with_suffix(".json").exists()]
    return missing


def report(rows: list[dict[str, Any]], web: list[dict[str, Any]], batch_missing: list[str]) -> str:
    """Render a Markdown summary of the run."""
    lines = ["# Real-world test run", "", f"Date: {dt.date.today().isoformat()}", ""]
    total = len(rows)
    ok = sum(1 for r in rows if r.get("classified_ok"))
    checked = sum(r.get("checked", 0) for r in rows)
    matching = sum(r.get("matching", 0) for r in rows)
    lines += [f"Classification: {ok}/{total} as expected", ""]
    if checked:
        lines += [f"Hand-checked values: {matching}/{checked} correct ({matching / checked:.1%})", ""]
    lines += ["| document | expected | got | s | hand-checked | empty fields | sanity |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if "crash" in r:
            lines.append(f"| {r['id']} | {r['expect']} | **CRASH** | | | | |")
            continue
        if r["expect"] == "none" and r["classified_ok"] and r["id"].startswith("kio_"):
            continue  # sampled rulings are summarised by the classification count
        mark = "" if r["classified_ok"] else " ❌"
        empty = ", ".join(r["empty"]) if r["got"] != "none" else ""
        hand = f"{r['matching']}/{r['checked']}" if r.get("checked") else ""
        lines.append(f"| {r['id']} | {r['expect']} | {r['got']}{mark} | {r['seconds']} | {hand} | {empty} | {len(r['sanity'])} |")
    lines += ["", "## Sanity problems", ""]
    for r in rows:
        for problem in r.get("sanity") or []:
            lines.append(f"- `{r['id']}` {problem}")
        for diff in r.get("diffs") or []:
            lines.append(f"- `{r['id']}` hand-checked {diff}")
        if r.get("crash"):
            lines.append(f"- `{r['id']}` crash:\n```\n{r['crash']}\n```")
    lines += ["", "## Web API failures", ""]
    lines += [f"- {json.dumps(f, ensure_ascii=False)}" for f in web] or ["none"]
    lines += ["", "## Batch mode", "", f"PDFs without an output JSON: {batch_missing or 'none'}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["fetch", "run"])
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--only", help="regular expression selecting seed ids")
    parser.add_argument("--no-web", action="store_true")
    args = parser.parse_args(argv)
    seeds = [s for s in load_seeds() if not args.only or re.search(args.only, s["id"])]
    if args.command == "fetch":
        missing = fetch(seeds, args.delay)
        print(f"{len(seeds) - missing}/{len(seeds)} documents available under {DATA.relative_to(ROOT)}")
        return 0
    rows = run_pipeline(seeds)
    web = [] if args.no_web else run_web(seeds)
    batch_missing = [] if args.no_web else run_batch()
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "report.json").write_text(json.dumps({"documents": rows, "web": web, "batch_missing": batch_missing},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    text = report(rows, web, batch_missing)
    (DATA / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

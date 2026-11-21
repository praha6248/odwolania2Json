"""The documented example of a new document type works without code changes."""

import re
import shutil
from pathlib import Path

from odwolania2json.classifier import classify
from odwolania2json.config import load_settings
from odwolania2json.engine import extract

ROOT = Path(__file__).resolve().parents[1]
TEXT = """Krajowa Izba Odwoławcza
Warszawa, dnia 12 marca 2026
WEZWANIE
do uzupełnienia wpisu od odwołania w sprawie KIO 1234/26.
Wzywam do uiszczenia brakującej kwoty 7 500,00 zł w terminie 3 dni."""


def test_documented_example_type(tmp_path):
    """The YAML from docs/nowy-typ-dokumentu.md loads, classifies and extracts."""
    config = tmp_path / "config"
    shutil.copytree(ROOT / "config", config)
    doc = (ROOT / "docs" / "nowy-typ-dokumentu.md").read_text(encoding="utf-8")
    example = re.search(r"```yaml\n(name: wezwanie_wpis.*?)```", doc, re.S).group(1)
    (config / "document_types" / "wezwanie_wpis.yaml").write_text(example, encoding="utf-8")
    settings = load_settings(config)
    assert classify(settings, TEXT, "wezwanie.pdf").doc_type == "wezwanie_wpis"
    data, _ = extract(TEXT, settings.get_type("wezwanie_wpis"))
    assert data == {"Wezwanie": {"sygnatura": "KIO 1234/26", "data": "2026-03-12", "kwota": 7500.0, "termin_dni": 3}}

"""Output contract: strict JSON structure and no JSON for documents outside the configured types."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from odwolania2json.config import load_settings
from odwolania2json.pipeline import Processor

FIXTURES = Path(__file__).parent / "fixtures"
NEGATIVE = Path(__file__).parent / "fixtures_negative" / "negatywny_przyklad.pdf"
PAIRS = {"odwolanie.pdf": "odwolanie.json", "pelnomocnictwo.pdf": "pelnomocnictwo.json", "potwierdzenie_przelewu.pdf": "przelew.json"}


def shape(value):
    """Describe the key structure of a JSON value (lists by the shape of their first item)."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return None


@pytest.fixture(scope="module")
def processor():
    """Processor without OCR and LLM."""
    settings = load_settings()
    settings.ocr["enabled"] = False
    return Processor(settings, use_llm=False)


@pytest.mark.parametrize("pdf_name", list(PAIRS))
def test_output_keys_match_reference_exactly(processor, pdf_name):
    """Every output has exactly the keys, nesting and key order of the UZP reference JSON."""
    for case in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        data = processor.process_pdf(case / pdf_name).data
        reference = json.loads((case / PAIRS[pdf_name]).read_text(encoding="utf-8"))
        assert shape(data) == shape(reference)
        assert list(json.dumps(data)) and json.dumps(shape(data)) == json.dumps(shape(reference))


def test_document_outside_known_types_gets_no_json(processor, tmp_path):
    """A TED notice is reported as unmatched and no JSON file is written."""
    result = processor.process_pdf(NEGATIVE)
    assert result.doc_type is None and result.data is None
    assert "Nie udało się dopasować typu" in result.message
    (tmp_path / "input" / "case1").mkdir(parents=True)
    (tmp_path / "input" / "case1" / NEGATIVE.name).write_bytes(NEGATIVE.read_bytes())
    processor.process_tree(tmp_path / "input", tmp_path / "output")
    assert not list((tmp_path / "output").rglob("*.json"))


def test_cli_extract_reports_unmatched_type():
    """The CLI prints the reason on stderr and exits with code 2 for an unmatched document."""
    run = subprocess.run([sys.executable, "-m", "odwolania2json", "extract", str(NEGATIVE)], capture_output=True, text=True)
    assert run.returncode == 2 and run.stdout == "" and "Nie udało się dopasować typu" in run.stderr

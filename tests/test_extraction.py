"""End-to-end and unit tests of the extraction pipeline."""

import json
from pathlib import Path

import pytest

from odwolania2json import fuzzy_re, normalizers
from odwolania2json.classifier import classify
from odwolania2json.config import load_settings
from odwolania2json.evaluate import evaluate_dataset
from odwolania2json.pipeline import Processor

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def processor():
    """Processor with OCR and LLM disabled for fast, deterministic tests."""
    settings = load_settings()
    settings.ocr["enabled"] = False
    return Processor(settings, use_llm=False)


def test_fixtures_reach_full_f1(processor):
    """Every field of the bundled sample cases is extracted exactly."""
    report = evaluate_dataset(processor, FIXTURES, fuzzy=False)
    assert report.total.f1 == 1.0, report.errors


@pytest.mark.parametrize(
    ("name", "expected"),
    [("odwolanie.pdf", "odwolanie"), ("pelnomocnictwo.pdf", "pelnomocnictwo"), ("potwierdzenie_przelewu.pdf", "przelew")],
)
def test_classification_ignores_filename(processor, name, expected, tmp_path):
    """Documents are classified by content even when the file name says nothing."""
    target = tmp_path / "plik.pdf"
    target.write_bytes((FIXTURES / "przyklad_07" / name).read_bytes())
    assert processor.process_pdf(target).doc_type == expected


def test_unknown_text_is_not_classified():
    """Unrelated text stays unclassified so no JSON is written for it."""
    assert classify(load_settings(), "Lista zakupów: mleko, chleb, masło.", "notatka.pdf").doc_type is None


def test_run_writes_mirrored_tree(processor, tmp_path):
    """Batch mode mirrors the input tree and names JSON files after the PDFs."""
    source = tmp_path / "input" / "case1"
    source.mkdir(parents=True)
    for pdf in (FIXTURES / "przyklad_41").glob("*.pdf"):
        (source / pdf.name).write_bytes(pdf.read_bytes())
    processor.process_tree(tmp_path / "input", tmp_path / "output")
    written = sorted(p.name for p in (tmp_path / "output" / "case1").glob("*.json"))
    assert written == ["odwolanie.json", "pelnomocnictwo.json", "potwierdzenie_przelewu.json"]
    data = json.loads((tmp_path / "output" / "case1" / "potwierdzenie_przelewu.json").read_text(encoding="utf-8"))
    assert set(data["przelew_bankowy"]) == {"data_operacji", "kwota", "na_rachunek", "numer_transakcji", "tytul", "z_rachunku"}


@pytest.mark.parametrize(
    ("raw", "iso"),
    [("3 września 2026 roku", "2026-09-03"), ("01-01-2026", "2026-01-01"), ("2026-03-21", "2026-03-21"), ("17.02.2026", "2026-02-17")],
)
def test_date_normalizer(raw, iso):
    """Polish date notations become ISO dates."""
    assert normalizers.date_iso(raw) == iso


@pytest.mark.parametrize(("raw", "value"), [("20 000,00 zł", 20000.0), ("PLN 34.00", 34.0), ("1.234,50", 1234.5), ("200", 200.0)])
def test_amount_normalizer(raw, value):
    """Amounts with Polish and English separators are parsed."""
    assert normalizers.amount(raw) == value


def test_identifier_normalizers():
    """TED, BZP and account numbers are brought to the reference format."""
    assert normalizers.ted("2026/S 142-999327") == "999327-2026"
    assert normalizers.bzp("2026/BZP 00999827") == "2026/BZP00999827"
    assert normalizers.account("PL07 1044 6255 1544 8206 2521 6547") == "PL07104462551544820625216547"
    assert normalizers.account("07 1044 6255 1544 8206 2521 6547") == "07104462551544820625216547"


def test_fuzzy_regex_returns_original_text():
    """Diacritic-insensitive matching keeps the original spelling of the value."""
    match = fuzzy_re.search(r"Odwołujący:\s*(\S+)", "Odwolujacy: Żółć")
    assert match is not None and match.group(1) == "Żółć"

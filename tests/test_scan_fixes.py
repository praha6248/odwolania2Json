"""Fixes for errors found on the real scans published by UZP (dane/skany)."""

from odwolania2json.extractors import signature_names, similar_name
from odwolania2json.normalizers import date_iso
from odwolania2json.ocr import fix_ocr_text


def test_ocr_text_fixes():
    """Common OCR confusions in scans are repaired without touching normal text."""
    assert fix_ocr_text("infrastrukturq towarzyszącq") == "infrastrukturą towarzyszącą"
    assert fix_ocr_text("Iraq FAQ") == "Iraq FAQ"
    assert fix_ocr_text("od peinomocnictwa") == "od pełnomocnictwa"
    assert fix_ocr_text("w dniu o2.o6.2026 r.") == "w dniu 02.06.2026 r."
    assert fix_ocr_text("r.malinowski@.kancelaria.example") == "r.malinowski@kancelaria.example"
    assert fix_ocr_text("reprezentowany przez.pełnomocnika") == "reprezentowany przez pełnomocnika"
    assert fix_ocr_text("opublikowanej przez. Zamawiającego") == "opublikowanej przez Zamawiającego"


def test_month_names_misread_by_ocr():
    """A month name with one wrong letter still gives the date; unrelated words do not."""
    assert date_iso("2 ezerwca 2026") == "2026-06-02"
    assert date_iso("5 marea 2026") == "2026-03-05"
    assert date_iso("5 kotka 2026") is None


def test_signers_in_one_line_and_similar_names():
    """Two signatories in one line are both found, and OCR variants of a name count as the same person."""
    assert signature_names("Dorota Topolska - Członek Zarządu Halina Baran - Prezes Zarządu") == ["Dorota Topolska", "Halina Baran"]
    assert similar_name("Szymon Jabłoń", ["Szymon Jabbon"])
    assert not similar_name("Dorota Szulc", ["Monika Kaczmarek"])


def test_missing_opening_quote_is_restored():
    """PP-OCRv6 drops the low opening quote; it is put back where a title or a defined term ends with a quote."""
    assert fix_ocr_text('pn. Odbiór i\nzagospodarowanie odpadów", nr') == 'pn. „Odbiór i\nzagospodarowanie odpadów", nr'
    assert fix_ocr_text('(dalej:\nMocodawca"), niniejszym') == '(dalej:\n„Mocodawca"), niniejszym'
    assert fix_ocr_text("pn. „Dostawa sprzętu”, nr") == "pn. „Dostawa sprzętu”, nr"


def test_text_quality_separates_clean_and_garbled_ocr():
    """Readable Polish scores high and garbled OCR output scores below the re-read threshold."""
    from odwolania2json.ocr import AUTO_THRESHOLD, text_quality

    assert text_quality("Potwierdzenie realizacji polecenia przelewu, data operacji, rachunek odbiorcy") > AUTO_THRESHOLD
    assert text_quality("Rachamesk slesenisdavty Dotae siputrerj Naner sefenncyuy Plaosikc Zaneedel") < AUTO_THRESHOLD

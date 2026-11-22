"""Redaction of personal data in PDFs."""

import io
from pathlib import Path

import pypdfium2 as pdfium
from fastapi.testclient import TestClient

from odwolania2json.anonymize import terms, valid_pesel
from odwolania2json.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def test_terms_cover_names_and_patterns():
    """Names from person fields become stems; PESEL needs a valid checksum; e-mails and phones come from the text."""
    fields = [{"field": "pelnomocnicy", "value": [{"imie_nazwisko": "Cezary Walczak", "pesel": None}]}, {"field": "nazwa", "value": "Firma sp. z o.o."}]
    found = terms(fields, "PESEL 44051401359, tel. 600 100 200, a@b.pl, PESEL 12345678901")
    assert ("osoba", "Cezar") in found and ("osoba", "Walcza") in found
    assert ("pesel", "44051401359") in found and ("pesel", "12345678901") not in found
    assert ("telefon", "600 100 200") in found and ("email", "a@b.pl") in found
    assert not any("Firma" in t for _, t in found)
    assert valid_pesel("44051401359")


def test_anonymized_pdf_has_no_text_and_hides_names(monkeypatch):
    """The redacted PDF is an image-only copy and names from the whole case are counted as covered."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    ids = {}
    for pdf in sorted((FIXTURES / "przyklad_07").glob("*.pdf")):
        doc = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))]).json()[0]
        ids[doc["doc_type"]] = doc["id"]
    response = client.get(f"/api/documents/{ids['przelew']}/anonymized.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert '"osoba": 2' in response.headers["x-redacted"]
    pdf = pdfium.PdfDocument(io.BytesIO(response.content))
    assert pdf[0].get_textpage().get_text_range().strip() == ""


def test_landline_numbers_are_personal_data():
    """Landline numbers (2-3-2-2 digits) are covered; NIP numbers written in the same groups are not."""
    found = terms([], "tel. +48 73 302 93 65, tel. (22) 458 77 77, NIP 999-649-46-61, NIP 999 239 80 73")
    phones = {t for kind, t in found if kind.startswith("telefon")}
    assert phones == {"+48 73 302 93 65", "(22) 458 77 77"}


def test_find_in_lines_ignores_case_diacritics_and_punctuation():
    """A term is found inside an OCR line regardless of case, Polish letters and punctuation, with a partial box."""
    from odwolania2json.ocr import find_in_lines

    lines = [((0.1, 0.2, 0.5, 0.22), "Wroclaw, 13.02.2026 r."), ((0.1, 0.3, 0.9, 0.32), "radca prawny Krzysztof Jodtowski")]
    (score, box), = find_in_lines(lines, "Wrocław")
    assert score == 1.0 and box[0] == 0.1 and box[2] < 0.5 and box[1] == 0.2
    assert find_in_lines(lines, "13.02.2026")[0][1][0] > 0.2
    fuzzy = find_in_lines(lines, "Krzysztof Jodłowski")
    assert fuzzy and 0.8 <= fuzzy[0][0] < 1.0
    assert find_in_lines(lines, "Krzysztof Jodłowski", min_score=1.0) == [] or find_in_lines(lines, "Krzysztof Jodłowski")[0][0] < 1.0
    assert find_in_lines(lines, "Zamawiający") == []


def _scan_of(pdf: Path, out: Path) -> Path:
    """Write an image-only copy of a PDF's first page, as a scanner would produce it."""
    document = pdfium.PdfDocument(str(pdf))
    document[0].render(scale=2).to_pil().convert("RGB").save(out, format="PDF", resolution=144)
    document.close()
    return out


def test_scan_sources_are_located_and_redacted(tmp_path, monkeypatch):
    """On a scan without a text layer, fields are highlighted from OCR lines and personal data is blacked out."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("O2J_CACHE_DIR", str(tmp_path / "cache"))
    scan = _scan_of(FIXTURES / "przyklad_41" / "odwolanie.pdf", tmp_path / "skan.pdf")
    client = TestClient(create_app())
    doc = client.post("/api/documents", files=[("files", ("skan.pdf", scan.read_bytes(), "application/pdf"))]).json()[0]
    assert doc["ocr"], "the copy has no text layer, so it must be read with OCR"
    boxes = client.get(f"/api/documents/{doc['id']}/locate/numer_postepowania").json()["boxes"]
    assert boxes and boxes[0]["page"] == 1 and all(0 <= v <= 1 for r in boxes[0]["rects"] for v in r)
    response = client.get(f"/api/documents/{doc['id']}/anonymized.pdf")
    assert response.status_code == 200
    assert sum(__import__("json").loads(response.headers["X-Redacted"]).values()) > 0

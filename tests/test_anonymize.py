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

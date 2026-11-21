"""Excel and CSV export and the model-free search."""

import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from odwolania2json.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def client_with_case(monkeypatch) -> TestClient:
    """A client with the three documents of one fixture case uploaded."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    for pdf in sorted((FIXTURES / "przyklad_07").glob("*.pdf")):
        client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))])
    return client


def test_excel_has_summary_type_sheets_and_formal_checks(monkeypatch):
    """The workbook lists every document, flattens each type into columns and includes the formal checks."""
    response = client_with_case(monkeypatch).get("/api/export.xlsx")
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Dokumenty", "Odwołanie do KIO", "Pełnomocnictwo", "Potwierdzenie przelewu", "Kontrola formalna"]
    assert book["Dokumenty"].max_row == 4
    header = [c.value for c in book["Odwołanie do KIO"][1]]
    assert "Odwolujacy[1].nazwa" in header
    row = [c.value for c in book["Odwołanie do KIO"][2]]
    assert row[header.index("ZamowieniePubliczne.numer_postepowania")] == "ZP.388.2026"
    assert {r[0].value for r in book["Kontrola formalna"].iter_rows(min_row=2)} == {"ZP.388.2026"}


def test_csv_is_excel_friendly(monkeypatch):
    """The CSV starts with a BOM, uses semicolons and has one row per document."""
    content = client_with_case(monkeypatch).get("/api/export.csv").content.decode("utf-8")
    assert content.startswith("﻿plik;typ;postepowanie")
    assert len(content.strip().splitlines()) == 4


def test_search_works_without_llm(monkeypatch):
    """Search returns fragments from the documents with the query words, without a model."""
    hits = client_with_case(monkeypatch).post("/api/search", json={"question": "numer referencyjny przelewu"}).json()["hits"]
    assert hits and hits[0]["filename"] == "potwierdzenie_przelewu.pdf"
    assert "referencyjny" in hits[0]["snippet"].lower()

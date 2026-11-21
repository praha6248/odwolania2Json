"""Document type wizard: rule suggestions, preview and saving a new type."""

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from odwolania2json.config import DEFAULT_CONFIG_DIR, load_settings
from odwolania2json.web.app import create_app
from odwolania2json.wizard import preview, suggest_field, suggest_keywords

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = """Sygn. akt: KIO 1234/26
WYROK
z dnia 3 marca 2026 r.
Krajowa Izba Odwoławcza
Przewodniczący:

Anna Nowak
Kwota wpisu: 15 000,00 zł
Rachunek: PL61 1090 1014 0000 0712 1981 2874
"""


def field_for(text: str, value: str) -> dict:
    """Suggest a field for the first occurrence of a value."""
    start = text.index(value)
    return suggest_field(text, start, start + len(value))


def test_suggestions_follow_the_value_shape_and_label():
    """Dates, amounts, accounts and names get matching normalizers and labels become field names."""
    assert field_for(SAMPLE, "KIO 1234/26")["name"] == "sygn_akt"
    date = field_for(SAMPLE, "3 marca 2026 r.")
    assert date["field"]["normalize"] == ["date_iso"] and date["name"] == "z_dnia"
    assert field_for(SAMPLE, "15 000,00 zł")["field"]["normalize"] == ["amount"]
    assert field_for(SAMPLE, "PL61 1090 1014 0000 0712 1981 2874")["field"]["normalize"] == ["account"]
    person = field_for(SAMPLE, "Anna Nowak")
    assert person["name"] == "przewodniczacy" and person["field"]["normalize"] == ["person_name"]
    assert suggest_keywords(SAMPLE)["head_keywords"].get("wyrok") == 5


def test_draft_extracts_values_and_generalizes():
    """A draft built from one sample extracts normalized values from another document of the same kind."""
    fields = {s["name"]: s["field"] for s in (field_for(SAMPLE, v) for v in ["KIO 1234/26", "3 marca 2026 r.", "Anna Nowak", "15 000,00 zł"])}
    draft = {"label": "Wyrok KIO", "classify": suggest_keywords(SAMPLE), "fields": fields}
    other = SAMPLE.replace("1234/26", "77/26").replace("3 marca", "12 maja").replace("Anna Nowak", "Jan Kowalski").replace("15 000,00", "7 500,00")
    result = preview(draft, other, threshold=5)
    assert result["recognized"]
    assert result["data"] == {"sygn_akt": "KIO 77/26", "z_dnia": "2026-05-12", "przewodniczacy": "Jan Kowalski", "kwota_wpisu": 7500.0}
    assert "name: wyrok_kio" in result["yaml"]


def test_wizard_api_saves_a_type_that_classifies_documents(tmp_path, monkeypatch):
    """The API suggests fields on an uploaded sample, saves the type as YAML and uses it after reload."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    client = TestClient(create_app(config))
    pdf = FIXTURES / "przyklad_07" / "potwierdzenie_przelewu.pdf"
    doc = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))]).json()[0]
    text = client.get(f"/api/documents/{doc['id']}").json()["text"]
    start = text.index("Numer referencyjny") + len("Numer referencyjny ")
    suggestion = client.post("/api/wizard/suggest", json={"doc_id": doc["id"], "start": start, "end": start + 16}).json()
    assert suggestion["name"] == "numer_referencyjny"
    draft = {"label": "Potwierdzenie z banku", "classify": {"head_keywords": {"potwierdzenie realizacji polecenia przelewu": 5}}, "fields": {suggestion["name"]: suggestion["field"]}}
    shown = client.post("/api/wizard/preview", json={"doc_id": doc["id"], "draft": draft}).json()
    assert shown["recognized"] and shown["data"] == {"numer_referencyjny": "CEN2607152350299"}
    saved = client.post("/api/types", json={"draft": draft}).json()
    assert (config / "document_types" / "potwierdzenie_z_banku.yaml").exists()
    assert "potwierdzenie_z_banku" in {t["name"] for t in saved["types"]}
    assert client.post("/api/types", json={"draft": draft}).status_code == 409
    assert load_settings(config).get_type("potwierdzenie_z_banku").fields["numer_referencyjny"]["normalize"] == ["strip"]

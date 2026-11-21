"""Tests of the web API."""

from pathlib import Path

from fastapi.testclient import TestClient

from odwolania2json.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def test_upload_and_download(monkeypatch):
    """A PDF can be uploaded, inspected, previewed and downloaded as JSON."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    pdf = FIXTURES / "przyklad_07" / "potwierdzenie_przelewu.pdf"
    response = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))])
    assert response.status_code == 200
    doc = response.json()[0]
    assert doc["doc_type"] == "przelew"
    assert all("field" in f for f in doc["fields"])
    assert client.get(f"/api/documents/{doc['id']}/pdf").headers["content-type"] == "application/pdf"
    download = client.get(f"/api/documents/{doc['id']}/json")
    assert download.json() == doc["data"]
    assert 'filename="potwierdzenie_przelewu.json"' in download.headers["content-disposition"]
    assert client.get("/api/update").json()["available"] is False


def test_llm_settings_are_optional_and_hide_the_key(monkeypatch):
    """LLM is off by default, can be toggled at runtime, and the API key is never returned."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    monkeypatch.delenv("O2J_LLM_ENABLED", raising=False)
    client = TestClient(create_app())
    view = client.put("/api/llm", json={"enabled": True, "base_url": "http://127.0.0.1:9/v1", "model": "m", "api_key": "secret"}).json()
    assert view == {"enabled": True, "base_url": "http://127.0.0.1:9/v1", "model": "m", "has_key": True}
    assert "secret" not in client.get("/api/llm").text
    assert client.post("/api/llm/check").json()["ok"] is False
    assert client.put("/api/llm", json={"enabled": False}).json()["enabled"] is False

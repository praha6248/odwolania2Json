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
    assert view == {"enabled": True, "mode": "fast", "base_url": "http://127.0.0.1:9/v1", "model": "m", "has_key": True}
    assert "secret" not in client.get("/api/llm").text
    assert client.post("/api/llm/check").json()["ok"] is False
    assert client.put("/api/llm", json={"enabled": False}).json()["enabled"] is False


def test_cases_manual_edit_and_assistant(monkeypatch):
    """Documents group into a case, a manual correction re-renders JSON, and the assistant cites retrieved fragments."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    ids = {}
    for pdf in sorted((FIXTURES / "przyklad_07").glob("*.pdf")):
        doc = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))]).json()[0]
        ids[doc["doc_type"]] = doc["id"]
    cases = client.get("/api/cases").json()
    assert len(cases) == 1 and cases[0]["reference"] == "ZP.388.2026" and cases[0]["consistent"] and not cases[0]["missing_types"]
    assert {c["id"]: c["status"] for c in cases[0]["checks"]}["pelnomocnik"] == "ok"

    located = client.get(f"/api/documents/{ids['odwolanie']}/locate/numer_postepowania").json()["boxes"]
    assert located and located[0]["page"] == 1
    assert all(0 <= v <= 1 for rect in located[0]["rects"] for v in rect)
    assert client.get(f"/api/documents/{ids['odwolanie']}/locate/nie_ma_takiego").status_code == 404

    edited = client.put(f"/api/documents/{ids['odwolanie']}/fields/czynnosc_powod_id", json={"value": "9"}).json()
    assert edited["data"]["OdwolanieKIO"]["czynnosc_powod_id"] == 9
    assert edited["data"]["OdwolanieKIO"]["czynnosc_opis"] == "Decyzja o unieważnieniu postępowania"
    assert next(f for f in edited["fields"] if f["field"] == "czynnosc_powod_id")["source"] == "manual"

    from odwolania2json import llm

    monkeypatch.setattr(llm.LLMClient, "chat", lambda self, system, user: '{"answer": "Kancelaria Adwokacka [1]", "cited": [1]}')
    client.put("/api/llm", json={"enabled": False, "base_url": "http://127.0.0.1:9/v1", "model": "m"})
    answer = client.post("/api/ask", json={"question": "Kto reprezentuje odwołującego?"}).json()
    assert answer["answer"].startswith("Kancelaria") and answer["sources"][0]["filename"].endswith(".pdf")


def test_page_previews_are_rendered(monkeypatch):
    """PDF pages are served as PNG images for the preview."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    pdf = FIXTURES / "przyklad_07" / "potwierdzenie_przelewu.pdf"
    doc = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))]).json()[0]
    assert client.get(f"/api/documents/{doc['id']}/pages").json()["pages"] >= 1
    image = client.get(f"/api/documents/{doc['id']}/pages/1.png")
    assert image.headers["content-type"] == "image/png" and image.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{doc['id']}/pages/99.png").status_code == 404


def test_parallel_page_rendering_is_safe(monkeypatch):
    """Concurrent preview requests must not crash the PDF renderer (pdfium is not thread-safe)."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    pdf = FIXTURES / "przyklad_41" / "odwolanie.pdf"
    doc = client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))]).json()[0]
    pages = client.get(f"/api/documents/{doc['id']}/pages").json()["pages"]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda n: client.get(f"/api/documents/{doc['id']}/pages/{n}.png").status_code, range(1, pages + 1)))
    assert codes == [200] * pages


def test_windowed_process_gets_streams_for_logging(tmp_path, monkeypatch):
    """Without a console (sys.stdout is None) the launcher redirects output to a log file, so uvicorn can configure logging."""
    import sys

    import uvicorn

    from odwolania2json.desktop import ensure_streams

    monkeypatch.setenv("O2J_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = ensure_streams()
    assert log == tmp_path / "odwolania2json.log" and sys.stdout is not None and sys.stderr is not None
    uvicorn.Config(lambda scope: None, log_level="warning").configure_logging()
    print("ok")
    assert "ok" in log.read_text(encoding="utf-8")

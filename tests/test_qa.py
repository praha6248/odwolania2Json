"""Answers to typical questions without a language model (config/assistant.yaml)."""

from pathlib import Path

from fastapi.testclient import TestClient

from odwolania2json.config import DEFAULT_CONFIG_DIR
from odwolania2json.qa import answer, fill, load_intents, pick_intent
from odwolania2json.web.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"
INTENTS = load_intents(DEFAULT_CONFIG_DIR)


def intent_of(question: str) -> str | None:
    """Id of the intent chosen for a question."""
    chosen = pick_intent(question, INTENTS)
    return chosen["id"] if chosen else None


def test_typical_questions_find_their_intent():
    """Common phrasings map to the right answer and unrelated questions to none."""
    assert intent_of("Kto reprezentuje odwołującego?") == "pelnomocnik"
    assert intent_of("Jaką kwotę i kiedy przelano?") == "przelew"
    assert intent_of("Czego dotyczy odwołanie?") == "czynnosc"
    assert intent_of("Kto jest zamawiającym?") == "zamawiajacy"
    assert intent_of("Jaki jest numer postępowania?") == "postepowanie"
    assert intent_of("Kto podpisał pełnomocnictwo?") == "mocodawca"
    assert intent_of("Jaka jest pogoda?") is None
    assert intent_of("zarzuty wobec zamawiającego art. 255") is None
    assert intent_of("Czego żąda odwołujący?") is None


def test_templates_format_amounts_dates_and_missing_values():
    """Amounts and dates are written the Polish way, lists are joined and empty values show a dash."""
    data = {"przelew_bankowy": {"kwota": 7500.0, "data_operacji": "2026-03-17", "tytul": None}, "x": [{"n": "A"}, {"n": "B"}]}
    text, found = fill("{przelew_bankowy.kwota|zl}, {przelew_bankowy.data_operacji|data}, {przelew_bankowy.tytul}, {x[].n}", data)
    assert found and text == "7 500,00 zł, 17.03.2026, —, A, B"
    assert fill("{brak.pola}", data) == ("—", False)


def test_answer_api_uses_the_extracted_json_and_cites_sources(monkeypatch):
    """The answer endpoint reads the same values as the output JSON, filters by a case number and lists sources."""
    monkeypatch.setenv("O2J_NO_UPDATE_CHECK", "1")
    client = TestClient(create_app())
    for case in ("przyklad_07", "przyklad_41"):
        for pdf in sorted((FIXTURES / case).glob("*.pdf")):
            client.post("/api/documents", files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))])
    result = client.post("/api/answer", json={"question": "Kto reprezentuje odwołującego w ZP.388.2026?"}).json()
    assert result["intent"] == "pelnomocnik"
    assert "Cezary Walczak" in result["answer"] and "Piotr Zalewski" not in result["answer"]
    assert result["sources"] and result["sources"][0]["filename"] == "odwolanie.pdf"
    assert result["hits"]
    other = client.post("/api/answer", json={"question": "Jaka jest pogoda?"}).json()
    assert other["answer"] is None and other["sources"] == []


def test_answers_cover_every_document_of_the_type():
    """Without a case number every matching document gets its own line."""
    documents = [
        {"id": "a", "filename": "przelew1.pdf", "doc_type": "przelew", "case_values": {"reference": "ZP.1"}, "fields": [], "data": {"przelew_bankowy": {"kwota": 17.0, "data_operacji": "2026-01-02", "z_rachunku": "1", "na_rachunek": "2", "tytul": "opłata"}}},
        {"id": "b", "filename": "przelew2.pdf", "doc_type": "przelew", "case_values": {"reference": "ZP.2"}, "fields": [], "data": {"przelew_bankowy": {"kwota": 34.0, "data_operacji": "2026-01-03", "z_rachunku": "3", "na_rachunek": "4", "tytul": "opłata"}}},
    ]
    result = answer("Ile wynosiła opłata?", documents, INTENTS)
    assert result["answer"].count("\n") == 1 and "17,00 zł" in result["answer"] and "34,00 zł" in result["answer"]

"""LLM refinement fills only empty fields and recomputes derived ones."""

import json

from odwolania2json.config import load_settings
from odwolania2json.engine import extract
from odwolania2json.llm import LLMClient


def test_llm_fills_empty_fields_and_derived_values(monkeypatch):
    """Empty reason id comes from the model; its canonical description is derived from the YAML map."""
    settings = load_settings()
    doc_type = settings.get_type("odwolanie")
    data, ctx = extract("Odwołujący:\nAlfa sp. z o.o.\nZarzut nr 1 czegoś innego.", doc_type)
    assert data["OdwolanieKIO"]["czynnosc_powod_id"] is None
    client = LLMClient({"base_url": "http://invalid"})
    monkeypatch.setattr(client, "chat", lambda system, user: json.dumps({"czynnosc_powod_id": "9", "tytul": "Budowa drogi"}))
    refined = client.refine(doc_type, ctx.text, data, ctx)
    assert refined["OdwolanieKIO"]["czynnosc_powod_id"] == 9
    assert refined["OdwolanieKIO"]["czynnosc_opis"] == "Decyzja o unieważnieniu postępowania"
    assert refined["ZamowieniePubliczne"]["tytul"] == "Budowa drogi"
    assert ctx.results["tytul"].source == "llm"

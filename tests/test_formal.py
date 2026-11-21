"""Formal checks of a case across its documents."""

import datetime as dt
import json
from pathlib import Path

from odwolania2json.config import load_settings
from odwolania2json.formal import holidays, run_checks, summary, working_day

FIXTURES = Path(__file__).parent / "fixtures"
TYPES = {"odwolanie.json": "odwolanie", "pelnomocnictwo.json": "pelnomocnictwo", "przelew.json": "przelew"}


def case(name: str) -> list[dict]:
    """Load the gold JSON of a fixture case as documents."""
    return [{"doc_type": t, "data": json.loads((FIXTURES / name / f).read_text(encoding="utf-8"))} for f, t in TYPES.items()]


def by_id(results: list[dict]) -> dict[str, dict]:
    """Index check results by id."""
    return {r["id"]: r for r in results}


def test_holidays_and_working_days():
    """Easter-based holidays are computed and deadlines move past weekends and holidays."""
    days = holidays(2026)
    assert dt.date(2026, 4, 6) in days and dt.date(2026, 6, 4) in days and dt.date(2026, 12, 24) in days
    assert working_day(dt.date(2026, 4, 4)) == dt.date(2026, 4, 7)
    assert working_day(dt.date(2026, 7, 8)) == dt.date(2026, 7, 8)


def test_consistent_case_passes_party_checks():
    """A gold case passes the party, attorney, title, payment order and fee checks."""
    results = by_id(run_checks(load_settings().formal_checks, case("przyklad_07")))
    for check_id in ("strony", "pelnomocnik", "tytul_przelewu", "oplata_przed_odwolaniem", "oplata_skarbowa"):
        assert results[check_id]["status"] == "ok", results[check_id]
    assert results["termin"]["status"] == "warn"


def test_mismatches_are_reported():
    """A different principal, an unknown attorney, a late payment and a low fee are flagged."""
    docs = case("przyklad_07")
    docs[1]["data"]["mocodawca"][0]["data"]["nazwa"] = "Inna Firma sp. z o.o."
    docs[1]["data"]["pelnomocnicy"] = [{"imie_nazwisko": "Jan Kowalski"}, {"imie_nazwisko": "Anna Nowak"}]
    docs[2]["data"]["przelew_bankowy"].update({"data_operacji": "2026-07-20", "kwota": 17.0})
    results = by_id(run_checks(load_settings().formal_checks, docs))
    assert results["strony"]["status"] == "error"
    assert results["pelnomocnik"]["status"] == "error"
    assert results["oplata_przed_odwolaniem"]["status"] == "error"
    assert results["oplata_skarbowa"]["status"] == "warn"
    assert summary(list(results.values())) == "error"


def test_missing_document_is_skipped():
    """Checks that need an absent document are skipped instead of failing."""
    results = by_id(run_checks(load_settings().formal_checks, case("przyklad_07")[:1]))
    assert results["strony"]["status"] == "skip"
    assert "pelnomocnictwo" in results["strony"]["detail"]


def test_deadline_above_eu_thresholds_uses_ten_days():
    """A TED number switches the appeal deadline from 5 to 10 days."""
    docs = case("przyklad_07")
    docs[0]["data"]["OdwolanieKIO"].update({"czynnosc_dzien": "2026-07-03", "data": "2026-07-13"})
    assert by_id(run_checks(load_settings().formal_checks, docs))["termin"]["status"] == "warn"
    docs[0]["data"]["ZamowieniePubliczne"]["numer_ted"] = "2026/S 123-456789"
    assert by_id(run_checks(load_settings().formal_checks, docs))["termin"]["status"] == "ok"

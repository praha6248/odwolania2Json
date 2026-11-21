"""Comparable case details for the workspace, independent of the exported schema."""

import re


def case_values(kind, data, text):
    data = data or {}
    names = []
    reference = None
    if kind == "odwolanie":
        names = [party.get("nazwa") for party in data.get("Odwolujacy") or []]
        reference = (data.get("ZamowieniePubliczne") or {}).get("numer_postepowania")
    elif kind == "pelnomocnictwo":
        names = [(party.get("data") or {}).get("nazwa") for party in data.get("mocodawca") or []]
    elif kind == "przelew":
        sender = re.search(r"(?im)^[ \t]*(?:płatnik|nadawca|zleceniodawca|dane nadawcy)[ \t]*:?[ \t]*\n?[ \t]*([^\n]+)", text)
        if sender:
            names = [re.split(r",?\s+ul\.\s", sender[1], maxsplit=1)[0].strip()]
    if kind in ("pelnomocnictwo", "przelew"):
        source = text if kind == "pelnomocnictwo" else (data.get("przelew_bankowy") or {}).get("tytul") or ""
        match = re.search(r"(?:nr\s+referencyjny(?:\s+sprawy)?|znak\s+sprawy|(?:numer|nr)\s+postępowania|postępowani\w*\s+nr|w\s+przetargu)\s*:?\s*([\w./-]*\d[\w./-]*)", source, re.I)
        if match:
            reference = match[1].rstrip(".")
    return {"party": [name for name in names if name], "reference": reference}

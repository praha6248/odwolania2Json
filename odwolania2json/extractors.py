"""Domain specific extractors registered for use in document type configuration.

Each extractor receives the processing context and its YAML parameters, and
returns a value together with evidence. They are generic enough to be reused by
new document types by changing parameters only.
"""

from __future__ import annotations

import re
from typing import Any

from .engine import Context, Evidence, extractor, snippet
from .normalizers import DATE_PATTERN, date_iso, entity_name, person_name

UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
LOWER = "a-ząćęłńóśźż"
NAME_WORD = rf"[{UPPER}][{LOWER}]+(?:-[{UPPER}][{LOWER}]+)?"
PERSON = rf"{NAME_WORD}(?:[ \t]+{NAME_WORD}){{1,2}}"
TITLES = r"(?:adw\.|adwokat(?:a|em)?|r\.\s?pr\.|radc[aęy]\s+prawn(?:y|ego|ą|a)|radczyni\s+prawn[aą]|apl\.\s?(?:adw|radc)\.|aplikant\w*\s+\w+|mec\.)"
ID_PATTERNS = {
    "krs": r"KRS(?:\s*(?:nr|numer|pod numerem))?\s*[:]?\s*(\d[\d ]{8,12}\d)",
    "nip": r"NIP\s*[:]?\s*(\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}|\d{10})",
    "regon": r"REGON\s*[:]?\s*(\d{9}(?:\d{5})?)",
}
ADDRESS_STOP = (
    r"(?:\s*\((?:KRS|NIP|REGON|dalej)|\s+(?:udziela|ustanawia|upoważnia)|,\s*(?:ul\.|al\.|pl\.|os\.|ulica|aleja|z siedzibą|wpisan|KRS|NIP|REGON|adres)|\s*\(dalej|\s+z siedzibą|\s*\n\s*(?:ul\.|al\.|pl\.|os\.|KRS|NIP|REGON)"
    r"|,\s*\d{2}-\d{3}|\s+reprezentowan|\s*;)"
)
NOT_PERSON_WORDS = {
    "Prezes", "Zarządu", "Wiceprezes", "Członek", "Prokurent", "Wspólnik", "Dyrektor", "Pełnomocnik",
    "Mocodawca", "Pełnomocnictwo", "Komplementariusz", "Właściciel", "Kancelaria", "Partner",
    "Główny", "Księgowy", "Sp", "Spółka", "Zarząd", "Przyjmuję", "Odwołujący", "Zamawiający",
}


DEFAULT_LEADS = [
    r"do\s+reprezentacji\s+",
    r"Mocodawcą\s+jest\s+",
    r"Działając\s+w\s+imieniu\s+(?:wykonawcy\s+|spółki\s+|firmy\s+)?",
    r"^\s*Mocodawca\s*:?[ \t]*\n?",
    r"^\s*Wykonawca\s*:?[ \t]*\n?",
    r"(?:my|ja),?\s+niżej\s+podpisan\w*(?:\(a\))?,?\s+(?:w\s+imieniu\s+)?",
]
HEADER_LINE = re.compile(r"^\s*(?:P\s*E\s*Ł\s*N\s*O\s*M\s*O\s*C\s*N\s*I\s*C\s*T\s*W\s*O(?:\s+\w+)?|[^\n]*\d{4}(?:\s*r\.)?)\s*$", re.I)


def skip_header(head: str) -> int:
    """Return the offset of the first line that is neither a document title nor a place/date line."""
    offset = 0
    for line in head.split("\n"):
        if line.strip() and not HEADER_LINE.match(line):
            return offset
        offset += len(line) + 1
    return 0


def ids_in(text: str) -> dict[str, str | None]:
    """Return the first KRS, NIP and REGON numbers found in a text fragment."""
    out: dict[str, str | None] = {}
    for key, pattern in ID_PATTERNS.items():
        match = re.search(pattern, text, re.I)
        out[key] = re.sub(r"\D", "", match.group(1)) if match else None
    return out


def cut_name(text: str) -> str | None:
    """Return the organization name at the start of a fragment, ending before its address or identifiers."""
    text = text.strip().lstrip(":;,. ").strip()
    match = re.search(ADDRESS_STOP, text, re.I)
    name = text[: match.start()] if match else text.split("\n")[0]
    name = re.sub(r"\s*\n\s*", " ", name)
    return entity_name(name)


def is_person_line(line: str) -> bool:
    """Tell whether a line looks like a bare person name (signature line)."""
    line = re.sub(rf"^{TITLES}\s*", "", line.strip(), flags=re.I)
    if not re.fullmatch(PERSON, line):
        return False
    return not any(word in NOT_PERSON_WORDS for word in line.split())


def signature_names(block: str) -> list[str]:
    """Return person names written under signature lines within a block."""
    names: list[str] = []
    for line in block.split("\n"):
        line = line.strip()
        if is_person_line(line):
            name = person_name(line)
            if name and name not in names:
                names.append(name)
    return names


@extractor("principals")
def extract_principals(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Extract the principals (mocodawcy) of a power of attorney with their signatories."""
    text = ctx.text
    head_end = len(text)
    grant_verbs = list(re.finditer(r"\b(?:udziela\w*|ustanawia\w*|upoważnia\w*)\b", text, re.I))
    if grant_verbs:
        head_end = grant_verbs[0].start()
        if head_end < 80 and len(grant_verbs) > 1:
            head_end = grant_verbs[1].start()
    head = text[:head_end]
    principals: list[dict[str, Any]] = []

    natural = re.search(
        rf"(?:niżej podpisan\w+|Ja,)\s+(?:{TITLES}\s+)?({PERSON}),?\s+(?:prowadząc\w+|działając\w*)[^\n]*?(?:pod\s+(?:firmą|nazwą))\s+(.+?){ADDRESS_STOP}",
        head,
        re.I | re.S,
    )
    if natural:
        firm = entity_name(re.sub(r"\s*\n\s*", " ", natural.group(2)))
        data = {"imie_nazwisko": person_name(natural.group(1)), "krs": None, "nazwa": firm, **{k: v for k, v in ids_in(head).items() if k != "krs"}}
        data["krs"] = ids_in(head)["krs"]
        principals.append({"data": data, "start": natural.start()})
    else:
        items = list(re.finditer(r"(?:^|\s)(\d)\)\s+", head))
        chunks: list[tuple[int, str]] = []
        if len(items) >= 2:
            for index, item in enumerate(items):
                end = items[index + 1].start() if index + 1 < len(items) else len(head)
                chunks.append((item.end(), head[item.end():end]))
        else:
            start = 0
            for lead in spec.get("principal_leads", DEFAULT_LEADS):
                match = re.search(lead, head, re.I | re.M)
                if match:
                    start = match.end()
                    break
            else:
                start = skip_header(head)
            chunks.append((start, head[start:]))
        for start, chunk in chunks:
            name = cut_name(chunk)
            data = {"imie_nazwisko": None, "nazwa": name, **ids_in(chunk)}
            principals.append({"data": data, "start": start})

    for item in principals:
        data = item["data"]
        data["typ"] = "osoba_fizyczna" if data.get("imie_nazwisko") else "osoba_prawna"
        item["data"] = {k: data.get(k) for k in ("imie_nazwisko", "krs", "nazwa", "nip", "typ")}

    signatures = signers_by_principal(text, [p["data"]["nazwa"] or "" for p in principals])
    result = []
    for index, item in enumerate(principals):
        names = signatures[index] if index < len(signatures) else []
        result.append({"data": item["data"], "podpisujacy": [{"imie_nazwisko": n} for n in names]})
    if not result:
        return None, None
    start = principals[0]["start"]
    return result, Evidence("principals", snippet(text, start, start + 120), start, start + 120)


def signers_by_principal(text: str, names: list[str]) -> list[list[str]]:
    """Group signature names by principal using 'W imieniu X:' headers, else assign all to the first."""
    accept = re.search(r"Pełnomocnictwo\s+przyjmuj|Przyjmuję\s+pełnomocnictwo|Podpis(?:y)?\s+pełnomocnik|Pełnomocni(?:k|cy)\s*:\s*\n", text, re.I)
    tail_start = None
    for marker in (r"\n\s*Mocodawca\s*:?\s*\n", r"\n\s*W imieniu [^\n]*:\s*\n", r"\n\s*Za\s+Mocodawc\w+\s*:?\s*\n", r"\n\s*(?:Podpis(?:y)?|W imieniu Mocodawcy)[^\n]*\n", r"\n\.{5,}"):
        match = re.search(marker, text, re.I)
        if match and (accept is None or match.start() < accept.start()) and (tail_start is None or match.start() < tail_start):
            tail_start = match.start()
    if tail_start is None:
        return [[] for _ in names]
    block = text[tail_start: accept.start() if accept and accept.start() > tail_start else len(text)]
    groups = re.split(r"\n\s*W imieniu\s+([^\n]+?):?\s*\n", block)
    if len(groups) > 1 and len(names) > 1:
        out: list[list[str]] = [[] for _ in names]
        for label, body in zip(groups[1::2], groups[2::2]):
            target = best_match(label, names)
            out[target].extend(n for n in signature_names(body) if n not in out[target])
        return out
    out = [[] for _ in names] or [[]]
    out[0] = signature_names(block)
    return out


def best_match(label: str, names: list[str]) -> int:
    """Return the index of the name sharing the most words with a label."""
    words = set(re.findall(r"\w+", label.lower()))
    scores = [len(words & set(re.findall(r"\w+", n.lower()))) for n in names]
    return max(range(len(names)), key=lambda i: scores[i]) if names else 0


@extractor("attorneys")
def extract_attorneys(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Extract attorneys appointed in a power of attorney with optional PESEL numbers."""
    text = ctx.text
    accept = re.search(r"Pełnomocnictwo\s+przyjmuj\w*\s*:?|Przyjmuję\s+pełnomocnictwo\s*:?", text, re.I)
    segment = text[: accept.start()] if accept else text
    people: list[dict[str, Any]] = []
    for match in re.finditer(rf"{TITLES}\s*({NAME_WORD}(?:[ \t]+|[ \t]*\n[ \t]*){NAME_WORD})", segment):
        name = person_name(re.sub(r"\s+", " ", match.group(1)))
        if not name or any(w in NOT_PERSON_WORDS for w in name.split()):
            continue
        after = segment[match.end(): match.end() + 80]
        pesel = re.match(r"[^;\n]*?PESEL[:\s]*(\d{11})", after, re.I)
        if all(p["imie_nazwisko"] != name for p in people):
            people.append({"imie_nazwisko": name, "pesel": pesel.group(1) if pesel else None})
    if not people:
        if accept:
            for name in signature_names(text[accept.end():]):
                people.append({"imie_nazwisko": name, "pesel": None})
    if not people:
        return None, None
    return people, Evidence("attorneys", snippet(text, 0, min(len(text), 200)), 0, min(len(text), 200))


@extractor("dated_event")
def extract_dated_event(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Return the ISO date of the first sentence in scope that mentions a configured event verb."""
    text, offset = ctx.scope(spec.get("scope"))
    pattern = spec.get("pattern", rf"(?:w dniu|dnia)\s+({DATE_PATTERN})")
    for match in re.finditer(pattern, text, re.I):
        value = date_iso(match.group(1))
        if value:
            start, end = match.span(1)
            return value, Evidence("dated_event", snippet(text, start, end), offset + start, offset + end)
    return None, None

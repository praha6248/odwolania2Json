"""Domain specific extractors registered for use in document type configuration.

Each extractor receives the processing context and its YAML parameters, and
returns a value together with evidence. They are generic enough to be reused by
new document types by changing parameters only.
"""

from __future__ import annotations

import re
from typing import Any

from . import fuzzy_re as fx
from .engine import Context, Evidence, extractor, snippet
from .normalizers import DATE_PATTERN, OBLIQUE_TITLE, date_iso, entity_name, nominative, person_name

UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
LOWER = "a-ząćęłńóśźż"
NAME_WORD = rf"[{UPPER}][{LOWER}]+(?:-[{UPPER}][{LOWER}]+)?"
PERSON = rf"{NAME_WORD}(?:[ \t]+{NAME_WORD}){{1,2}}"
TITLES = r"(?:adw\.|adwokat(?:a|em|owi|ka|kę|ce)?|r\.\s?pr\.|radc[aęy]\s+prawn(?:y|ego|emu|ą|a)|radczyni[ęa]?\s+prawn(?:ą|a|ej)|apl\.\s?(?:adw|radc)\.|aplikant\w*\s+\w+|mec\.|mecenas(?:a|owi)?)"
ROLE = r"(?:(?:Wice)?prezes\s+Zarządu|Członek\s+Zarządu|Prokurent|Dyrektor(?:\s+\w+)?|Wspólnik|Właściciel|Komplementariusz)"
ID_PATTERNS = {
    "krs": r"KRS(?:\s*(?:nr|numer|pod numerem))?\s*[:]?\s*(\d[\d ]{8,12}\d)",
    "nip": r"NIP\s*[:]?\s*(\d{3}(?:[- ]\d{2,3}){3}|\d{10})",
    "regon": r"REGON\s*[;:]?\s*(\d{9}(?:\d{5})?)",
}
ADDRESS_STOP = (
    r"(?:\s*\((?:KRS|NIP|REGON|dalej)|\s+(?:ul|al|pl|os)\s?\.\s|\s+(?:udziela|ustanawia|upoważnia)|,\s*(?:ul\.?|al\.|pl\.|os\.|ulica|aleja|z siedzibą|wpisan|KRS|NIP|REGON|adres)|\s*\(dalej|\s+z siedzibą|\s*\n\s*(?:ul\.?|al\.|pl\.|os\.|KRS|NIP|REGON|PEŁNOMOCNI(?:K|CY)\b)"
    r"|,\s*\d{2}-\d{3}|\s*\n\s*\d{2}-\d{3}\b|\s+reprezentowan|\s*;)"
)
ORG_WORDS = {"kancelaria", "prawna", "prawny", "radca", "adwokacka", "spółka", "partnerzy", "legal", "biuro"}
NOT_PERSON_WORDS = {
    "Prezes", "Zarządu", "Wiceprezes", "Członek", "Prokurent", "Wspólnik", "Dyrektor", "Pełnomocnik",
    "Mocodawca", "Pełnomocnictwo", "Komplementariusz", "Właściciel", "Kancelaria", "Partner",
    "Główny", "Księgowy", "Sp", "Spółka", "Zarząd", "Przyjmuję", "Odwołujący", "Zamawiający",
}


DEFAULT_LEADS = [
    r"do\s+reprezentacji\s+",
    r"Mocodawcą\s+jest\s+",
    r"Działając\s+w\s+imieniu\s+(?:wykonawcy\s+|spółki\s+|firmy\s+)?",
    r"^\s*(?:[§S]\s*1\.?\s*)?Mocodawca\s*:?[ \t]*\n?",
    r"^\s*Wykonawca\s*:?[ \t]*\n?",
    r"(?:(?:my|ja),?\s*)?niżej\s+podpisan\w*(?:/a|\(a\))?,?\s+(?:w\s+imieniu\s+)?",
]
TITLE_LINE = r"^\s*P\s*E\s*Ł\s*N\s*O\s*M\s*O\s*C\s*N\s*I\s*C\s*T\s*W\s*O(?:\s+\w+)?\s*$"
HEADER_LINE = rf"^\s*(?:P\s*E\s*Ł\s*N\s*O\s*M\s*O\s*C\s*N\s*I\s*C\s*T\s*W\s*O(?:\s+\w+)?|[^\n]{{0,40}}{DATE_PATTERN}(?:\s*r(?:oku|\.)?)?)\s*$"


def skip_header(head: str) -> int:
    """Return the offset of the first line after the document title (and any letterhead or place/date line)."""
    title = fx.search(TITLE_LINE, head, re.I | re.M)
    offset = title.end() + 1 if title and title.end() < len(head) else 0
    for line in head[offset:].split("\n"):
        if line.strip() and not fx.match(HEADER_LINE, line, re.I):
            return offset
        offset += len(line) + 1
    return 0


def ids_in(text: str) -> dict[str, str | None]:
    """Return the first KRS, NIP and REGON numbers found in a text fragment."""
    out: dict[str, str | None] = {}
    for key, pattern in ID_PATTERNS.items():
        match = fx.search(pattern, text, re.I)
        out[key] = re.sub(r"\D", "", match.group(1)) if match else None
    return out


NAME_WINDOW = 250


def cut_name(text: str) -> str | None:
    """Return the organization name at the start of a fragment, ending before its address or identifiers."""
    text = text.strip().lstrip(":;,. ").strip()
    firm = fx.match(rf"{PERSON},?\s+(?:prowadząc\w*(?:/a|\(a\))?|działając\w*(?:/a|\(a\))?)[^\n]*?\bpod\s+(?:firmą|nazwą)\s+", text, re.I)
    if firm:
        text = text[firm.end():]
    match = fx.search(ADDRESS_STOP, text[:NAME_WINDOW], re.I)
    if match:
        name = text[: match.start()]
    else:
        lines = text.split("\n")
        name = lines[0]
        for line in lines[1:]:
            if not re.match(rf"[{LOWER}]", line.strip()):
                break
            name += " " + line
    name = re.sub(r"\s*\n\s*", " ", name)
    name = re.sub(r"\s*\((?:Lider|Partner|Członek|Pełnomocnik)\s+Konsorcjum\)\s*$", "", name, flags=re.I)
    return entity_name(name)


def is_person_line(line: str) -> bool:
    """Tell whether a line looks like a bare person name (signature line)."""
    line = re.sub(rf"^{TITLES}\s*", "", line.strip(), flags=re.I)
    if not fx.fullmatch(PERSON, line):
        return False
    return not any(word in NOT_PERSON_WORDS for word in line.split())


def signature_names(block: str) -> list[str]:
    """Return person names written under signature lines within a block."""
    names: list[str] = []
    for raw_line in block.split("\n"):
        line = re.sub(r"^\s*miejsce\s+na\s+pieczęć(?:\s+firmow\w+)?\s+", "", raw_line.strip(), flags=re.I)
        for match in fx.finditer(rf"({NAME_WORD}[ \t]+{NAME_WORD})\s*[-–—]\s*{ROLE}", line, re.I):
            name = person_name(match.group(1))
            if name and not any(w in NOT_PERSON_WORDS for w in name.split()) and name not in names:
                names.append(name)
        if is_person_line(line):
            name = person_name(line)
            if name and name not in names:
                names.append(name)
            continue
        pair = fx.fullmatch(rf"({NAME_WORD}[ \t]+{NAME_WORD})[ \t]+({NAME_WORD}[ \t]+{NAME_WORD})", line)
        if pair and not any(w in NOT_PERSON_WORDS for w in line.split()):
            for group in (1, 2):
                name = person_name(pair.group(group))
                if name and name not in names:
                    names.append(name)
    return names


@extractor("principals")
def extract_principals(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Extract the principals (mocodawcy) of a power of attorney with their signatories."""
    text = ctx.text
    head_end = len(text)
    grant_verbs = list(fx.finditer(r"\b(?:udziela\w*|ustanawia\w*|upoważnia\w*)\b", text, re.I))
    if grant_verbs:
        head_end = grant_verbs[0].start()
        if head_end < 80 and len(grant_verbs) > 1:
            head_end = grant_verbs[1].start()
    head = text[:head_end]
    principals: list[dict[str, Any]] = []

    natural = fx.search(
        rf"(?:(?:Ja,?\s*)?niżej\s+podpisan\w*(?:/a|\(a\))?|Ja),?\s+(?:{TITLES}\s+)?({PERSON}),?\s+(?:prowadząc\w*(?:/a|\(a\))?|działając\w*(?:/a|\(a\))?)[^\n]*?(?:pod\s+(?:firmą|nazwą))\s+(.+?){ADDRESS_STOP}",
        head,
        re.I | re.S,
    )
    if natural:
        firm = entity_name(re.sub(r"\s*\n\s*", " ", natural.group(2)))
        person = person_name(natural.group(1))
        data = {"imie_nazwisko": person, "krs": None, "nazwa": firm, **{k: v for k, v in ids_in(head).items() if k != "krs"}}
        data["krs"] = ids_in(head)["krs"]
        principals.append({"data": data, "start": natural.start(), "signers": [person] if person else []})
    else:
        items = list(fx.finditer(r"(?:^|\s)(\d)\)\s+", head))
        chunks: list[tuple[int, str]] = []
        if len(items) >= 2:
            for index, item in enumerate(items):
                end = items[index + 1].start() if index + 1 < len(items) else len(head)
                chunks.append((item.end(), head[item.end():end]))
        else:
            start = 0
            for lead in spec.get("principal_leads", DEFAULT_LEADS):
                match = fx.search(lead, head, re.I | re.M)
                if match:
                    start = match.end()
                    break
            else:
                start = skip_header(head)
            chunks.append((start, head[start:]))
        for start, chunk in chunks:
            name = cut_name(chunk)
            data = {"imie_nazwisko": None, "nazwa": name, **ids_in(chunk)}
            rep_match = fx.search(r"reprezentowan\w+\s+przez\s*:?\s*([^\n(]+(?:\n[^\n(]+)?)", chunk, re.I)
            inline = signature_names(re.sub(r"\s*\n\s*", " ", rep_match.group(1)).replace(",", "\n")) if rep_match else []
            principals.append({"data": data, "start": start, "signers": inline})

    for item in principals:
        data = item["data"]
        data["typ"] = "osoba_fizyczna" if data.get("imie_nazwisko") else "osoba_prawna"
        item["data"] = {k: data.get(k) for k in ("imie_nazwisko", "krs", "nazwa", "nip", "typ")}

    signatures = signers_by_principal(text, [p["data"]["nazwa"] or "" for p in principals])
    result = []
    for index, item in enumerate(principals):
        signed = signatures[index] if index < len(signatures) else []
        inline = list(item.get("signers") or [])
        elsewhere = {n for other in principals if other is not item for n in other.get("signers") or []}
        names = inline + [n for n in signed if not similar_name(n, inline) and not similar_name(n, list(elsewhere))] if inline else signed
        result.append({"data": item["data"], "podpisujacy": [{"imie_nazwisko": n} for n in names]})
    if not result:
        return None, None
    start = principals[0]["start"]
    return result, Evidence("principals", snippet(text, start, start + 120), start, start + 120)


def similar_name(name: str, others: list[str], cutoff: float = 0.8) -> bool:
    """Tell whether a person name matches one of the others, allowing OCR differences in a few letters."""
    import difflib

    key = fx.fold(name).lower()
    return any(difflib.SequenceMatcher(None, key, fx.fold(other).lower()).ratio() >= cutoff for other in others)


def signers_by_principal(text: str, names: list[str]) -> list[list[str]]:
    """Group signature names by principal using 'W imieniu X:' headers, else assign all to the first."""
    accept = fx.search(r"Pełnomocnictwo\s+przyjmuj|Przyjmuję\s+pełnomocnictwo|Podpis(?:y)?\s+pełnomocnik|Pełnomocni(?:k|cy)\s*:\s*\n", text, re.I)
    limit = accept.start() if accept else len(text)
    tail_start = None
    for marker in (r"\n\s*Mocodawca\s*:?\s*\n", r"\n\s*W imieniu [^\n]*:\s*\n", r"\n\s*Za\s+Mocodawc\w+\s*:?\s*\n", r"\n\s*Za\s+[A-ZĄĆĘŁŃÓŚŹŻ][^\n]+\n", r"\n\s*(?:Podpis(?:y)?|W imieniu Mocodawcy)[^\n]*\n", r"\n\.{5,}"):
        match = fx.search(marker, text, re.I)
        if match and match.start() < limit and (tail_start is None or match.start() < tail_start):
            tail_start = match.start()
    out = [[] for _ in names] or [[]]
    if tail_start is not None:
        block = text[tail_start: limit if limit > tail_start else len(text)]
        groups = fx.split(r"\n\s*W imieniu\s+([^\n]+?):?\s*\n", block)
        if len(groups) > 1 and len(names) > 1:
            for label, body in zip(groups[1::2], groups[2::2]):
                target = best_match(label, names)
                out[target].extend(n for n in signature_names(body) if n not in out[target])
            return out
        out[0] = signature_names(block)
        if out[0]:
            return out
    body_tail = text[len(text) // 3:limit]
    for match in fx.finditer(rf"(?:^\s*(?:miejsce\s+na\s+pieczęć(?:\s+firmow\w+)?\s+)?({NAME_WORD}[ \t]+{NAME_WORD})\s*\n\s*{ROLE}\b|Dokument\s+podpisany\s+przez\s+({NAME_WORD}[ \t]+{NAME_WORD}))", body_tail, re.I | re.M):
        name = person_name(match.group(1) or match.group(2))
        if name and not any(w in NOT_PERSON_WORDS for w in name.split()) and name not in out[0]:
            out[0].append(name)
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
    accept = fx.search(r"Pełnomocnictwo\s+przyjmuj\w*\s*:?|Przyjmuję\s+pełnomocnictwo\s*:?", text, re.I)
    footer = fx.search(r"\n\s*(?:Za\s+Mocodawc|Signature\s+Not\s+Verified|Dokument\s+podpisany)", text, re.I)
    end_pos = min(p.start() for p in (accept, footer) if p) if (accept or footer) else len(text)
    segment = text[:end_pos]
    people: list[dict[str, Any]] = []

    grant = fx.search(r"(?:udziela\w*|ustanawia\w*|upoważnia\w*)?[ \t]*pełnomocnictwa\s*:\s*\n(.+?)\n\s*do\s+(?:reprezentowania|działania|występowania|wniesienia|składania)\b", segment, re.I | re.S)
    if grant:
        block = grant.group(1)
        matches = list(fx.finditer(rf"(?:^\s*(?:\d+[.)]\s*)?|\b(?:oraz|i)\s+)(?:{TITLES}\s+)?({NAME_WORD}[ \t]+{NAME_WORD})", block, re.M))
        for idx, match in enumerate(matches):
            name = person_name(match.group(1))
            if not name or any(w in NOT_PERSON_WORDS for w in name.split()):
                continue
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
            after = block[match.end():next_start]
            pesel = fx.search(r"PESEL[:\s]*(\d{11})", after, re.I)
            if all(p["imie_nazwisko"] != name for p in people):
                people.append({"imie_nazwisko": name, "pesel": pesel.group(1) if pesel else None})

    if not people:
        for match in fx.finditer(rf"({TITLES})\s*({NAME_WORD}(?:[ \t]+|[ \t]*\n[ \t]*){NAME_WORD})", segment):
            name = person_name(re.sub(r"\s+", " ", match.group(2)))
            if not name or any(w in NOT_PERSON_WORDS for w in name.split()):
                continue
            after = segment[match.end(): match.end() + 80]
            pesel = fx.match(r"[^;()]{0,40}?PESEL[:\s]*(\d{11})", after, re.I)
            if all(p["imie_nazwisko"] != name for p in people):
                people.append({"imie_nazwisko": name, "pesel": pesel.group(1) if pesel else None})
    if not people and accept:
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
    for match in fx.finditer(pattern, text, re.I):
        value = date_iso(match.group(1))
        if value:
            start, end = match.span(1)
            return value, Evidence("dated_event", snippet(text, start, end), offset + start, offset + end)
    return None, None


EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
PARTY_STOP = (
    r"^\s*(?:[^\n]{0,60}?\(\s*(?:Odwołując|Zamawiając)\w*\s*\)\s*:|Wykonawca\s+wnosząc\w*|Odwołując\w*|Zamawiając\w*|dotyczy|Wykonawca\s+wybrany|Przystępując\w*|Uczestni\w*|"
    r"O\s*D\s*W\s*O\s*Ł\s*A\s*N\s*I\s*E|Prezes\s+Krajowej|Krajowa\s+Izba|Wartość\s+zamówienia|Wpis\s+od|Do\s*:)"
)


def party_block(text: str, label: str, stop: str) -> tuple[str, int] | None:
    """Return the text block that follows a party label line, up to the next party/section label."""
    match = fx.search(rf"^\s*{label}", text, re.I | re.M)
    if not match:
        return None
    end_match = fx.search(stop, text, re.I | re.M, match.end() + 1)
    end = end_match.start() if end_match else min(len(text), match.end() + 1500)
    return text[match.end():end], match.end()


EMPLOYEE = r"(?:pracownik\w*|osob\w+\s+upoważnion\w*)\s*(?:[–—-]\s*)?"


def governed_nominative(name: str) -> str:
    """Return the nominative of a name governed by 'przez' (accusative), when the inflection is unambiguous.

    'Roberta Kubiaka' and 'Annę Szymańską' are converted; 'Kamila Nowak' (a nominative female name that is also
    the genitive of 'Kamil') is kept, because the surname does not change.
    """
    converted = nominative(name)
    if not converted or converted == name:
        return name
    if converted.split()[-1] != name.split()[-1] or re.search(r"[ęą]\b", name):
        return converted
    return name


def parse_entity(block: str) -> dict[str, Any]:
    """Parse name, identifiers, representative, law firm and e-mail from a party block."""
    body = re.sub(r"^\s*(?:\([^)]*\)\s*)?[:']?", "", block, count=1)
    first = body.lstrip()
    if fx.match(r"(?:Konsorcjum|wykonawcy\s+wspólnie|Zamawiający\s+wspólnie)", first, re.I):
        first = first.split("\n", 1)[1] if "\n" in first else ""
    first = re.sub(r"^\s*\d[.)]\s*[^\n]*:\s*\n", "", first)
    first = re.sub(r"^\s*\d{1,2}[.)]\s+(?=\S)", "", first)
    name = cut_name(first)
    represented = fx.search(r"reprezentowan\w*[\s.]+przez|pełnomocnik\w*\s*:", body, re.I)
    rep = fx.search(rf"(?:(?P<through>reprezentowan\w*[\s.]+przez)\s*:?\s*(?:pełnomocnik\w*\s*:?\s*)?|pełnomocni(?:k|cy)\s*:\s*)({EMPLOYEE})?((?:{TITLES}\s*)?)({NAME_WORD}(?:[ \t]+|[ \t]*\n[ \t]*){NAME_WORD})", body, re.I)
    rep_name = person_name(re.sub(r"\s+", " ", rep.group(4))) if rep else None
    if rep_name and OBLIQUE_TITLE.search(rep.group(3)):
        rep_name = nominative(rep_name)
    elif rep_name and rep.group("through") and not rep.group(2):
        rep_name = governed_nominative(rep_name)
    if rep_name and any(w in NOT_PERSON_WORDS or w.lower() in ORG_WORDS for w in rep_name.split()):
        rep_name = None
    firm = fx.search(r"adres\s+do\s+korespondencj?i+\s*:?\s*(.+?)(?:,\s*(?:ul\.?|al\.|pl\.|os\.)|,\s*\d{2}-\d{3}|\n\s*(?:tel|ul\.?|al\.|pl\.|os\.|\d{2}-\d{3}))", body, re.I | re.S)
    firm_name = entity_name(re.sub(r"\s*\n\s*", " ", firm.group(1))) if firm else None
    if not firm_name and represented:
        after = body[represented.end():]
        after = after[after.find("\n") + 1:] if "\n" in after else ""
        for pattern in (r"^[^\n]*\bKancelari\w*[^\n]*$", r"^[^\n]*\b(?:Spółka\s+Partnerska|Adwokac\w+|Radc\w+\s+Prawn\w+)[^\n]*$"):
            office = fx.search(pattern, after[:400], re.I | re.M)
            if office:
                firm_name = entity_name(office.group(0))
                break
    mail = fx.search(EMAIL, body[represented.start():] if represented else "")
    return {
        "name": name,
        **ids_in(body),
        "represented": bool(represented),
        "rep": rep_name,
        "firm": firm_name,
        "mail": fx.fold(mail.group(0)).lower() if mail else None,
    }


def split_members(block: str) -> list[tuple[str, str]]:
    """Split a party block into numbered members, returning (header line, member text) pairs."""
    items = list(fx.finditer(r"^\s*\d\)\s*([^\n]*)\n", block, re.M))
    if len(items) < 2:
        return []
    out = []
    for index, item in enumerate(items):
        end = items[index + 1].start() if index + 1 < len(items) else len(block)
        header = item.group(1).strip()
        rest = block[item.end():end]
        if header.endswith(":"):
            out.append((header, rest))
        else:
            out.append((header, f"{header}\n{rest}"))
    return out


@extractor("appellants")
def extract_appellants(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Extract the appellant (or consortium leader) with its attorney details."""
    found = party_block(ctx.text, spec.get("label", r"(?:[^\n]{0,60}?\(\s*)?Odwołując\w*\s*\)?(?=\s*:)"), spec.get("stop", PARTY_STOP))
    if not found:
        return None, None
    block, start = found
    members = split_members(block)
    main = block
    if members:
        leader = next((m for m in members if fx.search(r"lider|pełnomocnik", m[0], re.I)), members[0])
        main = leader[1]
    entity = parse_entity(main)
    shared = parse_entity(block)
    rep = entity["rep"] or shared["rep"]
    result = {
        "krs": entity["krs"],
        "nazwa": entity["name"],
        "nip": entity["nip"],
        "regon": entity["regon"],
        "przez-pelnomocnika": 1 if rep or entity["represented"] or shared["represented"] else 0,
        "pelnomocnik": {
            "imie_nazwisko": rep,
            "nazwa": entity["firm"] or shared["firm"],
            "mail": entity["mail"] or shared["mail"],
        },
    }
    return [result], Evidence("appellants", snippet(ctx.text, start, start + len(block), 0), start, start + len(block))


@extractor("contracting_authorities")
def extract_contracting_authorities(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Extract one or more contracting authorities, marking the one conducting a joint procedure."""
    found = party_block(ctx.text, spec.get("label", r"(?:[^\n]{0,60}?\(\s*)?Zamawiając\w*\s*\)?(?=\s*[:(])"), spec.get("stop", PARTY_STOP))
    if not found:
        return None, None
    block, start = found
    members = split_members(block)
    out = []
    if members:
        for header, body in members:
            entity = parse_entity(body)
            leading = 1 if fx.search(r"prowadząc|lider|pełnomocnik\s+zamawiaj", f"{header}\n{body}", re.I) else 0
            out.append({"krs": entity["krs"], "nazwa": entity["name"], "nip": entity["nip"], "regon": entity["regon"], "prowadzacy_postepowanie": leading})
    else:
        listed = split_listed(block)
        for part in listed or [block]:
            entity = parse_entity(part)
            out.append({"krs": entity["krs"], "nazwa": entity["name"], "nip": entity["nip"], "regon": entity["regon"], "prowadzacy_postepowanie": None})
    return out, Evidence("contracting_authorities", snippet(ctx.text, start, start + len(block), 0), start, start + len(block))


CONTACT_LINE = r"\s*(?:tel|fax|faks|e-?mail|adres|NIP|KRS|REGON|www|https?:|reprezentowan|strona|platforma|numer\s+telefonu)"
STREET_START = r"\s*(?:ul|al|pl|os)\s?\.|\s*\d"


def split_listed(block: str) -> list[str]:
    """Split an unnumbered list of entities written one per address (joint procurement) into separate parts.

    Each part ends with the line that holds its postal code; the list ends at the first contact line or blank line.
    Returns [] unless at least two parts that each start with a name are found.
    """
    body = re.sub(r"^\s*(?:\([^)]*\)\s*)?:?", "", block, count=1).strip("\n")
    parts: list[str] = []
    current: list[str] = []
    for line in body.split("\n"):
        if not line.strip() or fx.match(CONTACT_LINE, line, re.I):
            break
        current.append(line)
        if re.search(r"\b\d{2}-\d{3}\b", line):
            parts.append("\n".join(current))
            current = []
    if len(parts) < 2 or any(fx.match(STREET_START, part, re.I) or not re.match(rf"\s*[{UPPER}]", part) for part in parts):
        return []
    return parts

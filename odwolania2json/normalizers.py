"""Value normalizers referenced by name from document type configuration."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

MONTHS = {
    "stycznia": 1, "styczeń": 1, "styczen": 1,
    "lutego": 2, "luty": 2,
    "marca": 3, "marzec": 3,
    "kwietnia": 4, "kwiecień": 4, "kwiecien": 4,
    "maja": 5, "maj": 5,
    "czerwca": 6, "czerwiec": 6,
    "lipca": 7, "lipiec": 7,
    "sierpnia": 8, "sierpień": 8, "sierpien": 8,
    "września": 9, "wrzesnia": 9, "wrzesień": 9, "wrzesien": 9,
    "października": 10, "pazdziernika": 10, "październik": 10,
    "listopada": 11, "listopad": 11,
    "grudnia": 12, "grudzień": 12, "grudzien": 12,
}

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}

MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))

DATE_PATTERN = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    r"|\d{1,2}\s+(?:" + MONTH_NAMES + r")\s+\d{4}"
    r"|\d{1,2}\s+(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)\s+\d{4})"
)

_REGISTRY: dict[str, Callable[[Any], Any]] = {}


def normalizer(name: str) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
    """Register a function as a named normalizer."""

    def wrap(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
        _REGISTRY[name] = func
        return func

    return wrap


def apply(names: list[str] | str | None, value: Any) -> Any:
    """Apply the listed normalizers to a value in order, short-circuiting on None."""
    if names is None:
        return value
    if isinstance(names, str):
        names = [names]
    for name in names:
        if value is None:
            return None
        if name not in _REGISTRY:
            raise KeyError(f"Unknown normalizer: {name}")
        value = _REGISTRY[name](value)
    return value


def available() -> list[str]:
    """Return the names of all registered normalizers."""
    return sorted(_REGISTRY)


@normalizer("strip")
def strip(value: str) -> str | None:
    """Trim whitespace and trailing punctuation, returning None for empty strings."""
    value = re.sub(r"\s+", " ", str(value)).strip(" \t\n,;:")
    return value or None


@normalizer("reference")
def reference(value: str) -> str | None:
    """Join a reference number written with spaced separators ('ZP / D / 8 / 22' -> 'ZP/D/8/22')."""
    text = re.sub(r"\s*/\s*", "/", str(value)).strip()
    return text or None


@normalizer("strip_quotes")
def strip_quotes(value: str) -> str:
    """Remove surrounding typographic and ASCII quotes."""
    return str(value).strip().strip("„”\"'“«»").strip()


@normalizer("digits")
def digits(value: str) -> str | None:
    """Keep only digits."""
    out = re.sub(r"\D", "", str(value))
    return out or None


@normalizer("account")
def account(value: str) -> str | None:
    """Account number as written in the document without whitespace: digits, with the country code (PL or other) when shown."""
    text = str(value).strip()
    country = re.match(r"([A-Za-z]{2})\s?\d", text)
    if country:
        body = re.sub(r"[^0-9A-Za-z]", "", text[2:]).upper()
        return country.group(1).upper() + body if body else None
    digits = re.sub(r"[^0-9]", "", text)
    return digits or None


@normalizer("date_iso")
def date_iso(value: str) -> str | None:
    """Convert Polish date notations to ISO YYYY-MM-DD."""
    text = str(value).strip().lower()
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return _iso(year, month, day)
    match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if match:
        day, month, year = match.groups()
        return _iso(year, month, day)
    match = re.search(r"(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})", text)
    if match:
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name) or ROMAN.get(month_name) or _close_month(month_name)
        if month:
            return _iso(year, month, day)
    match = re.search(r"(\d{1,2})\s+(\d{1,2})\s+(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return _iso(year, month, day)
    return None


def _close_month(word: str) -> int | None:
    """Month number of a month name misread by OCR (e.g. 'ezerwca'), when it is close to exactly one name."""
    import difflib

    if len(word) < 4:
        return None
    match = difflib.get_close_matches(word, MONTHS, n=1, cutoff=0.8)
    return MONTHS[match[0]] if match else None


def _iso(year: Any, month: Any, day: Any) -> str | None:
    """Format date components as ISO string, rejecting impossible values."""
    year, month, day = int(year), int(month), int(day)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


@normalizer("amount")
def amount(value: str) -> float | None:
    """Parse a monetary amount written with Polish or English separators."""
    text = re.sub(r"[^\d,.\s]", "", str(value)).strip()
    text = re.sub(r"\s+", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else text.replace(",", "")
    elif text.count(".") > 1:
        head, _, tail = text.rpartition(".")
        text = f"{head.replace('.', '')}.{tail}"
    try:
        return round(float(text), 2)
    except ValueError:
        return None


@normalizer("ted")
def ted(value: str) -> str | None:
    """Normalize a TED notice number to the NNNNNN-YYYY form."""
    text = str(value)
    match = re.search(r"(\d{4})\s*/\s*S\s*\d{1,3}\s*[-–]\s*(\d{5,7})", text)
    if match:
        return f"{match.group(2)}-{match.group(1)}"
    match = re.search(r"(\d{5,7})\s*[-–]\s*(\d{4})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return None


@normalizer("bzp")
def bzp(value: str) -> str | None:
    """Normalize a BZP notice number to YYYY/BZP######## without spaces."""
    match = re.search(r"(\d{4})\s*/\s*BZP\s*([\d\s]{6,12}\d)(\s*/\s*\d{1,2})?", str(value), flags=re.I)
    if not match:
        return None
    suffix = re.sub(r"\s", "", match.group(3) or "")
    return f"{match.group(1)}/BZP{re.sub(r'\s', '', match.group(2))}{suffix}"


@normalizer("int")
def to_int(value: Any) -> int | None:
    """Convert value to int when possible."""
    try:
        return int(str(value).strip())
    except ValueError:
        return None


@normalizer("person_name")
def person_name(value: str) -> str | None:
    """Strip professional titles and trailing qualifiers from a person name, converting oblique forms to nominative."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(
        r"^(?:(?:r\.\s*pr\.|radc[ayę]\s+prawn[ya]|radc(?:y|ę|omu)\s+prawn(?:ego|emu|ej)|radczyni[ę]?\s+prawn(?:a|ą|ej)|adw\.|adwokat(?:a|owi|em|ka|kę|ce)?|mec\.|mecenas(?:a|owi)?|pan[iau]?|dr|prof\.|hab\.|aplikant\w*\s+\w+)\s*)+",
        "",
        text,
        flags=re.I,
    )
    text = re.split(r"\s*[\(,;–—]|\s+-\s+|\s+\(", text)[0]
    words = text.split()
    kept = [w for w in words if re.match(r"^[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ'-]*\.?$", w)]
    if len(kept) < 2:
        return text.strip() or None
    return nominative(" ".join(kept[:3]).rstrip("."))


PLACEHOLDER = re.compile(r"_{3,}|\.{4,}|…{2,}|\[\s*(?:nazwa|imię)", re.I)
MAX_NAME_LENGTH = 160


@normalizer("entity_name")
def entity_name(value: str) -> str | None:
    """Clean an organization name; reject form placeholders and runaway text that is not a name."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"\(dalej[^)]*\)?", "", text, flags=re.I)
    text = text.strip(" ,;:").strip("„”\"")
    if not text or PLACEHOLDER.search(text) or len(text) > MAX_NAME_LENGTH:
        return None
    return text


@lru_cache(maxsize=1)
def _place_lexicon() -> dict[str, str]:
    """Load place names from config/lexicons/miejscowosci.txt keyed by their accent-free lowercase form."""
    import os
    from pathlib import Path

    from .fuzzy_re import fold

    base = Path(os.environ.get("O2J_CONFIG_DIR") or Path(__file__).resolve().parent.parent / "config")
    path = base / "lexicons" / "miejscowosci.txt"
    if not path.exists():
        return {}
    names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {fold(name).lower(): name for name in names}


@normalizer("place")
def place(value: str) -> str | None:
    """Restore Polish diacritics of known place names lost by OCR (Wroclaw -> Wrocław, Lódż -> Łódź)."""
    from .fuzzy_re import fold

    text = re.sub(r"\s+", " ", str(value)).strip(" ,.")
    if not text:
        return None
    key = fold(text).lower()
    lexicon = _place_lexicon()
    if key in lexicon:
        return lexicon[key]
    for variant in (key.replace("t", "l"), key.replace("h", "l"), key.replace("f", "l")):
        if variant in lexicon:
            return lexicon[variant]
    return text


OBLIQUE_TITLE = re.compile(r"(?i)\b(?:radcę|radcy|radczynię|radczyni|adwokata|adwokatowi|adwokatkę|adwokatce|mecenasa|mecenasowi|pełnomocnika|pełnomocnikowi)\b")


@lru_cache(maxsize=1)
def _morfeusz():
    """Morfeusz2 analyser if installed."""
    try:
        import morfeusz2

        return morfeusz2.Morfeusz(generate=False)
    except Exception:
        return None


SUFFIX_RULES = {
    "m1": [(r"([sc]k|dzk)iego$", r"\1i"), (r"([sc]k|dzk)iemu$", r"\1i"), (r"(?<=[bcdfghjklłmnprstwzż])a$", ""), (r"(?<=[bcdfghjklłmnprstwzż])owi$", "")],
    "f": [(r"([sc]k|dzk)iej$", r"\1a"), (r"owej$", "owa")],
}
OBLIQUE_CASE = re.compile(r"(?:^|[:.])(?:gen|acc|dat|inst)(?:[:.]|$)")
NOM_CASE = re.compile(r"(?:^|[:.])nom(?:[:.]|$)")


def _readings(token: str) -> list[tuple[str, str, str, list[str]]]:
    """Singular noun/adjective readings of a token as (lemma, case field, gender field, qualifiers)."""
    analyser = _morfeusz()
    if analyser is None:
        return []
    out = []
    for item in analyser.analyse(token):
        tag = item[2][2].split(":")
        if tag[0] in ("subst", "adj") and len(tag) >= 4 and "sg" in tag[1].split("."):
            out.append((item[2][1].split(":")[0], tag[2], tag[3], list(item[2][3])))
    return out


def _is_nom(token: str, gender: str | None = None, is_first: bool = False) -> bool:
    """Tell whether a token already has a singular nominative reading (as a first name when is_first is set)."""
    all_readings = _readings(token)
    has_given = any("imię" in q for _, _, _, q in all_readings)
    for lemma, case, genders, quals in all_readings:
        if lemma == token and NOM_CASE.search(case) and (gender is None or gender in genders.split(".")):
            if not is_first or "imię" in quals or not has_given:
                return True
    return False


def _convert(token: str, gender: str, is_first: bool = False) -> tuple[str, bool]:
    """Nominative of a capitalized token for a gender; the flag says whether an oblique reading was used."""
    if not token[:1].isupper() or _is_nom(token, gender, is_first):
        return token, False
    all_readings = _readings(token)
    has_given = any("imię" in q for _, _, _, q in all_readings)
    for lemma, case, genders, quals in all_readings:
        if lemma[:1].isupper() and gender in genders.split(".") and OBLIQUE_CASE.search(case):
            if is_first and "imię" not in quals and has_given:
                continue
            return lemma, True
    return token, False


@normalizer("nominative")
def nominative(value: str) -> str | None:
    """Convert a person name written in an oblique case (e.g. 'Mateusza Szymańskiego') to nominative with Morfeusz2."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or _morfeusz() is None:
        return text or None
    words_in = text.split(" ")
    best: tuple[int, str] = (0, text)
    best_gender = None
    for gender in ("m1", "f"):
        converted = 0
        ambig_first = False
        words = []
        for idx, word in enumerate(words_in):
            pieces = []
            for piece in word.split("-"):
                new, used = _convert(piece, gender, is_first=(idx == 0))
                if idx == 0 and used and _is_nom(piece, is_first=True):
                    ambig_first = True
                converted += used
                pieces.append(new)
            words.append("-".join(pieces))
        if ambig_first and converted == 1:
            continue
        if converted > best[0]:
            best = (converted, " ".join(words))
            best_gender = gender
    if best_gender is None:
        return best[1]
    words = best[1].split(" ")
    rules = SUFFIX_RULES[best_gender]
    for i, (new, old) in enumerate(zip(words, words_in)):
        if new == old and new[:1].isupper() and not _readings(new):
            for pattern, replacement in rules:
                if re.search(pattern, new):
                    words[i] = re.sub(pattern, replacement, new)
                    break
    return " ".join(words)

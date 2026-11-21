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
    """Normalize a bank account number to bare digits without the PL prefix."""
    out = re.sub(r"[^0-9]", "", re.sub(r"^\s*PL", "", str(value), flags=re.I))
    return out or None


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
        month = MONTHS.get(month_name) or ROMAN.get(month_name)
        if month:
            return _iso(year, month, day)
    return None


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
    """Strip professional titles and trailing qualifiers from a person name."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(
        r"^(?:(?:r\.\s*pr\.|radc[ay]\s+prawn[ya]|radczyni\s+prawna|adw\.|adwokat|mec\.|pan[i]?|dr|prof\.|hab\.|aplikant\w*\s+\w+)\s*)+",
        "",
        text,
        flags=re.I,
    )
    text = re.split(r"\s*[\(,;–]|\s+-\s+|\s+\(", text)[0]
    words = text.split()
    kept = [w for w in words if re.match(r"^[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ'-]*\.?$", w)]
    if len(kept) < 2:
        return text.strip() or None
    return " ".join(kept[:3]).rstrip(".")


@normalizer("entity_name")
def entity_name(value: str) -> str | None:
    """Clean an organization name of quotes, trailing punctuation and role markers."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"\(dalej[^)]*\)?", "", text, flags=re.I)
    text = text.strip(" ,;:").strip("„”\"")
    return text or None


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
OBLIQUE_CASE = re.compile(r"(?:^|[:.])(?:gen|acc|dat|inst|loc)(?:[:.]|$)")


def _readings(token: str) -> list[tuple[str, str, str]]:
    """Noun readings of a token as (lemma, case field, gender field)."""
    analyser = _morfeusz()
    if analyser is None:
        return []
    out = []
    for item in analyser.analyse(token):
        tag = item[2][2].split(":")
        if tag[0] == "subst" and len(tag) >= 4:
            out.append((item[2][1].split(":")[0], tag[2], tag[3]))
    return out


def _convert(token: str, gender: str) -> tuple[str, bool]:
    """Nominative of a capitalized token for a gender; the flag says whether an oblique reading was used."""
    if not token[:1].isupper():
        return token, False
    for lemma, case, genders in _readings(token):
        if lemma[:1].isupper() and gender in genders.split(".") and OBLIQUE_CASE.search(case):
            return lemma, True
    return token, False


@normalizer("nominative")
def nominative(value: str) -> str | None:
    """Convert a person name written in an oblique case (e.g. 'Jana Kowalskiego') to nominative with Morfeusz2."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or _morfeusz() is None:
        return text or None
    best: tuple[int, str] = (0, text)
    best_gender = None
    for gender in ("m1", "f"):
        converted = 0
        words = []
        for word in text.split(" "):
            pieces = []
            for piece in word.split("-"):
                new, used = _convert(piece, gender)
                converted += used
                pieces.append(new)
            words.append("-".join(pieces))
        if converted > best[0]:
            best = (converted, " ".join(words))
            best_gender = gender
    if best_gender is None:
        return best[1]
    words = best[1].split(" ")
    original = text.split(" ")
    rules = SUFFIX_RULES[best_gender]
    for i, (new, old) in enumerate(zip(words, original)):
        if new == old and new[:1].isupper() and not _readings(new):
            for pattern, replacement in rules:
                if re.search(pattern, new):
                    words[i] = re.sub(pattern, replacement, new)
                    break
    return " ".join(words)

"""Value normalizers referenced by name from document type configuration."""

from __future__ import annotations

import re
from collections.abc import Callable
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

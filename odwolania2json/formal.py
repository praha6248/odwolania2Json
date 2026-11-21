"""Formal checks of a case across its documents, defined in config/formal_checks.yaml.

Each check reads values from the output JSON of the documents in one case through paths such as
'odwolanie:Odwolujacy[].nazwa' and returns a status: ok, warn, error or skip (a document or value is missing).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from .cases import key

CHECKS: dict[str, Callable[[dict[str, Any], dict[str, Any]], tuple[str, str]]] = {}


def check(kind: str) -> Callable:
    """Register a check implementation under a kind name."""
    def wrap(func: Callable) -> Callable:
        CHECKS[kind] = func
        return func
    return wrap


class Missing(Exception):
    """A document or value needed by a check is not available."""


def walk(node: Any, parts: list[str]) -> list[Any]:
    """Follow dotted path parts through dicts, expanding 'name[]' over lists."""
    nodes = [node]
    for part in parts:
        name = part.removesuffix("[]")
        nodes = [n.get(name) if isinstance(n, dict) else None for n in nodes]
        if part.endswith("[]"):
            nodes = [item for n in nodes for item in (n or [])]
    return nodes


def values(case: dict[str, Any], path: str, required: bool = True) -> list[Any]:
    """Return non-empty values at 'type:path' in the case; raise Missing when required and nothing is found."""
    doc_type, _, rest = path.partition(":")
    if doc_type not in case:
        raise Missing(f"brak dokumentu: {doc_type}")
    found = [v for v in walk(case[doc_type], rest.split(".")) if v not in (None, "", [])]
    if required and not found:
        raise Missing(f"brak wartości: {rest}")
    return found


def as_date(value: Any) -> dt.date:
    """Parse an ISO date."""
    return dt.date.fromisoformat(str(value)[:10])


def easter(year: int) -> dt.date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return dt.date(year, month, day)


def holidays(year: int) -> set[dt.date]:
    """Polish public holidays of a year."""
    sunday = easter(year)
    fixed = {(1, 1), (1, 6), (5, 1), (5, 3), (8, 15), (11, 1), (11, 11), (12, 25), (12, 26)}
    if year >= 2025:
        fixed.add((12, 24))
    days = {dt.date(year, m, d) for m, d in fixed}
    return days | {sunday, sunday + dt.timedelta(days=1), sunday + dt.timedelta(days=49), sunday + dt.timedelta(days=60)}


def working_day(day: dt.date) -> dt.date:
    """Move a deadline falling on a Saturday, Sunday or public holiday to the next working day."""
    while day.weekday() >= 5 or day in holidays(day.year):
        day += dt.timedelta(days=1)
    return day


def pl_date(day: dt.date) -> str:
    """Format a date as DD.MM.YYYY."""
    return day.strftime("%d.%m.%Y")


@check("same")
def same(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """Every value on the left appears on the right (names compared without case, accents and punctuation)."""
    left, right = values(case, spec["left"]), values(case, spec["right"])
    missing = [v for v in left if key(str(v)) not in {key(str(r)) for r in right}]
    if missing:
        return "error", f"{', '.join(map(str, missing))} ≠ {', '.join(map(str, right))}"
    return "ok", ", ".join(map(str, left))


@check("contains")
def contains(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """Every item value is one of the 'within' values."""
    items, within = values(case, spec["item"]), values(case, spec["within"])
    absent = [v for v in items if key(str(v)) not in {key(str(w)) for w in within}]
    if absent:
        return "error", f"{', '.join(map(str, absent))} nie występuje wśród: {', '.join(map(str, within))}"
    return "ok", ", ".join(map(str, items))


@check("mentions")
def mentions(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """The text contains the value (ignoring spacing and punctuation)."""
    text, value = str(values(case, spec["text"])[0]), str(values(case, spec["value"])[0])
    if key(value) in key(text):
        return "ok", f"„{value}” w tytule"
    return "warn", f"tytuł nie zawiera „{value}”"


@check("date_order")
def date_order(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """The earlier date is not after the later one."""
    earlier, later = as_date(values(case, spec["earlier"])[0]), as_date(values(case, spec["later"])[0])
    if earlier <= later:
        return "ok", f"{pl_date(earlier)} ≤ {pl_date(later)}"
    return "error", f"{pl_date(earlier)} jest po {pl_date(later)}"


@check("min_amount")
def min_amount(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """The amount covers a per-item fee times the number of items."""
    amount = float(values(case, spec["amount"])[0])
    count = max(1, len(values(case, spec["count"])))
    expected = spec["per_item"] * count
    text = f"{amount:.2f} zł, wymagane co najmniej {expected:.2f} zł ({spec['per_item']} zł × {count} {spec.get('unit', '')})".replace(".", ",")
    return ("ok" if amount + 1e-6 >= expected else "warn"), text.strip()


@check("deadline")
def deadline(case: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """The end date is within the configured number of days after the start date, moved to the next working day."""
    start, end = as_date(values(case, spec["start"])[0]), as_date(values(case, spec["end"])[0])
    days = spec["days"]
    condition = spec.get("days_if") or {}
    if condition and values(case, condition["present"], required=False):
        days = condition["days"]
    limit = working_day(start + dt.timedelta(days=days))
    text = f"{days} dni od {pl_date(start)}: do {pl_date(limit)}; odwołanie z {pl_date(end)}"
    return ("ok" if end <= limit else "warn"), text


def run_checks(specs: list[dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the configured checks over one case given as its documents (with doc_type and data)."""
    case: dict[str, Any] = {}
    for doc in documents:
        if doc.get("doc_type") and doc.get("data"):
            case.setdefault(doc["doc_type"], doc["data"])
    out = []
    for spec in specs:
        func = CHECKS.get(spec.get("kind", ""))
        if func is None:
            continue
        try:
            status, detail = func(case, spec)
        except Missing as exc:
            status, detail = "skip", str(exc)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            status, detail = "skip", f"nie można sprawdzić: {exc}"
        out.append({"id": spec.get("id"), "label": spec.get("label", spec.get("id")), "status": status, "detail": detail, "note": spec.get("note")})
    return out


def summary(results: list[dict[str, Any]]) -> str:
    """Worst status among the results: error, warn or ok."""
    statuses = {r["status"] for r in results}
    return "error" if "error" in statuses else "warn" if "warn" in statuses else "ok"


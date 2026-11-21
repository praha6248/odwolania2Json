"""Diacritic-insensitive regular expressions that still return spans and groups from the original text.

Polish diacritics are frequently lost by OCR ("Odwołujący" -> "Odwolujacy"). Text and pattern are folded
character by character to their base letters, which preserves length, so match positions map 1:1 back to the
original text and extracted values keep their original spelling.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

SPECIAL = {"ł": "l", "Ł": "L", "đ": "d", "ø": "o", "ß": "s"}


@lru_cache(maxsize=4096)
def _fold_char(char: str) -> str:
    """Fold a single character to its base letter, always returning exactly one character."""
    if char in SPECIAL:
        return SPECIAL[char]
    if ord(char) < 128:
        return char
    base = unicodedata.normalize("NFD", char)[0]
    return base if len(base) == 1 else char


def fold(text: str) -> str:
    """Remove diacritics while keeping the string length unchanged."""
    return "".join(_fold_char(c) for c in text)


def fold_pattern(pattern: str) -> str:
    """Fold a regex pattern; 'ł' also accepts OCR look-alikes (t, f, h, 1, |) and a space matches any whitespace run."""
    out = []
    in_class = False
    escaped = False
    for char in pattern:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if in_class:
            if char == "]":
                in_class = False
            if char in "łŁ":
                out.append("lLtfh1|")
                continue
        elif char == "[":
            in_class = True
        elif char in "łŁ":
            out.append("[lLtfh1|]")
            continue
        elif char == " ":
            out.append(r"\s+")
            continue
        out.append(_fold_char(char))
    return _fix_quantified_spaces("".join(out))


def _fix_quantified_spaces(pattern: str) -> str:
    """Keep explicit quantifiers on a space working after it was widened to \\s+ (e.g. ' ?' -> \\s*)."""
    return pattern.replace(r"\s+?", r"\s*").replace(r"\s+*", r"\s*").replace(r"\s++", r"\s+")


@lru_cache(maxsize=2048)
def compile_folded(pattern: str, flags: int) -> re.Pattern[str]:
    """Compile a folded, OCR-tolerant version of a pattern (cached)."""
    return re.compile(fold_pattern(pattern), flags)


class FoldedMatch:
    """Match proxy exposing groups taken from the original (unfolded) text."""

    def __init__(self, match: re.Match[str], original: str) -> None:
        """Wrap a match made on folded text."""
        self._m = match
        self._original = original
        self.re = match.re

    def group(self, *index: Any) -> Any:
        """Return group(s) as substrings of the original text."""
        if not index:
            index = (0,)
        values = []
        for i in index:
            start, end = self._m.span(i)
            values.append(None if start < 0 else self._original[start:end])
        return values[0] if len(values) == 1 else tuple(values)

    def groups(self) -> tuple[Any, ...]:
        """Return all capture groups from the original text."""
        return tuple(self.group(i) for i in range(1, self.re.groups + 1))

    def start(self, group: Any = 0) -> int:
        """Start offset of a group."""
        return self._m.start(group)

    def end(self, group: Any = 0) -> int:
        """End offset of a group."""
        return self._m.end(group)

    def span(self, group: Any = 0) -> tuple[int, int]:
        """Span of a group."""
        return self._m.span(group)

    def __getitem__(self, index: Any) -> Any:
        """Allow match[i] access like re.Match."""
        return self.group(index)


def search(pattern: str, text: str, flags: int = 0, pos: int = 0) -> FoldedMatch | None:
    """Diacritic-insensitive re.search starting at pos."""
    match = compile_folded(pattern, flags).search(fold(text), pos)
    return FoldedMatch(match, text) if match else None


def match(pattern: str, text: str, flags: int = 0) -> FoldedMatch | None:
    """Diacritic-insensitive re.match."""
    found = compile_folded(pattern, flags).match(fold(text))
    return FoldedMatch(found, text) if found else None


def finditer(pattern: str, text: str, flags: int = 0) -> Iterator[FoldedMatch]:
    """Diacritic-insensitive re.finditer."""
    for found in compile_folded(pattern, flags).finditer(fold(text)):
        yield FoldedMatch(found, text)


def split(pattern: str, text: str, flags: int = 0) -> list[str]:
    """Diacritic-insensitive re.split returning pieces of the original text."""
    pieces: list[str] = []
    last = 0
    for found in compile_folded(pattern, flags).finditer(fold(text)):
        pieces.append(text[last:found.start()])
        for i in range(1, found.re.groups + 1):
            start, end = found.span(i)
            pieces.append(None if start < 0 else text[start:end])
        last = found.end()
    pieces.append(text[last:])
    return pieces


def fullmatch(pattern: str, text: str, flags: int = 0) -> FoldedMatch | None:
    """Diacritic-insensitive re.fullmatch."""
    found = compile_folded(pattern, flags).fullmatch(fold(text))
    return FoldedMatch(found, text) if found else None

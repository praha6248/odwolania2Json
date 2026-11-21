"""Dictionary based repair of OCR words: restore lost Polish diacritics and typical letter confusions.

Known forms come from wordfreq (frequencies) and, when installed, Morfeusz2 (SGJP inflection dictionary).

A word that is not in the Polish frequency lexicon (wordfreq) is replaced by the most frequent lexicon word that
differs only by diacritics or by characters OCR commonly reads instead of 'ł' (t, f, h, 1, |). Words that exist are
never changed, so correct text, rare proper names and numbers stay untouched.
"""

from __future__ import annotations

import itertools
import logging
import re
from functools import lru_cache

from .fuzzy_re import fold

log = logging.getLogger(__name__)

WORD = re.compile(r"[A-Za-zÀ-žĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}")
L_LOOKALIKES = "tfh"
MAX_SUBSTITUTIONS = 3
ACCENT_MARGIN = 0.5


@lru_cache(maxsize=1)
def lexicon(size: int = 400000) -> tuple[frozenset[str], dict[str, str], dict[str, str]]:
    """Return known words, the most frequent spelling per accent-free form, and the most frequent accented one."""
    try:
        import wordfreq
    except ImportError:
        log.warning("wordfreq not installed, OCR spelling repair disabled")
        return frozenset(), {}, {}
    words = wordfreq.top_n_list("pl", size)
    index: dict[str, str] = {}
    accented: dict[str, str] = {}
    for word in words:
        key = fold(word)
        index.setdefault(key, word)
        if word != key:
            accented.setdefault(key, word)
    return frozenset(words), index, accented


@lru_cache(maxsize=1)
def _morfeusz():
    """Return a Morfeusz2 analyser when installed (full SGJP inflection dictionary), else None."""
    try:
        import morfeusz2

        return morfeusz2.Morfeusz(generate=False)
    except Exception:
        return None


@lru_cache(maxsize=65536)
def is_word(word: str) -> bool:
    """Tell whether a form exists in the frequency lexicon or in the Morfeusz2 dictionary."""
    known = lexicon()[0]
    if word.lower() in known:
        return True
    analyser = _morfeusz()
    if analyser is None:
        return False
    return any(item[2][2] != "ign" for item in analyser.analyse(word))


def _frequency(word: str) -> float:
    """Zipf frequency of a word (0 when unknown)."""
    import wordfreq

    return wordfreq.zipf_frequency(word, "pl")


def _variants(key: str) -> list[str]:
    """Folded variants where up to MAX_SUBSTITUTIONS look-alike letters are read as 'l' (folded 'ł')."""
    positions = [i for i, c in enumerate(key) if c in L_LOOKALIKES]
    out = []
    for count in range(1, min(MAX_SUBSTITUTIONS, len(positions)) + 1):
        for chosen in itertools.combinations(positions, count):
            chars = list(key)
            for i in chosen:
                chars[i] = "l"
            out.append("".join(chars))
    return out


ACCENTS = {"a": "ą", "e": "ę", "l": "ł", "t": "ł", "o": "ó", "s": "ś", "c": "ć", "n": "ń", "z": "żź"}


def _restore_with_morfeusz(lower: str, max_changes: int = 2) -> str | None:
    """Find a dictionary form differing by at most two diacritic or 'ł' restorations (Morfeusz2 only)."""
    if _morfeusz() is None or len(lower) > 24:
        return None
    positions = [i for i, c in enumerate(lower) if c in ACCENTS]
    if len(positions) > 8:
        max_changes = 1
    for count in range(1, max_changes + 1):
        for chosen in itertools.combinations(positions, count):
            for letters in itertools.product(*(ACCENTS[lower[i]] for i in chosen)):
                chars = list(lower)
                for i, letter in zip(chosen, letters):
                    chars[i] = letter
                candidate = "".join(chars)
                if is_word(candidate):
                    return candidate
    return None


def _match_case(original: str, word: str) -> str:
    """Apply the capitalization pattern of the original token to the replacement."""
    if original.isupper() and len(original) > 1:
        return word.upper()
    if original[0].isupper():
        return word[0].upper() + word[1:]
    return word


def correct_word(token: str, min_zipf: float = 2.0) -> str:
    """Return the most likely intended word for an OCR token, or the token itself."""
    known, index, accented = lexicon()
    if not known:
        return token
    lower = token.lower()
    key = fold(lower)
    if lower in known:
        better = accented.get(key)
        if better and lower == key and _frequency(better) - _frequency(lower) >= ACCENT_MARGIN:
            return _match_case(token, better)
        return token
    if key in index and index[key] != lower:
        return _match_case(token, index[key])
    if is_word(token):
        return token
    candidates = []
    for variant in _variants(key):
        if variant in index:
            candidates.append(index[variant])
    if not candidates:
        restored = _restore_with_morfeusz(lower)
        return _match_case(token, restored) if restored else token
    best = max(candidates, key=_frequency)
    if _frequency(best) < min_zipf:
        return token
    return _match_case(token, best)


def correct_text(text: str, min_zipf: float = 2.0) -> str:
    """Repair every word of an OCR text that is not in the lexicon."""
    return WORD.sub(lambda m: correct_word(m.group(0), min_zipf), text)

"""Text-quality and script signals on diarized segment bodies (Layer B helpers)."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from transcriptions_analysis.text_format import ParsedSegment

# Zero-width and BOM-like marks often seen in pasted text.
_ZERO_WIDTH = frozenset({0x200B, 0x200C, 0x200D, 0xFEFF})
_REPLACEMENT = "\ufffd"


def segment_body_strings(segments: list[ParsedSegment]) -> list[str]:
    """One string per segment: joined body lines, stripped."""
    return ["\n".join(s.body_lines).strip() for s in segments]


def concatenate_segment_bodies(segments: list[ParsedSegment], joiner: str = "\n") -> str:
    """Full text for Unicode / lexical stats (segment bodies only, no speaker/ts lines)."""
    parts = [b for b in segment_body_strings(segments) if b]
    return joiner.join(parts)


def unicode_oddity_counts(text: str) -> dict[str, Any]:
    """
    Count Unicode oddities and non-printable share.

    Returns counts and ``nonprintable_ratio`` in [0, 1].
    """
    n = len(text)
    if n == 0:
        return {
            "unicode_replacement_count": 0,
            "control_char_count": 0,
            "zero_width_count": 0,
            "nonprintable_ratio": 0.0,
        }

    replacement = 0
    control = 0
    zero_w = 0
    nonprint = 0
    for ch in text:
        o = ord(ch)
        if ch == _REPLACEMENT:
            replacement += 1
        if o in _ZERO_WIDTH:
            zero_w += 1
        cat = unicodedata.category(ch)
        if cat[0] == "C" and ch not in "\t\n\r":
            control += 1
        # Non-printable: control (except tab/newline) or explicit non-printable surrogate, etc.
        if not ch.isprintable() and ch not in "\t\n\r":
            nonprint += 1

    return {
        "unicode_replacement_count": replacement,
        "control_char_count": control,
        "zero_width_count": zero_w,
        "nonprintable_ratio": nonprint / n,
    }


def _is_cyrillic(ch: str) -> bool:
    o = ord(ch)
    return 0x0400 <= o <= 0x04FF or 0x0500 <= o <= 0x052F


def _is_latin_letter(ch: str) -> bool:
    if not ch.isalpha():
        return False
    o = ord(ch)
    return (0x0041 <= o <= 0x024F) or (0x1E00 <= o <= 0x1EFF)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF:
        return True
    if 0x3400 <= o <= 0x4DBF:
        return True
    if 0x3000 <= o <= 0x303F:  # CJK punctuation
        return True
    if 0x3040 <= o <= 0x30FF:  # Hiragana/Katakana
        return True
    if 0xAC00 <= o <= 0xD7AF:  # Hangul syllables
        return True
    return False


def _is_arabic(ch: str) -> bool:
    o = ord(ch)
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF


def script_ratios(text: str) -> dict[str, float]:
    """
    Ratios of script classes over letters + digits (denominator).

    ``digit_ratio`` uses decimal digit characters only; ``other`` is the remainder
    of letter+digit mass after known scripts.
    """
    cyr = lat = cjk = arab = digit = other = 0
    for ch in text:
        if ch.isdigit():
            digit += 1
            continue
        if _is_cyrillic(ch):
            cyr += 1
        elif _is_latin_letter(ch):
            lat += 1
        elif _is_cjk(ch):
            cjk += 1
        elif _is_arabic(ch):
            arab += 1
        elif ch.isalpha():
            other += 1

    denom = cyr + lat + cjk + arab + digit + other
    if denom == 0:
        return {
            "cyrillic_ratio": 0.0,
            "latin_ratio": 0.0,
            "cjk_ratio": 0.0,
            "arabic_ratio": 0.0,
            "digit_ratio": 0.0,
            "other_ratio": 0.0,
        }
    return {
        "cyrillic_ratio": cyr / denom,
        "latin_ratio": lat / denom,
        "cjk_ratio": cjk / denom,
        "arabic_ratio": arab / denom,
        "digit_ratio": digit / denom,
        "other_ratio": other / denom,
    }


def tokenize_words(blob: str) -> list[str]:
    """Whitespace tokenization; keeps non-empty tokens."""
    return [w for w in re.split(r"\s+", blob.strip()) if w]


def shannon_entropy_bits(tokens: list[str]) -> float | None:
    """Unigram Shannon entropy in bits; None if no tokens."""
    if not tokens:
        return None
    n = len(tokens)
    counts = Counter(tokens)
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    return h


def type_token_ratio(tokens: list[str]) -> float | None:
    if not tokens:
        return None
    return len(set(tokens)) / len(tokens)


def hapax_ratio(tokens: list[str]) -> float | None:
    """Share of token *positions* whose type appears exactly once."""
    if not tokens:
        return None
    counts = Counter(tokens)
    hapax_types = {t for t, c in counts.items() if c == 1}
    return sum(1 for t in tokens if t in hapax_types) / len(tokens)


def mean_median_word_length(tokens: list[str]) -> tuple[float | None, float | None]:
    if not tokens:
        return None, None
    lens = sorted(len(t) for t in tokens)
    n = len(lens)
    mid = n // 2
    median = float(lens[mid]) if n % 2 else (lens[mid - 1] + lens[mid]) / 2.0
    return sum(lens) / n, median


def long_word_ratio(tokens: list[str], min_len: int = 7) -> float | None:
    if not tokens:
        return None
    return sum(1 for t in tokens if len(t) >= min_len) / len(tokens)


def short_utterance_ratio(bodies: list[str], max_words: int = 2) -> float:
    """
    Share of non-empty segment bodies with at most ``max_words`` words.
    """
    nonempty = [b for b in bodies if b.strip()]
    if not nonempty:
        return 0.0
    short = 0
    for b in nonempty:
        wc = len(tokenize_words(b))
        if wc <= max_words:
            short += 1
    return short / len(nonempty)


def repeated_char_run_ratio(text: str, min_run: int = 3) -> float:
    """
    Share of alphanumeric characters that sit in a run of identical char of length >= min_run.
    """
    if not text:
        return 0.0
    s = text
    n = len(s)
    in_run = [False] * n
    i = 0
    while i < n:
        ch = s[i]
        if not (ch.isalnum()):
            i += 1
            continue
        j = i + 1
        while j < n and s[j] == ch and ch.isalnum():
            j += 1
        run_len = j - i
        if run_len >= min_run:
            for k in range(i, j):
                in_run[k] = True
        i = j
    alnum_positions = sum(1 for c in s if c.isalnum())
    if alnum_positions == 0:
        return 0.0
    hit = sum(1 for idx, c in enumerate(s) if c.isalnum() and in_run[idx])
    return hit / alnum_positions


def lexical_and_quality_from_bodies(
    full_text: str,
    bodies: list[str],
) -> dict[str, Any]:
    """
    Lexical stats on ``full_text`` (concatenated bodies) and utterance shape on ``bodies``.
    """
    tokens = tokenize_words(full_text)
    ent = shannon_entropy_bits(tokens)
    ttr = type_token_ratio(tokens)
    hap = hapax_ratio(tokens)
    mean_w, med_w = mean_median_word_length(tokens)
    long_r = long_word_ratio(tokens)
    short_u = short_utterance_ratio(bodies)
    rep_r = repeated_char_run_ratio(full_text)

    return {
        "total_tokens": len(tokens),
        "unique_tokens": len(set(tokens)) if tokens else 0,
        "type_token_ratio": ttr if ttr is not None else None,
        "hapax_ratio": hap if hap is not None else None,
        "word_entropy_bits": ent,
        "mean_word_length": mean_w,
        "median_word_length": med_w,
        "long_word_ratio": long_r if long_r is not None else None,
        "short_utterance_ratio": short_u,
        "repeated_char_run_ratio": rep_r,
    }

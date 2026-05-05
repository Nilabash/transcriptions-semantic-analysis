"""Layer A scalar features per transcript row."""

from __future__ import annotations

import re
from typing import Any

from transcriptions_analysis.text_format import (
    ParsedSegment,
    count_separator_lines,
    parse_segments,
    segment_word_char_counts,
)

_METRIC_VERSION = "layer_a_v2"


def _normalize_body(seg: ParsedSegment) -> str:
    blob = "\n".join(seg.body_lines).strip().lower()
    blob = re.sub(r"\s+", " ", blob)
    return blob


def _speaker_switch_count(segments: list[ParsedSegment]) -> int:
    prev: str | None = None
    switches = 0
    for seg in segments:
        sp = seg.speaker
        if sp is None:
            continue
        if prev is not None and sp != prev:
            switches += 1
        prev = sp
    return switches


def _duplicate_adjacent_ratio(segments: list[ParsedSegment]) -> float:
    if len(segments) < 2:
        return 0.0
    dups = 0
    pairs = 0
    prev_body: str | None = None
    for seg in segments:
        b = _normalize_body(seg)
        if not b:
            continue
        if prev_body is not None:
            pairs += 1
            if b == prev_body:
                dups += 1
        prev_body = b
    return dups / pairs if pairs else 0.0


def empty_layer_a() -> dict[str, Any]:
    """Layer A feature dict for empty / null transcription text."""
    return {
        "layer_a_segment_count": 0,
        "layer_a_separator_count": 0,
        "layer_a_distinct_speakers": 0,
        "layer_a_median_words_per_segment": None,
        "layer_a_median_chars_per_segment": None,
        "layer_a_max_words_per_segment": None,
        "layer_a_malformed_timestamp_ratio": 0.0,
        "layer_a_duplicate_adjacent_segment_ratio": 0.0,
        "layer_a_speaker_switch_count": 0,
        "layer_a_speaker_switch_rate": 0.0,
        "layer_a_unreasonable_speaker_churn": False,
    }


def compute_layer_a_for_parsed(t: str, segs: list[ParsedSegment]) -> dict[str, Any]:
    """
    Compute Layer A features given full text and pre-parsed segments.

    Use with :func:`parse_segments` once per row when also computing Layer B.
    """
    sep_count = count_separator_lines(t)

    words_list: list[int] = []
    chars_list: list[int] = []

    for seg in segs:
        ch, wc = segment_word_char_counts(seg)
        chars_list.append(ch)
        words_list.append(wc)

    # Segments with a speaker label should have a well-formed bracketed timestamp line after it.
    malformed = sum(
        1
        for seg in segs
        if seg.speaker is not None
        and (seg.timestamp_line_malformed or not seg.has_timestamp)
    )
    denom = max(len(segs), 1)
    malformed_ratio = malformed / denom

    words_sorted = sorted(words_list) if words_list else []
    chars_sorted = sorted(chars_list) if chars_list else []

    def median(vals: list[int]) -> float | None:
        if not vals:
            return None
        n = len(vals)
        mid = n // 2
        if n % 2:
            return float(vals[mid])
        return (vals[mid - 1] + vals[mid]) / 2.0

    distinct_speakers = len({s.speaker for s in segs if s.speaker is not None})
    switch_count = _speaker_switch_count(segs)
    dup_ratio = _duplicate_adjacent_ratio(segs)
    switch_rate = switch_count / denom
    # Heuristic: many switches per segment for short transcript
    unreasonable = switch_count > max(5, len(segs)) and switch_rate > 0.8

    return {
        "layer_a_segment_count": len(segs),
        "layer_a_separator_count": max(sep_count, 0),
        "layer_a_distinct_speakers": distinct_speakers,
        "layer_a_median_words_per_segment": median(words_sorted),
        "layer_a_median_chars_per_segment": median(chars_sorted),
        "layer_a_max_words_per_segment": max(words_list) if words_list else None,
        "layer_a_malformed_timestamp_ratio": malformed_ratio,
        "layer_a_duplicate_adjacent_segment_ratio": dup_ratio,
        "layer_a_speaker_switch_count": switch_count,
        "layer_a_speaker_switch_rate": switch_rate,
        "layer_a_unreasonable_speaker_churn": unreasonable,
    }


def compute_layer_a_for_text(text: str | None) -> dict[str, Any]:
    """Compute Layer A features for one transcription_text cell."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return empty_layer_a()

    t = str(text)
    segs = parse_segments(t)
    return compute_layer_a_for_parsed(t, segs)


def metric_definition_version() -> str:
    return _METRIC_VERSION

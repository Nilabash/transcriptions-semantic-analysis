"""Layer B and content-characterization scalar features per transcript row."""

from __future__ import annotations

from typing import Any

from transcriptions_analysis.content_category import classify_content
from transcriptions_analysis.content_language import detect_primary_language
from transcriptions_analysis.content_metadata import derive_file_metadata
from transcriptions_analysis.content_text import (
    concatenate_segment_bodies,
    lexical_and_quality_from_bodies,
    script_ratios,
    segment_body_strings,
    unicode_oddity_counts,
)
from transcriptions_analysis.text_format import ParsedSegment, parse_segments

_METRIC_VERSION = "layer_b_v3"  # content_category v2: strength-based primary + dominance confidence

# Numeric columns for time-bucket aggregates (exclude string language / extension / category).
NUMERIC_LAYER_B: tuple[str, ...] = (
    "layer_b_unicode_replacement_count",
    "layer_b_control_char_count",
    "layer_b_zero_width_count",
    "layer_b_nonprintable_ratio",
    "layer_b_repeated_char_run_ratio",
    "layer_b_total_tokens",
    "layer_b_unique_tokens",
    "layer_b_type_token_ratio",
    "layer_b_hapax_ratio",
    "layer_b_word_entropy_bits",
    "layer_b_mean_word_length",
    "layer_b_median_word_length",
    "layer_b_long_word_ratio",
    "layer_b_short_utterance_ratio",
    "layer_b_primary_language_confidence",
    "layer_b_language_mixed",
    "content_script_cyrillic_ratio",
    "content_script_latin_ratio",
    "content_script_cjk_ratio",
    "content_script_arabic_ratio",
    "content_script_digit_ratio",
    "content_script_other_ratio",
    "content_file_basename_token_count",
    "content_file_path_depth",
    "content_category_confidence",  # from new content_category classifier
)


def empty_layer_b(file_name: str | None = None) -> dict[str, Any]:
    """Default Layer B + content dict for empty text (file metadata still derived)."""
    meta = derive_file_metadata(file_name)
    return {
        "layer_b_unicode_replacement_count": 0,
        "layer_b_control_char_count": 0,
        "layer_b_zero_width_count": 0,
        "layer_b_nonprintable_ratio": 0.0,
        "layer_b_repeated_char_run_ratio": 0.0,
        "layer_b_total_tokens": 0,
        "layer_b_unique_tokens": 0,
        "layer_b_type_token_ratio": None,
        "layer_b_hapax_ratio": None,
        "layer_b_word_entropy_bits": None,
        "layer_b_mean_word_length": None,
        "layer_b_median_word_length": None,
        "layer_b_long_word_ratio": None,
        "layer_b_short_utterance_ratio": 0.0,
        "layer_b_primary_language": "",
        "layer_b_primary_language_confidence": 0.0,
        "layer_b_language_mixed": False,
        "content_script_cyrillic_ratio": 0.0,
        "content_script_latin_ratio": 0.0,
        "content_script_cjk_ratio": 0.0,
        "content_script_arabic_ratio": 0.0,
        "content_script_digit_ratio": 0.0,
        "content_script_other_ratio": 0.0,
        "content_file_extension": meta["content_file_extension"],
        "content_file_basename_token_count": meta["content_file_basename_token_count"],
        "content_file_path_depth": meta["content_file_path_depth"],
        "content_primary_category": "unknown",
        "content_category_confidence": 0.0,
    }


def compute_layer_b_for_row(
    transcription_text: str | None,
    file_name: str | None,
    segments: list[ParsedSegment] | None = None,
    *,
    max_chars: int = 4000,
    iso_codes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Layer B + content features. Pass pre-parsed ``segments`` to avoid a second parse.

    ``iso_codes`` constrains lingua (see :func:`content_language.get_detector`).
    """
    meta = derive_file_metadata(file_name)

    if transcription_text is None or not str(transcription_text).strip():
        out = empty_layer_b(file_name)
        return out

    t = str(transcription_text)
    segs = segments if segments is not None else parse_segments(t)
    bodies = segment_body_strings(segs)
    full_body_text = concatenate_segment_bodies(segs, joiner="\n")

    if not full_body_text.strip():
        out = empty_layer_b(file_name)
        return out

    odd = unicode_oddity_counts(full_body_text)
    scripts = script_ratios(full_body_text)
    lex = lexical_and_quality_from_bodies(full_body_text, bodies)

    iso, conf, mixed = detect_primary_language(
        full_body_text,
        max_chars=max_chars,
        iso_codes=iso_codes,
    )

    # New content category classification (integrated from parallel script + structural signals)
    # Use row id when available in future; for now use a stable placeholder
    cat = classify_content(segs, row_id="batch_row")

    return {
        "layer_b_unicode_replacement_count": odd["unicode_replacement_count"],
        "layer_b_control_char_count": odd["control_char_count"],
        "layer_b_zero_width_count": odd["zero_width_count"],
        "layer_b_nonprintable_ratio": odd["nonprintable_ratio"],
        "layer_b_repeated_char_run_ratio": lex["repeated_char_run_ratio"],
        "layer_b_total_tokens": lex["total_tokens"],
        "layer_b_unique_tokens": lex["unique_tokens"],
        "layer_b_type_token_ratio": lex["type_token_ratio"],
        "layer_b_hapax_ratio": lex["hapax_ratio"],
        "layer_b_word_entropy_bits": lex["word_entropy_bits"],
        "layer_b_mean_word_length": lex["mean_word_length"],
        "layer_b_median_word_length": lex["median_word_length"],
        "layer_b_long_word_ratio": lex["long_word_ratio"],
        "layer_b_short_utterance_ratio": lex["short_utterance_ratio"],
        "layer_b_primary_language": iso,
        "layer_b_primary_language_confidence": conf,
        "layer_b_language_mixed": mixed,
        "content_script_cyrillic_ratio": scripts["cyrillic_ratio"],
        "content_script_latin_ratio": scripts["latin_ratio"],
        "content_script_cjk_ratio": scripts["cjk_ratio"],
        "content_script_arabic_ratio": scripts["arabic_ratio"],
        "content_script_digit_ratio": scripts["digit_ratio"],
        "content_script_other_ratio": scripts["other_ratio"],
        "content_file_extension": meta["content_file_extension"],
        "content_file_basename_token_count": meta["content_file_basename_token_count"],
        "content_file_path_depth": meta["content_file_path_depth"],
        # Content category (primary + confidence)
        "content_primary_category": cat["primary_category"],
        "content_category_confidence": cat["confidence"],
    }


def metric_definition_version() -> str:
    return _METRIC_VERSION

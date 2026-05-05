"""Tests for Layer B text utilities (Unicode, scripts, lexical stats)."""

from transcriptions_analysis.content_text import (
    lexical_and_quality_from_bodies,
    repeated_char_run_ratio,
    script_ratios,
    shannon_entropy_bits,
    unicode_oddity_counts,
)
from transcriptions_analysis.text_format import parse_segments


def test_unicode_replacement_and_zero_width():
    odd = unicode_oddity_counts("a\ufffdb\u200b")
    assert odd["unicode_replacement_count"] == 1
    assert odd["zero_width_count"] >= 1


def test_script_ratios_cyrillic_latin():
    s = script_ratios("Привет hello")
    assert s["cyrillic_ratio"] > 0 and s["latin_ratio"] > 0


def test_entropy_uniform_two_types():
    toks = ["a", "b", "a", "b"]
    ent = shannon_entropy_bits(toks)
    assert ent is not None and abs(ent - 1.0) < 1e-9


def test_repeated_char_run_ratio():
    r = repeated_char_run_ratio("soooo good")
    assert r > 0


def test_lexical_from_segment_bodies():
    text = """--------------------------------------------------------------------------------
SPEAKER_00
[00:00:00 - 00:00:02]
hello world
--------------------------------------------------------------------------------
SPEAKER_00
[00:00:02 - 00:00:04]
hello again"""
    segs = parse_segments(text)
    bodies = ["\n".join(s.body_lines).strip() for s in segs]
    full = "\n".join(b for b in bodies if b)
    lex = lexical_and_quality_from_bodies(full, bodies)
    assert lex["total_tokens"] >= 4
    assert lex["short_utterance_ratio"] >= 0.0

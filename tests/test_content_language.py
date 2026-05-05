"""Tests for lingua wrapper."""

from transcriptions_analysis.content_language import (
    detection_sample,
    detect_primary_language,
    parse_iso_codes_csv,
)


def test_parse_iso_defaults():
    assert len(parse_iso_codes_csv(None)) >= 3


def test_detect_english():
    iso, conf, mixed = detect_primary_language(
        "The quick brown fox jumps over the lazy dog.",
        max_chars=200,
        iso_codes=("en", "ru"),
    )
    assert iso == "en"
    assert conf > 0.5
    assert mixed is False


def test_detect_russian():
    iso, conf, mixed = detect_primary_language(
        "Это простой текст на русском языке для проверки.",
        max_chars=200,
        iso_codes=("en", "ru"),
    )
    assert iso == "ru"
    assert conf > 0.3


def test_empty_returns_empty():
    iso, conf, mixed = detect_primary_language("", max_chars=100)
    assert iso == ""
    assert conf == 0.0
    assert mixed is False


def test_detection_sample_respects_budget():
    s = "a" * 10_000
    out = detection_sample(s, 4000)
    assert len(out) == 4000
    wing = 4000 // 3
    assert out.startswith(s[:wing])
    assert out.endswith(s[-wing:])


def test_detect_russian_after_long_ascii_prefix_not_prefix_only_bias():
    """
    Prefix-only sampling used to see only Latin preamble; head/middle/tail must
    include later Cyrillic and yield Russian.
    """
    ascii_block = ("The meeting notes alpha bravo delta charlie " * 200)[:5200]
    russian = "Это длинная русская фраза для проверки. " * 350
    text = ascii_block + russian

    iso_prefix_only, _, _ = detect_primary_language(
        text[:4000],
        max_chars=4000,
        iso_codes=("en", "ru"),
    )

    iso, conf, mixed = detect_primary_language(
        text,
        max_chars=4000,
        iso_codes=("en", "ru"),
    )

    assert iso_prefix_only == "en"
    assert iso == "ru"
    assert conf > 0.2

"""Lingua-based primary language detection (singleton detector, bounded input)."""

from __future__ import annotations

from lingua import IsoCode639_1, Language, LanguageDetector, LanguageDetectorBuilder

# Default allow-list aligned with project plan (§2.4).
_DEFAULT_ISO_CODES: tuple[str, ...] = ("en", "ru", "uk", "de", "pl", "be")

_detector: LanguageDetector | None = None
_detector_key: tuple[str, ...] | None = None


def default_iso_codes() -> tuple[str, ...]:
    """Default ISO 639-1 codes (lowercase) for the constrained detector."""
    return _DEFAULT_ISO_CODES


def parse_iso_codes_csv(s: str | None) -> tuple[str, ...]:
    """
    Parse comma-separated ISO 639-1 codes; normalize to sorted unique lowercase tuple.

    Empty or invalid input falls back to :func:`default_iso_codes`.
    """
    if s is None or not str(s).strip():
        return default_iso_codes()
    parts = tuple(sorted({p.strip().lower() for p in str(s).split(",") if p.strip()}))
    return parts if parts else default_iso_codes()


def _iso_codes_to_enum(codes: tuple[str, ...]) -> list[IsoCode639_1]:
    """Map lowercase ISO codes to :class:`IsoCode639_1` (lingua uses type-level constants)."""
    out: list[IsoCode639_1] = []
    for c in codes:
        key = c.upper()
        if hasattr(IsoCode639_1, key):
            out.append(getattr(IsoCode639_1, key))
    if not out:
        for c in default_iso_codes():
            key = c.upper()
            if hasattr(IsoCode639_1, key):
                out.append(getattr(IsoCode639_1, key))
    return out


def get_detector(iso_codes: tuple[str, ...] | None = None) -> LanguageDetector:
    """
    Return a cached :class:`LanguageDetector` for the given ISO code set.

    The detector is rebuilt when the code tuple changes.
    """
    global _detector, _detector_key
    key: tuple[str, ...] = iso_codes if iso_codes is not None else default_iso_codes()
    if _detector is not None and _detector_key == key:
        return _detector
    enums = _iso_codes_to_enum(key)
    _detector = LanguageDetectorBuilder.from_iso_codes_639_1(*enums).build()
    _detector_key = key
    return _detector


def _language_to_iso(lang: Language | None) -> str:
    if lang is None:
        return ""
    return lang.iso_code_639_1.name.lower()


def detection_sample(text: str, max_chars: int) -> str:
    """
    Build a bounded excerpt for lingua that is representative of long transcripts.

    A naive prefix biases toward whatever appears first — e.g. a long Latin-heavy
    preamble before Cyrillic prose. Uses three disjoint slices totaling
    ``max_chars``: start, middle band, end (each wing length is ``max_chars // 3``;
    the remainder joins the middle slice).

    Args:
        text: Full text body (typically concatenated segment bodies).
        max_chars: Total character budget. Non-positive returns ``text`` unchanged.

    Returns:
        Up to ``max_chars`` characters, or ``text`` when already shorter than the budget.
    """
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text

    wing = max_chars // 3
    if wing <= 0:
        return text[:max_chars]

    n = len(text)
    head = text[:wing]
    tail = text[(n - wing) :]

    remainder = max_chars - wing - wing  # distributes max_chars mod 3 to middle slice
    usable_mid = (n - wing) - wing

    if remainder <= 0:
        combined = head + tail
        return combined[:max_chars]

    mid_start = wing + max(0, (usable_mid - remainder) // 2)
    middle = text[mid_start : mid_start + remainder]
    return head + middle + tail


def detect_primary_language(
    text: str,
    *,
    max_chars: int = 4000,
    iso_codes: tuple[str, ...] | None = None,
) -> tuple[str, float, bool]:
    """
    Detect primary language on a bounded **representative excerpt** for cost control.

    Long inputs use :func:`detection_sample` (head/middle/end) rather than a prefix-only
    slice so Cyrillic-heavy bodies are not drowned out by a long Latin prelude.

    Returns:
        ``(iso639_1, confidence, mixed_flag)``. ``iso639_1`` is empty when unknown.
        ``confidence`` is the detector's score for the winning language in [0, 1].
        ``mixed_flag`` is True when multiple languages are likely (ambiguous top-2
        or multiple segments from :meth:`detect_multiple_languages_of`).
    """
    if not text or not text.strip():
        return "", 0.0, False

    sample = detection_sample(text, max_chars)
    detector = get_detector(iso_codes)

    multi = detector.detect_multiple_languages_of(sample)
    mixed_segments = False
    if len(multi) >= 2:
        langs = {m.language for m in multi}
        mixed_segments = len(langs) >= 2

    detected = detector.detect_language_of(sample)
    iso = _language_to_iso(detected)

    conf = 0.0
    if detected is not None:
        conf = float(detector.compute_language_confidence(sample, detected))

    vals = detector.compute_language_confidence_values(sample)
    ambiguous = False
    if len(vals) >= 2:
        top, second = float(vals[0].value), float(vals[1].value)
        ambiguous = top > 0 and second > 0 and (top - second) < 0.08

    mixed = mixed_segments or ambiguous
    return iso, conf, mixed

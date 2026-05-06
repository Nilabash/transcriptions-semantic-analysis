"""Build a compact LLM-judge packet from the raw transcription CSV."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from transcriptions_analysis.content_category import KEYWORDS
from transcriptions_analysis.content_language import detect_primary_language, parse_iso_codes_csv
from transcriptions_analysis.content_text import repeated_char_run_ratio

DEFAULT_OUTPUT_DIR = Path("outputs") / "llm_judge"
DEFAULT_PACKET_NAME = "llm_judge_packet.md"
DEFAULT_PROMPT_NAME = "llm_judge_prompt.md"
DEFAULT_INDEX_NAME = "llm_judge_sample_index.csv"
DEFAULT_JSONL_NAME = "llm_judge_transcripts.jsonl"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
LANGUAGE_FILTER_ALIASES = {
    "russian": "ru",
    "rus": "ru",
    "ru-ru": "ru",
    "cyrillic": "cyrillic_dominant",
    "cyrillic-heavy": "cyrillic_dominant",
}
WORD_RE = re.compile(r"[^\W\d_]{2,}(?:['-][^\W\d_]+)?", re.UNICODE)
SPEAKER_LINE_RE = re.compile(
    r"(?im)^\s*\[?\s*(SPEAKER_\d+|SPEAKER_[A-Z]{1,3})\s*\]?\s*$"
)
TIMESTAMP_RE = re.compile(
    r"\[\s*\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*[-–—]\s*"
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*\]|"
    r"^\s*\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*[-–—]\s*"
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?:",
    re.MULTILINE,
)
SEPARATOR_RE = re.compile(r"(?m)^-{20,}\s*$")


@dataclass(frozen=True)
class Candidate:
    source_row_number: int
    transcript_id: str
    month: str
    created_at: str
    file_name: str
    text: str
    body_text: str
    features: dict[str, Any]
    strata: dict[str, str]


@dataclass(frozen=True)
class SelectedCandidate:
    candidate: Candidate
    selection_reason: str
    excerpt: str
    excerpt_limited: bool


def parse_month(created_at: str) -> str | None:
    try:
        return datetime.strptime(created_at.strip(), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m")
    except ValueError:
        return None


def resolve_input_csv(explicit_path: str | Path | None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)

    candidates = sorted(REPO_ROOT.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError("No top-level CSV file found. Pass --input explicitly.")
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise RuntimeError(f"Multiple top-level CSV files found: {names}. Pass --input explicitly.")
    return candidates[0]


def resolve_output_dir(base_dir: str | Path, run_id: str | None) -> Path:
    base = Path(base_dir)
    if run_id is None or not run_id.strip():
        return base
    run_id = run_id.strip()
    if not RUN_ID_RE.match(run_id):
        raise ValueError(
            "--run-id may contain only letters, numbers, dots, underscores, and hyphens."
        )
    return base / run_id


def normalize_language_filters(value: str | None, *, russian_only: bool = False) -> tuple[str, ...]:
    parts: list[str] = []
    if value:
        parts.extend(part.strip().lower() for part in value.split(",") if part.strip())
    if russian_only:
        parts.append("ru")
    normalized = [LANGUAGE_FILTER_ALIASES.get(part, part) for part in parts]
    return tuple(dict.fromkeys(normalized))


def filter_uses_lingua(language_filters: tuple[str, ...]) -> bool:
    return any(len(item) == 2 for item in language_filters)


def iso_prefilter_match(proxy_language: str, language_filters: tuple[str, ...]) -> str:
    if "ru" in language_filters and proxy_language in {
        "cyrillic_dominant",
        "mixed_cyrillic_latin",
    }:
        return "ru_proxy_cyrillic_prefilter"
    if "en" in language_filters and proxy_language in {
        "latin_dominant",
        "mixed_cyrillic_latin",
    }:
        return "en_proxy_latin_prefilter"
    return ""


def language_filter_match(
    text: str,
    features: dict[str, Any],
    *,
    language_filters: tuple[str, ...],
    lang_detect_max_chars: int,
    lang_detect_languages: tuple[str, ...],
    language_min_confidence: float,
) -> tuple[bool, dict[str, Any]]:
    if not language_filters:
        return True, features

    proxy_language = str(features.get("layer_b_primary_language") or "")
    if proxy_language in language_filters:
        return True, {**features, "language_filter_match": proxy_language}

    prefilter = iso_prefilter_match(proxy_language, language_filters)
    if prefilter:
        return True, {**features, "language_filter_match": prefilter}

    return False, features


def load_excluded_transcript_ids(paths: list[str]) -> set[str]:
    excluded: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"Excluded sample index does not exist: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                transcript_id = (row.get("transcript_id") or "").strip()
                if transcript_id:
                    excluded.add(transcript_id)
    return excluded


def exact_language_match_candidate(
    candidate: Candidate,
    *,
    language_filters: tuple[str, ...],
    lang_detect_max_chars: int,
    lang_detect_languages: tuple[str, ...],
    language_min_confidence: float,
) -> Candidate | None:
    iso, confidence, mixed = detect_primary_language(
        candidate.text,
        max_chars=lang_detect_max_chars,
        iso_codes=lang_detect_languages or None,
    )
    if iso not in language_filters or confidence < language_min_confidence:
        return None

    features = {
        **candidate.features,
        "layer_b_primary_language": iso,
        "layer_b_primary_language_confidence": confidence,
        "layer_b_language_mixed": mixed,
        "language_filter_match": iso,
    }
    strata = {**candidate.strata, "language": iso}
    return replace(candidate, features=features, strata=strata)


def refine_candidates_by_exact_language(
    candidates: list[Candidate],
    *,
    language_filters: tuple[str, ...],
    samples_per_month: int,
    seed: int,
    lang_detect_max_chars: int,
    lang_detect_languages: tuple[str, ...],
    language_min_confidence: float,
) -> list[Candidate]:
    if not filter_uses_lingua(language_filters):
        return candidates

    rng = random.Random(seed)
    by_month: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_month[candidate.month].append(candidate)

    refined: list[Candidate] = []
    for month in sorted(by_month):
        pool = by_month[month]
        target = min(samples_per_month, len(pool))
        checked_ids: set[str] = set()
        month_refined: list[Candidate] = []
        scan_target = min(len(pool), max(samples_per_month * 8, samples_per_month + 12))

        while len(month_refined) < target and len(checked_ids) < len(pool):
            provisional = select_month_candidates(
                pool,
                samples_per_month=scan_target,
                rng=rng,
            )
            for candidate, _reason in provisional:
                if candidate.transcript_id in checked_ids:
                    continue
                checked_ids.add(candidate.transcript_id)
                exact = exact_language_match_candidate(
                    candidate,
                    language_filters=language_filters,
                    lang_detect_max_chars=lang_detect_max_chars,
                    lang_detect_languages=lang_detect_languages,
                    language_min_confidence=language_min_confidence,
                )
                if exact is not None:
                    month_refined.append(exact)
                    if len(month_refined) >= target:
                        break
            if scan_target >= len(pool):
                break
            scan_target = min(len(pool), scan_target * 2)

        refined.extend(month_refined)

    return refined


def length_bin(total_tokens: int) -> str:
    if total_tokens < 20:
        return "very_short"
    if total_tokens < 120:
        return "short"
    if total_tokens < 500:
        return "medium"
    if total_tokens < 1200:
        return "long"
    return "very_long"


def dialogue_bin(distinct_speakers: int, segment_count: int) -> str:
    if distinct_speakers <= 1:
        return "monologue_or_single_speaker"
    if distinct_speakers == 2 and segment_count < 20:
        return "two_speaker_light"
    if distinct_speakers == 2:
        return "two_speaker_dense"
    return "multi_speaker"


def quality_bin(features: dict[str, Any]) -> str:
    malformed = float(features.get("layer_a_malformed_timestamp_ratio") or 0.0)
    unicode_replacement = int(features.get("layer_b_unicode_replacement_count") or 0)
    nonprintable = float(features.get("layer_b_nonprintable_ratio") or 0.0)
    churn = bool(features.get("layer_a_unreasonable_speaker_churn"))
    if malformed > 0.2 or unicode_replacement > 0 or nonprintable > 0.01 or churn:
        return "structural_or_text_anomaly"
    if malformed > 0 or float(features.get("layer_b_repeated_char_run_ratio") or 0.0) > 0.05:
        return "minor_artifact_signal"
    return "typical"


def representative_text_sample(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    wing = max_chars // 3
    midpoint = len(text) // 2
    middle_start = max(0, midpoint - wing // 2)
    return text[:wing] + text[middle_start : middle_start + wing] + text[-wing:]


def script_counts(text: str) -> dict[str, int]:
    counts = {"cyrillic": 0, "latin": 0, "cjk": 0, "arabic": 0, "digit": 0, "other": 0}
    for ch in text:
        code = ord(ch)
        if ch.isdigit():
            counts["digit"] += 1
        elif 0x0400 <= code <= 0x052F:
            counts["cyrillic"] += 1
        elif ch.isalpha() and ((0x0041 <= code <= 0x024F) or (0x1E00 <= code <= 0x1EFF)):
            counts["latin"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
            counts["cjk"] += 1
        elif 0x0600 <= code <= 0x08FF:
            counts["arabic"] += 1
        elif ch.isalpha():
            counts["other"] += 1
    return counts


def infer_language_proxy(counts: dict[str, int]) -> tuple[str, float, bool]:
    """Fast script-based language proxy for sampling balance, not semantic language ID."""
    denom = max(1, sum(counts.values()))
    cyr = counts["cyrillic"] / denom
    lat = counts["latin"] / denom
    cjk = counts["cjk"] / denom
    arab = counts["arabic"] / denom

    script_scores = {
        "cyrillic_dominant": cyr,
        "latin_dominant": lat,
        "cjk_dominant": cjk,
        "arabic_dominant": arab,
    }
    best, best_score = max(script_scores.items(), key=lambda item: item[1])
    mixed = cyr >= 0.2 and lat >= 0.2
    if mixed:
        return "mixed_cyrillic_latin", min(1.0, cyr + lat), True
    if best_score <= 0:
        return "unknown", 0.0, False
    return best, best_score, False


def cheap_content_category(
    text_sample: str,
    *,
    total_tokens: int,
    distinct_speakers: int,
    speaker_switches: int,
) -> tuple[str, float]:
    lower = text_sample.lower()
    scores: dict[str, int] = {}
    for category, words in KEYWORDS.items():
        hits = sum(1 for word in words if word.lower() in lower)
        if hits:
            scores[category] = hits
    if scores:
        category, hits = max(scores.items(), key=lambda item: (item[1], item[0]))
        return category, min(1.0, hits / 4)
    if distinct_speakers >= 2 and speaker_switches >= 3:
        return "dialogue_meeting", min(1.0, math.log1p(speaker_switches) / math.log1p(20))
    if total_tokens < 15:
        return "short_note", 0.6
    if total_tokens < 60:
        return "quick_message", 0.5
    return "general_monologue", 0.4


def cheap_feature_proxy(text: str) -> dict[str, Any]:
    sample = representative_text_sample(text)
    tokens = WORD_RE.findall(text)
    speaker_sequence = [match.group(1).upper() for match in SPEAKER_LINE_RE.finditer(text)]
    distinct_speakers = len(set(speaker_sequence))
    speaker_switches = sum(
        1 for prev, cur in zip(speaker_sequence, speaker_sequence[1:]) if prev != cur
    )
    timestamp_count = len(TIMESTAMP_RE.findall(text))
    separator_count = len(SEPARATOR_RE.findall(text))
    segment_count = max(timestamp_count, len(speaker_sequence), separator_count)
    malformed_ratio = 0.0
    if speaker_sequence and timestamp_count == 0:
        malformed_ratio = 1.0
    elif speaker_sequence:
        malformed_ratio = max(
            0.0,
            (len(speaker_sequence) - timestamp_count) / len(speaker_sequence),
        )

    scripts = script_counts(sample)
    language, language_confidence, language_mixed = infer_language_proxy(scripts)
    category, category_confidence = cheap_content_category(
        sample,
        total_tokens=len(tokens),
        distinct_speakers=distinct_speakers,
        speaker_switches=speaker_switches,
    )
    sample_len = max(1, len(sample))
    nonprintable = sum(
        1 for ch in sample if (not ch.isprintable() and ch not in "\t\n\r")
    ) / sample_len

    return {
        "layer_a_segment_count": segment_count,
        "layer_a_separator_count": separator_count,
        "layer_a_distinct_speakers": distinct_speakers,
        "layer_a_malformed_timestamp_ratio": malformed_ratio,
        "layer_a_duplicate_adjacent_segment_ratio": 0.0,
        "layer_a_speaker_switch_count": speaker_switches,
        "layer_a_speaker_switch_rate": speaker_switches / max(1, segment_count),
        "layer_a_unreasonable_speaker_churn": speaker_switches > max(5, segment_count),
        "layer_a_duration_covered_seconds": None,
        "layer_b_unicode_replacement_count": sample.count("\ufffd"),
        "layer_b_nonprintable_ratio": nonprintable,
        "layer_b_repeated_char_run_ratio": repeated_char_run_ratio(sample),
        "layer_b_total_tokens": len(tokens),
        "layer_b_primary_language": language,
        "layer_b_primary_language_confidence": language_confidence,
        "layer_b_language_mixed": language_mixed,
        "content_primary_category": category,
        "content_category_confidence": category_confidence,
    }


def build_candidate(
    row: dict[str, str],
    *,
    source_row_number: int,
    language_filters: tuple[str, ...],
    lang_detect_max_chars: int,
    lang_detect_languages: tuple[str, ...],
    language_min_confidence: float,
) -> Candidate | None:
    created_at = (row.get("created_at") or "").strip()
    month = parse_month(created_at)
    if month is None:
        return None

    text = row.get("transcription_text") or ""
    transcript_id = (row.get("id") or "").strip() or f"row_{source_row_number:06d}"
    file_name = (row.get("file_name") or "").strip()
    features = cheap_feature_proxy(text)
    matches_filter, features = language_filter_match(
        text,
        features,
        language_filters=language_filters,
        lang_detect_max_chars=lang_detect_max_chars,
        lang_detect_languages=lang_detect_languages,
        language_min_confidence=language_min_confidence,
    )
    if not matches_filter:
        return None

    total_tokens = int(features.get("layer_b_total_tokens") or 0)
    distinct_speakers = int(features.get("layer_a_distinct_speakers") or 0)
    segment_count = int(features.get("layer_a_segment_count") or 0)

    strata = {
        "content_category": str(features.get("content_primary_category") or "unknown"),
        "language": str(features.get("layer_b_primary_language") or "unknown"),
        "length_bin": length_bin(total_tokens),
        "dialogue_bin": dialogue_bin(distinct_speakers, segment_count),
        "quality_bin": quality_bin(features),
    }

    return Candidate(
        source_row_number=source_row_number,
        transcript_id=transcript_id,
        month=month,
        created_at=created_at,
        file_name=file_name,
        text=text,
        body_text=text,
        features=features,
        strata=strata,
    )


def read_candidates(
    input_csv: Path,
    *,
    max_rows: int | None,
    language_filters: tuple[str, ...],
    lang_detect_max_chars: int,
    lang_detect_languages: tuple[str, ...],
    language_min_confidence: float,
) -> list[Candidate]:
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2**31 - 1)
    candidates: list[Candidate] = []
    with input_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for source_row_number, row in enumerate(reader, start=1):
            if max_rows is not None and source_row_number > max_rows:
                break
            candidate = build_candidate(
                row,
                source_row_number=source_row_number,
                language_filters=language_filters,
                lang_detect_max_chars=lang_detect_max_chars,
                lang_detect_languages=lang_detect_languages,
                language_min_confidence=language_min_confidence,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def month_center(candidates: list[Candidate]) -> dict[str, float]:
    return {
        "tokens": median([float(c.features.get("layer_b_total_tokens") or 0) for c in candidates]),
        "segments": median(
            [float(c.features.get("layer_a_segment_count") or 0) for c in candidates]
        ),
        "speakers": median(
            [float(c.features.get("layer_a_distinct_speakers") or 0) for c in candidates]
        ),
        "malformed": median(
            [float(c.features.get("layer_a_malformed_timestamp_ratio") or 0) for c in candidates]
        ),
    }


def representative_distance(candidate: Candidate, center: dict[str, float]) -> float:
    tokens = float(candidate.features.get("layer_b_total_tokens") or 0)
    segments = float(candidate.features.get("layer_a_segment_count") or 0)
    speakers = float(candidate.features.get("layer_a_distinct_speakers") or 0)
    malformed = float(candidate.features.get("layer_a_malformed_timestamp_ratio") or 0)
    return (
        abs(math.log1p(tokens) - math.log1p(center["tokens"]))
        + abs(math.log1p(segments) - math.log1p(center["segments"]))
        + abs(speakers - center["speakers"]) * 0.4
        + abs(malformed - center["malformed"]) * 2.0
    )


def anomaly_score(candidate: Candidate, center: dict[str, float]) -> float:
    f = candidate.features
    tokens = float(f.get("layer_b_total_tokens") or 0)
    center_tokens = max(float(center.get("tokens") or 0), 1.0)
    length_outlier = abs(math.log1p(tokens) - math.log1p(center_tokens))
    return (
        float(f.get("layer_a_malformed_timestamp_ratio") or 0.0) * 5.0
        + float(f.get("layer_a_duplicate_adjacent_segment_ratio") or 0.0) * 2.0
        + float(f.get("layer_a_speaker_switch_rate") or 0.0) * 0.5
        + float(f.get("layer_b_repeated_char_run_ratio") or 0.0) * 3.0
        + float(f.get("layer_b_nonprintable_ratio") or 0.0) * 10.0
        + float(f.get("layer_b_unicode_replacement_count") or 0.0) * 0.5
        + (2.0 if bool(f.get("layer_a_unreasonable_speaker_churn")) else 0.0)
        + length_outlier * 0.2
    )


def group_key(candidate: Candidate) -> tuple[str, str, str, str]:
    return (
        candidate.strata["content_category"],
        candidate.strata["language"],
        candidate.strata["length_bin"],
        candidate.strata["dialogue_bin"],
    )


def choose_best(
    pool: list[Candidate],
    *,
    center: dict[str, float],
    rng: random.Random,
) -> Candidate:
    return min(pool, key=lambda c: (representative_distance(c, center), rng.random()))


def select_month_candidates(
    candidates: list[Candidate],
    *,
    samples_per_month: int,
    rng: random.Random,
) -> list[tuple[Candidate, str]]:
    if len(candidates) <= samples_per_month:
        return [(c, "all_available_for_sparse_month") for c in candidates]

    center = month_center(candidates)
    selected: list[tuple[Candidate, str]] = []
    selected_ids: set[str] = set()

    target = min(samples_per_month, len(candidates))
    anomaly_target = 1 if target >= 4 else 0
    representative_target = max(1, round(target * 0.65))
    contrastive_target = max(0, target - representative_target - anomaly_target)

    grouped: dict[tuple[str, str, str, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[group_key(candidate)].append(candidate)

    groups_by_size = sorted(grouped.values(), key=lambda group: len(group), reverse=True)
    for group in groups_by_size:
        if len(selected) >= representative_target:
            break
        available = [c for c in group if c.transcript_id not in selected_ids]
        if not available:
            continue
        choice = choose_best(available, center=center, rng=rng)
        selected.append((choice, "representative_dominant_stratum"))
        selected_ids.add(choice.transcript_id)

    while len(selected) < representative_target:
        available = [c for c in candidates if c.transcript_id not in selected_ids]
        if not available:
            break
        choice = choose_best(available, center=center, rng=rng)
        selected.append((choice, "representative_month_center"))
        selected_ids.add(choice.transcript_id)

    rare_groups = sorted(grouped.values(), key=lambda group: (len(group), rng.random()))
    for group in rare_groups:
        if contrastive_target <= 0:
            break
        available = [c for c in group if c.transcript_id not in selected_ids]
        if not available:
            continue
        choice = choose_best(available, center=center, rng=rng)
        selected.append((choice, "contrastive_rare_stratum"))
        selected_ids.add(choice.transcript_id)
        contrastive_target -= 1

    if anomaly_target:
        available = [c for c in candidates if c.transcript_id not in selected_ids]
        if available:
            choice = max(available, key=lambda c: (anomaly_score(c, center), rng.random()))
            selected.append((choice, "quality_sentinel"))
            selected_ids.add(choice.transcript_id)

    while len(selected) < target:
        available = [c for c in candidates if c.transcript_id not in selected_ids]
        if not available:
            break
        choice = choose_best(available, center=center, rng=rng)
        selected.append((choice, "balanced_fill"))
        selected_ids.add(choice.transcript_id)

    return selected


def make_excerpt(text: str, max_chars: int) -> tuple[str, bool]:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean, False

    window = max(500, max_chars // 3)
    start = clean[:window].rstrip()
    midpoint = len(clean) // 2
    middle_start = max(0, midpoint - window // 2)
    middle = clean[middle_start : middle_start + window].strip()
    end = clean[-window:].lstrip()
    excerpt = (
        "[BEGINNING EXCERPT]\n"
        f"{start}\n\n"
        "[MIDDLE EXCERPT]\n"
        f"{middle}\n\n"
        "[ENDING EXCERPT]\n"
        f"{end}"
    )
    return excerpt[: max_chars + 300], True


def select_candidates(
    candidates: list[Candidate],
    *,
    samples_per_month: int,
    seed: int,
    max_transcript_chars: int,
) -> list[SelectedCandidate]:
    rng = random.Random(seed)
    by_month: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_month[candidate.month].append(candidate)

    selected: list[SelectedCandidate] = []
    for month in sorted(by_month):
        chosen = select_month_candidates(
            by_month[month],
            samples_per_month=samples_per_month,
            rng=rng,
        )
        for candidate, reason in chosen:
            excerpt, limited = make_excerpt(candidate.text, max_transcript_chars)
            selected.append(
                SelectedCandidate(
                    candidate=candidate,
                    selection_reason=reason,
                    excerpt=excerpt,
                    excerpt_limited=limited,
                )
            )
    return selected


def prompt_text() -> str:
    return """# LLM-as-Judge Prompt: Transcription and Diarization Quality Over Time

You are evaluating diarized transcription quality over time. Use only the transcript evidence
provided below. Do not infer correctness from the topic, speaker identity, or outside knowledge.

Evaluate each transcript independently with a stable rubric. Some transcripts are excerpts from
long rows; when `excerpt_limited` is true, judge only the visible evidence and lower confidence
if the excerpt is insufficient.

Return valid JSON only. Do not wrap it in Markdown.

Use this schema:

{
  "rubric_version": "llm_judge_v1",
  "overall_notes": "brief methodological caveats",
  "per_transcript": [
    {
      "transcript_id": "string",
      "month": "YYYY-MM",
      "transcription_quality_score": 1,
      "diarization_quality_score": 1,
      "timestamp_structure_score": 1,
      "artifact_severity_score": 1,
      "judge_confidence": 1,
      "primary_failure_modes": ["short labels"],
      "evidence": "one concise sentence grounded in the provided transcript"
    }
  ],
  "monthly_summary": [
    {
      "month": "YYYY-MM",
      "n_evaluated": 0,
      "mean_transcription_quality_score": 0.0,
      "mean_diarization_quality_score": 0.0,
      "mean_timestamp_structure_score": 0.0,
      "mean_artifact_severity_score": 0.0,
      "confidence_weighted_takeaway": "brief"
    }
  ],
  "trend_assessment": {
    "direction": "improved | worsened | mixed | no_clear_change",
    "strongest_evidence": "brief",
    "main_limitations": ["brief"]
  }
}

Scoring rubrics:

`transcription_quality_score`:
1 = empty, incoherent, mostly unusable, or dominated by obvious recognition artifacts.
2 = partially understandable but many recognition errors, broken phrases, or repeated artifacts.
3 = usable gist with noticeable errors or awkward segmentation.
4 = mostly clear, coherent, and readable with minor errors.
5 = highly clear and natural, with very few visible transcription issues.

`diarization_quality_score`:
1 = speaker attribution absent or unusable for multi-speaker content.
2 = labels exist but are often inconsistent, fragmented, or implausible.
3 = usable speaker separation with visible mistakes or over-fragmentation.
4 = mostly consistent speaker turns and reasonable boundaries.
5 = clean, stable diarization with natural turns and no visible attribution problems.

`timestamp_structure_score`:
1 = timestamps absent, malformed, or structurally unusable.
2 = timestamps present but inconsistent or frequently malformed.
3 = timestamps mostly present with some structural issues.
4 = timestamps consistent and readable.
5 = timestamps consistent, granular, and well aligned with speaker turns.

`artifact_severity_score`:
1 = severe artifacts dominate the transcript.
2 = frequent artifacts materially affect interpretation.
3 = moderate artifacts are visible but the transcript remains usable.
4 = minor artifacts only.
5 = no meaningful visible artifacts.

`judge_confidence`:
1 = too little evidence or excerpt too limited.
2 = weak confidence.
3 = moderate confidence.
4 = high confidence.
5 = very high confidence.
"""


def selected_to_record(selected: SelectedCandidate) -> dict[str, Any]:
    c = selected.candidate
    f = c.features
    return {
        "transcript_id": c.transcript_id,
        "source_row_number": c.source_row_number,
        "month": c.month,
        "created_at": c.created_at,
        "selection_reason": selected.selection_reason,
        "excerpt_limited": selected.excerpt_limited,
        "file_name": c.file_name,
        "content_category": c.strata["content_category"],
        "language": c.strata["language"],
        "length_bin": c.strata["length_bin"],
        "dialogue_bin": c.strata["dialogue_bin"],
        "quality_bin": c.strata["quality_bin"],
        "total_tokens": f.get("layer_b_total_tokens"),
        "segment_count": f.get("layer_a_segment_count"),
        "distinct_speakers": f.get("layer_a_distinct_speakers"),
        "malformed_timestamp_ratio": f.get("layer_a_malformed_timestamp_ratio"),
        "speaker_switch_rate": f.get("layer_a_speaker_switch_rate"),
        "duration_covered_seconds": f.get("layer_a_duration_covered_seconds"),
        "language_confidence": f.get("layer_b_primary_language_confidence"),
        "content_category_confidence": f.get("content_category_confidence"),
    }


def render_packet(
    selected: list[SelectedCandidate],
    *,
    input_csv: Path,
    run_id: str | None,
    samples_per_month: int,
    seed: int,
    max_transcript_chars: int,
    language_filters: tuple[str, ...],
    language_min_confidence: float,
    excluded_sample_indexes: list[str],
) -> str:
    counts_by_month = Counter(item.candidate.month for item in selected)
    metadata = {
        "run_id": run_id or "",
        "source_file": str(input_csv),
        "rubric_version": "llm_judge_v1",
        "sampling_seed": seed,
        "target_samples_per_month": samples_per_month,
        "max_transcript_chars": max_transcript_chars,
        "language_filter": list(language_filters),
        "language_min_confidence": language_min_confidence,
        "excluded_sample_indexes": excluded_sample_indexes,
        "selected_transcripts": len(selected),
        "selected_by_month": dict(sorted(counts_by_month.items())),
    }

    lines: list[str] = [
        "# LLM Judge Packet",
        "",
        (
            "Copy this whole file into ChatGPT. The prompt is first, "
            "followed by the sampled transcripts."
        ),
        "",
        "## Packet Metadata",
        "",
        "```json",
        json.dumps(metadata, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Prompt",
        "",
        prompt_text().strip(),
        "",
        "## Transcript Samples",
        "",
    ]

    for index, item in enumerate(selected, start=1):
        c = item.candidate
        record = selected_to_record(item)
        lines.extend(
            [
                f"### Sample {index}: {c.transcript_id}",
                "",
                "```json",
                json.dumps(record, ensure_ascii=False, indent=2),
                "```",
                "",
                "```text",
                item.excerpt,
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_index(path: Path, selected: list[SelectedCandidate]) -> None:
    rows = [selected_to_record(item) for item in selected]
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, selected: list[SelectedCandidate]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for item in selected:
            record = selected_to_record(item)
            record["transcript_excerpt"] = item.excerpt
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic ChatGPT-ready LLM judge sample packet."
    )
    parser.add_argument(
        "--input",
        "-i",
        default=None,
        help="Input CSV path. Defaults to a single top-level repo CSV.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory or run root (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run folder name created under --output-dir.",
    )
    parser.add_argument(
        "--samples-per-month",
        type=int,
        default=8,
        help="Target number of transcripts selected per calendar month.",
    )
    parser.add_argument("--seed", type=int, default=20260506, help="Deterministic sample seed.")
    parser.add_argument(
        "--max-transcript-chars",
        type=int,
        default=4500,
        help="Maximum transcript characters included per selected sample.",
    )
    parser.add_argument(
        "--lang-detect-max-chars",
        type=int,
        default=4000,
        help="Accepted for compatibility; the sampler uses a fast script-based language proxy.",
    )
    parser.add_argument(
        "--lang-detect-languages",
        default=None,
        help="Comma-separated ISO 639-1 allow-list for exact language filters.",
    )
    parser.add_argument(
        "--language-filter",
        default=None,
        help=(
            "Comma-separated language filters. Use ru/russian for Lingua Russian "
            "detection, or proxy labels such as cyrillic_dominant."
        ),
    )
    parser.add_argument(
        "--russian-only",
        action="store_true",
        help="Shortcut for --language-filter ru.",
    )
    parser.add_argument(
        "--language-min-confidence",
        type=float,
        default=0.5,
        help="Minimum Lingua confidence for ISO language filters, default 0.5.",
    )
    parser.add_argument(
        "--exclude-sample-index",
        action="append",
        default=[],
        help="Prior llm_judge_sample_index.csv whose transcript_id values should be skipped.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional cap for smoke tests.",
    )
    return parser


def parse_lang_codes(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.samples_per_month < 1:
        raise SystemExit("--samples-per-month must be >= 1.")
    if args.max_transcript_chars < 1200:
        raise SystemExit("--max-transcript-chars must be >= 1200.")
    if args.lang_detect_max_chars < 1:
        raise SystemExit("--lang-detect-max-chars must be >= 1.")
    if not 0.0 <= args.language_min_confidence <= 1.0:
        raise SystemExit("--language-min-confidence must be in [0, 1].")

    input_csv = resolve_input_csv(args.input)
    output_dir = resolve_output_dir(args.output_dir, args.run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    language_filters = normalize_language_filters(
        args.language_filter,
        russian_only=args.russian_only,
    )
    lang_detect_languages = parse_iso_codes_csv(args.lang_detect_languages)
    excluded_transcript_ids = load_excluded_transcript_ids(args.exclude_sample_index)

    candidates = read_candidates(
        input_csv,
        max_rows=args.max_rows,
        language_filters=language_filters,
        lang_detect_max_chars=args.lang_detect_max_chars,
        lang_detect_languages=lang_detect_languages,
        language_min_confidence=args.language_min_confidence,
    )
    if excluded_transcript_ids:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.transcript_id not in excluded_transcript_ids
        ]
    candidates = refine_candidates_by_exact_language(
        candidates,
        language_filters=language_filters,
        samples_per_month=args.samples_per_month,
        seed=args.seed,
        lang_detect_max_chars=args.lang_detect_max_chars,
        lang_detect_languages=lang_detect_languages,
        language_min_confidence=args.language_min_confidence,
    )
    if not candidates:
        raise RuntimeError("No candidates with parseable created_at were found.")

    selected = select_candidates(
        candidates,
        samples_per_month=args.samples_per_month,
        seed=args.seed,
        max_transcript_chars=args.max_transcript_chars,
    )

    packet_path = output_dir / DEFAULT_PACKET_NAME
    prompt_path = output_dir / DEFAULT_PROMPT_NAME
    index_path = output_dir / DEFAULT_INDEX_NAME
    jsonl_path = output_dir / DEFAULT_JSONL_NAME

    packet_path.write_text(
        render_packet(
            selected,
            input_csv=input_csv,
            run_id=args.run_id,
            samples_per_month=args.samples_per_month,
            seed=args.seed,
            max_transcript_chars=args.max_transcript_chars,
            language_filters=language_filters,
            language_min_confidence=args.language_min_confidence,
            excluded_sample_indexes=args.exclude_sample_index,
        ),
        encoding="utf-8",
    )
    prompt_path.write_text(prompt_text().strip() + "\n", encoding="utf-8")
    write_index(index_path, selected)
    write_jsonl(jsonl_path, selected)

    summary = {
        "run_id": args.run_id or "",
        "output_dir": str(output_dir.resolve()),
        "candidates": len(candidates),
        "excluded_transcripts": len(excluded_transcript_ids),
        "language_filter": list(language_filters),
        "selected": len(selected),
        "months": sorted({candidate.month for candidate in candidates}),
        "packet": str(packet_path.resolve()),
        "prompt": str(prompt_path.resolve()),
        "index": str(index_path.resolve()),
        "jsonl": str(jsonl_path.resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

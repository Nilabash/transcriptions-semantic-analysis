"""Run manifest and metrics dictionary (reproducibility pack)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from transcriptions_analysis import __version__ as pkg_version
from transcriptions_analysis.metrics_layer_a import metric_definition_version as layer_a_version
from transcriptions_analysis.metrics_layer_b import metric_definition_version as layer_b_version


@dataclass
class RunManifest:
    run_id: str
    created_utc: str
    package_version: str
    metrics_definition_version: str
    input_snapshot: dict[str, Any]
    rows_read: int
    rows_dropped_null_ts: int
    created_at_min: str | None
    created_at_max: str | None
    dependency_lock_hash: str | None
    git_commit: str | None
    docker_image_digest: str | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["input"] = d.pop("input_snapshot")
        return d


def lockfile_hash(repo_root: Path) -> str | None:
    """SHA-256 hex of uv.lock if present, else requirements-lock.txt, else None."""
    import hashlib

    for name in ("uv.lock", "requirements-lock.txt"):
        p = repo_root / name
        if p.is_file():
            return hashlib.sha256(p.read_bytes()).hexdigest()
    return None


def write_manifest(path: Path, manifest: RunManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")


def combined_metrics_definition_version(include_layer_b: bool) -> str:
    """Version string for manifest; omits Layer B suffix when a run skips Layer B."""
    if not include_layer_b:
        return layer_a_version()
    return f"{layer_a_version()}+{layer_b_version()}"


def build_metrics_dictionary() -> dict[str, Any]:
    """Canonical Layer A + Layer B + content metric definitions for downstream plots and QA."""
    return {
        "schema_version": "1",
        "metrics": [
            {
                "name": "layer_a_segment_count",
                "layer": "A",
                "unit": "count",
                "description": (
                    "Count of diarized segments detected after separator/speaker parsing."
                ),
                "description_ru": (
                    "Число сегментов диаризации после разбора разделителей и меток спикеров."
                ),
            },
            {
                "name": "layer_a_separator_count",
                "layer": "A",
                "unit": "count",
                "description": "Lines matching long dashed separator pattern.",
                "description_ru": "Число строк, совпадающих с шаблоном длинного разделителя (штрихи).",
            },
            {
                "name": "layer_a_distinct_speakers",
                "layer": "A",
                "unit": "count",
                "description": "Distinct SPEAKER_* labels in the transcript.",
                "description_ru": "Число уникальных меток SPEAKER_* в тексте транскрипта.",
            },
            {
                "name": "layer_a_median_words_per_segment",
                "layer": "A",
                "unit": "words",
                "description": "Median word count per segment body.",
                "description_ru": "Медианное число слов в теле одного сегмента.",
            },
            {
                "name": "layer_a_median_chars_per_segment",
                "layer": "A",
                "unit": "chars",
                "description": "Median character count per segment body.",
                "description_ru": "Медианное число символов в теле одного сегмента.",
            },
            {
                "name": "layer_a_max_words_per_segment",
                "layer": "A",
                "unit": "words",
                "description": "Maximum words in any single segment body.",
                "description_ru": "Максимум слов в любом одном сегменте.",
            },
            {
                "name": "layer_a_malformed_timestamp_ratio",
                "layer": "A",
                "unit": "ratio",
                "description": (
                    "Share of segments with a speaker label but missing or malformed "
                    "bracketed [start - end] timestamp."
                ),
                "description_ru": (
                    "Доля сегментов с меткой спикера, у которых отсутствует или некорректна временная "
                    "метка в скобках [начало — конец]."
                ),
            },
            {
                "name": "layer_a_duplicate_adjacent_segment_ratio",
                "layer": "A",
                "unit": "ratio",
                "description": (
                    "Share of adjacent segment pairs with identical normalized body text."
                ),
                "description_ru": (
                    "Доля пар соседних сегментов с одинаковым нормализованным текстом тела."
                ),
            },
            {
                "name": "layer_a_speaker_switch_count",
                "layer": "A",
                "unit": "count",
                "description": "Number of times consecutive labeled segments change speaker.",
                "description_ru": (
                    "Число смен спикера между последовательными сегментами с метками."
                ),
            },
            {
                "name": "layer_a_speaker_switch_rate",
                "layer": "A",
                "unit": "ratio",
                "description": "Speaker switch count divided by segment count.",
                "description_ru": "Число смен спикера, делённое на число сегментов.",
            },
            {
                "name": "layer_a_unreasonable_speaker_churn",
                "layer": "A",
                "unit": "boolean",
                "description": "Heuristic flag for excessive speaker churn vs segment count.",
                "description_ru": (
                    "Эвристический признак избыточной «перемешанности» спикеров относительно "
                    "числа сегментов."
                ),
            },
            {
                "name": "layer_b_unicode_replacement_count",
                "layer": "B",
                "unit": "count",
                "description": "U+FFFD replacement characters in segment bodies.",
                "description_ru": "Число символов замены U+FFFD в текстах сегментов.",
            },
            {
                "name": "layer_b_control_char_count",
                "layer": "B",
                "unit": "count",
                "description": "Unicode category Cc control characters (excludes tab/newline).",
                "description_ru": (
                    "Число управляющих символов категории Cc (без табуляции и перевода строки)."
                ),
            },
            {
                "name": "layer_b_zero_width_count",
                "layer": "B",
                "unit": "count",
                "description": "Zero-width / BOM-like marks (e.g. U+200B, U+FEFF).",
                "description_ru": "Число меток нулевой ширины и подобных BOM (напр. U+200B, U+FEFF).",
            },
            {
                "name": "layer_b_nonprintable_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": (
                    "Share of characters that are not printable (excluding tab/newline)."
                ),
                "description_ru": (
                    "Доля непечатаемых символов (исключая табуляцию и перевод строки)."
                ),
            },
            {
                "name": "layer_b_repeated_char_run_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": (
                    "Share of alphanumeric characters in runs of identical char length ≥3."
                ),
                "description_ru": (
                    "Доля буквенно-цифровых символов, входящих в повторы одного символа длины ≥3."
                ),
            },
            {
                "name": "layer_b_total_tokens",
                "layer": "B",
                "unit": "count",
                "description": "Whitespace token count over concatenated segment bodies.",
                "description_ru": "Число токенов по пробелам по объединённым текстам сегментов.",
            },
            {
                "name": "layer_b_unique_tokens",
                "layer": "B",
                "unit": "count",
                "description": "Distinct whitespace tokens.",
                "description_ru": "Число уникальных токенов (по пробелам).",
            },
            {
                "name": "layer_b_type_token_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": "Unique tokens / total tokens (TTR).",
                "description_ru": "Отношение уникальных токенов к общему числу (TTR).",
            },
            {
                "name": "layer_b_hapax_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": "Share of token positions whose type appears once (hapax legomena).",
                "description_ru": (
                    "Доля позиций токенов, для которых тип встречается ровно один раз."
                ),
            },
            {
                "name": "layer_b_word_entropy_bits",
                "layer": "B",
                "unit": "bits",
                "description": "Shannon entropy of unigram token distribution (bits).",
                "description_ru": "Энтропия Шеннона распределения униграмм токенов (в битах).",
            },
            {
                "name": "layer_b_mean_word_length",
                "layer": "B",
                "unit": "chars",
                "description": "Mean token length (characters).",
                "description_ru": "Средняя длина токена в символах.",
            },
            {
                "name": "layer_b_median_word_length",
                "layer": "B",
                "unit": "chars",
                "description": "Median token length.",
                "description_ru": "Медианная длина токена.",
            },
            {
                "name": "layer_b_long_word_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": "Share of tokens with length ≥7.",
                "description_ru": "Доля токенов длины не менее 7 символов.",
            },
            {
                "name": "layer_b_short_utterance_ratio",
                "layer": "B",
                "unit": "ratio",
                "description": "Share of non-empty segment bodies with at most 2 words.",
                "description_ru": (
                    "Доля ненулевых сегментов, в которых не больше двух слов."
                ),
            },
            {
                "name": "layer_b_primary_language",
                "layer": "B",
                "unit": "categorical",
                "description": "ISO 639-1 from lingua on head/middle/end segment-body excerpt (allow-list).",
                "description_ru": (
                    "Основной язык ISO 639-1 по detector на выдержках начала/середины/конца текста "
                    "(allow-list)."
                ),
            },
            {
                "name": "layer_b_primary_language_confidence",
                "layer": "B",
                "unit": "ratio",
                "description": "Detector confidence for the primary language [0,1].",
                "description_ru": "Уверенность детектора основного языка в диапазоне [0, 1].",
            },
            {
                "name": "layer_b_language_mixed",
                "layer": "B",
                "unit": "boolean",
                "description": "Ambiguous top-2 languages or multiple segments in detect_multiple.",
                "description_ru": (
                    "Признак неоднозначности топ-2 языков или нескольких языковых сегментов."
                ),
            },
            {
                "name": "content_script_cyrillic_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "Cyrillic letters / (letters+digits) in segment bodies.",
                "description_ru": "Доля кириллических букв среди (букв+цифр) в сегментах.",
            },
            {
                "name": "content_script_latin_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "Latin letters / (letters+digits).",
                "description_ru": "Доля латинских букв среди (букв+цифр).",
            },
            {
                "name": "content_script_cjk_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "CJK / Hangul etc. / (letters+digits).",
                "description_ru": "Доля CJK/хангыля и смежных блоков среди (букв+цифр).",
            },
            {
                "name": "content_script_arabic_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "Arabic script / (letters+digits).",
                "description_ru": "Доля символов арабской письменности среди (букв+цифр).",
            },
            {
                "name": "content_script_digit_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "Decimal digits / (letters+digits).",
                "description_ru": "Доля десятичных цифр среди (букв+цифр).",
            },
            {
                "name": "content_script_other_ratio",
                "layer": "content",
                "unit": "ratio",
                "description": "Other letters / (letters+digits).",
                "description_ru": "Доля прочих букв среди (букв+цифр).",
            },
            {
                "name": "content_file_extension",
                "layer": "content",
                "unit": "categorical",
                "description": "Lowercased file extension from file_name.",
                "description_ru": "Расширение файла из file_name в нижнем регистре.",
            },
            {
                "name": "content_file_basename_token_count",
                "layer": "content",
                "unit": "count",
                "description": "Tokens in basename split on non-word characters.",
                "description_ru": (
                    "Число токенов в базовом имени файла (разбиение по несловным символам)."
                ),
            },
            {
                "name": "content_primary_category",
                "layer": "B",
                "unit": "categorical",
                "description": (
                    "Rule-based primary bucket from content_category: keyword gazetteers "
                    "(word-boundary matches on cleaned segment bodies) plus structural dialogue hints "
                    "from ParsedSegment.speaker; fallbacks short_note / quick_message / general_monologue."
                ),
                "description_ru": (
                    "Основная категория контента (правила): словари ключевых слов с границами слов "
                    "на очищенных телах сегментов плюс структурные признаки диалога по полю speaker "
                    "у ParsedSegment; при отсутствии совпадений — длина текста (short_note / "
                    "quick_message / general_monologue)."
                ),
            },
            {
                "name": "content_category_confidence",
                "layer": "B",
                "unit": "ratio",
                "description": (
                    "Dominance of winning label — best strength vs runner-up (or vs a fixed scale if alone); "
                    "strength is dictionary coverage for keyword buckets and a log-scaled structural score for dialogue; "
                    "not a calibrated probability."
                ),
                "description_ru": (
                    "Относительная «сила» выбранной основной метки — отношение лучшего сигнала "
                    "ко второму (или к шкале при отсутствии конкурента). Для словарных категорий сила — доля сработавших "
                    "ключей от размера словаря; для диалога — логически масштабированная структура спикеров. "
                    "Не вероятность класса и не softmax-уверенность."
                ),
            },
        ],
        "layer_a_code_version": layer_a_version(),
        "layer_b_code_version": layer_b_version(),
        "package_version": pkg_version,
    }


def write_metrics_dictionary(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_metrics_dictionary(), indent=2), encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def docker_digest_from_env() -> str | None:
    return os.environ.get("DOCKER_IMAGE_DIGEST")

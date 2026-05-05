"""Content category classification for diarized transcriptions.

Rule-based + structural classification using keywords (Russian-first) from parallel analysis script
and Layer A speaker/segment signals. Primary category + multi-label support.
Integrated as part of Layer B for time-series categorical shares.

Primary selection (v2): compares *strength* of evidence (dictionary coverage and dialogue structure),
with tie-break order — not a fixed lexical priority that ignores hit counts.

Follows Clean Architecture, deterministic, fully testable, with robust error handling.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from transcriptions_analysis.text_format import ParsedSegment

# Rules version for reproducibility / audit (bump when primary logic or KEYWORDS change materially).
CONTENT_CATEGORY_RULES_VERSION = "v2_strength_primary"

# Comprehensive Russian-focused keywords (ported + improved from scripts/analyze_raw_transcriptions.py)
KEYWORDS = {
    "business_work": [
        "клиент", "проект", "задач", "встреч", "совещан", "созвон", "договор", "сделк", "бизнес",
        "команд", "маркет", "продаж", "офис", "meeting", "project", "client", "task", "deal", "contract",
    ],
    "tech_it": [
        "код", "программ", "сервер", "баг", "ошибк", "api", "python", "javascript", "sql", "docker",
        "алгоритм", "данн", "deploy", "backend", "frontend", "debug", "github", "prompt", "llm", "model",
    ],
    "education": [
        "урок", "курс", "обуч", "школ", "универ", "экзам", "лекц", "lesson", "course", "learn", "study",
    ],
    "personal": [
        "семь", "мам", "пап", "друз", "отношен", "дом", "поездк", "покупк", "здоров", "жизн", "семья",
        "family", "friend", "home", "life",
    ],
    "media_creative": [
        "музык", "песн", "фильм", "видео", "подкаст", "youtube", "тикток", "story", "script", "music", "video",
    ],
    "finance_legal": [
        "деньг", "оплат", "счет", "налог", "кредит", "банк", "юрист", "суд", "долг", "budget", "payment", "tax",
    ],
    "support": [
        "инструкц", "настрой", "помог", "поддерж", "проблем", "решен", "issue", "support", "fix", "setup",
    ],
}

# When two categories have equal strength, prefer the earlier label here (product policy).
PRIMARY_TIE_BREAK_ORDER = [
    "tech_it",
    "business_work",
    "finance_legal",
    "education",
    "support",
    "media_creative",
    "personal",
    "dialogue_meeting",
]

# Legacy name kept for imports that referenced priority list; same order as tie-break for keywords.
PRIMARY_PRIORITY = [c for c in PRIMARY_TIE_BREAK_ORDER if c != "dialogue_meeting"]

# Dialogue may become primary only if lexical signal is thin (avoids "one API token" beating a real meeting).
DIALOGUE_PRIMARY_MAX_LEXICAL_COVERAGE = 0.12
DIALOGUE_PRIMARY_MAX_ANY_KEYWORD_HITS = 2

NOISE_PATTERNS = [
    re.compile(r"\b(ээ+|мм+|ух|ага|ммм)\b", re.IGNORECASE),
    re.compile(r"\[(noise|music|silence|applause|неразборчиво)\]", re.IGNORECASE),
]


def clean_text_for_classification(segments: list[ParsedSegment]) -> str:
    """Extract clean body text for classification, removing speaker labels and timestamps."""
    try:
        bodies = []
        for seg in segments:
            for line in seg.body_lines:
                # Remove common diarization noise
                cleaned = re.sub(r"\[?SPEAKER_\d+\]?", "", line, flags=re.IGNORECASE)
                cleaned = re.sub(r"\[\d{2}:\d{2}:\d{2}.*?\]", "", cleaned)
                cleaned = re.sub(r"\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}:?", "", cleaned)
                cleaned = cleaned.strip()
                if cleaned and len(cleaned) > 2:
                    bodies.append(cleaned)
        return " ".join(bodies)
    except Exception as e:
        raise RuntimeError(f"Failed to clean text for classification: {e}") from e


def _keyword_coverage(hits: int, category: str) -> float:
    """Share of dictionary stems that fired at least once for this category, capped at 1.0."""
    n = max(1, len(KEYWORDS[category]))
    return min(1.0, hits / n)


def _dialogue_structure_strength(distinct_speakers: int, speaker_switches: int) -> float:
    """Comparable 0..1 score from diarization structure (not lexical)."""
    raw = distinct_speakers + 2 * speaker_switches
    return min(1.0, math.log1p(raw) / math.log1p(28.0))


def _dialogue_may_win_primary(keyword_hits: dict[str, int]) -> bool:
    """Thin lexical evidence: allow structural dialogue as primary winner."""
    if not keyword_hits:
        return True
    max_cov = 0.0
    max_hits = 0
    for cat, h in keyword_hits.items():
        if cat not in KEYWORDS or h <= 0:
            continue
        max_hits = max(max_hits, h)
        max_cov = max(max_cov, _keyword_coverage(h, cat))
    return (
        max_cov < DIALOGUE_PRIMARY_MAX_LEXICAL_COVERAGE
        and max_hits <= DIALOGUE_PRIMARY_MAX_ANY_KEYWORD_HITS
    )


def _tie_break_index(category: str) -> int:
    try:
        return PRIMARY_TIE_BREAK_ORDER.index(category)
    except ValueError:
        return len(PRIMARY_TIE_BREAK_ORDER)


def _pick_primary_category(
    *,
    keyword_hits: dict[str, int],
    dialogue_in_scores: bool,
    dialogue_strength: float,
    matched_order: list[str],
) -> tuple[str, float, float | None]:
    """Return (primary, best_strength, runner_up_strength) using strength + tie order.

    ``matched_order`` preserves multi-label order for fallback if no keyword and no dialogue.
    """
    candidates: list[tuple[str, float]] = []
    for cat in KEYWORDS:
        h = keyword_hits.get(cat, 0)
        if h <= 0:
            continue
        candidates.append((cat, _keyword_coverage(h, cat)))

    allow_dialogue = dialogue_in_scores and _dialogue_may_win_primary(keyword_hits)
    if dialogue_in_scores and allow_dialogue:
        candidates.append(("dialogue_meeting", dialogue_strength))

    if not candidates:
        # Structural dialogue only (no keyword hits) — still in matched via dialogue branch
        if dialogue_in_scores:
            return "dialogue_meeting", dialogue_strength, None
        # Should not happen if caller ensured matched non-empty
        return matched_order[0], 0.0, None

    best_s = max(s for _, s in candidates)
    tied = [c for c, s in candidates if abs(s - best_s) < 1e-12]
    primary = min(tied, key=_tie_break_index)
    strengths = sorted((s for _, s in candidates), reverse=True)
    runner = strengths[1] if len(strengths) > 1 else None
    return primary, best_s, runner


def _dominance_confidence(best: float, runner: float | None) -> float:
    """Interpretable 0..1: relative margin when two signals exist, else absolute strength."""
    if runner is None or runner <= 1e-12:
        return min(1.0, best / 0.18)
    return min(1.0, best / max(runner, 1e-12))


def classify_content(segments: list[ParsedSegment], row_id: str = "unknown") -> dict[str, Any]:
    """Classify transcription content using keywords + structural signals.

    Returns:
        {
            "primary_category": str,
            "categories": list[str],
            "category_scores": dict (keyword hit counts + dialogue structural score),
            "is_dialogue": bool,
            "confidence": float — dominance / strength of winning label (not softmax probability),
            "distinct_speakers": int,
            "content_category_rules_version": str,
        }
    """
    try:
        if not segments:
            return {
                "primary_category": "empty",
                "categories": ["empty"],
                "category_scores": {},
                "is_dialogue": False,
                "confidence": 0.0,
                "content_category_rules_version": CONTENT_CATEGORY_RULES_VERSION,
            }

        full_text = clean_text_for_classification(segments)
        if not full_text.strip():
            return {
                "primary_category": "empty",
                "categories": ["empty"],
                "category_scores": {},
                "is_dialogue": False,
                "confidence": 0.0,
                "distinct_speakers": 0,
                "content_category_rules_version": CONTENT_CATEGORY_RULES_VERSION,
            }

        lower_text = full_text.lower()
        tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9'-]{3,}", lower_text)

        for pattern in NOISE_PATTERNS:
            lower_text = pattern.sub(" ", lower_text)
        lower_text = re.sub(r"\s+", " ", lower_text).strip()

        matched: list[str] = []
        scores: Counter[str] = Counter()
        keyword_hits: dict[str, int] = {}

        for category, words in KEYWORDS.items():
            hits = 0
            for w in words:
                if re.search(r"\b" + re.escape(w) + r"\b", lower_text):
                    hits += 1
            if hits > 0:
                matched.append(category)
                scores[category] = hits
                keyword_hits[category] = hits

        distinct_speakers = len({s.speaker for s in segments if s.speaker is not None})
        speaker_switches = sum(
            1
            for i in range(1, len(segments))
            if segments[i].speaker is not None
            and segments[i - 1].speaker is not None
            and segments[i].speaker != segments[i - 1].speaker
        )
        is_dialogue = distinct_speakers >= 2 or speaker_switches > 3

        dialogue_strength = _dialogue_structure_strength(distinct_speakers, speaker_switches)
        dialogue_in_scores = False
        if is_dialogue and "business_work" not in matched and "support" not in matched:
            matched.append("dialogue_meeting")
            struct_points = distinct_speakers + speaker_switches * 2
            scores["dialogue_meeting"] = struct_points
            dialogue_in_scores = True

        if not matched:
            word_count = len(tokens)
            if word_count < 15:
                primary = "short_note"
            elif word_count < 60:
                primary = "quick_message"
            else:
                primary = "general_monologue"
            matched = [primary]
            scores[primary] = 10
            confidence = min(1.0, 10.0 / max(5, word_count or 5) * 0.8)
            return {
                "primary_category": primary,
                "categories": matched,
                "category_scores": dict(scores),
                "is_dialogue": is_dialogue,
                "confidence": round(confidence, 3),
                "distinct_speakers": distinct_speakers,
                "content_category_rules_version": CONTENT_CATEGORY_RULES_VERSION,
            }

        primary, best_s, runner_s = _pick_primary_category(
            keyword_hits=keyword_hits,
            dialogue_in_scores=dialogue_in_scores,
            dialogue_strength=dialogue_strength,
            matched_order=list(matched),
        )
        confidence = round(_dominance_confidence(best_s, runner_s), 3)

        return {
            "primary_category": primary,
            "categories": matched,
            "category_scores": dict(scores),
            "is_dialogue": is_dialogue,
            "confidence": confidence,
            "distinct_speakers": distinct_speakers,
            "content_category_rules_version": CONTENT_CATEGORY_RULES_VERSION,
        }
    except Exception as e:
        context = f"row_id={row_id}, segments={len(segments)}, text_preview={full_text[:80] if 'full_text' in locals() else 'N/A'}"
        raise RuntimeError(f"Content classification failed [{context}]: {e}") from e

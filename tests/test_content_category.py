"""Tests for rule-based content category classification (v2 strength primary)."""

from __future__ import annotations

from transcriptions_analysis.content_category import (
    CONTENT_CATEGORY_RULES_VERSION,
    classify_content,
)
from transcriptions_analysis.text_format import ParsedSegment


def _seg(body: str, speaker: str = "SPEAKER_00") -> ParsedSegment:
    return ParsedSegment(
        speaker=speaker,
        body_lines=[body],
        has_timestamp=True,
        timestamp_line_malformed=False,
    )


def test_primary_prefers_higher_dictionary_coverage_not_fixed_tech_priority() -> None:
    """One IT stem vs several business stems: business should win (argmax coverage)."""
    text = (
        "клиент просит договор по проекту и встречу в офисе для продаж "
        "команда маркетинга созвон по сделке meeting project client task deal contract "
        "код ревью"
    )
    segs = [_seg(text, "SPEAKER_00")]
    out = classify_content(segs)
    assert out["primary_category"] == "business_work"
    assert "tech_it" in out["categories"]
    assert out["content_category_rules_version"] == CONTENT_CATEGORY_RULES_VERSION


def test_single_category_one_hit_still_primary() -> None:
    out = classify_content([_seg("обсудили python и docker для сервера", "SPEAKER_00")])
    assert out["primary_category"] == "tech_it"


def test_dialogue_wins_when_lexical_signal_is_thin() -> None:
    """Many speaker turns but almost no keywords -> dialogue_meeting can be primary."""
    bodies = [
        "ну да согласен",
        "ок давай так",
        "хорошо подумаю",
        "ага",
        "спасибо",
    ]
    segs = [
        _seg(bodies[0], "SPEAKER_00"),
        _seg(bodies[1], "SPEAKER_01"),
        _seg(bodies[2], "SPEAKER_00"),
        _seg(bodies[3], "SPEAKER_01"),
        _seg(bodies[4], "SPEAKER_00"),
    ]
    out = classify_content(segs)
    assert out["is_dialogue"] is True
    assert out["primary_category"] == "dialogue_meeting"
    assert "dialogue_meeting" in out["categories"]


def test_strong_lexical_blocks_dialogue_primary() -> None:
    """Enough keyword coverage: dialogue stays secondary even if structural dialogue is true."""
    text = (
        "клиент договор проект встреча офис продажи маркетинг команда созвон сделка бизнес "
        "ещё клиент проект задача"
    )
    segs = []
    for i, line in enumerate(text.split()):
        sp = f"SPEAKER_{i % 2:02d}"
        segs.append(_seg(line, sp))
    out = classify_content(segs)
    assert out["is_dialogue"] is True
    assert out["primary_category"] == "business_work"


def test_fallback_by_length_when_no_keywords() -> None:
    short = " ".join(["word"] * 5)
    out = classify_content([_seg(short)])
    assert out["primary_category"] == "short_note"

    mid = " ".join(["wordish"] * 20)
    out2 = classify_content([_seg(mid)])
    assert out2["primary_category"] == "quick_message"

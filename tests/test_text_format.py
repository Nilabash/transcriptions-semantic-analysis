from transcriptions_analysis.text_format import (
    count_separator_lines,
    extract_timestamp_range_seconds,
    is_wellformed_timestamp_line,
    parse_segments,
    split_separator_lines,
)


def test_bracket_ts_detection():
    assert is_wellformed_timestamp_line("[00:00:00 - 00:00:01]") is True
    assert is_wellformed_timestamp_line("no ts here") is False


def test_inline_ts_detection():
    assert is_wellformed_timestamp_line("00:00:08 - 00:00:10: hello") is True
    assert is_wellformed_timestamp_line("00:00:08 — 00:00:10: ") is True
    assert is_wellformed_timestamp_line("not 00:00:01 - 00:00:02: a timestamp line") is False


def test_extract_timestamp_range_seconds_variants():
    assert extract_timestamp_range_seconds("[00:00:05 - 00:00:09]") == (5.0, 9.0)
    assert extract_timestamp_range_seconds("00:10:00 - 00:10:30: hello") == (600.0, 630.0)
    assert extract_timestamp_range_seconds("no timestamp here") is None


def test_bracket_speaker_header_and_inline_turns():
    text = """[SPEAKER_01]
00:00:08 - 00:00:10: First line.
00:00:12 - 00:00:14: Second line.

[SPEAKER_00]
00:00:16 - 00:00:20: Reply."""
    segs = parse_segments(text)
    assert len(segs) == 3
    sp01 = [s for s in segs if s.speaker == "SPEAKER_01"]
    assert len(sp01) == 2
    bodies = ["\n".join(s.body_lines) for s in sp01]
    assert any("First line" in b for b in bodies)
    assert any("Second line" in b for b in bodies)
    assert sp01[0].timestamp_start_s == 8.0
    assert sp01[0].timestamp_end_s == 10.0


def test_split_separators():
    text = "a\n" + ("-" * 30) + "\nb"
    parts = split_separator_lines(text)
    assert len(parts) == 2


def test_parse_two_speakers_with_separator():
    text = """--------------------------------------------------------------------------------
SPEAKER_00
[00:00:00 - 00:00:02]
Hello
--------------------------------------------------------------------------------
SPEAKER_01
[00:00:02 - 00:00:05]
World"""
    segs = parse_segments(text)
    assert len(segs) >= 2
    speakers = [s.speaker for s in segs if s.speaker]
    assert "SPEAKER_00" in speakers and "SPEAKER_01" in speakers


def test_count_separator_lines():
    blob = "\n".join(["-" * 25, "x", "-" * 25])
    assert count_separator_lines(blob) == 2

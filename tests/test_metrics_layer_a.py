from transcriptions_analysis.metrics_layer_a import compute_layer_a_for_text


def test_empty_text():
    out = compute_layer_a_for_text("")
    assert out["layer_a_segment_count"] == 0


def test_malformed_timestamp_flags():
    text = """SPEAKER_00
broken
still talking"""
    out = compute_layer_a_for_text(text)
    assert out["layer_a_malformed_timestamp_ratio"] > 0


def test_layer_a_counts_bracketed_speaker_inline_ts():
    text = """[SPEAKER_00]
00:00:00 - 00:00:02: Одна фраза.
00:00:03 - 00:00:05: Другая фраза."""
    out = compute_layer_a_for_text(text)
    assert out["layer_a_segment_count"] == 2
    assert out["layer_a_distinct_speakers"] == 1
    assert out["layer_a_separator_count"] == 0


def test_wellformed_segment_counts():
    text = """--------------------------------------------------------------------------------
SPEAKER_00
[00:00:00 - 00:00:02]
Hi
--------------------------------------------------------------------------------
SPEAKER_00
[00:00:02 - 00:00:04]
Again"""
    out = compute_layer_a_for_text(text)
    assert out["layer_a_segment_count"] >= 2
    assert out["layer_a_distinct_speakers"] == 1


def test_duration_metrics_from_inline_ranges():
    text = """[SPEAKER_00]
00:00:00 - 00:00:02: One.
00:00:03 - 00:00:05: Two."""
    out = compute_layer_a_for_text(text)
    assert out["layer_a_duration_covered_seconds"] == 4.0
    assert out["layer_a_duration_span_seconds"] == 5.0
    assert out["layer_a_duration_coverage_ratio"] == 0.8
    assert out["layer_a_segments_with_duration_ratio"] == 1.0


def test_duration_metrics_skip_invalid_ranges():
    text = """SPEAKER_00
[00:00:10 - 00:00:08]
Bad range
--------------------------------------------------------------------------------
SPEAKER_01
[00:00:12 - 00:00:15]
Good range"""
    out = compute_layer_a_for_text(text)
    assert out["layer_a_duration_covered_seconds"] == 3.0
    assert out["layer_a_duration_span_seconds"] == 3.0
    assert out["layer_a_segments_with_duration_ratio"] == 0.5

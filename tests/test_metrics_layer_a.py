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

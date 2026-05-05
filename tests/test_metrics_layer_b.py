"""Tests for Layer B per-row metrics."""

from transcriptions_analysis.metrics_layer_b import compute_layer_b_for_row


def test_empty_transcription():
    out = compute_layer_b_for_row("", "x.mp3")
    assert out["layer_b_total_tokens"] == 0
    assert out["content_file_extension"] == "mp3"


def test_diarized_fixture():
    text = """--------------------------------------------------------------------------------
SPEAKER_00
[00:00:00 - 00:00:02]
Hello world this is a test
--------------------------------------------------------------------------------
SPEAKER_01
[00:00:02 - 00:00:05]
Second line here"""
    out = compute_layer_b_for_row(text, "rec.mp3", max_chars=500, iso_codes=("en",))
    assert "layer_b_total_tokens" in out
    assert out["layer_b_total_tokens"] >= 6
    assert "content_script_latin_ratio" in out
    assert out["content_file_extension"] == "mp3"

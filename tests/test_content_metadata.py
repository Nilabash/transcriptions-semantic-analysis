"""Tests for file_name metadata derivation."""

from transcriptions_analysis.content_metadata import derive_file_metadata


def test_plain_filename():
    m = derive_file_metadata("Meeting_notes.mp3")
    assert m["content_file_extension"] == "mp3"
    assert m["content_file_basename_token_count"] >= 1
    assert m["content_file_path_depth"] == 0


def test_nested_path():
    m = derive_file_metadata("folder/sub/voice memo.wav")
    assert m["content_file_path_depth"] >= 1
    assert m["content_file_extension"] == "wav"


def test_empty():
    m = derive_file_metadata(None)
    assert m["content_file_extension"] == ""
    assert m["content_file_basename_token_count"] == 0

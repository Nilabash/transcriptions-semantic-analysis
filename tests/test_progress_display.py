from transcriptions_analysis.progress_display import format_duration, progress_target_rows


def test_progress_target_rows():
    assert progress_target_rows(100, 50) == 50
    assert progress_target_rows(100, None) == 100
    assert progress_target_rows(None, 10) == 10
    assert progress_target_rows(None, None) is None


def test_format_duration():
    assert format_duration(45) == "45s"
    assert format_duration(90) == "1m30s"
    assert "h" in format_duration(3700)

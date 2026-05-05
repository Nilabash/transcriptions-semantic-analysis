"""Integration tests requiring Polars (run in Docker if host CPU lacks AVX2)."""

from pathlib import Path

import pytest

from transcriptions_analysis.ingest import (
    EXPECTED_COLUMNS,
    count_csv_logical_rows_first_column,
    normalize_bom_columns,
    read_csv_batches,
)


@pytest.fixture
def sample_csv() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_multiline.csv"


def test_read_multiline_csv(sample_csv: Path):
    parts = list(read_csv_batches(sample_csv, batch_size=10, max_rows=10))
    assert len(parts) == 1
    df = normalize_bom_columns(parts[0])
    for col in EXPECTED_COLUMNS:
        assert col in df.columns
    assert len(df) == 2
    assert "\n" in df["transcription_text"][0]


def test_count_first_column_matches_wide_read(sample_csv: Path):
    n = count_csv_logical_rows_first_column(sample_csv, batch_size=1)
    full = sum(len(b) for b in read_csv_batches(sample_csv))
    assert n == full == 2

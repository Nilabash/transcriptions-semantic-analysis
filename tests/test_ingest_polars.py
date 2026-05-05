"""Integration tests requiring Polars (run in Docker if host CPU lacks AVX2)."""

import shutil
import uuid
from pathlib import Path

import pytest

from transcriptions_analysis.ingest import (
    EXPECTED_COLUMNS,
    REQUIRED_COLUMNS,
    count_csv_logical_rows_first_column,
    missing_required_columns,
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


def test_read_minimal_contract_csv():
    tmp_dir = Path("tests") / "_tmp" / f"minimal-contract-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        csv_path = tmp_dir / "minimal.csv"
        csv_path.write_text(
            'created_at,transcription_text\n'
            '"2024-01-15 10:00:00","SPEAKER_00\n[00:00:00 - 00:00:02]\nHello"\n',
            encoding="utf-8",
        )

        parts = list(read_csv_batches(csv_path, batch_size=10, max_rows=10))
        assert len(parts) == 1
        df = normalize_bom_columns(parts[0])
        for col in REQUIRED_COLUMNS:
            assert col in df.columns
        assert missing_required_columns(df.columns) == []
        assert "file_name" not in df.columns
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

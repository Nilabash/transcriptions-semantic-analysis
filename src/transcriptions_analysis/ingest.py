"""RFC 4180–aware CSV ingest with UTF-8 BOM handling and batched reads."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import polars as pl

EXPECTED_COLUMNS = (
    "id",
    "telegram_user_internal_id",
    "telegram_user_id",
    "created_at",
    "file_name",
    "transcription_text",
)

REQUIRED_COLUMNS = (
    "created_at",
    "transcription_text",
)

# Default Polars ``collect_batches(chunk_size=…)`` for wide CSV rows (large transcription_text).
# Smaller chunks lower peak RAM during read_phase + Layer A/B; raises part file count slightly.
DEFAULT_CSV_BATCH_ROWS = 4_096


def normalize_bom_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Rename columns whose names carry a UTF-8 BOM prefix (e.g. \\ufeffid)."""
    renames = {c: c.lstrip("\ufeff") for c in df.columns if c != c.lstrip("\ufeff")}
    return df.rename(renames) if renames else df


def _schema_overrides() -> dict[str, pl.DataType]:
    return {
        "id": pl.Utf8,
        "telegram_user_internal_id": pl.Utf8,
        "telegram_user_id": pl.Utf8,
        "created_at": pl.Utf8,
        "file_name": pl.Utf8,
        "transcription_text": pl.Utf8,
    }


def missing_required_columns(columns: list[str] | tuple[str, ...]) -> list[str]:
    """Return core contract columns that must exist for the pipeline to run."""
    return [c for c in REQUIRED_COLUMNS if c not in columns]


def count_csv_logical_rows_first_column(
    path: str | Path,
    batch_size: int = DEFAULT_CSV_BATCH_ROWS,
) -> int:
    """
    Count logical CSV rows once by streaming **column index 0** only.

    Stream whichever column is physically first so we skip parsing mega multiline
    ``transcription_text`` fields — much cheaper than two full wide reads while
    still respecting quoted multiline fields.
    """
    path = Path(path)
    if not path.is_file():
        msg = f"Input CSV not found: {path}"
        raise FileNotFoundError(msg)

    lf0 = pl.scan_csv(
        str(path),
        encoding="utf8",
        try_parse_dates=False,
        low_memory=True,
    )
    names = lf0.collect_schema().names()
    if not names:
        return 0
    first = names[0]
    lf = lf0.select(pl.col(first))
    total = 0
    for batch in lf.collect_batches(chunk_size=batch_size):
        df = normalize_bom_columns(batch)
        total += len(df)
    return total


def read_csv_batches(
    path: str | Path,
    batch_size: int = DEFAULT_CSV_BATCH_ROWS,
    max_rows: int | None = None,
) -> Iterator[pl.DataFrame]:
    """
    Yield DataFrame chunks from a multiline-safe CSV reader.

    Uses ``scan_csv`` + streaming batch collection so quoted multiline fields stay intact.
    """
    path = Path(path)
    if not path.is_file():
        msg = f"Input CSV not found: {path}"
        raise FileNotFoundError(msg)

    lf = pl.scan_csv(
        str(path),
        encoding="utf8",
        schema_overrides=_schema_overrides(),
        try_parse_dates=False,
        low_memory=True,
    )
    seen = 0
    for batch in lf.collect_batches(chunk_size=batch_size):
        df = normalize_bom_columns(batch)
        if max_rows is not None:
            remain = max_rows - seen
            if remain <= 0:
                break
            if len(df) > remain:
                df = df.head(remain)
        seen += len(df)
        yield df
        if max_rows is not None and seen >= max_rows:
            break


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    """
    Size plus SHA-256 of the first 8 MiB (fast on huge exports).

    Full-file hashing is intentionally avoided for multi-GB CSVs.
    """
    import hashlib

    p = Path(path)
    st = p.stat()
    h: str | None
    try:
        sha = hashlib.sha256()
        with p.open("rb") as f:
            sha.update(f.read(8 * 1024 * 1024))
        h = sha.hexdigest()
    except OSError:
        h = None
    return {
        "path": str(p.resolve()),
        "size_bytes": st.st_size,
        "sha256_first_8mib": h,
    }

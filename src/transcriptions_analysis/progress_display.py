"""Console progress helpers (stderr, TTY-aware)."""

from __future__ import annotations

import sys


def stderr_progress_enabled(force_on: bool, force_off: bool) -> bool:
    if force_off:
        return False
    if force_on:
        return True
    return sys.stderr.isatty()


def progress_target_rows(total_rows: int | None, max_rows: int | None) -> int | None:
    """
    Rows to use for ETA: min(total_rows, max_rows) when both set; otherwise whichever is set.
    """
    if total_rows is not None and max_rows is not None:
        return min(total_rows, max_rows)
    if total_rows is not None:
        return total_rows
    if max_rows is not None:
        return max_rows
    return None


def format_duration(seconds: float) -> str:
    """Short human duration (e.g. 90s → 1m30s)."""
    if seconds < 0 or seconds != seconds:
        return "?"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def emit_batch_progress(
    *,
    phase: str,
    batch_number: int,
    rows_delta: int,
    rows_total: int,
    batch_wall_s: float,
    elapsed_s: float,
    target_rows: int | None,
    file_mb: float | None = None,
) -> None:
    """
    One stderr line per batch.

    ETA uses cumulative average throughput when target_rows is set.
    """
    prefix = "[ta-batch]"
    parts = [
        f"{prefix} {phase}",
        f"batch={batch_number}",
        f"+{rows_delta}",
        f"total_rows={rows_total}",
    ]
    if file_mb is not None:
        parts.append(f"file_mb~{file_mb:.1f}")

    rate = rows_total / elapsed_s if elapsed_s > 0 else 0.0
    parts.append(f"avg~{rate:.0f}_rows/s")

    parts.append(f"batch_wall={format_duration(batch_wall_s)}")
    parts.append(f"elapsed={format_duration(elapsed_s)}")

    if target_rows is not None and rows_total < target_rows and rate > 0:
        remaining = target_rows - rows_total
        eta_s = remaining / rate
        parts.append(f"ETA~{format_duration(eta_s)}")
        parts.append(f"left~{remaining}")

    print(" ".join(parts), file=sys.stderr, flush=True)


def emit_phase_line(message: str) -> None:
    print(f"[ta-batch] {message}", file=sys.stderr, flush=True)

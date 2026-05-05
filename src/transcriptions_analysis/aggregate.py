"""Time-bucket aggregates (median, IQR, N)."""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl

from transcriptions_analysis.metrics_layer_b import NUMERIC_LAYER_B


def _quantile(col: str, q: float, alias: str) -> pl.Expr:
    return pl.col(col).quantile(q, interpolation="linear").alias(alias)


def parse_created_at_column(df: pl.DataFrame, col: str = "created_at") -> pl.DataFrame:
    """Parse naive datetime string; null on failure (no row drop at this step)."""
    return df.with_columns(
        pl.col(col)
        .str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False)
        .alias("created_at_parsed")
    )


def with_time_bucket_columns(
    df: pl.DataFrame,
    ts_col: str = "created_at_parsed",
) -> pl.DataFrame:
    """
    Add day / ISO week / month start columns.

    Assumes naive timestamps (timezone policy TBD — see manifest notes).
    """
    ts = pl.col(ts_col)
    return df.with_columns(
        ts.dt.truncate("1d").alias("bucket_day"),
        ts.dt.strftime("%G-W%V").alias("bucket_iso_week"),
        ts.dt.truncate("1mo").alias("bucket_month"),
    )


NUMERIC_LAYER_A = (
    "layer_a_segment_count",
    "layer_a_separator_count",
    "layer_a_distinct_speakers",
    "layer_a_median_words_per_segment",
    "layer_a_median_chars_per_segment",
    "layer_a_max_words_per_segment",
    "layer_a_malformed_timestamp_ratio",
    "layer_a_duplicate_adjacent_segment_ratio",
    "layer_a_speaker_switch_count",
    "layer_a_speaker_switch_rate",
    "layer_a_unreasonable_speaker_churn",
)

NUMERIC_LAYER_AB: tuple[str, ...] = NUMERIC_LAYER_A + NUMERIC_LAYER_B

# Omit from temporal rollups — usually constant/uninformative for typical Telegram file_name values.
TIME_AGG_SKIP_METRICS: frozenset[str] = frozenset({"content_file_path_depth"})


def aggregate_bucket(
    df: pl.DataFrame,
    bucket_col: str,
    metric_cols: Iterable[str] = NUMERIC_LAYER_A,
) -> pl.DataFrame:
    """Per-bucket median, Q1, Q3, and row count N."""
    cols = list(metric_cols)
    aggs: list[pl.Expr] = [pl.len().alias("n_rows")]
    for c in cols:
        if c not in df.columns:
            continue
        aggs.extend(
            [
                pl.col(c).median().alias(f"{c}_median"),
                _quantile(c, 0.25, f"{c}_q1"),
                _quantile(c, 0.75, f"{c}_q3"),
            ]
        )
    return df.group_by(bucket_col).agg(aggs).sort(bucket_col)


def aggregate_categorical_share(
    df: pl.DataFrame,
    bucket_col: str,
    category_col: str,
    *,
    null_label: str = "(null)",
) -> pl.DataFrame:
    """
    Per time bucket, count rows per category and ``share = n_cat / n_bucket``.

    Null or empty string categories are mapped to ``null_label``.
    """
    d = df.with_columns(
        pl.when(pl.col(category_col).is_null() | (pl.col(category_col).cast(pl.Utf8) == ""))
        .then(pl.lit(null_label))
        .otherwise(pl.col(category_col).cast(pl.Utf8))
        .alias("_category")
    )
    counts = d.group_by([bucket_col, "_category"]).agg(pl.len().alias("n_in_category"))
    totals = counts.group_by(bucket_col).agg(pl.col("n_in_category").sum().alias("n_in_bucket"))
    out = counts.join(totals, on=bucket_col, how="left")
    out = out.with_columns(
        (pl.col("n_in_category") / pl.col("n_in_bucket").cast(pl.Float64)).alias("share")
    )
    return out.sort([bucket_col, "_category"])


def aggregate_user_month(
    df: pl.DataFrame,
    user_col: str = "telegram_user_internal_id",
    bucket_col: str = "bucket_month",
    metric_cols: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Per-user calendar month: median, Q1, Q3, N for numeric metric columns."""
    cols = list(metric_cols) if metric_cols is not None else list(NUMERIC_LAYER_AB)
    aggs: list[pl.Expr] = [pl.len().alias("n_rows")]
    for c in cols:
        if c not in df.columns:
            continue
        aggs.extend(
            [
                pl.col(c).median().alias(f"{c}_median"),
                _quantile(c, 0.25, f"{c}_q1"),
                _quantile(c, 0.75, f"{c}_q3"),
            ]
        )
    return df.group_by([user_col, bucket_col]).agg(aggs).sort([user_col, bucket_col])

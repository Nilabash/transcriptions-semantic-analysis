"""Tests for Layer B aggregates (categorical share, user-month)."""

import polars as pl

from transcriptions_analysis.aggregate import (
    aggregate_categorical_share,
    aggregate_user_month,
    parse_created_at_column,
    with_time_bucket_columns,
)


def test_categorical_share():
    df = pl.DataFrame(
        {
            "bucket_day": ["2024-01-01", "2024-01-01", "2024-01-02"],
            "layer_b_primary_language": ["en", "en", ""],
        }
    )
    out = aggregate_categorical_share(df, "bucket_day", "layer_b_primary_language")
    assert "share" in out.columns
    assert out.filter(pl.col("bucket_day") == "2024-01-01")["n_in_bucket"][0] == 2


def test_user_month_numeric():
    df = pl.DataFrame(
        {
            "telegram_user_internal_id": ["u1", "u1"],
            "created_at": ["2024-01-10 12:00:00", "2024-01-15 12:00:00"],
            "layer_a_segment_count": [2, 3],
            "layer_b_total_tokens": [10, 20],
        }
    )
    df = parse_created_at_column(df)
    df = with_time_bucket_columns(df)
    agg = aggregate_user_month(
        df,
        metric_cols=("layer_a_segment_count", "layer_b_total_tokens"),
    )
    assert len(agg) == 1
    assert "layer_b_total_tokens_median" in agg.columns
    assert agg["n_rows"][0] == 2

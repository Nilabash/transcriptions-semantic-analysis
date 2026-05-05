import polars as pl

from transcriptions_analysis.aggregate import (
    aggregate_bucket,
    parse_created_at_column,
    with_time_bucket_columns,
)


def test_time_buckets_and_aggregate():
    df = pl.DataFrame(
        {
            "created_at": ["2024-01-10 12:00:00", "2024-01-10 15:00:00"],
            "layer_a_segment_count": [2, 4],
            "layer_a_malformed_timestamp_ratio": [0.0, 0.1],
        }
    )
    df = parse_created_at_column(df)
    df = with_time_bucket_columns(df)
    agg = aggregate_bucket(df, "bucket_day")
    assert len(agg) == 1
    assert "layer_a_segment_count_median" in agg.columns
    assert agg["n_rows"][0] == 2

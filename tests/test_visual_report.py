"""Visual export helpers (PNG + long CSV shaping)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl

from transcriptions_analysis.artifacts import write_metrics_dictionary
from transcriptions_analysis.visual_report import (
    export_visual_bundle,
    list_metric_names_from_aggregate,
    load_metric_descriptions_ru,
    time_aggregate_to_long,
)


def test_time_aggregate_to_long_shape() -> None:
    agg = pl.DataFrame(
        {
            "bucket_month": [datetime(2024, 1, 1), datetime(2024, 2, 1)],
            "n_rows": [10, 20],
            "layer_a_segment_count_median": [5.0, 6.0],
            "layer_a_segment_count_q1": [4.0, 5.0],
            "layer_a_segment_count_q3": [6.0, 7.0],
        }
    )
    long = time_aggregate_to_long(agg, "bucket_month")
    assert long.height == 2
    assert set(long.columns) == {
        "time_bucket",
        "metric",
        "median",
        "q1",
        "q3",
        "n_rows_per_bucket",
    }
    assert long["metric"].unique().to_list() == ["layer_a_segment_count"]


def test_load_metric_descriptions_ru_reads_dictionary(tmp_path: Path) -> None:
    """``description_ru`` entries resolve from written metrics_dictionary.json."""
    p = tmp_path / "metrics_dictionary.json"
    write_metrics_dictionary(p)
    m = load_metric_descriptions_ru(p)
    assert "layer_a_segment_count" in m
    assert "диаризации" in m["layer_a_segment_count"]


def test_list_metric_names_derived() -> None:
    df = pl.DataFrame({"x_median": [1.0], "x_q1": [0.0], "x_q3": [2.0], "n_rows": [3]})
    assert list_metric_names_from_aggregate(df) == ["x"]


def test_export_visual_bundle_smoke(tmp_path: Path) -> None:
    run = tmp_path / "run1"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(
        '{"run_id":"t","rows_read":2,"created_at_min":"2024-01-01",'
        '"created_at_max":"2024-02-01","metrics_definition_version":"a+b"}',
        encoding="utf-8",
    )

    bm = datetime(2024, 1, 15)
    agg_m = pl.DataFrame(
        {
            "bucket_month": [bm],
            "n_rows": [42],
            "layer_a_segment_count_median": [12.0],
            "layer_a_segment_count_q1": [11.0],
            "layer_a_segment_count_q3": [13.0],
        }
    )
    agg_w = pl.DataFrame(
        {
            "bucket_iso_week": [f"2024-W{i:02d}" for i in range(19, 23)],
            "n_rows": [31, 29, 32, 30],
            "layer_a_segment_count_median": [6.5, 6.55, 6.6, 6.72],
            "layer_a_segment_count_q1": [5.12, 5.3, 5.4, 5.52],
            "layer_a_segment_count_q3": [7.92, 7.88, 7.9, 7.95],
        }
    )

    iso = (
        datetime(2024, 5, 1),
        datetime(2024, 5, 8),
        datetime(2024, 5, 15),
        datetime(2024, 5, 22),
        datetime(2024, 5, 29),
    )
    agg_d = pl.DataFrame(
        {
            "bucket_day": iso,
            "n_rows": [8, 9, 11, 7, 8],
            "layer_a_segment_count_median": [4.0, 4.1, 4.2, 4.25, 4.5],
            "layer_a_segment_count_q1": [3.0, 3.1, 3.18, 3.22, 3.44],
            "layer_a_segment_count_q3": [5.5, 5.4, 5.62, 5.71, 5.8],
        }
    )

    agg_m.write_parquet(run / "time_agg_month.parquet")
    agg_w.write_parquet(run / "time_agg_iso_week.parquet")
    agg_d.write_parquet(run / "time_agg_day.parquet")
    parts = run / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "created_at_parsed": [
                datetime(2024, 5, 1, 10, 0, 0),
                datetime(2024, 5, 1, 12, 0, 0),
                datetime(2024, 5, 8, 9, 0, 0),
            ],
            "layer_a_duration_covered_seconds": [120.0, 180.0, 300.0],
        }
    ).write_parquet(parts / "part_00000.parquet")

    write_metrics_dictionary(run / "metrics_dictionary.json")

    export_visual_bundle(
        run,
        include_buckets=("day", "iso_week", "month"),
        layer_b=False,
        show_progress=False,
    )

    html = run / "report.html"
    assert html.is_file()
    report_body = html.read_text(encoding="utf-8")
    assert "Итоговый визуальный отчёт аналитического прогона" in report_body
    assert "figures/day/layer_a_segment_count.png" in report_body
    assert "figures/day/layer_a_duration_total_sum_day.png" in report_body
    assert "Смысл показателя: Число сегментов диаризации" in report_body
    assert not (run / "result.html").exists()

    figures_m = sorted((run / "figures" / "month").glob("*.png"))
    assert len(figures_m) >= 1
    assert (run / "time_agg_month_long.csv").is_file()


def test_export_visual_bundle_language_png(tmp_path: Path) -> None:
    """Stacked PNG when Layer B language share parquet exists."""

    run = tmp_path / "run2"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text("{}")
    bm = datetime(2024, 3, 1)
    d1, d2 = datetime(2024, 3, 5), datetime(2024, 3, 12)
    agg_m = pl.DataFrame(
        {
            "bucket_month": [bm, bm.replace(day=31)],
            "n_rows": [100, 80],
            "layer_a_segment_count_median": [12.0, 11.0],
            "layer_a_segment_count_q1": [10.5, 9.9],
            "layer_a_segment_count_q3": [13.9, 12.88],
        }
    )
    agg_d = pl.DataFrame(
        {
            "bucket_day": [d1, d2],
            "n_rows": [50, 50],
            "layer_a_segment_count_median": [12.0, 11.0],
            "layer_a_segment_count_q1": [10.5, 9.9],
            "layer_a_segment_count_q3": [13.9, 12.88],
        }
    )
    agg_m.write_parquet(run / "time_agg_month.parquet")
    agg_d.write_parquet(run / "time_agg_day.parquet")
    lng = pl.DataFrame(
        {
            "bucket_day": [d1, d1, d2, d2],
            "_category": ["Spanish", "English", "Spanish", "English"],
            "n_in_category": [30, 20, 25, 25],
            "n_in_bucket": [50, 50, 50, 50],
            "share": [0.6, 0.4, 0.5, 0.5],
        }
    )
    lng.write_parquet(run / "language_share_time_agg_day.parquet")

    write_metrics_dictionary(run / "metrics_dictionary.json")

    export_visual_bundle(run, layer_b=True, show_progress=False)

    assert (run / "figures" / "language_share_day.png").is_file()
    report = (run / "report.html").read_text(encoding="utf-8")
    assert "Накопительная (стековая) доля строк" in report
    assert "figures/language_share_day.png" in report
    assert not (run / "result.html").exists()

"""Human-oriented exports: long-format CSV, trend charts, HTML index."""

from __future__ import annotations

import html as html_module
import json
import logging
import math
import re
from pathlib import Path

import numpy as np
import polars as pl
import polars.datatypes as dt

_LOG = logging.getLogger("ta.visual_report")

_RU_TREND_CHART_GLOSSARY = (
    "Как читать график: синяя линия показывает медиану метрики в каждом временном интервале; "
    "полупрозрачная полоса — разброс между первым и третьим квартилями (Q1–Q3, межквартильный интервал); "
    "полупрозрачные столбцы (вторая вертикальная шкала) — число транскриптов N в этом интервале."
)

_BUCKET_LABEL_RU: dict[str, str] = {
    "day": "календарным дням",
    "iso_week": "неделям ISO (формат год‑неделя)",
    "month": "календарным месяцам",
}

_LANGUAGE_MIX_CAPTION_RU = (
    "Накопительная (стековая) доля строк по основному определённому языку фрагмента транскрипта "
    "(слой B: детекция по выдержкам начала/середины/конца текста). Ось времени — календарные дни "
    "поля created_at (один столбец на день); сопоставляйте с графиками метрик по дням и столбцами N."
)


def load_metric_descriptions_ru(metrics_dictionary_path: Path) -> dict[str, str]:
    """Parse ``metrics_dictionary.json`` for ``description_ru`` keyed by canonical metric ``name``."""
    if not metrics_dictionary_path.is_file():
        return {}
    try:
        raw = json.loads(metrics_dictionary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("metrics_dictionary_read_failed path=%s err=%s", metrics_dictionary_path, exc)
        return {}
    out: dict[str, str] = {}
    for row in raw.get("metrics", []):
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        ru = row.get("description_ru")
        if isinstance(name, str) and isinstance(ru, str) and ru.strip():
            out[name] = ru.strip()
    return out


def _collect_png_rels_under(run_dir: Path, subdir: Path) -> list[str]:
    if not subdir.is_dir():
        return []
    return sorted(
        str(p.relative_to(run_dir)).replace("\\", "/")
        for p in subdir.glob("*.png")
        if p.is_file()
    )


def _metric_name_from_png_stem(stem: str) -> str:
    """Canonical metric prefix for aggregate columns (PNG filename stem matches ``_safe_slug(metric)``)."""
    return stem


def _safe_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_")
    return s or "metric"


def _pretty_metric_title(metric: str) -> str:
    return metric.replace("layer_a_", "").replace("layer_b_", "").replace("_", " ").strip()


def _configure_matplotlib() -> tuple:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    return plt, mdates


def list_metric_names_from_aggregate(df: pl.DataFrame) -> list[str]:
    """Return base metric names derived from ``*_median`` columns."""
    return sorted({c[:-7] for c in df.columns if c.endswith("_median")}, key=str.lower)


def _is_datetime_column(dtype: pl.DataType) -> bool:
    return isinstance(dtype, dt.Datetime)


def time_aggregate_to_long(df: pl.DataFrame, bucket_col: str) -> pl.DataFrame:
    """
    Tidy rows: one row per time bucket × metric.

    Columns: time_bucket (string ISO), metric, median, q1, q3, n_rows_per_bucket.

    ``n_rows`` repeats per metric for simple spreadsheet pivots.
    """
    dtype = df.schema[bucket_col]
    if _is_datetime_column(dtype):
        label_expr = pl.col(bucket_col).dt.strftime("%Y-%m-%d %H:%M:%S").alias("time_bucket")
    else:
        label_expr = pl.col(bucket_col).cast(pl.Utf8).alias("time_bucket")

    bases = list_metric_names_from_aggregate(df)
    if not bases:
        return pl.DataFrame(
            schema={
                "time_bucket": pl.Utf8,
                "metric": pl.Utf8,
                "median": pl.Float64,
                "q1": pl.Float64,
                "q3": pl.Float64,
                "n_rows_per_bucket": pl.Int64,
            }
        )

    chunks: list[pl.DataFrame] = []
    for b in bases:
        med, q1_col, q3_col = f"{b}_median", f"{b}_q1", f"{b}_q3"
        if not all(x in df.columns for x in (med, q1_col, q3_col)):
            continue
        chunks.append(
            df.select(
                label_expr,
                pl.lit(b).alias("metric"),
                pl.col(med).alias("median"),
                pl.col(q1_col).alias("q1"),
                pl.col(q3_col).alias("q3"),
                pl.col("n_rows").alias("n_rows_per_bucket"),
            )
        )

    return pl.concat(chunks, how="vertical").sort(["time_bucket", "metric"])


def _xs_for_buckets(df_sorted: pl.DataFrame, bucket_col: str):
    """Return matplotlib x-values and ``is_dates`` flag for axis formatting."""
    dtype = df_sorted.schema[bucket_col]
    if _is_datetime_column(dtype):
        import matplotlib.dates as mdates

        s = df_sorted[bucket_col].dt.strftime("%Y-%m-%d %H:%M:%S").to_list()
        xs = np.asarray(mdates.datestr2num(s), dtype=np.float64)
        return xs, True

    xs = np.arange(len(df_sorted), dtype=np.float64)
    return xs, False


def write_metric_trend_figure(
    df: pl.DataFrame,
    *,
    bucket_col: str,
    metric: str,
    out_png: Path,
) -> None:
    """PNG: median line, Q1–Q3 band, secondary translucent bars for N."""
    plt, mdates = _configure_matplotlib()
    med_col, q1_col, q3_col = f"{metric}_median", f"{metric}_q1", f"{metric}_q3"

    subset = (
        df.select([bucket_col, med_col, q1_col, q3_col, "n_rows"])
        .sort(bucket_col)
        .filter(pl.col(med_col).is_not_null())
    )
    if len(subset) == 0:
        _LOG.warning("skip_empty_metric_plot metric=%s", metric)
        return

    xs, is_dates = _xs_for_buckets(subset, bucket_col)
    cat_labels = subset[bucket_col].cast(pl.Utf8).to_list() if not is_dates else []

    med = subset[med_col].cast(pl.Float64).to_numpy()
    lo = subset[q1_col].cast(pl.Float64).to_numpy()
    hi = subset[q3_col].cast(pl.Float64).to_numpy()
    n_rows = subset["n_rows"].cast(pl.Int64).to_numpy()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 3.75), layout="constrained")
    ttl = _pretty_metric_title(metric)
    subtitle = " (dense timeline — dense buckets)" if len(xs) > 400 else ""
    ax.set_title(f"{ttl} — median ± IQR; bars = transcript count per bucket{subtitle}")

    bw = xs[1] - xs[0] if len(xs) > 1 else 1.0
    width = bw * (0.62 if is_dates else 0.82)
    pad = bw * (0.015 if is_dates else 0.12)

    ax.fill_between(xs, lo, hi, alpha=0.22, linewidth=0, label="Q1–Q3 (IQR)")
    ax.plot(xs, med, color="#1f77b4", linewidth=1.8, label="Median")

    ax2 = ax.twinx()
    ax2.bar(xs - pad, n_rows, width=width, alpha=0.18, color="#444444")

    ax2.set_ylabel("Transcripts (N)", color="#555555")

    handles1, l1 = ax.get_legend_handles_labels()
    legend_bar = plt.Rectangle((0, 0), 1, 1, fc="#444444", alpha=0.18)
    ax.legend(handles1 + [legend_bar], l1 + ["N (bars)"], loc="upper left", fontsize="small")
    ax.grid(True, alpha=0.35)
    ax.set_ylabel("Metric value")

    if is_dates:
        locator = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=35, ha="right")
    else:
        step = max(1, math.ceil(len(xs) / 32))
        tick_idx = list(range(0, len(xs), step))
        ax.set_xticks(xs[tick_idx])
        labels = [
            str(cat_labels[int(i)])[:16] if int(i) < len(cat_labels) else "" for i in tick_idx
        ]
        ax.set_xticklabels(labels, rotation=55, ha="right", fontsize="x-small")

    try:
        fig.savefig(out_png, dpi=120)
    except (MemoryError, OSError, RuntimeError, ValueError) as exc:
        _LOG.warning("metric_png_save_failed path=%s err=%s", out_png, exc)
    plt.close(fig)


def write_language_share_stack_figure(df: pl.DataFrame, bucket_col: str, out_png: Path) -> None:
    """Stacked-area share plot (top languages + other); requires ``_category``, ``share``."""
    plt, mdates = _configure_matplotlib()

    if len(df) == 0:
        return

    wide = (
        df.sort(bucket_col).pivot(on="_category", index=bucket_col, values="share")
    )
    if wide.height == 0:
        return

    cats = [c for c in wide.columns if c != bucket_col]
    if not cats:
        return

    wide = wide.fill_null(0.0)

    sums = [(c, float(wide[c].sum())) for c in cats]
    sums.sort(key=lambda x: x[1], reverse=True)

    max_layers = 12
    tops = [c for c, _ in sums[:max_layers]]
    other = [c for c, _ in sums[max_layers:]]
    if other:
        other_expr = pl.sum_horizontal(*[pl.col(c).fill_null(0) for c in other]).alias("__other__")
        plot_df = wide.select([bucket_col, *tops]).with_columns(other_expr)
        layer_names = [str(x) for x in tops] + ["(other languages)"]
        cols_for_stack = tops + ["__other__"]
    else:
        plot_df = wide.select([bucket_col] + [pl.col(c) for c in tops])
        layer_names = [str(x) for x in tops]
        cols_for_stack = list(tops)

    xs, is_dates = _xs_for_buckets(plot_df, bucket_col)
    cat_labels = plot_df[bucket_col].cast(pl.Utf8).to_list() if not is_dates else []

    ys_stack = [plot_df[c].cast(pl.Float64).to_numpy() for c in cols_for_stack]

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")

    bottom = None
    for label, ys in zip(layer_names, ys_stack, strict=True):
        name = label[:72]
        if bottom is None:
            ax.fill_between(xs, 0.0, ys, alpha=0.6, linewidth=0, label=name)
            bottom = ys
        else:
            ax.fill_between(xs, bottom, bottom + ys, alpha=0.6, linewidth=0, label=name)
            bottom = bottom + ys

    ax.set_ylabel("Share of rows")
    ax.set_ylim(0.0, 1.0)
    ax.set_title("Language mix by time bucket (Layer B)")
    ax.legend(ncol=2, fontsize="x-small", loc="upper left")

    if is_dates:
        locator = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=35, ha="right")
    else:
        step = max(1, math.ceil(len(xs) / 28))
        tick_idx = list(range(0, len(xs), step))
        ax.set_xticks(xs[tick_idx])
        labels = []
        for i in tick_idx:
            if i < len(cat_labels):
                labels.append(str(cat_labels[int(i)])[:18])
        ax.set_xticklabels(labels, rotation=52, ha="right", fontsize="x-small")

    try:
        fig.savefig(out_png, dpi=120)
    except (MemoryError, OSError, RuntimeError, ValueError) as exc:
        _LOG.warning("language_share_png_save_failed path=%s err=%s", out_png, exc)
    plt.close(fig)


def write_visual_report_html(
    run_dir: Path,
    *,
    language_chart_rel: str | None,
) -> None:
    """Write ``report.html`` — single Russian report: daily metric plots + optional daily language stack."""
    metrics_dict_path = run_dir / "metrics_dictionary.json"
    ru_by_metric = load_metric_descriptions_ru(metrics_dict_path)

    manifest_path = run_dir / "manifest.json"
    summary_dl = ""
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            summary_dl = (
                "<dl class='manifest'>"
                "<dt>Идентификатор запуска</dt>"
                f"<dd>{html_module.escape(str(manifest.get('run_id', '')))}</dd>"
                "<dt>Обработано строк</dt>"
                f"<dd>{html_module.escape(str(manifest.get('rows_read', '')))}</dd>"
                "<dt>Диапазон created_at</dt>"
                f"<dd>{html_module.escape(str(manifest.get('created_at_min', '')))}"
                " — "
                f"{html_module.escape(str(manifest.get('created_at_max', '')))}</dd>"
                "<dt>Версия набора метрик</dt>"
                f"<dd>{html_module.escape(str(manifest.get('metrics_definition_version', '')))}</dd>"
                "</dl>"
            )
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("manifest_read_failed path=%s err=%s", manifest_path, exc)

    css = """<style>
body { font-family: system-ui, "Segoe UI", sans-serif; max-width: 1100px; margin: 24px auto; color: #1a1a1a;
  line-height: 1.45; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; }
.manifest dt { font-weight: 600; }
.manifest dd { margin: 0 0 12px 0; }
section { margin-top: 1.5rem; }
figure { margin: 1.25rem 0; border-bottom: 1px solid #e8e8e8; padding-bottom: 1.1rem; }
img { max-width: 100%; height: auto; }
.caption { font-size: 0.93rem; color: #333; margin-top: 6px; }
.lead { font-size: 1.02rem; color: #2a2a2a; }
.note { font-size: 0.9rem; color: #555; }
</style>"""

    body_inner: list[str] = []
    body_inner.append("<h1>Итоговый визуальный отчёт аналитического прогона</h1>")
    body_inner.append(
        "<p class='lead'>Единый итоговый отчёт на русском: графики строятся по "
        "<strong>календарным дням</strong> (bucket_day из created_at). "
        "Дополнительные разрешения (неделя ISO, месяц) сохранены в таблицах и в папках "
        "<code>figures/iso_week</code> и <code>figures/month</code>, но сюда не включены.</p>"
    )
    body_inner.append(
        "<p class='note'>Табличные агрегаты: "
        "<code>time_agg_day_long.csv</code> (и при необходимости <code>time_agg_*_long.csv</code>), "
        "широкие <code>time_agg_*.csv</code>, parquet.</p>"
    )
    body_inner.append(f"<p class='note'>{html_module.escape(_RU_TREND_CHART_GLOSSARY)}</p>")
    if summary_dl:
        body_inner.append("<section><h2>Сводка по запуску</h2>")
        body_inner.append(summary_dl)
        body_inner.append("</section>")

    body_inner.append("<section><h2>Смесь языков (слой&nbsp;B), по дням</h2>")
    if language_chart_rel:
        lc = language_chart_rel.replace("\\", "/")
        body_inner.append(
            f"<figure><img src=\"{html_module.escape(lc)}\""
            ' alt="доли языков по дням"/>'
            f"<figcaption class='caption'>"
            f"{html_module.escape(_LANGUAGE_MIX_CAPTION_RU)}"
            "</figcaption></figure>"
        )
    else:
        body_inner.append(
            "<p><em>График смеси языков недоступен: слой B отключён или нет данных для "
            "<code>language_share_time_agg_day</code>.</em></p>"
        )
    body_inner.append("</section>")

    bucket_key = "day"
    bucket_ru = _BUCKET_LABEL_RU[bucket_key]
    body_inner.append("<section><h2>Числовые метрики по времени</h2>")
    body_inner.append(
        f"<h2>Разрешение: по {bucket_ru}</h2>"
    )
    fig_root = run_dir / "figures" / bucket_key
    rels = _collect_png_rels_under(run_dir, fig_root)
    if not rels:
        body_inner.append(
            "<p><em>Нет дневных PNG (проверьте наличие time_agg_day и этапа визуализации).</em></p>"
        )
    else:
        for rel in rels:
            rf = rel.replace("\\", "/")
            metric_key = _metric_name_from_png_stem(Path(rel).stem)
            meaning = ru_by_metric.get(metric_key)
            if meaning is None:
                meaning = (
                    f"Смысл метрики задаётся в metrics_dictionary.json; "
                    f"техническое имя: «{metric_key}» (поле description_ru подставится автоматически)."
                )
            cap = f"Агрегация по календарным дням (created_at → bucket_day). Смысл показателя: {meaning}"
            body_inner.append(
                f"<figure><img src=\"{html_module.escape(rf)}\" alt=\"{html_module.escape(metric_key)}\"/>"
                f"<figcaption class=\"caption\">{html_module.escape(cap)}</figcaption></figure>"
            )
    body_inner.append("</section>")

    html_doc = (
        "<!DOCTYPE html>\n"
        "<html lang=\"ru\"><head><meta charset=\"utf-8\"/>"
        "<title>Итоговый отчёт — анализ транскрипций</title>"
        f"{css}</head><body>\n"
        + "\n".join(body_inner)
        + "\n</body></html>\n"
    )
    out = run_dir / "report.html"
    out.write_text(html_doc, encoding="utf-8")


def export_visual_bundle(
    run_dir: Path,
    *,
    include_buckets: tuple[str, ...] = ("day", "iso_week", "month"),
    layer_b: bool,
    show_progress: bool,
) -> None:
    """Create long CSVs, PNG figures per bucket, and a single Russian ``report.html`` (day plots only)."""
    import time as time_mod

    if show_progress:
        from transcriptions_analysis.progress_display import emit_phase_line, format_duration

    t0 = time_mod.perf_counter()
    bucket_map = {
        "day": ("bucket_day", "time_agg_day.parquet"),
        "iso_week": ("bucket_iso_week", "time_agg_iso_week.parquet"),
        "month": ("bucket_month", "time_agg_month.parquet"),
    }

    for key in include_buckets:
        if key not in bucket_map:
            _LOG.warning("unknown_report_bucket name=%s (skip)", key)
            continue
        bcol, fname = bucket_map[key]
        p = run_dir / fname
        if not p.is_file():
            _LOG.warning("aggregate_parquet_missing path=%s", p)
            continue

        agg = pl.read_parquet(p)
        long_csv = run_dir / f"time_agg_{key}_long.csv"
        time_aggregate_to_long(agg, bucket_col=bcol).write_csv(long_csv)

        fig_root = run_dir / "figures" / key
        for mname in list_metric_names_from_aggregate(agg):
            out_png = fig_root / f"{_safe_slug(mname)}.png"
            write_metric_trend_figure(agg, bucket_col=bcol, metric=mname, out_png=out_png)

    language_rel = None
    if layer_b:
        ld = run_dir / "language_share_time_agg_day.parquet"
        if ld.is_file():
            lf = run_dir / "figures" / "language_share_day.png"
            write_language_share_stack_figure(
                pl.read_parquet(ld), bucket_col="bucket_day", out_png=lf
            )
            if lf.is_file():
                language_rel = str(lf.relative_to(run_dir)).replace("\\", "/")

    write_visual_report_html(run_dir, language_chart_rel=language_rel)

    if show_progress:
        emit_phase_line(
            "visual_report: charts + HTML + long CSV "
            f"({format_duration(time_mod.perf_counter() - t0)})",
        )

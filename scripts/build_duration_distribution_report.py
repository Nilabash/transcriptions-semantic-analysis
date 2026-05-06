"""Build a duration distribution report (monthly + last 30 days) for a run folder."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from transcriptions_analysis.metrics_layer_a import compute_layer_a_for_text

OUT = REPO / "outputs"


@dataclass(frozen=True)
class RowDuration:
    created_at: datetime
    duration_seconds: float


def parse_created_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def percentile_linear(sorted_vals: list[float], p: float) -> float:
    """Linear interpolation percentile, p in [0, 100]."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def resolve_input_csv(run_dir: Path, manifest: dict) -> Path:
    manifest_path = manifest.get("input", {}).get("path")
    if manifest_path:
        candidate = Path(manifest_path)
        if candidate.is_file():
            return candidate
        # manifest path is usually /data/<name>.csv in container
        fallback = REPO / candidate.name
        if fallback.is_file():
            return fallback
    local_default = REPO / "transcriptions_all_telegram_utf8_bom_new.csv"
    if local_default.is_file():
        return local_default
    raise FileNotFoundError(
        "Could not resolve input CSV from manifest or repository root. Pass --input-csv explicitly."
    )


def collect_durations(
    csv_path: Path,
    start_dt: datetime,
    end_dt: datetime,
) -> list[RowDuration]:
    csv.field_size_limit(sys.maxsize)
    out: list[RowDuration] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            created = parse_created_at(row.get("created_at"))
            if created is None:
                continue
            if created < start_dt or created > end_dt:
                continue
            metrics = compute_layer_a_for_text(row.get("transcription_text"))
            duration = float(metrics.get("layer_a_duration_covered_seconds") or 0.0)
            out.append(RowDuration(created_at=created, duration_seconds=max(duration, 0.0)))
    return out


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def summarize(values: list[float]) -> dict[str, float]:
    sv = sorted(values)
    n = len(sv)
    if n == 0:
        return {
            "n": 0,
            "mean": float("nan"),
            "median": float("nan"),
            "variance": float("nan"),
            "stddev": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
            "p01": float("nan"),
            "p05": float("nan"),
            "p10": float("nan"),
            "p25": float("nan"),
            "p50": float("nan"),
            "p75": float("nan"),
            "p90": float("nan"),
            "p95": float("nan"),
            "p99": float("nan"),
        }
    mean = sum(sv) / n
    var = statistics.pvariance(sv) if n > 1 else 0.0
    std = math.sqrt(var)
    return {
        "n": n,
        "mean": mean,
        "median": percentile_linear(sv, 50),
        "variance": var,
        "stddev": std,
        "min": sv[0],
        "max": sv[-1],
        "p01": percentile_linear(sv, 1),
        "p05": percentile_linear(sv, 5),
        "p10": percentile_linear(sv, 10),
        "p25": percentile_linear(sv, 25),
        "p50": percentile_linear(sv, 50),
        "p75": percentile_linear(sv, 75),
        "p90": percentile_linear(sv, 90),
        "p95": percentile_linear(sv, 95),
        "p99": percentile_linear(sv, 99),
    }


def fmt_seconds(seconds: float) -> str:
    if seconds != seconds:
        return "NaN"
    return f"{seconds:.1f}"


def to_minutes(values: list[float]) -> list[float]:
    return [v / 60.0 for v in values]


def histogram(values_minutes: list[float], bins: list[float]) -> list[int]:
    out = [0 for _ in range(len(bins) - 1)]
    for v in values_minutes:
        idx = None
        for i in range(len(bins) - 1):
            left, right = bins[i], bins[i + 1]
            if (v >= left and v < right) or (i == len(bins) - 2 and v >= left and v <= right):
                idx = i
                break
        if idx is not None:
            out[idx] += 1
    return out


def main(run_id: str, *, output_html: Path | None, input_csv: Path | None) -> None:
    run_dir = (OUT / run_id).resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Run manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    start_dt = parse_created_at(manifest.get("created_at_min"))
    end_dt = parse_created_at(manifest.get("created_at_max"))
    if start_dt is None or end_dt is None:
        raise SystemExit("Manifest missing created_at_min/max in expected format.")
    csv_path = input_csv if input_csv else resolve_input_csv(run_dir, manifest)

    rows = collect_durations(csv_path, start_dt=start_dt, end_dt=end_dt)
    if not rows:
        raise SystemExit("No duration rows were collected in the run date window.")

    by_month: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_month[month_key(r.created_at)].append(r.duration_seconds)

    months = sorted(by_month.keys())
    month_summaries = {m: summarize(by_month[m]) for m in months}

    # Last 30 days from max created_at in this run
    last_30_start = end_dt - timedelta(days=30)
    last_30_values = [r.duration_seconds for r in rows if r.created_at >= last_30_start]
    last_30_summary = summarize(last_30_values)
    last_30_range_label = f"{last_30_start.strftime('%Y-%m-%d')} — {end_dt.strftime('%Y-%m-%d')}"

    # Distribution bins in minutes, tuned for voice-note/session lengths.
    bins_minutes = [0, 1, 2, 3, 5, 8, 12, 20, 30, 45, 60, 90, 120, 180]
    bin_labels = [f"{bins_minutes[i]}-{bins_minutes[i+1]} мин" for i in range(len(bins_minutes) - 1)]
    bin_midpoints = [
        (bins_minutes[i] + bins_minutes[i + 1]) / 2.0 for i in range(len(bins_minutes) - 1)
    ]
    monthly_hist = {
        m: histogram(to_minutes(by_month[m]), bins_minutes)
        for m in months
    }
    last_30_hist = histogram(to_minutes(last_30_values), bins_minutes)
    all_values = [r.duration_seconds for r in rows]
    all_summary = summarize(all_values)

    # CSV export for month summary
    csv_out = run_dir / "duration_distribution_monthly_stats.csv"
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "month",
                "n",
                "mean_seconds",
                "median_seconds",
                "variance_seconds2",
                "stddev_seconds",
                "p01",
                "p05",
                "p10",
                "p25",
                "p50",
                "p75",
                "p90",
                "p95",
                "p99",
                "min_seconds",
                "max_seconds",
            ]
        )
        for m in months:
            s = month_summaries[m]
            writer.writerow(
                [
                    m,
                    s["n"],
                    f"{s['mean']:.6f}",
                    f"{s['median']:.6f}",
                    f"{s['variance']:.6f}",
                    f"{s['stddev']:.6f}",
                    f"{s['p01']:.6f}",
                    f"{s['p05']:.6f}",
                    f"{s['p10']:.6f}",
                    f"{s['p25']:.6f}",
                    f"{s['p50']:.6f}",
                    f"{s['p75']:.6f}",
                    f"{s['p90']:.6f}",
                    f"{s['p95']:.6f}",
                    f"{s['p99']:.6f}",
                    f"{s['min']:.6f}",
                    f"{s['max']:.6f}",
                ]
            )

    output = output_html or (run_dir / "duration_distribution_report.html")
    labels = months
    medians = [round(month_summaries[m]["median"] / 60.0, 3) for m in months]
    p25 = [round(month_summaries[m]["p25"] / 60.0, 3) for m in months]
    p75 = [round(month_summaries[m]["p75"] / 60.0, 3) for m in months]
    stddev = [round(month_summaries[m]["stddev"] / 60.0, 3) for m in months]
    n_series = [month_summaries[m]["n"] for m in months]

    monthly_hist_datasets = [
        {
            "label": m,
            "data": monthly_hist[m],
        }
        for m in months
    ]
    monthly_hist_linear_datasets = [
        {
            "label": m,
            "data": [
                {"x": bin_midpoints[i], "y": monthly_hist[m][i]}
                for i in range(len(bin_midpoints))
            ],
        }
        for m in months
    ]

    table_rows = []
    for m in months:
        s = month_summaries[m]
        table_rows.append(
            "<tr>"
            f"<td>{escape(m)}</td>"
            f"<td class='num'>{s['n']}</td>"
            f"<td class='num'>{fmt_seconds(s['median'])}</td>"
            f"<td class='num'>{fmt_seconds(s['stddev'])}</td>"
            f"<td class='num'>{fmt_seconds(s['variance'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p10'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p25'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p50'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p75'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p90'])}</td>"
            f"<td class='num'>{fmt_seconds(s['p95'])}</td>"
            f"</tr>"
        )

    last30 = last_30_summary
    month_with_max_median = max(months, key=lambda m: month_summaries[m]["median"])
    month_with_min_median = min(months, key=lambda m: month_summaries[m]["median"])
    short_upto_3m = sum(last_30_hist[:3])
    long_over_30m = sum(last_30_hist[8:])
    last30_n = max(int(last30["n"]), 1)
    short_share = 100.0 * short_upto_3m / last30_n
    long_share = 100.0 * long_over_30m / last30_n
    tail_ratio_30 = (last30["p95"] / last30["p50"]) if last30["p50"] and last30["p50"] > 0 else float("nan")
    tail_ratio_all = (
        (all_summary["p95"] / all_summary["p50"])
        if all_summary["p50"] and all_summary["p50"] > 0
        else float("nan")
    )
    iqr_30 = last30["p75"] - last30["p25"]

    key_findings_html = f"""
      <ul class="list-disc pl-6 space-y-2 text-sm text-slate-700">
        <li><strong>Последние 30 дней:</strong> медиана длительности составляет <strong>{fmt_seconds(last30["median"])} сек</strong>, межквартильный диапазон (IQR) — <strong>{fmt_seconds(iqr_30)} сек</strong>.</li>
        <li><strong>Структура хвоста (30 дней):</strong> отношение P95/P50 равно <strong>{tail_ratio_30:.2f}x</strong>, что указывает на выраженный длинный хвост (редкие, но очень длинные записи).</li>
        <li><strong>Формат потребления (30 дней):</strong> короткие записи до 3 минут — <strong>{short_share:.1f}%</strong>, длинные записи свыше 30 минут — <strong>{long_share:.1f}%</strong>.</li>
        <li><strong>Диапазон месячных медиан:</strong> максимум в <strong>{escape(month_with_max_median)}</strong> ({fmt_seconds(month_summaries[month_with_max_median]["median"])} сек), минимум в <strong>{escape(month_with_min_median)}</strong> ({fmt_seconds(month_summaries[month_with_min_median]["median"])} сек).</li>
        <li><strong>Общий профиль по всему периоду:</strong> отношение P95/P50 составляет <strong>{tail_ratio_all:.2f}x</strong>; распределение длительности остаётся тяжёлохвостым на всём горизонте данных.</li>
      </ul>
    """

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Отчёт по распределению длительности транскрипций</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#f8fafc; color:#0f172a; margin:0; }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:28px; }}
    .hero {{ background:#ffffff; color:#0f172a; border:1px solid #dbe4f0; border-radius:20px; padding:24px; box-shadow:0 2px 10px rgba(15,23,42,0.06); margin-bottom:20px; }}
    .card {{ background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-bottom:16px; box-shadow:0 1px 2px rgba(15,23,42,0.04); }}
    .section-title {{ font-size:1.3rem; font-weight:700; margin-bottom:10px; color:#0f172a; }}
    .kpi-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; }}
    .kpi {{ border:1px solid #dbeafe; background:#f8fbff; border-radius:12px; padding:12px; }}
    .kpi .k {{ font-size:12px; color:#334155; margin-bottom:6px; }}
    .kpi .v {{ font-size:1.25rem; font-weight:700; color:#0f172a; font-variant-numeric: tabular-nums; }}
    .chart {{ height:360px; }}
    .table-wrap {{ overflow:auto; max-height:440px; border:1px solid #e2e8f0; border-radius:12px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ border-bottom:1px solid #e2e8f0; padding:8px 10px; }}
    th {{ background:#f1f5f9; text-align:left; position:sticky; top:0; z-index:2; }}
    td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
    .badge {{ display:inline-block; font-size:12px; color:#0f172a; background:#e2e8f0; border-radius:999px; padding:2px 10px; margin-right:6px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1 class="text-3xl md:text-4xl font-bold mb-2">Отчёт по распределению длительности транскрипций</h1>
      <p class="text-slate-600 text-sm md:text-base">Глубокий анализ длительности аудио: распределения, перцентили, дисперсия и отклонение с акцентом на последние 30 дней.</p>
      <div class="mt-4 text-xs md:text-sm text-slate-600 leading-relaxed">
        <div><span class="badge">Прогон</span><code>{escape(run_id)}</code></div>
        <div class="mt-1"><span class="badge">Окно дат</span><code>{escape(manifest["created_at_min"])}</code> — <code>{escape(manifest["created_at_max"])}</code></div>
      </div>
    </header>

    <div class="card">
      <h2 class="section-title">Словарь переменных и метрик</h2>
      <ul class="list-disc pl-6 space-y-2 text-sm text-slate-700">
        <li><strong>N</strong> — число транскрипций в периоде/месяце.</li>
        <li><strong>P10, P25, P50, P75, P90, P95, P99</strong> — перцентили длительности; например, P50 — медиана.</li>
        <li><strong>StdDev</strong> — стандартное отклонение длительности (в секундах), мера типичного разброса вокруг среднего.</li>
        <li><strong>Variance</strong> — дисперсия (квадрат стандартного отклонения), единицы: сек².</li>
        <li><strong>IQR</strong> — межквартильный диапазон, то есть интервал между P25 и P75.</li>
      </ul>
    </div>

    <div class="card">
      <h2 class="section-title">Ключевые выводы</h2>
      {key_findings_html}
    </div>

    <div class="card">
      <h2 class="section-title">Срез последних 30 дней</h2>
      <div class="kpi-grid">
        <div class="kpi"><div class="k">Количество строк</div><div class="v">{last30["n"]}</div></div>
        <div class="kpi"><div class="k">Медиана длительности</div><div class="v">{fmt_seconds(last30["median"])} сек</div></div>
        <div class="kpi"><div class="k">Стандартное отклонение</div><div class="v">{fmt_seconds(last30["stddev"])} сек</div></div>
        <div class="kpi"><div class="k">Дисперсия</div><div class="v">{fmt_seconds(last30["variance"])} сек²</div></div>
        <div class="kpi"><div class="k">P10</div><div class="v">{fmt_seconds(last30["p10"])} сек</div></div>
        <div class="kpi"><div class="k">P25</div><div class="v">{fmt_seconds(last30["p25"])} сек</div></div>
        <div class="kpi"><div class="k">P50</div><div class="v">{fmt_seconds(last30["p50"])} сек</div></div>
        <div class="kpi"><div class="k">P75</div><div class="v">{fmt_seconds(last30["p75"])} сек</div></div>
        <div class="kpi"><div class="k">P90</div><div class="v">{fmt_seconds(last30["p90"])} сек</div></div>
        <div class="kpi"><div class="k">P95</div><div class="v">{fmt_seconds(last30["p95"])} сек</div></div>
        <div class="kpi"><div class="k">Среднее</div><div class="v">{fmt_seconds(last30["mean"])} сек</div></div>
        <div class="kpi"><div class="k">P99</div><div class="v">{fmt_seconds(last30["p99"])} сек</div></div>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Распределение длительности по месяцам (интервалы в минутах)</h2>
      <p class="text-sm text-slate-600 mb-2">Легенда кликабельна: нажмите на месяц, чтобы скрыть/показать кривую. Масштабирование: колесо мыши или выделение рамкой (drag). Панорамирование: Shift + перетаскивание.</p>
      <div class="chart"><canvas id="monthlyDist"></canvas></div>
      <div class="mt-2 flex gap-2">
        <button id="resetMonthlyDistZoom" class="px-3 py-1.5 text-xs rounded-md border border-slate-300 bg-white hover:bg-slate-50">Сбросить масштаб</button>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Распределение длительности по месяцам (линейная ось X, минуты)</h2>
      <p class="text-sm text-slate-600 mb-2">Легенда кликабельна: нажмите на месяц, чтобы скрыть/показать кривую. Масштабирование: колесо мыши или выделение рамкой (drag). Панорамирование: Shift + перетаскивание.</p>
      <div class="chart"><canvas id="monthlyDistLinearX"></canvas></div>
      <div class="mt-2 flex gap-2">
        <button id="resetMonthlyDistLinearZoom" class="px-3 py-1.5 text-xs rounded-md border border-slate-300 bg-white hover:bg-slate-50">Сбросить масштаб</button>
      </div>
    </div>

    <div class="card">
      <h2 class="section-title">Распределение за последние 30 дней (интервалы в минутах)</h2>
      <p class="text-sm text-slate-600 mb-2">Период: <strong>{escape(last_30_range_label)}</strong></p>
      <div class="chart"><canvas id="last30Dist"></canvas></div>
    </div>

    <div class="card">
      <h2 class="section-title">Тренд по месяцам: медиана / IQR / stddev (минуты)</h2>
      <div class="chart"><canvas id="trend"></canvas></div>
    </div>

    <div class="card">
      <h2 class="section-title">Месячная статистика (секунды)</h2>
      <p class="text-sm text-slate-600 mb-3">Также экспортировано в <code>{escape(str(csv_out))}</code>.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Месяц</th><th>N</th><th>Медиана</th><th>StdDev</th><th>Дисперсия</th>
              <th>P10</th><th>P25</th><th>P50</th><th>P75</th><th>P90</th><th>P95</th>
            </tr>
          </thead>
          <tbody>
            {"".join(table_rows)}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
    const MONTHS = {json.dumps(labels)};
    const MED = {json.dumps(medians)};
    const P25 = {json.dumps(p25)};
    const P75 = {json.dumps(p75)};
    const STD = {json.dumps(stddev)};
    const N_SERIES = {json.dumps(n_series)};
    const BIN_LABELS = {json.dumps(bin_labels)};
    const MONTHLY_DATASETS = {json.dumps(monthly_hist_datasets)};
    const MONTHLY_LINEAR_DATASETS = {json.dumps(monthly_hist_linear_datasets)};
    const LAST30 = {json.dumps(last_30_hist)};

    const monthlyDistChart = new Chart(document.getElementById("monthlyDist"), {{
      type: "line",
      data: {{
        labels: BIN_LABELS,
        datasets: MONTHLY_DATASETS.map((d, i) => ({{
          label: d.label,
          data: d.data,
          borderColor: `hsl(${{(i * 43) % 360}} 70% 45%)`,
          backgroundColor: `hsl(${{(i * 43) % 360}} 70% 45%)`,
          tension: 0.2,
          fill: false
        }}))
      }},
      options: {{
        responsive:true,
        maintainAspectRatio:false,
        interaction: {{ mode: "nearest", intersect: false }},
        plugins: {{
          legend: {{ display: true, position: "bottom" }},
          zoom: {{
            pan: {{
              enabled: true,
              mode: "xy",
              modifierKey: "shift"
            }},
            zoom: {{
              wheel: {{ enabled: true }},
              pinch: {{ enabled: true }},
              drag: {{ enabled: true }},
              mode: "xy"
            }}
          }}
        }}
      }}
    }});

    const monthlyDistLinearXChart = new Chart(document.getElementById("monthlyDistLinearX"), {{
      type: "line",
      data: {{
        datasets: MONTHLY_LINEAR_DATASETS.map((d, i) => ({{
          label: d.label,
          data: d.data,
          borderColor: `hsl(${{(i * 43) % 360}} 70% 45%)`,
          backgroundColor: `hsl(${{(i * 43) % 360}} 70% 45%)`,
          tension: 0.2,
          fill: false,
          parsing: false
        }}))
      }},
      options: {{
        responsive:true,
        maintainAspectRatio:false,
        interaction: {{ mode: "nearest", intersect: false }},
        plugins: {{
          legend: {{ display: true, position: "bottom" }},
          zoom: {{
            pan: {{
              enabled: true,
              mode: "xy",
              modifierKey: "shift"
            }},
            zoom: {{
              wheel: {{ enabled: true }},
              pinch: {{ enabled: true }},
              drag: {{ enabled: true }},
              mode: "xy"
            }}
          }}
        }},
        scales: {{
          x: {{
            type: "linear",
            title: {{ display: true, text: "Длительность (минуты, линейная шкала)" }}
          }},
          y: {{
            beginAtZero: true,
            title: {{ display: true, text: "Количество транскрипций" }}
          }}
        }}
      }}
    }});

    document.getElementById("resetMonthlyDistZoom")?.addEventListener("click", () => monthlyDistChart.resetZoom());
    document.getElementById("resetMonthlyDistLinearZoom")?.addEventListener("click", () => monthlyDistLinearXChart.resetZoom());

    new Chart(document.getElementById("last30Dist"), {{
      type: "bar",
      data: {{
        labels: BIN_LABELS,
        datasets: [{{ label: "Количество транскрипций (последние 30 дней)", data: LAST30, backgroundColor: "#2563eb" }}]
      }},
      options: {{ responsive:true, maintainAspectRatio:false }}
    }});

    new Chart(document.getElementById("trend"), {{
      data: {{
        labels: MONTHS,
        datasets: [
          {{ type:"line", label:"Медиана (мин)", data: MED, borderColor:"#0ea5e9", tension:0.2 }},
          {{ type:"line", label:"P25 (мин)", data: P25, borderColor:"#a78bfa", tension:0.2 }},
          {{ type:"line", label:"P75 (мин)", data: P75, borderColor:"#8b5cf6", tension:0.2 }},
          {{ type:"line", label:"StdDev (мин)", data: STD, borderColor:"#f97316", tension:0.2 }},
          {{ type:"bar", label:"N строк", data: N_SERIES, yAxisID:"y1", backgroundColor:"rgba(100,116,139,0.35)" }}
        ]
      }},
      options: {{
        responsive:true,
        maintainAspectRatio:false,
        scales: {{
          y: {{ title: {{ display:true, text:"Минуты" }} }},
          y1: {{ position:"right", beginAtZero:true, grid:{{ drawOnChartArea:false }}, title:{{ display:true, text:"Строки" }} }}
        }}
      }}
    }});
  </script>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Wrote {csv_out}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build monthly and last-30-days duration distribution report for a run."
    )
    p.add_argument("--run-id", required=True, help="Run UUID under outputs/")
    p.add_argument(
        "--output-html",
        type=Path,
        default=None,
        help="Output HTML path (default: outputs/<run-id>/duration_distribution_report.html)",
    )
    p.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="Optional explicit source CSV path; otherwise resolve from manifest/repo.",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(args.run_id, output_html=args.output_html, input_csv=args.input_csv)

# Operations

## Default Runtime

The primary runtime path is Docker Compose.

## Docker Layout

| Mount | Purpose |
|------|------|
| `/data` | Read-only repository mount, including input CSV and tests |
| `/out` | Writable output mount backed by `./outputs` |

## Basic Run

```bash
docker compose build analytics
docker compose run --rm -e MAX_ROWS=500 analytics
```

## Input Resolution

`scripts/docker-entrypoint-analytics.sh` resolves input this way:

1. Use `INPUT_CSV` if provided.
2. Otherwise auto-detect a single top-level `/data/*.csv`.
3. Fail if there are zero or multiple CSV candidates.

## Environment Variables

| Variable | Meaning |
|------|------|
| `INPUT_CSV` | Input CSV path inside the container |
| `OUTPUT_DIR` | Output root, default `/out` |
| `MAX_ROWS` | Row cap for smoke runs |
| `BATCH_SIZE` | Logical CSV rows per batch |
| `RUN_ID` | Fixed run folder name |
| `TOTAL_ROWS` | Explicit row count for ETA |
| `PROGRESS` | Force on or off human progress output |
| `INFER_TOTAL_ROWS` | Force on or off first-column row counting |
| `LAYER_B` | `0` disables Layer B |
| `LANG_DETECT_MAX_CHARS` | Max characters passed to language detection |
| `LANG_DETECT_LANGUAGES` | Comma-separated ISO 639-1 allow-list |
| `USER_STRATIFY` | `0` disables per-user month aggregates |
| `EXPORT_REPORT` | `0` disables PNG and HTML export |

## CLI

### `ta-batch run`

Core flags:

| Flag | Meaning |
|------|------|
| `-i, --input` | Input CSV |
| `-o, --output-dir` | Output root |
| `--run-id` | Custom run id |
| `--max-rows` | Row cap |
| `--batch-size` | Batch size, default `4096` |
| `--no-layer-b` | Layer A only |
| `--no-user-stratify` | Skip `user_time_agg_month.*` |
| `--no-export-report` | Skip charts and HTML |
| `--total-rows` | Explicit row total for ETA |
| `--infer-total-rows` | Count logical rows before read phase |
| `--no-infer-total-rows` | Skip row-count pass |
| `--merge-per-row-parquet` | Write merged `per_row_features.parquet` when small enough |

### `ta-batch staging-parquet`

Creates a single Parquet file from the CSV without Layer A or Layer B extraction.

## Output Layout

| Path | Contents |
|------|------|
| `parts/part_*.parquet` | Per-batch enriched rows |
| `time_agg_day.*` | Daily numeric aggregates |
| `time_agg_iso_week.*` | ISO-week numeric aggregates |
| `time_agg_month.*` | Monthly numeric aggregates |
| `time_agg_*_long.csv` | Tidy long-form aggregates |
| `language_share_time_agg_*.*` | Language share tables when Layer B is on |
| `content_category_share_time_agg_*.*` | Content-category share tables when Layer B is on |
| `file_extension_share_time_agg_month.*` | File-extension shares by month |
| `user_time_agg_month.*` | Per-user monthly aggregates unless disabled |
| `figures/**/*.png` | Trend charts |
| `figures/day/layer_a_duration_total_sum_day.png` | Dedicated daily total duration chart (sum of `layer_a_duration_covered_seconds`) |
| `report.html` | Built-in HTML report |
| `manifest.json` | Run metadata and input fingerprint |
| `metrics_dictionary.json` | Metric definitions |

## Reports

### Built-in visual bundle

Written by `ta-batch run` when report export is enabled:

- long CSV reshapes
- PNG charts
- `report.html`
- dedicated day chart `figures/day/layer_a_duration_total_sum_day.png` with total seconds/day and N bars

Notes:

- the HTML report is generated from run artifacts already written to disk
- day, ISO week, and month PNGs are produced
- the built-in HTML focuses on daily views
- the built-in HTML is currently Russian-language

### Final research report

`scripts/build_final_research_report.py` is a second-stage report builder. Run it after `ta-batch run` when the batch output already exists in `outputs/<run_id>/`.

Build from an existing run:

```powershell
python scripts\build_final_research_report.py --run-id <uuid>
```

Default output:

- `outputs/final_research_report.html`

Optional output path:

```powershell
python scripts\build_final_research_report.py --run-id <uuid> -o outputs\my_final_report.html
```

You can also supply the run id through the environment:

```powershell
$env:FINAL_REPORT_RUN_ID = "<uuid>"
python scripts\build_final_research_report.py
```

The script expects these run artifacts:

| Path inside `outputs/<run_id>/` | Purpose |
|------|------|
| `manifest.json` | Validates that the run folder exists and provides run metadata |
| `metrics_dictionary.json` | Metric names and report captions |
| `time_agg_month.csv` | Monthly numeric metrics used for narrative summaries |
| `content_category_share_time_agg_month.csv` | Monthly content-category mix |
| `language_share_time_agg_month.csv` | Monthly language mix |
| `figures/**/*.png` | Daily metric figures embedded into the final HTML |

Notes:

- The generated HTML is intended as a shareable research deliverable, separate from the built-in `report.html`.
- PNG figures are embedded as base64 data URIs, so the final HTML does not need the original `figures/` directory at viewing time.
- Monthly content-category and language sections are rendered from the share CSVs and `time_agg_month.csv`.
- `build_final_research_report.py` embeds the dedicated daily total-duration chart when `figures/day/layer_a_duration_total_sum_day.png` exists.
- The script keeps backward compatibility with older runs that do not have this chart.
- If `manifest.json` is missing or the run id does not resolve to `outputs/<run_id>/`, the script exits with an error.

Recommended flow:

1. Run `ta-batch run`.
2. Inspect `outputs/<run_id>/report.html` and the aggregate files if needed.
3. Build `final_research_report.html` from the same `run_id` for a self-contained research handoff.

## Jupyter

```bash
docker compose --profile notebook up notebook
```

Defaults:

- port `8888`
- token controlled by `JUPYTER_TOKEN`

## Troubleshooting

### Container exits on large files

Try:

- `MAX_ROWS` for bounded runs
- smaller `BATCH_SIZE`
- `LAYER_B=0` to isolate Layer B cost
- higher Docker memory limits

### ETA looks wrong on smoke runs

When `MAX_ROWS` is set, ETA uses the row cap, not the physical file size.

### Rows are missing from aggregates

Check `manifest.json`:

- invalid `created_at` values are counted in `rows_dropped_null_ts`

### Import or build issues in Docker

If the image reports `ImportError` around `ta-batch`:

1. verify `src/transcriptions_analysis/cli.py` is not empty
2. rebuild without cache:

```bash
docker compose build --no-cache analytics
```

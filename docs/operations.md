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

### `scripts/build_llm_judge_sample.py`

Builds a deterministic ChatGPT-ready sample packet for Layer C style LLM judging.

```powershell
python scripts\build_llm_judge_sample.py
```

Repeatable run-folder example for a second Russian-only packet:

```powershell
python scripts\build_llm_judge_sample.py `
  --output-dir outputs\llm_judge_runs `
  --run-id russian-2026-05-06-r2 `
  --russian-only `
  --exclude-sample-index outputs\llm_judge\llm_judge_sample_index.csv
```

Useful flags:

| Flag | Meaning |
|------|------|
| `--input, -i` | Input CSV; defaults to a single top-level repo CSV |
| `--output-dir, -o` | Output directory, or run root when `--run-id` is set; default `outputs/llm_judge` |
| `--run-id` | Optional child folder name under `--output-dir` |
| `--samples-per-month` | Target selected transcripts per calendar month, default `8` |
| `--seed` | Deterministic sampling seed |
| `--max-transcript-chars` | Maximum characters included per selected transcript |
| `--russian-only` | Shortcut for `--language-filter ru` |
| `--language-filter` | Comma-separated filters; `ru`/`russian` uses Lingua detection, proxy labels such as `cyrillic_dominant` use the fast script proxy |
| `--language-min-confidence` | Minimum Lingua confidence for ISO filters, default `0.5` |
| `--lang-detect-languages` | Comma-separated ISO 639-1 allow-list for exact language filters |
| `--exclude-sample-index` | Prior `llm_judge_sample_index.csv` whose transcript IDs should be skipped |
| `--max-rows` | Optional cap for smoke tests |

### `scripts/analyze_llm_judge_output.py`

Summarizes the JSON returned by ChatGPT and joins it to the sample index.

```powershell
python scripts\analyze_llm_judge_output.py
```

Run-folder example after saving ChatGPT JSON as `outputs\llm_judge_runs\russian-2026-05-06-r2\llm_judge_output.json`:

```powershell
python scripts\analyze_llm_judge_output.py `
  --output-dir outputs\llm_judge_runs `
  --run-id russian-2026-05-06-r2
```

Defaults:

| Input | Default path |
|------|------|
| Judge JSON | `llm_judge_output.json` inside the resolved output directory |
| Sample index | `llm_judge_sample_index.csv` inside the resolved output directory |
| Output directory | `outputs/llm_judge/`, or `outputs/llm_judge_runs/<run-id>/` when using the example above |

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
| `duration_distribution_report.html` | Optional standalone duration-distribution report (built by script) |
| `duration_distribution_monthly_stats.csv` | Optional monthly duration stats export (built by script) |
| `manifest.json` | Run metadata and input fingerprint |
| `metrics_dictionary.json` | Metric definitions |

## LLM Judge Outputs

`scripts/build_llm_judge_sample.py` writes a separate handoff bundle under `outputs/llm_judge/` by default. For multiple independent judge passes, prefer a run root such as `outputs/llm_judge_runs/` plus `--run-id`; this keeps the packet, sample index, returned JSON, derived CSVs, Markdown report, and HTML report together.

| Path | Contents |
|------|------|
| `llm_judge_packet.md` | Single file to provide to ChatGPT; includes prompt plus transcript samples |
| `llm_judge_prompt.md` | Reusable fixed prompt only |
| `llm_judge_sample_index.csv` | Audit table with selected row ids, month, strata, metrics, and selection reason |
| `llm_judge_transcripts.jsonl` | Machine-readable transcript excerpts and metadata |
| `llm_judge_joined_scores.csv` | One judged transcript per row, joined to sample metadata |
| `llm_judge_monthly_scores.csv` | Monthly means for all selected rows and representative-only rows |
| `llm_judge_failure_modes.csv` | Failure-mode counts by month and sample group |
| `llm_judge_analysis.md` | Compact Markdown analysis report from the returned JSON |
| `llm_judge_research_report.html` | Standalone Russian-language visual HTML report from the returned JSON |

The packet is meant for qualitative judging of transcription and diarization quality over time. It samples per month across content, script/language proxy, length, speaker structure, and anomaly signals, then excerpts very long transcripts with beginning, middle, and ending windows.

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

### Duration distribution report

`scripts/build_duration_distribution_report.py` is a run-folder report builder focused on transcription duration analysis.

Build from an existing run:

```powershell
python scripts\build_duration_distribution_report.py --run-id <uuid>
```

Optional explicit input CSV:

```powershell
python scripts\build_duration_distribution_report.py `
  --run-id <uuid> `
  --input-csv d:\path\to\transcriptions.csv
```

Optional explicit output HTML:

```powershell
python scripts\build_duration_distribution_report.py `
  --run-id <uuid> `
  --output-html outputs\my_duration_report.html
```

Default outputs:

- `outputs/<run_id>/duration_distribution_report.html`
- `outputs/<run_id>/duration_distribution_monthly_stats.csv`

What this report adds:

- month-level duration distributions from recomputed per-row `layer_a_duration_covered_seconds`
- month-level statistics: variance, stddev, percentiles
- dedicated last-30-days section with explicit date range
- interactive monthly distribution charts with legend toggle, zoom, pan, and reset buttons

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

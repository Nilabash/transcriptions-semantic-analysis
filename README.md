# Transcriptions Analysis

Batch analytics for diarized transcription exports, optimized for large multiline CSV files.

The project reads a historical transcription export, extracts structural and text-level signals from each transcript, aggregates them over time, and writes reproducible artifacts for analysis and reporting.

## At A Glance

- Input: one UTF-8 CSV export with multiline `transcription_text`
- Runtime: Docker-first, Python 3.11, Polars
- Main CLI: `ta-batch`
- Output: Parquet, CSV, PNG charts, `report.html`, `manifest.json`
- Scope today: Layer A and Layer B descriptive metrics, not reference-based ASR accuracy

## What It Analyzes

- Transcript structure: segments, speakers, timestamps, speaker switches
- Duration from timestamps: covered seconds, timeline span, coverage ratio, timestamped-segment ratio
- Text quality proxies: token counts, entropy, odd Unicode, repeated characters
- Language and script mix
- File-name metadata
- Rule-based content categories
- Time buckets from `created_at`: day, ISO week, month

## Input Requirements

The batch pipeline expects a CSV file, not an `.xlsx` file.

If the source is managed in Excel, export it to CSV first and keep these exact column names when you use the related features:

| Column | Required | Notes |
|------|------|------|
| `created_at` | Core | Format: `YYYY-MM-DD HH:MM:SS`; required for time aggregation |
| `transcription_text` | Core | Full diarized transcript, may span many CSV lines |
| `telegram_user_internal_id` | Optional | Enables `user_time_agg_month.*`; if absent, user stratification is skipped |
| `file_name` | Optional | Enables file-name-derived metadata such as extension and basename token count |
| `id` | Optional | Preserved when present; useful as a source row identifier |
| `telegram_user_id` | Optional | Preserved when present; not required by current pipeline logic |

More detail: [docs/data-contract.md](docs/data-contract.md)

## Quick Start

Build the image and run a bounded smoke batch:

```bash
docker compose build analytics
docker compose run --rm -e MAX_ROWS=500 analytics
```

Use the fixture file for a minimal end-to-end check:

```bash
docker compose run --rm -e INPUT_CSV=/data/tests/fixtures/sample_multiline.csv -e MAX_ROWS=10 analytics
```

By default:

- the repository is mounted read-only at `/data`
- generated artifacts are written to `./outputs` on the host and `/out` in the container
- if `INPUT_CSV` is unset, the entrypoint auto-detects a single top-level `/data/*.csv`

## Main Commands

| Command | Purpose |
|------|------|
| `ta-batch run -i PATH [-o DIR]` | Run the analytics pipeline |
| `ta-batch staging-parquet -i PATH -o OUT.parquet` | Convert CSV to Parquet without feature extraction |
| `python scripts/build_final_research_report.py --run-id <uuid>` | Build a standalone final HTML report from an existing run |
| `python scripts/build_duration_distribution_report.py --run-id <uuid>` | Build a standalone duration-distribution HTML report (monthly + last 30 days) |
| `python scripts/build_llm_judge_sample.py` | Build a deterministic ChatGPT-ready LLM judge sample packet |
| `python scripts/analyze_llm_judge_output.py` | Summarize ChatGPT judge JSON into CSV and Markdown outputs |
| `python scripts/analyze_raw_transcriptions.py` | Run an ad-hoc raw CSV summary outside the batch pipeline |

## Output Artifacts

Each run creates `outputs/<run_id>/` with:

- `parts/part_*.parquet`
- `time_agg_day.csv|parquet`
- `time_agg_iso_week.csv|parquet`
- `time_agg_month.csv|parquet`
- `time_agg_*_long.csv`
- `language_share_time_agg_*` when Layer B is enabled
- `content_category_share_time_agg_*` when Layer B is enabled
- `file_extension_share_time_agg_month.*` when Layer B is enabled
- `user_time_agg_month.*` unless disabled or the input omits `telegram_user_internal_id`
- `figures/**/*.png`
- `report.html` built-in HTML report, currently Russian-language
- `duration_distribution_report.html` optional standalone duration-distribution report (if built explicitly)
- `duration_distribution_monthly_stats.csv` optional month-level duration stats export (if built explicitly)
- `manifest.json`
- `metrics_dictionary.json`

## Build A Research Report From An Existing Run

Use `scripts/build_final_research_report.py` after `ta-batch run` when you want a single handoff HTML document built from the saved analysis artifacts.

Example:

```powershell
python scripts\build_final_research_report.py --run-id <uuid>
```

The script reads `outputs/<uuid>/` and writes `outputs/final_research_report.html` by default. You can override the destination:

```powershell
python scripts\build_final_research_report.py --run-id <uuid> -o outputs\my_final_report.html
```

You can also provide the run id through `FINAL_REPORT_RUN_ID`:

```powershell
$env:FINAL_REPORT_RUN_ID = "<uuid>"
python scripts\build_final_research_report.py
```

The report is built from analysis outputs already on disk. In the current implementation it requires:

- `manifest.json`
- `metrics_dictionary.json`
- `time_agg_month.csv`
- `content_category_share_time_agg_month.csv`
- `language_share_time_agg_month.csv`
- `figures/**/*.png`

What you get:

- a standalone `final_research_report.html`
- monthly content-category and language summaries rendered with Chart.js in the browser
- daily PNG charts embedded into the HTML as base64 data URIs
- the dedicated daily total-duration chart when `figures/day/layer_a_duration_total_sum_day.png` exists

## Build A Duration Distribution Report From An Existing Run

Use `scripts/build_duration_distribution_report.py` when you need a focused duration analysis with:

- monthly duration distributions
- last-30-days distribution
- variance, standard deviation, and percentiles
- interactive month-distribution charts (legend toggle, zoom, pan, reset zoom)

Example:

```powershell
python scripts\build_duration_distribution_report.py --run-id <uuid>
```

Optional input override:

```powershell
python scripts\build_duration_distribution_report.py `
  --run-id <uuid> `
  --input-csv d:\path\to\transcriptions.csv
```

Outputs inside `outputs/<uuid>/`:

- `duration_distribution_report.html`
- `duration_distribution_monthly_stats.csv`

## Build An LLM Judge Packet

Use `scripts/build_llm_judge_sample.py` when you want a compact file for ChatGPT-based qualitative judging instead of sending the raw CSV.

```powershell
python scripts\build_llm_judge_sample.py
```

Default outputs are written to `outputs/llm_judge/`. For repeatable research runs, use `--run-id` so each packet and returned report has its own folder:

```powershell
python scripts\build_llm_judge_sample.py `
  --output-dir outputs\llm_judge_runs `
  --run-id russian-2026-05-06-r2 `
  --russian-only `
  --exclude-sample-index outputs\llm_judge\llm_judge_sample_index.csv
```

This writes to `outputs/llm_judge_runs/russian-2026-05-06-r2/` and filters the candidate pool to Russian (`ru`) transcripts. `--exclude-sample-index` is optional, but useful when a follow-up run should avoid transcript IDs already used in a previous packet.

Each run folder contains:

- `llm_judge_packet.md`: one ChatGPT-ready file containing the prompt and sampled transcripts
- `llm_judge_prompt.md`: the reusable judging prompt only
- `llm_judge_sample_index.csv`: selected row metadata and sampling reasons
- `llm_judge_transcripts.jsonl`: machine-readable transcript excerpts

The sampler is deterministic by seed and selects a balanced monthly panel using month, content category, script/language proxy, transcript length, speaker structure, and anomaly signals.

After ChatGPT returns JSON, save it as `llm_judge_output.json` inside the same run folder and run:

```powershell
python scripts\analyze_llm_judge_output.py `
  --output-dir outputs\llm_judge_runs `
  --run-id russian-2026-05-06-r2
```

This writes:

- `llm_judge_joined_scores.csv`: one row per judged transcript joined to sample metadata
- `llm_judge_monthly_scores.csv`: monthly means for all samples and representative-only rows
- `llm_judge_failure_modes.csv`: failure-mode counts by month and sample group
- `llm_judge_analysis.md`: compact Markdown analysis report
- `llm_judge_research_report.html`: standalone Russian-language visual research report

## Documentation

- [docs/README.md](docs/README.md): documentation index
- [docs/data-contract.md](docs/data-contract.md): input schema and transcript format
- [docs/architecture.md](docs/architecture.md): pipeline and code structure
- [docs/operations.md](docs/operations.md): Docker, CLI, outputs, troubleshooting
- [docs/development.md](docs/development.md): local development and contributor workflow

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Current Boundaries

The default batch path does not yet include:

- WER, CER, or other reference-based ASR metrics
- human evaluation workflows
- CI automation
- DuckDB-based reporting in the default pipeline

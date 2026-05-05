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

If the source is managed in Excel, export it to CSV first and keep these exact column names:

| Column | Required | Notes |
|------|------|------|
| `id` | Yes | Row identifier |
| `telegram_user_internal_id` | Yes | Internal user key |
| `telegram_user_id` | Yes | Telegram user id |
| `created_at` | Yes | Format: `YYYY-MM-DD HH:MM:SS` |
| `file_name` | Yes | Source file name or path-like reference |
| `transcription_text` | Yes | Full diarized transcript, may span many CSV lines |

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
- `user_time_agg_month.*` unless disabled
- `figures/**/*.png`
- `report.html` built-in HTML report, currently Russian-language
- `manifest.json`
- `metrics_dictionary.json`

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

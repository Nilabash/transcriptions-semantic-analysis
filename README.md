# Transcriptions Analysis

Docker-first analytics for studying how diarized transcription text changes over time.

This repository processes a large CSV export of transcriptions, extracts structural and text-level signals from each transcript, and aggregates those signals by day, ISO week, and month. It is designed for repeatable batch analysis first, with optional notebook-based exploration on top.

## What This Project Does

- Ingests a large UTF-8 BOM CSV with multiline quoted `transcription_text` fields.
- Parses diarized transcript structure such as speaker labels and timestamped segments.
- Computes per-row quality-oriented features.
- Aggregates metrics over time using `created_at`.
- Exports machine-readable artifacts and human-readable reports.

Today the implemented pipeline includes:

- **Layer A:** structural and schema-faithful transcript signals.
- **Layer B:** text statistics, language detection, metadata-derived features, and rule-based content categorization.
- **Visual export:** PNG figures, tidy long-form CSVs, and a single `report.html` artifact.

## Why It Exists

The main goal is to make transcription-quality analysis reproducible on a large historical dataset. The repository is built around a practical workflow:

1. Run the batch pipeline on the source export.
2. Produce stable artifacts for inspection and comparison.
3. Use those artifacts to study quality drift, content-mix changes, and operational anomalies over time.

The current system is descriptive rather than evaluative: it measures observable signals in transcript text and structure, but it does not yet implement reference-based accuracy metrics such as WER/CER.

## Repository Map

| Path | Purpose |
|------|---------|
| `src/transcriptions_analysis/` | Core ingest, parsing, metrics, aggregation, artifacts, and CLI code |
| `scripts/` | Helper scripts such as the final report builder and ad-hoc CSV analysis |
| `tests/` | Pytest coverage for ingest, parsing, metrics, aggregation, and reporting |
| `docs/` | Architecture and operations documentation |
| `outputs/` | Generated run artifacts (gitignored) |

## Quick Start

### Run with Docker Compose

The default workflow is Docker-first.

1. Place one input CSV in the repository root, or set `INPUT_CSV` explicitly.
2. Build the analytics image.
3. Run a bounded batch first to validate the environment.

```bash
docker compose build analytics
docker compose run --rm -e MAX_ROWS=500 analytics
```

By default:

- the repository is mounted read-only at `/data` inside the container
- generated artifacts are written to `./outputs` on the host and `/out` in the container
- if `INPUT_CSV` is unset, the entrypoint auto-detects a single top-level `/data/*.csv`

Smoke test with the fixture dataset:

```bash
docker compose run --rm -e INPUT_CSV=/data/tests/fixtures/sample_multiline.csv -e MAX_ROWS=10 analytics
```

### Expected Output

Each run creates `outputs/<run_id>/` with artifacts such as:

- `parts/part_*.parquet`
- `time_agg_day|iso_week|month.{parquet,csv}`
- `time_agg_day|iso_week|month_long.csv`
- `language_share_time_agg_*.{parquet,csv}` when Layer B is enabled
- `content_category_share_time_agg_*.{parquet,csv}` when Layer B is enabled
- `file_extension_share_time_agg_month.{parquet,csv}` when Layer B is enabled
- `user_time_agg_month.{parquet,csv}` unless disabled
- `figures/**/*.png`
- `report.html`
- `manifest.json`
- `metrics_dictionary.json`

## CLI

The package exposes `ta-batch`:

| Command | Purpose |
|---------|---------|
| `ta-batch run -i PATH [-o DIR]` | Run the batch pipeline on a CSV |
| `ta-batch staging-parquet -i PATH -o OUT.parquet` | Convert CSV to staged Parquet without metric extraction |

Common options on `ta-batch run` include:

- `--max-rows` for bounded smoke runs
- `--batch-size` to reduce peak memory pressure
- `--no-layer-b` for faster Layer A-only runs
- `--no-user-stratify` to skip per-user monthly aggregates
- `--no-export-report` to skip figures and HTML output
- `--total-rows` or inferred row counting for ETA support

Run `ta-batch run --help` for the full flag set.

## Final Research Report

You can build a standalone final HTML report from an existing run:

```powershell
python scripts\build_final_research_report.py --run-id <uuid>
```

Optional output path:

```powershell
python scripts\build_final_research_report.py --run-id <uuid> -o outputs\my_final_report.html
```

The builder expects a completed run under `outputs/<uuid>/` and embeds daily PNG figures directly into the HTML as base64 data URIs.

## Local Development

Python `3.11+` is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ta-batch run --help
```

Key dependencies:

- `polars[rtcompat]`
- `lingua-language-detector`
- `matplotlib`
- `duckdb` for future SQL-on-Parquet workflows

## Testing

The repository includes pytest coverage for:

- multiline CSV ingest
- diarized transcript parsing
- Layer A and Layer B metrics
- categorical aggregation
- progress display
- visual-report generation

Run locally:

```powershell
pytest
```

Run inside Docker:

```bash
docker compose run --rm --entrypoint python analytics -m pytest /workspace/tests
```

## Documentation

- [docs/README.md](docs/README.md): documentation hub
- [docs/architecture.md](docs/architecture.md): pipeline, modules, and outputs
- [docs/operations.md](docs/operations.md): Docker, CLI, environment variables, and troubleshooting

## Current Boundaries

The current batch path does **not** yet implement:

- reference-based quality metrics such as WER/CER
- Layer C or human-in-the-loop evaluation workflows
- CI/CD automation
- productionized DuckDB query flows in the default pipeline

Those ideas are tracked in the architecture and operations docs, but the README reflects only what is implemented today.

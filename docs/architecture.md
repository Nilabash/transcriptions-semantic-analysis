# Architecture

## Scope

The repository implements a Docker-first batch pipeline for one large CSV export of diarized transcriptions.

Current implemented layers:

- Layer A: structural transcript metrics
- Layer B: text, language, script, metadata, and content-category metrics
- Visual export: long CSV, PNG charts, and `report.html`

## Pipeline

```text
CSV -> batched ingest -> transcript parsing -> Layer A/B features
    -> part Parquet files -> time aggregates -> optional share tables
    -> manifest + metrics dictionary -> visual bundle
```

## Processing Stages

1. Ingest
   Reads the CSV in logical-row batches with Polars so multiline transcript cells remain intact.
2. Parse
   Extracts speaker blocks, timestamps, and segment bodies from `transcription_text`.
3. Feature extraction
   Computes Layer A metrics and optional Layer B metrics for each row.
4. Persist
   Writes per-batch Parquet parts under `outputs/<run_id>/parts/`.
5. Aggregate
   Buckets rows by day, ISO week, and month using `created_at`.
6. Export
   Writes CSV, Parquet, PNG, HTML, and provenance artifacts.

## Main Modules

| Module | Responsibility |
|------|------|
| `ingest.py` | CSV reading, BOM normalization, fast row counting, input fingerprinting |
| `text_format.py` | Transcript parsing for separators, speakers, and timestamps |
| `metrics_layer_a.py` | Structural metrics per transcript |
| `metrics_layer_b.py` | Text, language, script, metadata, and content-category metrics |
| `aggregate.py` | Time buckets and aggregate tables |
| `artifacts.py` | `manifest.json` and `metrics_dictionary.json` |
| `visual_report.py` | Long CSV, PNG charts, `report.html` |
| `cli.py` | `ta-batch` commands |

## Time Buckets

All aggregation is based on parsed `created_at`:

- day: truncated datetime
- ISO week: `%G-W%V`
- month: first day of month

Timestamps are currently treated as naive datetimes.

## Output Model

The pipeline produces:

- per-row batch parts
- numeric time aggregates
- categorical share tables
- optional per-user monthly aggregates when `telegram_user_internal_id` is present
- reproducibility metadata
- human-readable charts and HTML

## Layer Summary

### Layer A

Examples:

- segment count
- distinct speaker count
- malformed timestamp ratio
- speaker switch count
- duplicate adjacent segment ratio
- duration covered seconds (sum of valid segment durations)
- duration span seconds (max end minus min start)
- duration coverage ratio
- ratio of segments with valid positive durations

### Layer B

Examples:

- Unicode oddity counts
- token diversity and entropy
- language detection
- script ratios
- file-name metadata
- `content_primary_category`
- `content_category_confidence`

## Built-in Report

The default visual bundle writes:

- `time_agg_*_long.csv`
- PNG charts for day, ISO week, and month
- `report.html`
- dedicated daily total-duration chart: `figures/day/layer_a_duration_total_sum_day.png` (sum over rows by day)

The built-in `report.html` is a compact human-facing summary generated from run artifacts. The current implementation is Russian-language and focuses on daily metric charts and daily language-share visualization when Layer B is enabled.

## Non-Goals In Current Code

The default pipeline does not yet implement:

- reference-based transcription accuracy metrics
- human evaluation loops
- CI-driven production workflows
- DuckDB-powered reporting as part of the main run path

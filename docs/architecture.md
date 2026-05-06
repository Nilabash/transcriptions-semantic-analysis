# Architecture

## Scope

The repository implements a Docker-first batch pipeline for one large CSV export of diarized transcriptions.

Current implemented layers:

- Layer A: structural transcript metrics
- Layer B: text, language, script, metadata, and content-category metrics
- Visual export: long CSV, PNG charts, and `report.html`
- Research handoff export: standalone `final_research_report.html` built from a completed run folder
- LLM judge handoff: deterministic monthly sample packet for ChatGPT-based qualitative review

## Pipeline

```text
CSV -> batched ingest -> transcript parsing -> Layer A/B features
    -> part Parquet files -> time aggregates -> optional share tables
    -> manifest + metrics dictionary -> visual bundle
    -> optional final research report build from outputs/<run_id>/
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

## Reporting Layers

The repository has two HTML reporting surfaces:

- `report.html`: built automatically by `ta-batch run` from run artifacts; compact, Russian-language, and centered on daily charts
- `final_research_report.html`: built later by `scripts/build_final_research_report.py` from an existing `outputs/<run_id>/`; intended as a standalone research handoff
- `duration_distribution_report.html`: built by `scripts/build_duration_distribution_report.py` from an existing `outputs/<run_id>/`; focused on duration distribution and last-30-days analysis

The final research report reuses saved aggregates instead of recomputing features. It reads `manifest.json`, `metrics_dictionary.json`, monthly share CSVs, `time_agg_month.csv`, and PNG figures from the completed run folder.

The duration distribution report reuses run metadata (`manifest.json`) but recomputes per-row duration from source text (`compute_layer_a_for_text`) over the run date window. It then writes a run-scoped HTML plus `duration_distribution_monthly_stats.csv` with percentiles, variance, and standard deviation.

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

The separate LLM judge sampler reads the raw CSV directly, uses fast Layer A/B style feature proxies for monthly balancing, and writes `llm_judge_packet.md` plus audit files. By default it writes to `outputs/llm_judge/`; for independent research passes it supports `--run-id` child folders such as `outputs/llm_judge_runs/russian-2026-05-06-r2/`. It does not change the main `ta-batch run` artifact contract.

The sampler can filter the candidate pool for Russian transcripts with `--russian-only` (`--language-filter ru`) and can skip transcript IDs from prior `llm_judge_sample_index.csv` files with `--exclude-sample-index`, which is useful for second-pass sampling.

After external ChatGPT judging, `scripts/analyze_llm_judge_output.py` validates the returned JSON, joins transcript scores back to `llm_judge_sample_index.csv`, and writes joined score, monthly score, failure-mode, Markdown analysis, and standalone visual HTML report artifacts into the same resolved judge run folder.

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

The separate `final_research_report.html` is a second-stage artifact. It embeds daily PNG figures as base64 data URIs and adds a broader research-style narrative based on the monthly aggregate CSVs and share tables in `outputs/<run_id>/`.

## Non-Goals In Current Code

The default pipeline does not yet implement:

- reference-based transcription accuracy metrics
- human evaluation loops
- CI-driven production workflows
- DuckDB-powered reporting as part of the main run path

The LLM judge packet is a handoff artifact for external model review. The repository can summarize the returned judge JSON, but it does not yet merge those scores into the main `ta-batch run` reports.

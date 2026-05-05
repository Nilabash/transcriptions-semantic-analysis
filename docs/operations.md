# Operations

## Docker Compose (`analytics` service)

Default layout:

- Host repository root is mounted **read-only** at **`/data`** (CSV and tests).
- **`./outputs`** on the host is mounted read-write at **`/out`**.

The shell entrypoint builds a `ta-batch run` command from environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `INPUT_CSV` | *(auto-detect)* | Input CSV path **inside the container**. If unset, the entrypoint uses the only top-level `*.csv` under `/data`; otherwise it fails and asks you to set `INPUT_CSV`. |
| `OUTPUT_DIR` | `/out` | Root directory for runs (`/out/<run_id>/…`) |
| `MAX_ROWS` | *(unset)* | If set, cap total rows processed (smoke tests) |
| `BATCH_SIZE` | *(unset)* | If set, passed as `--batch-size` (Polars CSV logical rows per chunk; lower → less peak RAM on wide text) |
| `RUN_ID` | *(unset)* | If set, fixed run folder name under `OUTPUT_DIR` |
| `TOTAL_ROWS` | *(unset)* | Passed through as `ta-batch run --total-rows`; skips inferred row tally when set |
| `PROGRESS` | *(unset)* | `1` → `--progress`; `0` → `--no-progress`. Default: progress on when stderr is a TTY |
| `INFER_TOTAL_ROWS` | *(unset)* | `1` → `--infer-total-rows`; `0` → `--no-infer-total-rows`. Default tally: **on** when progress is enabled and neither `TOTAL_ROWS` nor `MAX_ROWS` is set (streams **column 0** only once to count logical rows). |
| `LAYER_B` | *(unset)* | `0` → `--no-layer-b` (Layer A only; skip Layer B and content columns). |
| `LANG_DETECT_MAX_CHARS` | *(unset)* | Passed as `--lang-detect-max-chars` (cap text sent to lingua; default CLI `4000`). |
| `LANG_DETECT_LANGUAGES` | *(unset)* | Comma-separated ISO 639-1 codes for lingua allow-list (e.g. `en,ru,uk`). |
| `USER_STRATIFY` | *(unset)* | `0` → `--no-user-stratify` (skip `user_time_agg_month.*`). |
| `EXPORT_REPORT` | *(unset)* | `0` → `--no-export-report` (skip PNG figures, long CSV reshapes, `report.html`). Charts are on by default. |
| `DOCKER_IMAGE_DIGEST` | *(unset)* | Optional; propagated into `manifest.json` when injected by orchestration |

**Progress and ETA:** With an interactive terminal, `ta-batch run` prints `[ta-batch]` lines on stderr during the **read_phase**: per-batch row counts, cumulative rows/s, elapsed, **ETA**.

**Full export row count:** If `TOTAL_ROWS` and `MAX_ROWS` are unset, the CLI **automatically streams the first CSV column only** (`id` from the input schema — **count_phase**) once to tally logical rows, then uses that for ETA. This pass still parses quoted multiline fields correctly on column 0 but avoids loading mega `transcription_text` payloads. Omit with `--no-infer-total-rows` / `INFER_TOTAL_ROWS=0` if you add `--total-rows` instead.

ETA uses **cumulative average** throughput across read_phase batches. The later **aggregate** phase (scan part Parquets, buckets, manifests) adds extra wall time logged separately — total runtime can exceed the read-phase ETA.

**`--max-rows` / `MAX_ROWS` and ETA:** When a row cap is set, the **count_phase** (column-0 logical row tally) is **skipped**, so the ETA row target is **`MAX_ROWS`**, not how many rows the file actually contains. A tiny fixture with two rows still shows an ETA toward the cap (e.g. `left~2998`) until processing stops; the **first batch** often has low rows/s (cold start), so that ETA is especially pessimistic. Omit `--max-rows` on a TTY for auto-inferred count, or pass **`--total-rows`** / **`TOTAL_ROWS`** when you know the logical row count. **`visual_report`** time is also **not** included in read-phase ETA.

**Examples:**

```bash
docker compose build analytics
docker compose run --rm -e MAX_ROWS=500 analytics
docker compose run --rm -e INPUT_CSV=/data/tests/fixtures/sample_multiline.csv -e MAX_ROWS=10 analytics
```

**Tests inside the image** (filesystem is `/workspace` at build time; image includes `tests/`):

```bash
docker compose run --rm --entrypoint python analytics -m pytest /workspace/tests
```

Lint (example; may require `--user root` if cache dirs are not writable):

```bash
docker compose run --rm --user 0:0 --workdir /workspace --entrypoint ruff analytics check src tests
```

## Jupyter (`notebook` profile)

```bash
docker compose --profile notebook up notebook
```

- Port: **`8888`** (override host side with `JUPYTER_PORT`).
- Token: optional `JUPYTER_TOKEN`; empty disables token auth (suitable **only** for trusted local use).

## CLI: `ta-batch` (local or container)

Installation: project package exposes console script **`ta-batch`** (`pyproject.toml`).

### `ta-batch run`

| Flag | Description |
|------|-------------|
| `-i` / `--input` | Path to UTF-8 BOM CSV (required) |
| `-o` / `--output-dir` | Output root (default `outputs`) |
| `--run-id` | Optional; default UUID |
| `--max-rows` | Optional cap |
| `--batch-size` | Polars CSV logical rows per chunk (default `4096`; lower reduces peak memory on wide `transcription_text` + Layer B) |
| `--merge-per-row-parquet` | Write single `per_row_features.parquet` when total rows ≤ `--merge-max-rows` |
| `--merge-max-rows` | Default `200000` |
| `--infer-total-rows` | Force **count_phase** before read (logical rows via column 0). Default behavior when neither `--total-rows` nor `--max-rows` is set and progress is enabled. |
| `--no-infer-total-rows` | Skip count pass (needs `--total-rows` for full-run ETA unless only `--max-rows` is used). |
| `--total-rows N` | Fixed row total for ETA; skips inferred count |
| `--progress` / `--no-progress` | Force human progress on stderr, or disable (default: on if stderr is a TTY) |
| `--no-layer-b` | Skip Layer B and content-characterization columns (faster; Layer A only). |
| `--lang-detect-max-chars N` | Max characters of segment-body text passed to lingua (default `4000`). |
| `--lang-detect-languages LIST` | Comma-separated ISO 639-1 allow-list for lingua (default `en,ru,uk,de,pl,be`). |
| `--no-user-stratify` | Do not write `user_time_agg_month.{parquet,csv}`. |
| `--export-report` / `--no-export-report` | Write (default) or skip **visual export**: `time_agg_{day,iso_week,month}_long.csv`, `figures/**`, `report.html` (RU — **day-only** charts in the HTML; week/month PNGs still written to `figures/`). |

Structured logs use **`event=key value`** lines on stderr (see `logging_utils.log_kv`). Human progress lines are separate `[ta-batch] …` lines on stderr.

### `ta-batch staging-parquet`

Loads CSV in batches (respecting multiline fields), writes **one** Parquet via **temp part files + merge** (`sink_parquet` when possible) so RAM stays proportional to batch size, not entire input: `-i`, `-o`, optional `--max-rows`, `--batch-size`.

## Output layout (`<output-dir>/<run_id>/`)

| Path | Purpose |
|------|---------|
| `parts/part_*.parquet` | Per-batch rows + Layer A (+ optional Layer B) columns + parsed `created_at` |
| `time_agg_day.{parquet,csv}` | Daily buckets (numeric metrics: Layer A + Layer B when enabled) |
| `time_agg_iso_week.{parquet,csv}` | ISO week buckets (`%G-W%V`) |
| `time_agg_month.{parquet,csv}` | Calendar month buckets |
| `time_agg_{day,iso_week,month}_long.csv` | **Tidy** CSV: one row per bucket × metric (`time_bucket`, `metric`, `median`, `q1`, `q3`, `n_rows_per_bucket`) — easier for spreadsheets than wide tables |
| `figures/{day,iso_week,month}/*.png` | Per-metric trend plots: median line, Q1–Q3 band, transcript count bars |
| `figures/language_share_day.png` | Stacked language share **by day** (Layer B only); embedded in `report.html` |
| `report.html` | **Single** human report (RU): manifest summary, daily language mix (Layer B), **day** metric trend PNGs with captions from `metrics_dictionary.json` **`description_ru`** |
| `language_share_time_agg_{day,iso_week,month}.{parquet,csv}` | Per-bucket row share by `layer_b_primary_language` (Layer B only) |
| `content_category_share_time_agg_{day,iso_week,month}.{parquet,csv}` | Per-bucket row share by `content_primary_category` (Layer B only; rule-based classifier in `content_category.py`) |
| `file_extension_share_time_agg_month.{parquet,csv}` | Per calendar month row share by `content_file_extension` (Layer B only) |
| `user_time_agg_month.{parquet,csv}` | Per `telegram_user_internal_id` × month medians/IQR/N (unless `--no-user-stratify`) |
| `manifest.json` | Run metadata, input fingerprint, counts, naive `created_at` min/max, lock hash |
| `metrics_dictionary.json` | Names, units, layer, descriptions for Layer A, B, and content metrics |

Optional: `per_row_features.parquet` when merge flags allow.

## Build final research report from an existing run

Script:

```powershell
python scripts\build_final_research_report.py --run-id <uuid>
```

Optional output path:

```powershell
python scripts\build_final_research_report.py --run-id <uuid> -o outputs\my_final_report.html
```

Behavior and requirements:

- `--run-id` can be supplied by `FINAL_REPORT_RUN_ID`.
- Script validates that `outputs/<uuid>/manifest.json` exists.
- Expected run artifacts: monthly content/language share CSVs, `metrics_dictionary.json`, and figure PNG files under `figures/`.
- Daily plot images are embedded into the final HTML as base64 data URIs, so the resulting file is self-contained for image assets.

## Troubleshooting

### Very large CSV: container exits or “unexpected EOF”

Full-file scans are **memory- and time-sensitive**. Prefer:

- Bounded runs: **`MAX_ROWS`** while validating the pipeline.
- Fixture smoke: **`INPUT_CSV=/data/tests/fixtures/sample_multiline.csv`**.
- Lower **`BATCH_SIZE`** / `--batch-size` (e.g. `2048`, `1024`) if **Layer B** + wide text causes OOM mid-`read_phase` (default Docker/CLI is **4096** logical rows per Polars chunk).
- Increased Docker Desktop **memory limits** when processing the production export without a row cap.

### Windows: Polars CPU / import warnings

`pyproject.toml` depends on **`polars[rtcompat]`** for broader CPU compatibility outside Docker. The **Linux** image uses standard Polars wheels suitable for typical server CPUs.

### `pytest` cache permission warnings

If the container user cannot write `.pytest_cache` under `/workspace`, either ignore the warning or run pytest with cache disabled / as a user that owns the mount.

### Image build: `ImportError: cannot import name 'main'` from `ta-batch`

That almost always means **`transcriptions_analysis.cli` loaded as an empty module** because a **cached `COPY src`** layer once baked **zero-byte** (or truncated) files — often after Docker Desktop / BuildKit glitches or interrupted builds.

Fix:

1. On the host confirm `src/transcriptions_analysis/cli.py` is non-empty (tens of KiB).
2. Rebuild **without** reuse of bad layers: **`docker compose build --no-cache analytics`**.
3. The **Dockerfile** now **fails the build** if `cli.py` is suspiciously small or missing `def main`, so a bad layer should not produce a “successful” image again.

If **`pytest` exits in ~0.01s** with no `N passed` line, **no tests ran** (usually the same broken image / failed collection). After a clean rebuild, expect **`34 passed`** (or current count) from:

`docker compose run --rm --entrypoint python analytics -m pytest /workspace/tests -q`

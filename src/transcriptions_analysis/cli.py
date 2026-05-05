"""CLI entrypoint for batch analytics."""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.exceptions as pl_exc

from transcriptions_analysis import __version__ as pkg_version
from transcriptions_analysis.aggregate import (
    NUMERIC_LAYER_A,
    NUMERIC_LAYER_AB,
    TIME_AGG_SKIP_METRICS,
    aggregate_bucket,
    aggregate_categorical_share,
    aggregate_user_month,
    parse_created_at_column,
    with_time_bucket_columns,
)
from transcriptions_analysis.artifacts import (
    RunManifest,
    combined_metrics_definition_version,
    docker_digest_from_env,
    lockfile_hash,
    utc_now_iso,
    write_manifest,
    write_metrics_dictionary,
)
from transcriptions_analysis.content_language import parse_iso_codes_csv
from transcriptions_analysis.ingest import (
    DEFAULT_CSV_BATCH_ROWS,
    count_csv_logical_rows_first_column,
    file_fingerprint,
    missing_required_columns,
    read_csv_batches,
)
from transcriptions_analysis.logging_utils import configure_logging, log_kv
from transcriptions_analysis.metrics_layer_a import (
    compute_layer_a_for_parsed,
    empty_layer_a,
)
from transcriptions_analysis.metrics_layer_b import compute_layer_b_for_row, empty_layer_b
from transcriptions_analysis.progress_display import (
    emit_batch_progress,
    emit_phase_line,
    format_duration,
    progress_target_rows,
    stderr_progress_enabled,
)
from transcriptions_analysis.text_format import parse_segments
from transcriptions_analysis.visual_report import export_visual_bundle


def _progress_flags(args: argparse.Namespace) -> bool:
    if getattr(args, "progress", False) and getattr(args, "no_progress", False):
        print("Cannot combine --progress with --no-progress.", file=sys.stderr)
        raise SystemExit(2)
    return stderr_progress_enabled(
        getattr(args, "progress", False),
        getattr(args, "no_progress", False),
    )


def _infer_total_rows_flag(args: argparse.Namespace, show_progress: bool) -> bool:
    """
    Scan column 0 once to tally rows for ETA when no explicit target exists.

    Off when ``--total-rows`` or ``--max-rows`` is set, or ``--no-infer-total-rows``.
    On by default when progress is enabled (typically TTY) and user did not disable infer.
    """
    if getattr(args, "no_infer_total_rows", False):
        return False
    if args.total_rows is not None or args.max_rows is not None:
        return False
    if getattr(args, "infer_total_rows", False):
        return True
    return show_progress


def _collect_lazy_materialize(lf: pl.LazyFrame) -> pl.DataFrame:
    """Prefer Polars streaming engine to cap aggregate-phase memory where supported."""
    try:
        return lf.collect(engine="streaming")
    except (TypeError, ValueError, pl_exc.PolarsError):
        return lf.collect()


def _format_ts(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    s = ts.strftime("%Y-%m-%d %H:%M:%S")
    return s


def _build_feature_frame(
    df: pl.DataFrame,
    *,
    layer_b: bool,
    lang_max_chars: int,
    lang_iso_codes: tuple[str, ...],
) -> pl.DataFrame:
    """Compute Layer A (+ optional Layer B) dicts and horizontal-concat feature columns."""
    texts = df["transcription_text"].to_list()
    names = df["file_name"].to_list() if "file_name" in df.columns else [None] * len(texts)

    rows_a: list[dict] = []
    rows_b: list[dict] = []
    for t, fn in zip(texts, names, strict=True):
        if t is None or (isinstance(t, str) and not str(t).strip()):
            rows_a.append(empty_layer_a())
            if layer_b:
                rows_b.append(empty_layer_b(fn))
            continue
        t_str = str(t)
        segs = parse_segments(t_str)
        rows_a.append(compute_layer_a_for_parsed(t_str, segs))
        if layer_b:
            rows_b.append(
                compute_layer_b_for_row(
                    t_str,
                    fn,
                    segments=segs,
                    max_chars=lang_max_chars,
                    iso_codes=lang_iso_codes,
                )
            )

    feat_a = pl.DataFrame(rows_a)
    feat_a = feat_a.with_columns(
        pl.col("layer_a_unreasonable_speaker_churn").cast(pl.Int8),
    )
    if not layer_b:
        return pl.concat([df, feat_a], how="horizontal")

    feat_b = pl.DataFrame(rows_b)
    feat_b = feat_b.with_columns(
        pl.col("layer_b_language_mixed").cast(pl.Int8),
    )
    return pl.concat([df, feat_a, feat_b], how="horizontal")


def cmd_run(args: argparse.Namespace) -> int:
    configure_logging(logging.INFO)
    if int(args.batch_size) < 1:
        print("--batch-size must be >= 1.", file=sys.stderr)
        raise SystemExit(2)
    if getattr(args, "infer_total_rows", False) and getattr(args, "no_infer_total_rows", False):
        print("Cannot combine --infer-total-rows with --no-infer-total-rows.", file=sys.stderr)
        raise SystemExit(2)
    input_path = Path(args.input)
    out_root = Path(args.output_dir)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = out_root / run_id
    parts_dir = run_dir / "parts"
    run_dir.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)

    log_kv(event="run_start", run_id=run_id, input=str(input_path))

    layer_b_enabled = not getattr(args, "no_layer_b", False)
    lang_max_chars = int(getattr(args, "lang_detect_max_chars", 4000))
    lang_iso_codes = parse_iso_codes_csv(getattr(args, "lang_detect_languages", None))

    show_progress = _progress_flags(args)
    fp = file_fingerprint(input_path)
    file_mb = None
    sz = fp.get("size_bytes")
    if isinstance(sz, int) and sz >= 0:
        file_mb = sz / (1024 * 1024)
    repo_root = Path(__file__).resolve().parents[2]

    infer_rows = _infer_total_rows_flag(args, show_progress)
    row_total_for_eta: int | None = args.total_rows
    if infer_rows:
        bs = max(int(args.batch_size), 256)
        if show_progress:
            emit_phase_line(
                "count_phase: tally logical rows (first CSV column only; skips heavy fields) …"
            )
        t_count0 = time.perf_counter()
        row_total_for_eta = count_csv_logical_rows_first_column(input_path, batch_size=bs)
        count_wall = time.perf_counter() - t_count0
        log_kv(
            event="row_count_inferred",
            logical_rows=row_total_for_eta,
            count_wall_s=round(count_wall, 3),
        )
        if show_progress:
            emit_phase_line(
                f"count_phase: logical_rows={row_total_for_eta} "
                f"wall={format_duration(count_wall)}"
            )

    eta_target_rows = progress_target_rows(row_total_for_eta, args.max_rows)

    rows_read = 0
    dropped_ts = 0
    created_min_ts: datetime | None = None
    created_max_ts: datetime | None = None
    user_stratify_requested = not getattr(args, "no_user_stratify", False)
    user_stratify_available: bool | None = None

    t_run0 = time.perf_counter()
    batch_idx = 0
    if show_progress:
        hint = "read_phase: wide CSV batches + Layer A"
        if layer_b_enabled:
            hint += " + Layer B"
        hint += " + part Parquet."
        if file_mb is not None:
            hint += f" Input ~{file_mb:.1f} MiB."
        emit_phase_line(hint)
        if eta_target_rows is None:
            emit_phase_line(
                "ETA: pass --total-rows, enable --infer-total-rows, or omit --no-infer "
                "(auto-infers when stderr is a TTY)."
            )
        elif args.max_rows is not None and row_total_for_eta is None:
            emit_phase_line(
                "ETA: using --max-rows as row target (infer disabled with --max-rows). "
                "Short files finish sooner than ETA; early batches are slow until warm. "
                "For file-accurate ETA on a TTY omit --max-rows, or pass --total-rows."
            )

    for batch in read_csv_batches(
        input_path,
        batch_size=args.batch_size,
        max_rows=args.max_rows,
    ):
        t_batch0 = time.perf_counter()
        missing = missing_required_columns(batch.columns)
        if missing:
            msg = f"CSV missing required columns: {missing}"
            raise ValueError(msg)
        if user_stratify_available is None:
            user_stratify_available = "telegram_user_internal_id" in batch.columns
            if user_stratify_requested and not user_stratify_available:
                logging.getLogger("ta").warning(
                    "user_time_agg_month skipped: input is missing telegram_user_internal_id"
                )
                if show_progress:
                    emit_phase_line(
                        "aggregate_phase: skip user_time_agg_month "
                        "(missing telegram_user_internal_id)."
                    )

        enriched = _build_feature_frame(
            batch,
            layer_b=layer_b_enabled,
            lang_max_chars=lang_max_chars,
            lang_iso_codes=lang_iso_codes,
        )
        enriched = parse_created_at_column(enriched)
        dropped_ts += int(enriched["created_at_parsed"].null_count())

        valid = enriched.filter(pl.col("created_at_parsed").is_not_null())
        if len(valid) > 0:
            cmin = valid["created_at_parsed"].min()
            cmax = valid["created_at_parsed"].max()
            if cmin is not None:
                if created_min_ts is None or cmin < created_min_ts:
                    created_min_ts = cmin
            if cmax is not None:
                if created_max_ts is None or cmax > created_max_ts:
                    created_max_ts = cmax

        part_path = parts_dir / f"part_{batch_idx:05d}.parquet"
        enriched.write_parquet(part_path, compression="zstd")
        rows_read += len(enriched)
        batch_idx += 1
        log_kv(
            event="batch_written",
            index=batch_idx,
            rows_batch=len(enriched),
            rows_total=rows_read,
        )
        if show_progress:
            elapsed = time.perf_counter() - t_run0
            batch_wall = time.perf_counter() - t_batch0
            emit_batch_progress(
                phase="read_phase",
                batch_number=batch_idx,
                rows_delta=len(enriched),
                rows_total=rows_read,
                batch_wall_s=batch_wall,
                elapsed_s=elapsed,
                target_rows=eta_target_rows,
                file_mb=file_mb,
            )

    if rows_read == 0:
        logging.getLogger("ta").warning("No rows read; empty CSV or max_rows=0")
        manifest = RunManifest(
            run_id=run_id,
            created_utc=utc_now_iso(),
            package_version=pkg_version,
            metrics_definition_version=combined_metrics_definition_version(layer_b_enabled),
            input_snapshot=fp,
            rows_read=0,
            rows_dropped_null_ts=0,
            created_at_min=None,
            created_at_max=None,
            dependency_lock_hash=lockfile_hash(repo_root),
            git_commit=_git_head(),
            docker_image_digest=docker_digest_from_env(),
            notes=(
                "created_at treated as naive wall time; timezone policy TBD. "
                "See project-context §5.3."
            ),
        )
        write_manifest(run_dir / "manifest.json", manifest)
        write_metrics_dictionary(run_dir / "metrics_dictionary.json")
        return 0

    parts = sorted(parts_dir.glob("part_*.parquet"))
    if show_progress:
        emit_phase_line(f"aggregate_phase: scan {len(parts)} part files · bucket + write …")
    t_agg0 = time.perf_counter()
    lf = pl.scan_parquet(parts)
    lf_valid = lf.filter(pl.col("created_at_parsed").is_not_null())
    df_b = with_time_bucket_columns(_collect_lazy_materialize(lf_valid))

    numeric_union = NUMERIC_LAYER_AB if layer_b_enabled else NUMERIC_LAYER_A
    metrics_cols = [
        c
        for c in numeric_union
        if c in df_b.columns and c not in TIME_AGG_SKIP_METRICS
    ]
    if "layer_a_unreasonable_speaker_churn" in df_b.columns:
        df_b = df_b.with_columns(pl.col("layer_a_unreasonable_speaker_churn").cast(pl.Float64))
    if "layer_b_language_mixed" in df_b.columns:
        df_b = df_b.with_columns(pl.col("layer_b_language_mixed").cast(pl.Float64))

    for bucket in ("bucket_day", "bucket_iso_week", "bucket_month"):
        agg = aggregate_bucket(df_b, bucket_col=bucket, metric_cols=metrics_cols)
        name = bucket.replace("bucket_", "")
        agg.write_parquet(run_dir / f"time_agg_{name}.parquet", compression="zstd")
        agg.write_csv(run_dir / f"time_agg_{name}.csv")

    if layer_b_enabled:
        for bucket in ("bucket_day", "bucket_iso_week", "bucket_month"):
            lang_sh = aggregate_categorical_share(
                df_b,
                bucket_col=bucket,
                category_col="layer_b_primary_language",
            )
            bname = bucket.replace("bucket_", "")
            lang_sh.write_parquet(
                run_dir / f"language_share_time_agg_{bname}.parquet",
                compression="zstd",
            )
            lang_sh.write_csv(run_dir / f"language_share_time_agg_{bname}.csv")

        # Content category shares (new in layer_b_v2) - shows what users were transcribing over time
        for bucket in ("bucket_day", "bucket_iso_week", "bucket_month"):
            cat_sh = aggregate_categorical_share(
                df_b,
                bucket_col=bucket,
                category_col="content_primary_category",
            )
            bname = bucket.replace("bucket_", "")
            cat_sh.write_parquet(
                run_dir / f"content_category_share_time_agg_{bname}.parquet",
                compression="zstd",
            )
            cat_sh.write_csv(run_dir / f"content_category_share_time_agg_{bname}.csv")

        ext_sh = aggregate_categorical_share(
            df_b,
            bucket_col="bucket_month",
            category_col="content_file_extension",
        )
        ext_sh.write_parquet(
            run_dir / "file_extension_share_time_agg_month.parquet",
            compression="zstd",
        )
        ext_sh.write_csv(run_dir / "file_extension_share_time_agg_month.csv")

    if user_stratify_requested and user_stratify_available:
        user_m = aggregate_user_month(df_b, metric_cols=metrics_cols)
        user_m.write_parquet(run_dir / "user_time_agg_month.parquet", compression="zstd")
        user_m.write_csv(run_dir / "user_time_agg_month.csv")

    if args.merge_per_row_parquet and rows_read <= args.merge_max_rows:
        full = _collect_lazy_materialize(pl.scan_parquet(parts))
        full.write_parquet(run_dir / "per_row_features.parquet", compression="zstd")

    if show_progress:
        emit_phase_line(
            f"aggregate_phase: done wall={format_duration(time.perf_counter() - t_agg0)} "
            f"(excludes read_phase; total_run~{format_duration(time.perf_counter() - t_run0)})"
        )

    manifest = RunManifest(
        run_id=run_id,
        created_utc=utc_now_iso(),
        package_version=pkg_version,
        metrics_definition_version=combined_metrics_definition_version(layer_b_enabled),
        input_snapshot=fp,
        rows_read=rows_read,
        rows_dropped_null_ts=dropped_ts,
        created_at_min=_format_ts(created_min_ts),
        created_at_max=_format_ts(created_max_ts),
        dependency_lock_hash=lockfile_hash(repo_root),
        git_commit=_git_head(),
        docker_image_digest=docker_digest_from_env(),
        notes=(
            "created_at treated as naive wall time; timezone policy TBD. "
            "See project-context §5.3."
        ),
    )
    write_manifest(run_dir / "manifest.json", manifest)
    write_metrics_dictionary(run_dir / "metrics_dictionary.json")

    if getattr(args, "export_report", True):
        try:
            export_visual_bundle(
                run_dir,
                include_buckets=("day", "iso_week", "month"),
                layer_b=layer_b_enabled,
                show_progress=show_progress,
            )
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            logging.getLogger("ta").warning("visual_export_failed error=%s", exc, exc_info=True)

    log_kv(event="run_complete", run_id=run_id, rows_read=rows_read, output=str(run_dir))
    return 0


def _git_head() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            or None
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def cmd_to_parquet(args: argparse.Namespace) -> int:
    """Optional staging: write Polars Parquet from CSV without full Layer A pass."""
    configure_logging(logging.INFO)
    if int(args.batch_size) < 1:
        print("--batch-size must be >= 1.", file=sys.stderr)
        raise SystemExit(2)
    show_progress = _progress_flags(args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fp = file_fingerprint(args.input)
    file_mb = fp.get("size_bytes")
    file_mb_f = (file_mb / (1024 * 1024)) if isinstance(file_mb, int) else None
    eta_target = progress_target_rows(None, args.max_rows)
    t0 = time.perf_counter()

    total = 0
    batch_idx = 0
    if show_progress:
        emit_phase_line(
            "staging-parquet: CSV → temp part Parquet rows (bounded RAM), then merge to one file."
        )
        if eta_target is None:
            emit_phase_line("ETA: pass --max-rows for a row cap/ETA, or expect unknown total.")

    comp = "zstd"
    with tempfile.TemporaryDirectory(prefix="ta-staging-parquet-") as tmp:
        tmp_parts = Path(tmp)
        for batch in read_csv_batches(
            args.input,
            batch_size=args.batch_size,
            max_rows=args.max_rows,
        ):
            t_b = time.perf_counter()
            part_path = tmp_parts / f"part_{batch_idx:05d}.parquet"
            batch.write_parquet(part_path, compression=comp)
            total += len(batch)
            batch_idx += 1
            if show_progress:
                elapsed = time.perf_counter() - t0
                emit_batch_progress(
                    phase="staging",
                    batch_number=batch_idx,
                    rows_delta=len(batch),
                    rows_total=total,
                    batch_wall_s=time.perf_counter() - t_b,
                    elapsed_s=elapsed,
                    target_rows=eta_target,
                    file_mb=file_mb_f,
                )
        if batch_idx == 0:
            log_kv(event="staging_empty", output=str(out))
            return 0
        part_files = sorted(tmp_parts.glob("part_*.parquet"))
        if show_progress:
            emit_phase_line(f"staging-parquet: merge {len(part_files)} part(s) → {out.name} …")
        tw = time.perf_counter()
        if len(part_files) == 1:
            if out.exists():
                out.unlink()
            shutil.move(str(part_files[0]), str(out))
        else:
            paths = [str(p) for p in part_files]
            lf_merge = pl.scan_parquet(paths)
            try:
                lf_merge.sink_parquet(out, compression=comp, mkdir=True)
            except pl_exc.PolarsError:
                _collect_lazy_materialize(pl.scan_parquet(paths)).write_parquet(out, compression=comp)
        if show_progress:
            wall = format_duration(time.perf_counter() - tw)
            emit_phase_line(f"staging-parquet: merge done wall={wall}")

    log_kv(event="staging_written", rows=total, output=str(out))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ta-batch", description="Transcription CSV batch analytics")
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        help="Ingest CSV, compute Layer A (+ optional Layer B), write aggregates + manifest",
    )
    run_p.add_argument("--input", "-i", required=True, help="Path to UTF-8 BOM CSV")
    run_p.add_argument(
        "--output-dir",
        "-o",
        default="outputs",
        help="Root directory for run outputs (default: outputs)",
    )
    run_p.add_argument("--run-id", default=None, help="Run identifier (default: UUID)")
    run_p.add_argument("--max-rows", type=int, default=None, help="Cap rows for smoke tests")
    run_p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_CSV_BATCH_ROWS,
        metavar="N",
        help=(
            f"Polars CSV chunk size in logical rows (default: {DEFAULT_CSV_BATCH_ROWS}; "
            "lower reduces peak RAM on wide multiline text)"
        ),
    )
    run_p.add_argument(
        "--merge-per-row-parquet",
        action="store_true",
        help="Also write per_row_features.parquet when rows <= --merge-max-rows",
    )
    run_p.add_argument(
        "--merge-max-rows",
        type=int,
        default=200_000,
        help="Max rows for merged per_row_features.parquet",
    )
    run_p.add_argument(
        "--total-rows",
        type=int,
        default=None,
        metavar="N",
        help="Explicit row count for ETA (skips count pass if set). Overrides inferred count.",
    )
    run_p.add_argument(
        "--infer-total-rows",
        action="store_true",
        help=(
            "Stream column 0 once to count rows before read_phase (ETA). "
            "Default: auto when progress is on and neither --total-rows nor --max-rows is set."
        ),
    )
    run_p.add_argument(
        "--no-infer-total-rows",
        action="store_true",
        help="Skip row-count scan (full run ETA only if --total-rows is set). Saves one pass.",
    )
    run_p.add_argument(
        "--progress",
        action="store_true",
        help="Always print progress lines to stderr (default: on if stderr is a TTY)",
    )
    run_p.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable human progress lines",
    )
    run_p.add_argument(
        "--no-layer-b",
        action="store_true",
        help="Skip Layer B and content-characterization columns (Layer A only)",
    )
    run_p.add_argument(
        "--lang-detect-max-chars",
        type=int,
        default=4000,
        metavar="N",
        help="Max characters of segment-body text passed to lingua (default: 4000)",
    )
    run_p.add_argument(
        "--lang-detect-languages",
        default=None,
        metavar="LIST",
        help=(
            "Comma-separated ISO 639-1 codes for lingua allow-list "
            "(default: en,ru,uk,de,pl,be)"
        ),
    )
    run_p.add_argument(
        "--no-user-stratify",
        action="store_true",
        help="Skip per-user month aggregates (user_time_agg_month.*)",
    )
    run_p.add_argument(
        "--export-report",
        dest="export_report",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Write report.html (RU; day charts in HTML), time_agg_*_long.csv, and PNG figures "
            "(default: on unless --no-export-report)"
        ),
    )
    run_p.set_defaults(func=cmd_run)

    st = sub.add_parser("staging-parquet", help="Copy CSV to Parquet (subset optional)")
    st.add_argument("--input", "-i", required=True)
    st.add_argument("--output", "-o", required=True, help="Target .parquet path")
    st.add_argument("--max-rows", type=int, default=None)
    st.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_CSV_BATCH_ROWS,
        metavar="N",
        help=f"CSV chunk size (default: {DEFAULT_CSV_BATCH_ROWS})",
    )
    st.add_argument("--progress", action="store_true", help="Force progress on stderr")
    st.add_argument("--no-progress", action="store_true", help="Disable progress")
    st.set_defaults(func=cmd_to_parquet)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

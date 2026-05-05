"""Contract flexibility tests for the batch CLI."""

from __future__ import annotations

from argparse import Namespace
import shutil
from pathlib import Path
import uuid

from transcriptions_analysis.cli import cmd_run


def test_cmd_run_accepts_minimal_headers():
    tmp_dir = Path("tests") / "_tmp" / f"cli-contract-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        input_csv = tmp_dir / "minimal.csv"
        out_dir = tmp_dir / "outputs"
        input_csv.write_text(
            'created_at,transcription_text\n'
            '"2024-01-15 10:00:00","SPEAKER_00\n[00:00:00 - 00:00:02]\nHello there"\n'
            '"2024-01-16 10:00:00","SPEAKER_01\n[00:00:03 - 00:00:05]\nGeneral Kenobi"\n',
            encoding="utf-8",
        )

        args = Namespace(
            input=str(input_csv),
            output_dir=str(out_dir),
            run_id="minimal-contract",
            max_rows=None,
            batch_size=100,
            merge_per_row_parquet=False,
            merge_max_rows=200_000,
            total_rows=None,
            infer_total_rows=False,
            no_infer_total_rows=True,
            progress=False,
            no_progress=True,
            no_layer_b=False,
            lang_detect_max_chars=4000,
            lang_detect_languages=None,
            no_user_stratify=False,
            export_report=False,
        )

        rc = cmd_run(args)

        run_dir = out_dir / "minimal-contract"
        assert rc == 0
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "time_agg_day.csv").exists()
        assert (run_dir / "language_share_time_agg_day.csv").exists()
        assert not (run_dir / "user_time_agg_month.csv").exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

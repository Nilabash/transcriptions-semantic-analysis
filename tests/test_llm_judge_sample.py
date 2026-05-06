"""Contract tests for the LLM judge sample builder."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def test_build_llm_judge_sample_outputs_packet_prompt_index_and_jsonl():
    tmp_dir = Path("tests") / "_tmp" / f"llm-judge-{uuid.uuid4().hex}"
    out_dir = tmp_dir / "outputs"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/build_llm_judge_sample.py",
                "--input",
                "tests/fixtures/sample_multiline.csv",
                "--output-dir",
                str(out_dir),
                "--samples-per-month",
                "2",
                "--max-transcript-chars",
                "1200",
                "--lang-detect-languages",
                "en",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        summary = json.loads(result.stdout)
        packet_path = Path(summary["packet"])
        prompt_path = Path(summary["prompt"])
        index_path = Path(summary["index"])
        jsonl_path = Path(summary["jsonl"])

        assert packet_path.exists()
        assert prompt_path.exists()
        assert index_path.exists()
        assert jsonl_path.exists()

        packet = packet_path.read_text(encoding="utf-8")
        assert "LLM-as-Judge Prompt" in packet
        assert "## Transcript Samples" in packet
        assert "transcription_quality_score" in packet

        with index_path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        assert len(rows) == 2
        assert {row["month"] for row in rows} == {"2024-01", "2024-02"}
        assert all(row["selection_reason"] for row in rows)

        jsonl_rows = [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(jsonl_rows) == 2
        assert all("transcript_excerpt" in row for row in jsonl_rows)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_build_llm_judge_sample_supports_run_id_russian_filter_and_exclusions():
    tmp_dir = Path("tests") / "_tmp" / f"llm-judge-ru-{uuid.uuid4().hex}"
    input_csv = tmp_dir / "input.csv"
    out_root = tmp_dir / "runs"
    exclude_index = tmp_dir / "previous_index.csv"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with input_csv.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "id",
                    "created_at",
                    "file_name",
                    "transcription_text",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "id": "ru_old",
                    "created_at": "2024-01-15 10:00:00",
                    "file_name": "ru-old.wav",
                    "transcription_text": (
                        "SPEAKER_00\n[00:00:00 - 00:00:02]\n"
                        "Привет, это русская тестовая расшифровка про качество речи."
                    ),
                }
            )
            writer.writerow(
                {
                    "id": "en_row",
                    "created_at": "2024-01-16 10:00:00",
                    "file_name": "en.wav",
                    "transcription_text": (
                        "SPEAKER_00\n[00:00:00 - 00:00:02]\n"
                        "Hello, this is an English transcript that should be filtered out."
                    ),
                }
            )
            writer.writerow(
                {
                    "id": "ru_new",
                    "created_at": "2024-02-15 10:00:00",
                    "file_name": "ru-new.wav",
                    "transcription_text": (
                        "SPEAKER_00\n[00:00:00 - 00:00:03]\n"
                        "Это еще одна русская расшифровка для второго запуска анализа."
                    ),
                }
            )

        with exclude_index.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["transcript_id"])
            writer.writeheader()
            writer.writerow({"transcript_id": "ru_old"})

        result = subprocess.run(
            [
                sys.executable,
                "scripts/build_llm_judge_sample.py",
                "--input",
                str(input_csv),
                "--output-dir",
                str(out_root),
                "--run-id",
                "russian-run",
                "--samples-per-month",
                "2",
                "--max-transcript-chars",
                "1200",
                "--russian-only",
                "--lang-detect-languages",
                "ru,en",
                "--language-min-confidence",
                "0.2",
                "--exclude-sample-index",
                str(exclude_index),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        summary = json.loads(result.stdout)
        assert summary["run_id"] == "russian-run"
        assert Path(summary["output_dir"]) == (out_root / "russian-run").resolve()
        assert summary["language_filter"] == ["ru"]

        with Path(summary["index"]).open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        assert [row["transcript_id"] for row in rows] == ["ru_new"]
        assert rows[0]["language"] == "ru"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

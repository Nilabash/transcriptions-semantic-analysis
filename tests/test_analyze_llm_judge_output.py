"""Contract tests for the LLM judge output analyzer."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def load_analyzer_module():
    spec = importlib.util.spec_from_file_location(
        "analyze_llm_judge_output",
        Path("scripts") / "analyze_llm_judge_output.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_json_repairs_unescaped_quotes_inside_evidence_string():
    module = load_analyzer_module()
    raw = (
        '{"rubric_version":"llm_judge_v1","per_transcript":['
        '{"transcript_id":"a","month":"2024-01",'
        '"transcription_quality_score":4,"diarization_quality_score":4,'
        '"timestamp_structure_score":4,"artifact_severity_score":4,'
        '"judge_confidence":4,"primary_failure_modes":["minor"],'
        '"evidence":"Readable, but phrases "bad quote", "second quote" appear."}'
        "],\"trend_assessment\":{}}"
    )

    repaired = module.repair_llm_judge_json_text(raw)
    data = json.loads(repaired)

    assert data["per_transcript"][0]["evidence"] == (
        'Readable, but phrases "bad quote", "second quote" appear.'
    )


def test_load_json_repairs_unescaped_quotes_inside_pretty_printed_evidence_string():
    module = load_analyzer_module()
    raw = """{
  "rubric_version": "llm_judge_v1",
  "per_transcript": [
    {
      "transcript_id": "a",
      "month": "2024-01",
      "transcription_quality_score": 4,
      "diarization_quality_score": 4,
      "timestamp_structure_score": 4,
      "artifact_severity_score": 4,
      "judge_confidence": 4,
      "primary_failure_modes": ["minor"],
      "evidence": "Readable, but phrases "bad quote", "second quote" appear."
    }
  ],
  "trend_assessment": {}
}"""

    repaired = module.repair_llm_judge_json_text(raw)
    data = json.loads(repaired)

    assert data["per_transcript"][0]["evidence"] == (
        'Readable, but phrases "bad quote", "second quote" appear.'
    )


def test_failure_modes_ru_excludes_excerpt_marker_and_translates_labels():
    module = load_analyzer_module()

    rendered = module.failure_modes_ru(
        "diarization_missing|coarse_timestamps|speaker_boundary_errors|excerpt_limited"
    )

    assert "отсутствует диаризация" in rendered
    assert "крупные временные блоки" in rendered
    assert "ошибки границ реплик" in rendered
    assert "оценка по фрагменту" not in rendered


def test_render_low_score_examples_shows_fragment_marker_separately():
    module = load_analyzer_module()
    rows = [
        {
            "transcript_id": "frag",
            "month": "2024-01",
            "transcription_quality_score": 2,
            "diarization_quality_score": 1,
            "artifact_severity_score": 2,
            "timestamp_structure_score": 3,
            "judge_confidence": 4,
            "selection_reason": "representative_dominant_stratum",
            "excerpt_limited": "True",
            "evidence": (
                "Multiple conversational voices appear inside a single speaker label "
                "and one timestamp block, despite generally understandable content."
            ),
            "primary_failure_modes": (
                "diarization_missing|coarse_timestamps|speaker_boundary_errors|excerpt_limited"
            ),
        }
    ]

    html = module.render_low_score_examples(rows)

    assert "оценка только по видимому фрагменту" in html
    assert "оценка по фрагменту" not in html
    assert "отсутствует диаризация" in html
    assert "ошибки границ реплик" in html


def test_failure_modes_ru_translates_r4_aliases():
    module = load_analyzer_module()

    rendered = module.failure_modes_ru(
        "timestamp_coarse|speaker_misattribution|foreign_text_artifacts|too_little_evidence|uncertain_diarization"
    )

    assert "крупные временные блоки" in rendered
    assert "ошибки атрибуции говорящих" in rendered
    assert "иноязычные артефакты" in rendered
    assert "слишком мало материала для оценки" in rendered
    assert "неуверенная диаризация" in rendered


def test_evidence_ru_translates_r4_low_score_example():
    module = load_analyzer_module()

    rendered = module.evidence_ru(
        "Multiple conversational turns are collapsed under one speaker label and the transcript contains broken phrases such as 'если его неужинит в рюк'."
    )

    assert "Несколько разговорных реплик слиты под одной меткой говорящего" in rendered


def test_failure_modes_ru_translates_r5_aliases():
    module = load_analyzer_module()

    rendered = module.failure_modes_ru(
        "asr_errors|long_ts|minor_asr|excerpt|speaker_merge|low_evidence|long_turns|punctuation|fragments"
    )

    assert "ошибки распознавания" in rendered
    assert "крупные временные блоки" in rendered
    assert "небольшие ошибки распознавания" in rendered
    assert "оценка только по видимому фрагменту" in rendered
    assert "слияние нескольких говорящих" in rendered
    assert "слишком мало материала для оценки" in rendered
    assert "слишком длинные реплики" in rendered
    assert "слабая пунктуация" in rendered
    assert "обрывочные фрагменты" in rendered


def test_trend_evidence_ru_translates_r5_headline():
    module = load_analyzer_module()

    rendered = module.trend_evidence_ru(
        "Later months contain more clear short-form/monologue samples, but artifact-heavy and merged-speaker cases recur."
    )

    assert "В более поздних месяцах чаще встречаются ясные короткие фрагменты" in rendered


def test_evidence_ru_translates_r5_low_score_example():
    module = load_analyzer_module()

    rendered = module.evidence_ru(
        "Multiple voices are visibly merged into one speaker and the transcript contains distorted phrases such as."
    )

    assert "Несколько голосов заметно слиты в одного говорящего" in rendered


def test_failure_modes_ru_translates_remaining_aliases():
    module = load_analyzer_module()

    rendered = module.failure_modes_ru(
        "false_split|foreign_noise|metadata|segmentation|low_readability|"
        "severe_asr|speaker_unclear|colloquial_asr|term_errors|jargon_asr|"
        "loanword_asr|lyrics_asr|montage|colloquial|cutoff|slang_distortion|"
        "format|missing_speech|term_asr"
    )

    assert "ложное дробление реплики" in rendered
    assert "иноязычный шум" in rendered
    assert "служебные метаданные в тексте" in rendered
    assert "ошибки сегментации" in rendered
    assert "низкая читаемость" in rendered
    assert "сильные ошибки распознавания" in rendered
    assert "неясное разделение говорящих" in rendered
    assert "ошибки распознавания разговорной речи" in rendered
    assert "ошибки в терминах" in rendered
    assert "ошибки распознавания жаргона" in rendered
    assert "ошибки распознавания заимствований" in rendered
    assert "ошибки распознавания текста песни" in rendered
    assert "монтажные фрагменты" in rendered
    assert "разговорная речь" in rendered
    assert "обрезанный фрагмент" in rendered
    assert "искажение сленга" in rendered
    assert "проблемы форматирования" in rendered
    assert "пропуск части речи" in rendered
    assert "ошибки распознавания терминов" in rendered


def test_render_low_score_examples_includes_one_example_per_month():
    module = load_analyzer_module()
    rows = [
        {
            "transcript_id": "a-low",
            "month": "2024-01",
            "transcription_quality_score": 1,
            "diarization_quality_score": 2,
            "artifact_severity_score": 1,
            "timestamp_structure_score": 3,
            "judge_confidence": 4,
            "selection_reason": "representative_dominant_stratum",
            "evidence": "Excerpt is almost entirely blank/invisible-character artifacts.",
            "primary_failure_modes": "gibberish",
        },
        {
            "transcript_id": "a-high",
            "month": "2024-01",
            "transcription_quality_score": 4,
            "diarization_quality_score": 4,
            "artifact_severity_score": 4,
            "timestamp_structure_score": 4,
            "judge_confidence": 4,
            "selection_reason": "representative_dominant_stratum",
            "evidence": "Personal monologue is understandable but one long timestamped segment.",
            "primary_failure_modes": "recognition_errors",
        },
        {
            "transcript_id": "b-low",
            "month": "2024-02",
            "transcription_quality_score": 2,
            "diarization_quality_score": 1,
            "artifact_severity_score": 2,
            "timestamp_structure_score": 3,
            "judge_confidence": 5,
            "selection_reason": "quality_sentinel",
            "evidence": "Personal monologue is understandable but one long timestamped segment.",
            "primary_failure_modes": "recognition_errors",
        },
        {
            "transcript_id": "b-high",
            "month": "2024-02",
            "transcription_quality_score": 5,
            "diarization_quality_score": 5,
            "artifact_severity_score": 5,
            "timestamp_structure_score": 5,
            "judge_confidence": 5,
            "selection_reason": "representative_dominant_stratum",
            "evidence": "Excerpt is almost entirely blank/invisible-character artifacts.",
            "primary_failure_modes": "gibberish",
        },
    ]

    html = module.render_low_score_examples(rows)

    assert "a-low" in html
    assert "b-low" in html
    assert "a-high" not in html
    assert "b-high" not in html


def test_render_html_report_hides_sentinel_comparison_when_no_sentinel_rows():
    module = load_analyzer_module()
    data = {
        "rubric_version": "llm_judge_v1",
        "trend_assessment": {
            "direction": "mixed",
            "strongest_evidence": "Small test trend.",
            "main_limitations": ["Synthetic fixture."],
        },
    }
    rows = [
        {
            "transcript_id": "a",
            "month": "2024-01",
            "selection_reason": "all_available_for_sparse_month",
            "sample_group": "representative_or_contrastive",
            "excerpt_limited": "False",
            "transcription_quality_score": 4,
            "diarization_quality_score": 4,
            "timestamp_structure_score": 4,
            "artifact_severity_score": 4,
            "judge_confidence": 4,
            "primary_failure_modes": "recognition_errors",
            "evidence": "Personal monologue is understandable but one long timestamped segment.",
        }
    ]
    summaries = [
        {
            "month": "2024-01",
            "sample_group": "all_selected",
            "n_evaluated": 1,
            "n_sentinel": 0,
            "n_excerpt_limited": 0,
            "mean_transcription_quality_score": 4.0,
            "confidence_weighted_mean_transcription_quality_score": 4.0,
            "mean_diarization_quality_score": 4.0,
            "confidence_weighted_mean_diarization_quality_score": 4.0,
            "mean_timestamp_structure_score": 4.0,
            "confidence_weighted_mean_timestamp_structure_score": 4.0,
            "mean_artifact_severity_score": 4.0,
            "confidence_weighted_mean_artifact_severity_score": 4.0,
        },
        {
            "month": "2024-01",
            "sample_group": "representative_excluding_sentinel",
            "n_evaluated": 1,
            "n_sentinel": 0,
            "n_excerpt_limited": 0,
            "mean_transcription_quality_score": 4.0,
            "confidence_weighted_mean_transcription_quality_score": 4.0,
            "mean_diarization_quality_score": 4.0,
            "confidence_weighted_mean_diarization_quality_score": 4.0,
            "mean_timestamp_structure_score": 4.0,
            "confidence_weighted_mean_timestamp_structure_score": 4.0,
            "mean_artifact_severity_score": 4.0,
            "confidence_weighted_mean_artifact_severity_score": 4.0,
        },
    ]

    html = module.render_html_report(data, rows, summaries, {})

    assert "Оценки по месяцам</h2>" in html
    assert "Оценки по месяцам: типичная выборка" not in html
    assert "Как контрольные выбросы меняют картину" not in html
    assert "нет отдельных sentinel-примеров" in html


def test_analyze_llm_judge_output_writes_joined_summaries_and_report():
    tmp_dir = Path("tests") / "_tmp" / f"llm-judge-analysis-{uuid.uuid4().hex}"
    out_root = tmp_dir / "runs"
    out_dir = out_root / "russian-run"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        judge_json = out_dir / "llm_judge_output.json"
        sample_index = out_dir / "llm_judge_sample_index.csv"

        judge_json.write_text(
            json.dumps(
                {
                    "rubric_version": "llm_judge_v1",
                    "per_transcript": [
                        {
                            "transcript_id": "a",
                            "month": "2024-01",
                            "transcription_quality_score": 4,
                            "diarization_quality_score": 3,
                            "timestamp_structure_score": 5,
                            "artifact_severity_score": 4,
                            "judge_confidence": 3,
                            "primary_failure_modes": ["recognition_errors"],
                            "evidence": (
                                "Personal monologue is understandable but "
                                "one long timestamped segment."
                            ),
                        },
                        {
                            "transcript_id": "b",
                            "month": "2024-01",
                            "transcription_quality_score": 1,
                            "diarization_quality_score": 2,
                            "timestamp_structure_score": 3,
                            "artifact_severity_score": 1,
                            "judge_confidence": 5,
                            "primary_failure_modes": ["gibberish"],
                            "evidence": (
                                "Excerpt is almost entirely "
                                "blank/invisible-character artifacts."
                            ),
                        },
                    ],
                    "trend_assessment": {
                        "direction": "mixed",
                        "strongest_evidence": "Small test trend.",
                        "main_limitations": ["Synthetic fixture."],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (out_dir / "llm_judge_packet.md").write_text(
            """
# LLM Judge Packet

## Packet Metadata

```json
{
  "source_file": "fixture.csv",
  "rubric_version": "llm_judge_v1",
  "sampling_seed": 123,
  "target_samples_per_month": 2,
  "max_transcript_chars": 4500,
  "selected_transcripts": 2,
  "selected_by_month": {
    "2024-01": 2
  }
}
```
""".lstrip(),
            encoding="utf-8",
        )

        with sample_index.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "transcript_id",
                    "month",
                    "selection_reason",
                    "content_category",
                    "language",
                    "length_bin",
                    "dialogue_bin",
                    "quality_bin",
                    "excerpt_limited",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "transcript_id": "a",
                    "month": "2024-01",
                    "selection_reason": "representative_dominant_stratum",
                    "content_category": "business_work",
                    "language": "latin_dominant",
                    "length_bin": "medium",
                    "dialogue_bin": "two_speaker_light",
                    "quality_bin": "typical",
                    "excerpt_limited": "False",
                }
            )
            writer.writerow(
                {
                    "transcript_id": "b",
                    "month": "2024-01",
                    "selection_reason": "quality_sentinel",
                    "content_category": "unknown",
                    "language": "unknown",
                    "length_bin": "short",
                    "dialogue_bin": "monologue_or_single_speaker",
                    "quality_bin": "structural_or_text_anomaly",
                    "excerpt_limited": "True",
                }
            )

        result = subprocess.run(
            [
                sys.executable,
                "scripts/analyze_llm_judge_output.py",
                "--output-dir",
                str(out_root),
                "--run-id",
                "russian-run",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        summary = json.loads(result.stdout)
        assert summary["run_id"] == "russian-run"
        assert Path(summary["output_dir"]) == out_dir.resolve()
        assert Path(summary["joined_scores"]).exists()
        assert Path(summary["monthly_scores"]).exists()
        assert Path(summary["failure_modes"]).exists()
        assert Path(summary["report"]).exists()
        assert Path(summary["html_report"]).exists()

        with Path(summary["monthly_scores"]).open("r", encoding="utf-8", newline="") as file:
            monthly_rows = list(csv.DictReader(file))
        assert {row["sample_group"] for row in monthly_rows} == {
            "all_selected",
            "representative_excluding_sentinel",
        }

        report = Path(summary["report"]).read_text(encoding="utf-8")
        assert "LLM Judge Analysis" in report
        assert "Representative-only" in report

        html_report = Path(summary["html_report"]).read_text(encoding="utf-8")
        assert "LLM-as-Judge: оценка качества транскрипции" in html_report
        assert "Оценки по месяцам: типичная выборка" in html_report
        assert "бессвязный текст" in html_report
        assert "Фрагмент почти полностью состоит" in html_report
        assert "<h3>b</h3>" in html_report
        assert "<h3>a</h3>" not in html_report
        assert "Как контрольные выбросы меняют картину" in html_report
        assert "Основные типы ошибок за весь период LLM-оценки" in html_report
        assert "общая частотность типов ошибок" in html_report
        assert "Типы ошибок по месяцам" in html_report
        assert "month-error-card" in html_report
        assert "оценка по фрагменту" not in html_report
        assert "только фрагмент" in html_report
        assert "sentinel: специально выбранный проблемный пример месяца" in html_report
        assert "Как была получена LLM-оценка" in html_report
        assert "fixture.csv" in html_report
        assert "seed=123" in html_report
        assert "scripts/build_llm_judge_sample.py" in html_report
        assert "scripts/analyze_llm_judge_output.py" in html_report
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

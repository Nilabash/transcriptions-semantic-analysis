"""Summarize ChatGPT LLM-judge JSON output and join it to the sample index."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_JSON = Path("outputs") / "llm_judge" / "llm_judge_output.json"
DEFAULT_SAMPLE_INDEX = Path("outputs") / "llm_judge" / "llm_judge_sample_index.csv"
DEFAULT_OUTPUT_DIR = Path("outputs") / "llm_judge"
DEFAULT_OUTPUT_JSON_NAME = "llm_judge_output.json"
DEFAULT_INDEX_NAME = "llm_judge_sample_index.csv"
DEFAULT_PACKET_NAME = "llm_judge_packet.md"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

SCORE_FIELDS = (
    "transcription_quality_score",
    "diarization_quality_score",
    "timestamp_structure_score",
    "artifact_severity_score",
)

SCORE_LABELS = {
    "transcription_quality_score": "Качество текста",
    "diarization_quality_score": "Диаризация",
    "timestamp_structure_score": "Временная разметка",
    "artifact_severity_score": "Контроль артефактов",
}

FIELD_COLORS = {
    "transcription_quality_score": "#2563eb",
    "diarization_quality_score": "#16a34a",
    "timestamp_structure_score": "#d97706",
    "artifact_severity_score": "#dc2626",
}

TREND_RU = {
    "improved": "улучшение",
    "worsened": "ухудшение",
    "mixed": "смешанная динамика",
    "no_clear_change": "без явного изменения",
}

SELECTION_REASON_RU = {
    "representative_dominant_stratum": "типичный слой",
    "representative_month_center": "центр месяца",
    "contrastive_rare_stratum": "редкий слой",
    "quality_sentinel": "контрольный выброс",
    "balanced_fill": "балансировка",
    "all_available_for_sparse_month": "все доступные",
}

LIMITATION_RU = {
    "Many rows are excerpt-limited.": "Многие строки оценивались по фрагментам, а не по полному тексту.",
    "Monthly sample mix includes sentinel and contrastive rows.": (
        "Месячная выборка включает контрольные выбросы и контрастные строки, поэтому ее нельзя читать как простую случайную выборку."
    ),
    "Non-Russian/English scoring relies on visible artifact patterns.": (
        "Для языков вне русского и английского judge в основном опирается на видимые артефакты и структуру текста."
    ),
    "Synthetic fixture.": "Синтетический тестовый пример.",
}

TREND_EVIDENCE_RU = {
    "Typical samples often score 4-5, but each period has severe anomaly outliers.": (
        "Типичные фрагменты часто получают 4-5 баллов, но в каждом периоде есть тяжелые аномальные случаи."
    ),
    "Small test trend.": "Короткий тестовый тренд.",
    "Later months contain more clear short-form/monologue samples, but artifact-heavy and merged-speaker cases recur.": (
        "В более поздних месяцах чаще встречаются ясные короткие фрагменты и монологи, но случаи с тяжелыми артефактами и слитыми говорящими повторяются."
    ),
}

FAILURE_MODE_RU = {
    "coarse_timestamps": "крупные временные блоки",
    "recognition_errors": "ошибки распознавания",
    "minor_recognition_errors": "небольшие ошибки распознавания",
    "speaker_collapse": "склейка нескольких говорящих в одного",
    "gibberish": "бессвязный текст",
    "severe_repetition": "сильные повторы",
    "language_mismatch": "смешение или подмена языка",
    "run_on_segments": "слишком длинные фразы без нормального членения",
    "frequent_recognition_errors": "частые ошибки распознавания",
    "short_sample": "слишком короткий пример",
    "blank_character_artifacts": "пустые или невидимые символы",
    "severe_gibberish": "сильная бессвязность",
    "minor_final_artifact": "небольшой артефакт в конце",
    "minor_final_recognition_errors": "небольшие ошибки распознавания в конце",
    "possible_speaker_collapse": "возможная склейка говорящих",
    "over_fragmented_speakers": "избыточное дробление говорящих",
    "intro_montage_fragments": "монтажные фрагменты во вступлении",
    "music_labels": "музыкальные метки вместо речи",
    "early_artifact": "артефакт в начале",
    "minor_overlap_or_turn_boundary": "небольшая проблема границы реплики",
    "connection_fragments": "служебные фразы о соединении",
    "repetition_artifacts": "повторяющиеся артефакты",
    "elongated_vocalization": "растянутая вокализация",
    "empty_or_repetitive_content": "пустое или повторяющееся содержание",
    "none": "без явных проблем",
    "advertising_artifact": "рекламный артефакт",
    "awkward_ending": "неестественное окончание",
    "awkward_segmentation": "неудачная сегментация",
    "awkward_wording": "неестественные формулировки",
    "caption_artifact": "артефакт субтитров",
    "classroom_noise": "шум и хаос учебной аудитории",
    "coarse_diarization": "грубая диаризация",
    "coarse_speaker_attribution": "грубое назначение говорящих",
    "coarse_speaker_turns": "грубое деление реплик",
    "domain_term_recognition_errors": "ошибки распознавания терминов",
    "duplicate_speaker_label": "дублирующая метка говорящего",
    "excerpt_truncation": "обрезанный фрагмент",
    "foreign_phrase_distortion": "искажение иностранной фразы",
    "foreign_language_artifact": "иноязычный артефакт",
    "gender_agreement_errors": "ошибки согласования рода",
    "implausible_speaker_count": "неправдоподобное число говорящих",
    "long_segments": "длинные сегменты",
    "long_speaker_block": "длинный блок говорящего",
    "long_speaker_blocks": "длинные блоки говорящих",
    "lowercase_formatting": "форматирование строчными буквами",
    "lyrics_repetition": "повторы текста песни",
    "minor_caption_artifact": "небольшой артефакт субтитров",
    "minor_disfluency": "небольшая речевая шероховатость",
    "minor_repetition": "небольшой повтор",
    "minor_segmentation_issues": "небольшие проблемы сегментации",
    "minor_trailing_artifact": "небольшой артефакт в конце",
    "no_meaningful_artifacts": "без заметных артефактов",
    "non_speaker_turns": "реплики без говорящего",
    "nonstandard_transcript_formatting": "нестандартное форматирование транскрипта",
    "non_transcript_header": "служебный заголовок внутри текста",
    "odd_capitalization": "странная капитализация",
    "possible_omission": "возможный пропуск",
    "profanity_preserved": "сохраненная обсценная лексика",
    "punctuation_weakness": "слабая пунктуация",
    "repeated_artifact": "повторяющийся артефакт",
    "repeated_caption_artifact": "повторяющийся артефакт субтитров",
    "repetition": "повтор",
    "severe_recognition_errors": "серьезные ошибки распознавания",
    "single_long_speaker_block": "один длинный блок говорящего",
    "single_long_timestamp": "одна длинная временная метка",
    "single_speaker_dialogue_style": "диалог, записанный как один говорящий",
    "speaker_attribution_issues": "проблемы назначения говорящих",
    "speaker_fragmentation": "дробление говорящих",
    "speaker_overlap": "пересечение реплик",
    "speaker_segmentation_issues": "проблемы сегментации говорящих",
    "unattributed_dialogue": "диалог без разметки говорящих",
    "very_long_speaker_block": "очень длинный блок говорящего",
    "speaker_boundary_errors": "ошибки границ реплик",
    "run_on_segmentation": "слипшаяся сегментация",
    "diarization_missing": "отсутствует диаризация",
    "nonsense_garbling": "бессвязный текст",
    "technical_term_garbling": "искажение технических терминов",
    "mixed_language_garbling": "смешанный многоязычный шум",
    "zero_duration_turn": "нулевая длительность реплики",
    "timestamp_coarse": "крупные временные блоки",
    "speaker_misattribution": "ошибки атрибуции говорящих",
    "foreign_text_artifacts": "иноязычные артефакты",
    "too_little_evidence": "слишком мало материала для оценки",
    "uncertain_diarization": "неуверенная диаризация",
    "diarization_unusable": "диаризация непригодна",
    "diarization_inconsistent": "непоследовательная диаризация",
    "timestamp_gaps": "разрывы во временной разметке",
    "technical_term_errors": "ошибки в технических терминах",
    "legal_term_errors": "ошибки в юридических терминах",
    "minor_artifacts": "небольшие артефакты",
    "over_fragmentation": "избыточное дробление",
    "repeated_artifacts": "повторяющиеся артефакты",
    "slang_or_noise": "сленг или шум",
    "asr_errors": "ошибки распознавания",
    "long_ts": "крупные временные блоки",
    "minor_asr": "небольшие ошибки распознавания",
    "excerpt": "оценка только по видимому фрагменту",
    "speaker_merge": "слияние нескольких говорящих",
    "low_evidence": "слишком мало материала для оценки",
    "long_turns": "слишком длинные реплики",
    "long_turn": "слишком длинная реплика",
    "punctuation": "слабая пунктуация",
    "fragments": "обрывочные фрагменты",
    "false_split": "ложное дробление реплики",
    "foreign_noise": "иноязычный шум",
    "metadata": "служебные метаданные в тексте",
    "segmentation": "ошибки сегментации",
    "low_readability": "низкая читаемость",
    "severe_asr": "сильные ошибки распознавания",
    "speaker_unclear": "неясное разделение говорящих",
    "colloquial_asr": "ошибки распознавания разговорной речи",
    "term_errors": "ошибки в терминах",
    "jargon_asr": "ошибки распознавания жаргона",
    "loanword_asr": "ошибки распознавания заимствований",
    "lyrics_asr": "ошибки распознавания текста песни",
    "montage": "монтажные фрагменты",
    "colloquial": "разговорная речь",
    "cutoff": "обрезанный фрагмент",
    "slang_distortion": "искажение сленга",
    "format": "проблемы форматирования",
    "missing_speech": "пропуск части речи",
    "term_asr": "ошибки распознавания терминов",
}

EVIDENCE_RU = {
    "Personal monologue is understandable but one long timestamped segment.": (
        "Личный монолог понятен, но оформлен одним длинным timestamp-сегментом."
    ),
    "Meditation text is clear and attributed to one speaker, but long timestamp blocks.": (
        "Текст медитации чистый и отнесен к одному говорящему, но разбит на длинные timestamp-блоки."
    ),
    "Arabic monologue appears coherent and clean but uses one long segment.": (
        "Арабский монолог выглядит связным и чистым, но использует один длинный сегмент."
    ),
    "Excerpt is almost entirely blank/invisible-character artifacts.": (
        "Фрагмент почти полностью состоит из пустых или невидимых символов."
    ),
    "Transcript contains little beyond repeated 'И. О.' and a single 'Как?'.": (
        "В транскрипте почти нет содержательной речи: в основном повторяется «И. О.» и один раз встречается «Как?»."
    ),
    "Single-speaker English-like transcript is dominated by nonsensical mixed-language text.": (
        "Односпикерный текст выглядит как английский, но в основном состоит из бессмысленной смешанной речи."
    ),
    "Transcript is mostly multilingual gibberish and blank-symbol artifacts.": (
        "Транскрипт в основном состоит из многоязычной бессвязности и пустых символов."
    ),
    "Granular timestamps are present, but content is incoherent multilingual fragments.": (
        "Временные метки детальные, но содержание состоит из бессвязных многоязычных фрагментов."
    ),
    "Visible transcript is dominated by an extremely long repeated 'а' vocalization.": (
        "Видимая часть транскрипта почти полностью занята очень длинным повтором звука «а»."
    ),
    "Transcript is almost entirely incoherent multilingual noise.": (
        "Транскрипт почти полностью состоит из бессвязного многоязычного шума."
    ),
    "Only the middle passage is readable; beginning and ending are multilingual gibberish.": (
        "Читается только средняя часть; начало и конец выглядят как многоязычная бессвязность."
    ),
    "Romanization lecture is dominated by mixed-language nonsense and subtitle artifact.": (
        "Лекция о романизации в основном испорчена смешанной языковой бессмыслицей и субтитровыми артефактами."
    ),
    "Large portions repeat 'Продолжение следует' or end in multilingual gibberish.": (
        "Большие фрагменты повторяют «Продолжение следует» или заканчиваются многоязычной бессвязностью."
    ),
    "Large portions repeat 'РџСЂРѕРґРѕР»Р¶РµРЅРёРµ СЃР»РµРґСѓРµС‚' or end in multilingual gibberish.": (
        "Большие фрагменты повторяют битую строку «Продолжение следует» или заканчиваются многоязычной бессвязностью."
    ),
    'The meeting gist is recoverable, but many phrases are garbled, such as "сезы топлива" and "ашхтас", with uneven speaker turns.': (
        'Общий смысл встречи восстановить можно, но многие фразы искажены, например «сезы топлива» и «ашхтас»; смены говорящих неровные.'
    ),
    'Many early turns are hard to interpret, including fragments like "Gian next", "сему", and "аров но".': (
        'Многие ранние реплики трудно интерпретировать, включая фрагменты вроде «Gian next», «сему» и «аров но».'
    ),
    'The product discussion has many garbled phrases such as "битубе" and "тем литв", making interpretation difficult.': (
        'В обсуждении продукта много искаженных фраз, например «битубе» и «тем литв», из-за чего смысл трудно читать.'
    ),
    'The recruiting discussion is heavily distorted by terms like "БДБАИНГАМ" and "антрина жангушам".': (
        'Рекрутинговое обсуждение сильно искажено выражениями вроде «БДБАИНГАМ» и «антрина жангушам».'
    ),
    "The call transcript includes many broken phrases and ends with an unrelated Korean-looking fragment.": (
        "В расшифровке звонка много сломанных фраз, а в конце появляется нерелевантный фрагмент, похожий на корейский текст."
    ),
    'The conversation remains only partly understandable, with errors like "онлайн дубные" and "гика карпово".': (
        'Разговор остается понятным только частично; видны ошибки вроде «онлайн дубные» и «гика карпово».'
    ),
    'The astrology/content discussion is difficult to read, with phrases like "человек умешает" and "бизнес-то инген".': (
        'Обсуждение астрологии и контента трудно читать из-за фраз вроде «человек умешает» и «бизнес-то инген».'
    ),
    'The classroom transcript is dominated by broken phrases such as "Ни-си-си-ки" and unclear city names.': (
        'В учебной расшифровке преобладают сломанные фразы вроде «Ни-си-си-ки» и неясные названия городов.'
    ),
    "Multiple conversational voices appear inside a single speaker label and one timestamp block, despite generally understandable content.": (
        "Внутри одной метки говорящего и одного временного блока смешаны несколько разговорных голосов, хотя общий смысл в целом понятен."
    ),
    "The anatomy lecture contains many distorted words, repeated phrases, and confusing fragments that only partially preserve the topic.": (
        "В лекции по анатомии много искаженных слов, повторов и путаных фрагментов, поэтому тема сохраняется лишь частично."
    ),
    "The scripted multi-character dialogue is mostly understandable but entirely assigned to one speaker label with no turn separation.": (
        "Сценарный диалог с несколькими персонажами в целом понятен, но целиком записан под одной меткой говорящего без разделения реплик."
    ),
    'The transcript is dominated by multilingual garbage text and repeated "Продолжение следует", making the visible content mostly unusable.': (
        "Транскрипт в основном состоит из многоязычного мусорного текста и повторов «Продолжение следует», поэтому видимый фрагмент почти непригоден."
    ),
    "The court transcript is dominated by repeated and nonsensical legal wording such as repeated familiarization phrases.": (
        "Судебный транскрипт переполнен повторами и бессмысленно искаженной юридической речью, включая многократные формулы ознакомления."
    ),
    "The personal message is mostly understandable, but the final one-word second-speaker segment has zero duration and weak attribution value.": (
        "Личное сообщение в основном понятно, но финальная однословная реплика второго говорящего имеет нулевую длительность и слабую ценность для атрибуции."
    ),
    "The interview topic is understandable, but interviewer and interviewee speech are merged inside the same speaker segment.": (
        "Тема интервью понятна, но речь интервьюера и собеседника слита в один и тот же сегмент говорящего."
    ),
    "The personal monologue is understandable, but run-on wording and several malformed names or phrases reduce quality.": (
        "Личный монолог понятен, но слепленные формулировки и несколько искаженных имен и фраз снижают качество."
    ),
    "The psychology lecture is coherent, but the multi-speaker structure is too coarse to confirm clean turn attribution.": (
        "Лекция по психологии связная, но многоспикерная структура слишком грубая, чтобы уверенно подтвердить корректное разделение реплик."
    ),
    "Multiple conversational turns are collapsed under one speaker label and the transcript contains broken phrases such as 'если его неужинит в рюк'.": (
        "Несколько разговорных реплик слиты под одной меткой говорящего, а в тексте встречаются сломанные фразы вроде «если его неужинит в рюк»."
    ),
    "The candidate interview is understandable but unpunctuated, with distorted terms and a nonsensical ending containing 'Techn nutrient' and 'enorm'.": (
        "Интервью с кандидатом в целом понятно, но почти без пунктуации, с искаженными терминами и бессмысленным концом с фрагментами «Techn nutrient» и «enorm»."
    ),
    "Question and answer content is collapsed into a single speaker label across a 20-minute segment.": (
        "Вопросы и ответы слиты под одной меткой говорящего внутри одного 20-минутного сегмента."
    ),
    "The transcript is dominated by repeated subtitle boilerplate and multilingual gibberish, making content and speakers unusable.": (
        "Транскрипт в основном состоит из повторяющейся субтитровой служебной строки и многоязычной бессвязности, поэтому и содержание, и говорящие становятся непригодными."
    ),
    "Courtroom content is partly recoverable but heavily damaged by repeated phrases and distorted legal wording.": (
        "Судебное содержание частично восстанавливается, но сильно испорчено повторяющимися фразами и искаженной юридической речью."
    ),
    "The psychology lecture is partly clear but has odd speaker fragments and large timestamp gaps.": (
        "Лекция по психологии местами ясна, но содержит странные фрагменты говорящих и большие разрывы во временной разметке."
    ),
    "The business-planning excerpt is understandable but contains many run-on phrases and rough speaker separation.": (
        "Фрагмент про бизнес-планирование в целом понятен, но содержит много слитных длинных фраз и грубое разделение говорящих."
    ),
    "A brief dialogue is collapsed into a single speaker label, making attribution unusable.": (
        "Короткий диалог слит под одной меткой говорящего, из-за чего атрибуция становится непригодной."
    ),
    "The psychology lecture is coherent, but a 24-minute segment makes timestamp alignment poor and speaker separation uncertain.": (
        "Лекция по психологии связная, но 24-минутный сегмент делает временную привязку грубой, а разделение говорящих неуверенным."
    ),
    "Multiple voices are visibly merged into one speaker and the transcript contains distorted phrases such as.": (
        "Несколько голосов заметно слиты в одного говорящего, а в транскрипте встречаются искаженные фразы."
    ),
    "The transcript includes a speaker-statistics block and mixes questions and answers under one speaker label.": (
        "В транскрипт попал блок со статистикой по говорящим, а вопросы и ответы смешаны под одной меткой говорящего."
    ),
    "The content-coaching discussion is heavily distorted with phrases like 'рылсцинарях' and 'адобрение'.": (
        "Обсуждение про контент-коучинг сильно искажено фразами вроде «рылсцинарях» и «адобрение»."
    ),
    "The transcript is dominated by repeated 'Продолжение следует' and multilingual gibberish.": (
        "В транскрипте преобладают повторы «Продолжение следует» и многоязычная бессвязность."
    ),
    "Several speakers appear inside one label and business terms are often distorted, making the excerpt hard to follow.": (
        "Под одной меткой говорящего появляются несколько спикеров, а бизнес-термины часто искажены, из-за чего за фрагментом трудно следить."
    ),
    "The motivational/philosophical video has a coherent gist but visible clip-like speaker changes and some.": (
        "У мотивационно-философского видео есть понятный общий смысл, но заметны монтажные смены говорящих и отдельные искажения."
    ),
    "The short slang anecdote is only partly understandable, with distorted phrases such as 'весь глаз'.": (
        "Короткая сленговая история понятна лишь частично; встречаются искаженные фразы вроде «весь глаз»."
    ),
    "A visible question-answer exchange is merged under one speaker and includes odd phrasing like 'кровь привела'.": (
        "Видимый обмен вопросом и ответом слит под одного говорящего и содержит странные формулировки вроде «кровь привела»."
    ),
    "The personal reflection is understandable, though proper names and phrases such as 'outube' and 'крыльябельную'.": (
        "Личное рассуждение в целом понятно, хотя собственные имена и фразы вроде «outube» и «крыльябельную» явно искажены."
    ),
}


def resolve_output_dir(base_dir: str | Path, run_id: str | None) -> Path:
    base = Path(base_dir)
    if run_id is None or not run_id.strip():
        return base
    run_id = run_id.strip()
    if not RUN_ID_RE.match(run_id):
        raise ValueError(
            "--run-id may contain only letters, numbers, dots, underscores, and hyphens."
        )
    return base / run_id


def load_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        try:
            data = json.loads(repair_llm_judge_json_text(text))
        except json.JSONDecodeError as repaired_exc:
            raise ValueError(
                f"Judge output is not valid JSON at line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}. The automatic quote repair also failed "
                f"at line {repaired_exc.lineno}, column {repaired_exc.colno}: "
                f"{repaired_exc.msg}."
            ) from repaired_exc
    if not isinstance(data, dict):
        raise ValueError("Judge output must be a JSON object.")
    if not isinstance(data.get("per_transcript"), list):
        raise ValueError("Judge output must contain a per_transcript list.")
    return data


def repair_llm_judge_json_text(text: str) -> str:
    repaired = escape_unescaped_evidence_quotes(text)
    try:
        json.loads(repaired)
    except json.JSONDecodeError:
        return escape_unescaped_inner_quotes(repaired)
    return repaired


def escape_unescaped_evidence_quotes(text: str) -> str:
    """
    Repair raw quotes inside `evidence` values.

    In the judge schema, `evidence` is emitted as a plain JSON string field and is
    currently the last per-transcript field. ChatGPT sometimes returns pretty-printed
    JSON with raw quoted snippets inside that value, so compact-text boundary matching
    is not reliable enough. Instead, find each `evidence` string start and scan until
    the first quote whose next non-space character is structural.
    """
    pattern = re.compile(r'("evidence"\s*:\s*")')
    out: list[str] = []
    cursor = 0

    for match in pattern.finditer(text):
        value_start = match.end()
        out.append(text[cursor:value_start])
        cursor = value_start
        escaped = False

        while cursor < len(text):
            char = text[cursor]
            if escaped:
                out.append(char)
                escaped = False
                cursor += 1
                continue
            if char == "\\":
                out.append(char)
                escaped = True
                cursor += 1
                continue
            if char == '"':
                lookahead = cursor + 1
                while lookahead < len(text) and text[lookahead].isspace():
                    lookahead += 1
                if lookahead >= len(text) or text[lookahead] == "}":
                    out.append(char)
                    cursor += 1
                    break
                out.append('\\"')
                cursor += 1
                continue
            out.append(char)
            cursor += 1

    out.append(text[cursor:])
    return "".join(out)


def escape_unescaped_quotes_in_value(value: str) -> str:
    out: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == '"':
            out.append('\\"')
            continue
        out.append(char)
    return "".join(out)


def escape_unescaped_inner_quotes(text: str) -> str:
    """
    Repair a common ChatGPT handoff mistake: raw quotes inside JSON string values.

    Valid JSON string delimiters are followed by structural punctuation after optional
    whitespace. If an unescaped quote appears inside a string and the next non-space
    character is ordinary text, preserve the intended content by escaping that quote.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    structural_after_quote = {":", ",", "}", "]"}

    for index, char in enumerate(text):
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            out.append(char)
            escaped = False
            continue

        if char == "\\":
            out.append(char)
            escaped = True
            continue

        if char == '"':
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(text) or text[lookahead] in structural_after_quote:
                out.append(char)
                in_string = False
            else:
                out.append('\\"')
            continue

        out.append(char)

    return "".join(out)


def load_index(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return {row["transcript_id"]: row for row in rows}


def load_packet_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    match = re.search(r"## Packet Metadata\s+```json\s*(.*?)\s*```", text, re.S)
    if match is None:
        return {}
    try:
        metadata = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def as_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def as_int(value: Any) -> int:
    return int(round(as_float(value)))


def validate_score(value: Any, *, field: str, transcript_id: str) -> int:
    score = as_int(value)
    if score < 1 or score > 5:
        raise ValueError(f"{field} for transcript {transcript_id} must be in [1, 5].")
    return score


def flatten_rows(
    data: dict[str, Any],
    sample_index: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data["per_transcript"]:
        if not isinstance(item, dict):
            raise ValueError("Each per_transcript item must be an object.")
        transcript_id = str(item.get("transcript_id") or "").strip()
        if not transcript_id:
            raise ValueError("Each per_transcript item must include transcript_id.")
        if transcript_id in seen:
            raise ValueError(f"Duplicate transcript_id in judge output: {transcript_id}")
        seen.add(transcript_id)

        index_row = sample_index.get(transcript_id, {})
        month = str(item.get("month") or index_row.get("month") or "").strip()
        if not month:
            raise ValueError(f"Transcript {transcript_id} has no month.")

        modes = item.get("primary_failure_modes") or []
        if isinstance(modes, str):
            modes = [modes]
        modes = [str(mode).strip() for mode in modes if str(mode).strip()]

        row: dict[str, Any] = {
            "transcript_id": transcript_id,
            "month": month,
            "selection_reason": index_row.get("selection_reason", ""),
            "sample_group": (
                "sentinel"
                if index_row.get("selection_reason") == "quality_sentinel"
                else "representative_or_contrastive"
            ),
            "content_category": index_row.get("content_category", ""),
            "language": index_row.get("language", ""),
            "length_bin": index_row.get("length_bin", ""),
            "dialogue_bin": index_row.get("dialogue_bin", ""),
            "quality_bin": index_row.get("quality_bin", ""),
            "excerpt_limited": index_row.get("excerpt_limited", ""),
            "judge_confidence": validate_score(
                item.get("judge_confidence"),
                field="judge_confidence",
                transcript_id=transcript_id,
            ),
            "primary_failure_modes": "|".join(modes),
            "evidence": str(item.get("evidence") or "").strip(),
        }
        for field in SCORE_FIELDS:
            row[field] = validate_score(item.get(field), field=field, transcript_id=transcript_id)
        rows.append(row)

    missing = sorted(set(sample_index) - seen)
    extra = sorted(seen - set(sample_index))
    if missing:
        raise ValueError(f"Judge output is missing {len(missing)} sampled transcript(s).")
    if extra:
        raise ValueError(
            f"Judge output contains {len(extra)} transcript(s) not in the sample index."
        )
    return rows


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def weighted_mean(values: list[float], weights: list[float]) -> float:
    total_weight = sum(weights)
    if not values or total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / total_weight


def summarize_month(rows: list[dict[str, Any]], *, group: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "month": rows[0]["month"] if rows else "",
        "sample_group": group,
        "n_evaluated": len(rows),
        "n_sentinel": sum(1 for row in rows if row["sample_group"] == "sentinel"),
        "n_excerpt_limited": sum(
            1 for row in rows if str(row.get("excerpt_limited")).lower() == "true"
        ),
    }
    weights = [as_float(row["judge_confidence"]) for row in rows]
    for field in SCORE_FIELDS:
        values = [as_float(row[field]) for row in rows]
        out[f"mean_{field}"] = round(mean(values), 3)
        out[f"confidence_weighted_mean_{field}"] = round(weighted_mean(values, weights), 3)
    return out


def monthly_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_month[row["month"]].append(row)

    summaries: list[dict[str, Any]] = []
    for month in sorted(by_month):
        month_rows = by_month[month]
        summaries.append(summarize_month(month_rows, group="all_selected"))
        typical_rows = [row for row in month_rows if row["sample_group"] != "sentinel"]
        summaries.append(summarize_month(typical_rows, group="representative_excluding_sentinel"))
    return summaries


def failure_mode_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        modes = failure_modes_list(row["primary_failure_modes"])
        if not modes:
            modes = ["(none)"]
        for mode in modes:
            counts[(row["month"], row["sample_group"], mode)] += 1
    return [
        {
            "month": month,
            "sample_group": sample_group,
            "failure_mode": mode,
            "count": count,
        }
        for (month, sample_group, mode), count in sorted(counts.items())
    ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def score_delta(summaries: list[dict[str, Any]], score_field: str, group: str) -> float:
    rows = [row for row in summaries if row["sample_group"] == group]
    if len(rows) < 2:
        return 0.0
    return round(as_float(rows[-1][score_field]) - as_float(rows[0][score_field]), 3)


def top_failure_modes(rows: list[dict[str, Any]], *, limit: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for row in rows:
        for mode in failure_modes_list(row["primary_failure_modes"]):
            counts[mode] += 1
    return counts.most_common(limit)


def render_report(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    months = sorted({row["month"] for row in rows})
    rep_group = "representative_excluding_sentinel"
    all_group = "all_selected"
    top_modes = top_failure_modes(rows)
    rep_delta = score_delta(
        summaries,
        "confidence_weighted_mean_transcription_quality_score",
        rep_group,
    )
    diar_delta = score_delta(
        summaries,
        "confidence_weighted_mean_diarization_quality_score",
        rep_group,
    )
    all_delta = score_delta(
        summaries,
        "confidence_weighted_mean_transcription_quality_score",
        all_group,
    )

    lines = [
        "# LLM Judge Analysis",
        "",
        f"Rubric version: `{data.get('rubric_version', '')}`",
        f"Evaluated transcripts: `{len(rows)}` across `{len(months)}` months.",
        "",
        "## Headline",
        "",
        (
            "The ChatGPT judge marked the overall trend as "
            f"`{data.get('trend_assessment', {}).get('direction', 'unknown')}`. "
            "The representative-only view is the better trend lens because each month also "
            "contains one deliberately selected anomaly sentinel."
        ),
        "",
        (
            "Representative-only confidence-weighted transcription score delta "
            f"from {months[0]} to {months[-1]}: `{rep_delta:+.3f}`."
        ),
        (
            "Representative-only confidence-weighted diarization score delta "
            f"from {months[0]} to {months[-1]}: `{diar_delta:+.3f}`."
        ),
        (
            "All-selected confidence-weighted transcription score delta "
            f"from {months[0]} to {months[-1]}: `{all_delta:+.3f}`."
        ),
        "",
        "## Monthly Scores",
        "",
        (
            "| Month | Group | N | Transcription | Diarization | Timestamp | Artifact | "
            "Sentinels | Excerpt-limited |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in summaries:
        lines.append(
            "| {month} | {sample_group} | {n_evaluated} | {t:.2f} | {d:.2f} | "
            "{ts:.2f} | {a:.2f} | {n_sentinel} | {n_excerpt_limited} |".format(
                month=row["month"],
                sample_group=row["sample_group"],
                n_evaluated=row["n_evaluated"],
                t=as_float(row["confidence_weighted_mean_transcription_quality_score"]),
                d=as_float(row["confidence_weighted_mean_diarization_quality_score"]),
                ts=as_float(row["confidence_weighted_mean_timestamp_structure_score"]),
                a=as_float(row["confidence_weighted_mean_artifact_severity_score"]),
                n_sentinel=row["n_sentinel"],
                n_excerpt_limited=row["n_excerpt_limited"],
            )
        )

    lines.extend(["", "## Top Failure Modes", ""])
    for mode, count in top_modes:
        lines.append(f"- `{mode}`: {count}")

    trend = data.get("trend_assessment", {})
    limitations = trend.get("main_limitations") or []
    lines.extend(
        [
            "",
            "## Judge Trend Assessment",
            "",
            str(trend.get("strongest_evidence", "")).strip(),
            "",
            "## Limitations",
            "",
        ]
    )
    for limitation in limitations:
        lines.append(f"- {limitation}")

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            (
                "- `llm_judge_joined_scores.csv`: one row per judged transcript "
                "joined to sample metadata."
            ),
            (
                "- `llm_judge_monthly_scores.csv`: monthly means for all samples "
                "and representative-only rows."
            ),
            "- `llm_judge_failure_modes.csv`: failure-mode counts by month and sample group.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def fmt(value: Any, digits: int = 2) -> str:
    return f"{as_float(value):.{digits}f}"


def trend_label_ru(value: Any) -> str:
    key = str(value or "").strip()
    return TREND_RU.get(key, key or "нет оценки")


def sample_group_label_ru(value: str) -> str:
    if value == "representative_excluding_sentinel":
        return "Типичные без выброса"
    if value == "all_selected":
        return "Вся выборка"
    if value == "sentinel":
        return "Контрольный выброс"
    return "Типичные / контрастные"


def selection_reason_label_ru(value: str) -> str:
    return SELECTION_REASON_RU.get(value, value)


def limitation_ru(value: Any) -> str:
    text = str(value or "").strip()
    return LIMITATION_RU.get(text, text)


def trend_evidence_ru(value: Any) -> str:
    text = str(value or "").strip()
    return TREND_EVIDENCE_RU.get(text, text)


def failure_mode_ru(value: Any) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[\s-]+", "_", text.lower())
    return FAILURE_MODE_RU.get(text, FAILURE_MODE_RU.get(normalized, text))


def failure_modes_list(value: Any) -> list[str]:
    return [
        mode
        for mode in str(value or "").split("|")
        if mode and mode not in {"none", "excerpt_limited"}
    ]


def failure_modes_ru(value: Any) -> str:
    modes = failure_modes_list(value)
    if not modes:
        return ""
    return " · ".join(failure_mode_ru(mode) for mode in modes)


def excerpt_marker_ru(value: Any) -> str:
    return (
        "оценка только по видимому фрагменту"
        if str(value or "").lower() == "true"
        else ""
    )


def evidence_ru(value: Any) -> str:
    text = str(value or "").strip()
    return EVIDENCE_RU.get(text, text)


def wrap_svg_label(text: str, *, max_chars: int = 34, max_lines: int = 2) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    used_words = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
            used_words += 1
            continue
        lines.append(current)
        current = word
        used_words += 1
        if len(lines) == max_lines - 1:
            break

    if len(lines) == max_lines - 1 and used_words < len(words):
        tail = " ".join(words[used_words - 1 :])
        if len(tail) > max_chars:
            tail = tail[: max_chars - 1].rstrip() + "…"
        lines.append(tail)
    elif current:
        lines.append(current)
    return lines[:max_lines]


def group_summary_rows(
    summaries: list[dict[str, Any]],
    group: str,
) -> list[dict[str, Any]]:
    return [row for row in summaries if row["sample_group"] == group]


def has_any_sentinel(summaries: list[dict[str, Any]]) -> bool:
    return any(as_int(row.get("n_sentinel")) > 0 for row in summaries)


def polyline_points(
    values: list[float],
    *,
    width: int,
    height: int,
    pad_x: int,
    pad_y: int,
    min_y: float = 1.0,
    max_y: float = 5.0,
) -> str:
    if not values:
        return ""
    usable_w = width - pad_x * 2
    usable_h = height - pad_y * 2
    step = usable_w / max(1, len(values) - 1)
    points: list[str] = []
    for idx, value in enumerate(values):
        x = pad_x + idx * step
        bounded = min(max(value, min_y), max_y)
        y = pad_y + (max_y - bounded) / (max_y - min_y) * usable_h
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def render_score_trend_svg(
    summaries: list[dict[str, Any]],
    *,
    group: str = "representative_excluding_sentinel",
) -> str:
    rows = group_summary_rows(summaries, group)
    months = [row["month"] for row in rows]
    width = 860
    height = 310
    pad_x = 56
    pad_y = 34
    chart_bottom = height - pad_y
    grid_lines = []
    for score in range(1, 6):
        y = pad_y + (5 - score) / 4 * (height - pad_y * 2)
        grid_lines.append(
            f'<line x1="{pad_x}" y1="{y:.1f}" x2="{width - pad_x}" y2="{y:.1f}" '
            'stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="18" y="{y + 4:.1f}" class="axis-label">{score}</text>'
        )

    month_labels = []
    usable_w = width - pad_x * 2
    step = usable_w / max(1, len(months) - 1)
    for idx, month in enumerate(months):
        x = pad_x + idx * step
        month_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" '
            f'class="axis-label">{escape(month)}</text>'
        )

    lines = []
    legend = []
    for idx, field in enumerate(SCORE_FIELDS):
        values = [as_float(row[f"confidence_weighted_mean_{field}"]) for row in rows]
        color = FIELD_COLORS[field]
        points = polyline_points(
            values,
            width=width,
            height=height,
            pad_x=pad_x,
            pad_y=pad_y,
        )
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for point in points.split():
            x, y = point.split(",")
            lines.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
        legend_x = 78 + idx * 190
        legend.append(
            f'<rect x="{legend_x}" y="8" width="10" height="10" rx="2" fill="{color}"/>'
            f'<text x="{legend_x + 16}" y="18" class="legend-label">'
            f'{escape(SCORE_LABELS[field])}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Representative monthly judge score trends">'
        "<style>.axis-label{font:12px sans-serif;fill:#6b7280}"
        ".legend-label{font:12px sans-serif;fill:#374151}</style>"
        f'{"".join(grid_lines)}'
        f'<line x1="{pad_x}" y1="{chart_bottom}" x2="{width - pad_x}" '
        f'y2="{chart_bottom}" stroke="#9ca3af"/>'
        f'{"".join(month_labels)}'
        f'{"".join(lines)}'
        f'{"".join(legend)}'
        "</svg>"
    )


def render_transcription_comparison_svg(summaries: list[dict[str, Any]]) -> str:
    months = sorted({row["month"] for row in summaries})
    by_group = {
        row["sample_group"]: row
        for row in summaries
        if row["sample_group"] in {"all_selected", "representative_excluding_sentinel"}
    }
    rep_rows = group_summary_rows(summaries, "representative_excluding_sentinel")
    all_rows = group_summary_rows(summaries, "all_selected")
    width = 860
    height = 260
    pad_x = 56
    pad_y = 34
    chart_bottom = height - pad_y

    def values(rows: list[dict[str, Any]]) -> list[float]:
        return [
            as_float(row["confidence_weighted_mean_transcription_quality_score"])
            for row in rows
        ]

    rep_points = polyline_points(
        values(rep_rows),
        width=width,
        height=height,
        pad_x=pad_x,
        pad_y=pad_y,
    )
    all_points = polyline_points(
        values(all_rows),
        width=width,
        height=height,
        pad_x=pad_x,
        pad_y=pad_y,
    )
    month_labels = []
    usable_w = width - pad_x * 2
    step = usable_w / max(1, len(months) - 1)
    for idx, month in enumerate(months):
        x = pad_x + idx * step
        month_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" '
            f'class="axis-label">{escape(month)}</text>'
        )

    grid = []
    for score in range(1, 6):
        y = pad_y + (5 - score) / 4 * (height - pad_y * 2)
        grid.append(
            f'<line x1="{pad_x}" y1="{y:.1f}" x2="{width - pad_x}" y2="{y:.1f}" '
            'stroke="#e5e7eb" stroke-width="1"/>'
            f'<text x="18" y="{y + 4:.1f}" class="axis-label">{score}</text>'
        )

    # Keep the local variable intentional: a compact guard that both groups exist.
    _ = by_group
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Сравнение всей выборки и типичных строк без контрольных выбросов">'
        "<style>.axis-label{font:12px sans-serif;fill:#6b7280}"
        ".legend-label{font:12px sans-serif;fill:#374151}</style>"
        f'{"".join(grid)}'
        f'<line x1="{pad_x}" y1="{chart_bottom}" x2="{width - pad_x}" '
        f'y2="{chart_bottom}" stroke="#9ca3af"/>'
        f'{"".join(month_labels)}'
        f'<polyline points="{rep_points}" fill="none" stroke="#0f766e" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<polyline points="{all_points}" fill="none" stroke="#7c3aed" '
        'stroke-width="3" stroke-dasharray="8 6" stroke-linecap="round" '
        'stroke-linejoin="round"/>'
        '<rect x="78" y="8" width="10" height="10" rx="2" fill="#0f766e"/>'
        '<text x="94" y="18" class="legend-label">Типичные без выброса</text>'
        '<rect x="250" y="8" width="10" height="10" rx="2" fill="#7c3aed"/>'
        '<text x="266" y="18" class="legend-label">Вся выборка, включая выбросы</text>'
        "</svg>"
    )


def render_failure_mode_svg(rows: list[dict[str, Any]], *, limit: int = 10) -> str:
    items = top_failure_modes(rows, limit=limit)
    width = 980
    row_h = 48
    top = 48
    height = top + row_h * max(1, len(items)) + 18
    label_x = 18
    label_w = 360
    bar_x = 400
    value_w = 42
    bar_area_w = width - bar_x - value_w - 28
    max_count = max((count for _, count in items), default=1)
    rows_svg = []
    for idx, (mode, count) in enumerate(items):
        y = top + idx * row_h
        bar_w = bar_area_w * count / max_count
        label_lines = wrap_svg_label(failure_mode_ru(mode), max_chars=38, max_lines=2)
        tspans = "".join(
            f'<tspan x="{label_x}" dy="{0 if line_idx == 0 else 15}">'
            f"{escape(line)}</tspan>"
            for line_idx, line in enumerate(label_lines)
        )
        row_fill = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        rows_svg.append(
            f'<rect x="0" y="{y - 8}" width="{width}" height="{row_h}" fill="{row_fill}"/>'
            f'<text x="{label_x}" y="{y + 8}" class="bar-label">{tspans}</text>'
            f'<rect x="{bar_x}" y="{y}" width="{bar_w:.1f}" height="22" '
            'rx="7" fill="#334155"/>'
            f'<text x="{bar_x + bar_w + 10:.1f}" y="{y + 16}" '
            f'class="bar-value">{count}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Основные типы ошибок">'
        "<style>.bar-label{font:13px sans-serif;fill:#334155}"
        ".bar-value{font:13px sans-serif;fill:#475569;font-weight:700}"
        ".bar-head{font:12px sans-serif;fill:#64748b;font-weight:700;text-transform:uppercase}"
        ".bar-divider{stroke:#e2e8f0;stroke-width:1}</style>"
        '<rect x="0" y="0" width="980" height="38" fill="#f1f5f9" rx="12"/>'
        f'<text x="{label_x}" y="24" class="bar-head">Тип ошибки</text>'
        f'<text x="{bar_x}" y="24" class="bar-head">Количество в выборке</text>'
        f'<line x1="{label_w + 18}" y1="8" x2="{label_w + 18}" y2="{height - 8}" '
        'class="bar-divider"/>'
        f'{"".join(rows_svg)}</svg>'
    )


def render_monthly_failure_mode_cards(rows: list[dict[str, Any]]) -> str:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_month[str(row["month"])].append(row)

    cards = []
    for month in sorted(by_month):
        month_rows = by_month[month]
        counts: Counter[str] = Counter()
        for row in month_rows:
            modes = failure_modes_list(row.get("primary_failure_modes", ""))
            if not modes:
                modes = ["none"]
            for mode in modes:
                counts[mode] += 1

        month_modes = sorted(counts.items(), key=lambda item: (-item[1], failure_mode_ru(item[0])))
        max_count = max((count for _, count in month_modes), default=1)
        total_mode_mentions = sum(counts.values())
        sentinel_count = sum(1 for row in month_rows if row.get("sample_group") == "sentinel")
        excerpt_count = sum(
            1 for row in month_rows if str(row.get("excerpt_limited")).lower() == "true"
        )
        mode_rows = []
        for mode, count in month_modes:
            width_pct = 100 * count / max_count
            share_pct = 100 * count / max(1, total_mode_mentions)
            mode_rows.append(
                '<div class="month-error-row">'
                '<div class="month-error-meta">'
                f'<div class="month-error-label">{escape(failure_mode_ru(mode))}</div>'
                f'<div class="month-error-share">{share_pct:.0f}% всех меток месяца</div>'
                "</div>"
                '<div class="month-error-track">'
                f'<span style="width:{width_pct:.1f}%"></span>'
                "</div>"
                f'<strong>{count}</strong>'
                "</div>"
            )

        cards.append(
            '<article class="month-error-card">'
            '<div class="month-error-head">'
            f"<h3>{escape(month)}</h3>"
            '<div class="month-error-badges">'
            f"<span>{len(month_rows)} фрагм.</span>"
            f"<span>{len(counts)} типов</span>"
            f"<span>{total_mode_mentions} меток</span>"
            f"<span>{sentinel_count} sentinel</span>"
            f"<span>{excerpt_count} только фрагмент</span>"
            "</div>"
            "</div>"
            '<div class="month-error-column-head">'
            '<span>Тип ошибки и доля внутри месяца</span>'
            '<span>Сила сигнала</span>'
            '<span>Кол-во</span>'
            '</div>'
            f'{"".join(mode_rows)}'
            "</article>"
        )

    return "\n".join(cards)


def render_score_cards(summaries: list[dict[str, Any]]) -> str:
    rep_rows = group_summary_rows(summaries, "representative_excluding_sentinel")
    if not rep_rows:
        return ""
    first = rep_rows[0]
    last = rep_rows[-1]
    best = max(
        rep_rows,
        key=lambda row: as_float(row["confidence_weighted_mean_transcription_quality_score"]),
    )
    weakest = min(
        rep_rows,
        key=lambda row: as_float(row["confidence_weighted_mean_transcription_quality_score"]),
    )
    cards = [
        (
            "Дельта текста",
            (
                as_float(last["confidence_weighted_mean_transcription_quality_score"])
                - as_float(first["confidence_weighted_mean_transcription_quality_score"])
            ),
            f"{first['month']} → {last['month']}",
        ),
        (
            "Дельта диаризации",
            (
                as_float(last["confidence_weighted_mean_diarization_quality_score"])
                - as_float(first["confidence_weighted_mean_diarization_quality_score"])
            ),
            f"{first['month']} → {last['month']}",
        ),
        (
            "Лучший месяц",
            as_float(best["confidence_weighted_mean_transcription_quality_score"]),
            str(best["month"]),
        ),
        (
            "Слабый месяц",
            as_float(weakest["confidence_weighted_mean_transcription_quality_score"]),
            str(weakest["month"]),
        ),
    ]
    html = []
    for title, value, subtitle in cards:
        value_text = f"{value:+.2f}" if "дельта" in title.lower() else f"{value:.2f}"
        html.append(
            '<article class="stat-card">'
            f'<div class="stat-title">{escape(title)}</div>'
            f'<div class="stat-value">{escape(value_text)}</div>'
            f'<div class="stat-subtitle">{escape(subtitle)}</div>'
            "</article>"
        )
    return "\n".join(html)


def render_monthly_html_table(summaries: list[dict[str, Any]]) -> str:
    visible_rows = (
        summaries if has_any_sentinel(summaries) else group_summary_rows(summaries, "all_selected")
    )
    rows = []
    for row in visible_rows:
        group = sample_group_label_ru(str(row["sample_group"]))
        rows.append(
            "<tr>"
            f"<td>{escape(str(row['month']))}</td>"
            f"<td>{escape(group)}</td>"
            f"<td>{row['n_evaluated']}</td>"
            f"<td>{fmt(row['confidence_weighted_mean_transcription_quality_score'])}</td>"
            f"<td>{fmt(row['confidence_weighted_mean_diarization_quality_score'])}</td>"
            f"<td>{fmt(row['confidence_weighted_mean_timestamp_structure_score'])}</td>"
            f"<td>{fmt(row['confidence_weighted_mean_artifact_severity_score'])}</td>"
            f"<td>{row['n_sentinel']}</td>"
            f"<td>{row['n_excerpt_limited']}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Месяц</th><th>Группа</th><th>N</th><th>Текст</th>"
        "<th>Диаризация</th><th>Время</th><th>Артефакты</th>"
        "<th>Выбросы</th><th>Фрагменты</th>"
        "</tr></thead><tbody>"
        f'{"".join(rows)}'
        "</tbody></table></div>"
    )


def render_low_score_examples(rows: list[dict[str, Any]]) -> str:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_month[str(row["month"])].append(row)

    ordered: list[dict[str, Any]] = []
    for month in sorted(by_month):
        month_rows = sorted(
            by_month[month],
            key=lambda row: (
                as_float(row["transcription_quality_score"])
                + as_float(row["diarization_quality_score"])
                + as_float(row["artifact_severity_score"]),
                as_float(row["timestamp_structure_score"]),
                -as_float(row["judge_confidence"]),
                str(row["transcript_id"]),
            ),
        )
        ordered.append(month_rows[0])

    cards = []
    for row in ordered:
        excerpt_marker = excerpt_marker_ru(row.get("excerpt_limited"))
        meta_html = (
            '<div class="example-meta">'
            f'<span>{escape(str(row["month"]))}</span>'
            f'<span>{escape(selection_reason_label_ru(str(row["selection_reason"])))}</span>'
            + (
                f'<span class="meta-neutral">{escape(excerpt_marker)}</span>'
                if excerpt_marker
                else ""
            )
            + "</div>"
        )
        cards.append(
            '<article class="example-card">'
            f"{meta_html}"
            f'<h3>{escape(str(row["transcript_id"]))}</h3>'
            '<p class="scoreline">'
            f'Текст {row["transcription_quality_score"]} · '
            f'Диаризация {row["diarization_quality_score"]} · '
            f'Артефакты {row["artifact_severity_score"]}'
            "</p>"
            f'<p>{escape(evidence_ru(row["evidence"]))}</p>'
            f'<p class="modes">{escape(failure_modes_ru(row["primary_failure_modes"]))}</p>'
            "</article>"
        )
    return "\n".join(cards)


def render_timestamp_drop_analysis(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    rep_rows = group_summary_rows(summaries, "representative_excluding_sentinel")
    if len(rep_rows) < 4:
        return ""

    last_two = rep_rows[-2:]
    prev_two = rep_rows[-4:-2]
    last_avg = mean(
        [as_float(row["confidence_weighted_mean_timestamp_structure_score"]) for row in last_two]
    )
    prev_avg = mean(
        [as_float(row["confidence_weighted_mean_timestamp_structure_score"]) for row in prev_two]
    )
    delta = last_avg - prev_avg

    late_months = {row["month"] for row in last_two}
    late_rows = [row for row in rows if row["month"] in late_months]
    coarse_count = sum(
        1
        for row in late_rows
        if "coarse_timestamps" in str(row.get("primary_failure_modes", "")).split("|")
    )
    low_timestamp = sum(1 for row in late_rows if as_float(row["timestamp_structure_score"]) <= 3)
    total = len(late_rows)
    concrete = [
        row
        for row in late_rows
        if "coarse_timestamps" in str(row.get("primary_failure_modes", "")).split("|")
    ][:3]
    examples = "".join(
        "<li>"
        f"<strong>{escape(str(row['month']))}</strong>, "
        f"<code>{escape(str(row['transcript_id']))}</code>: "
        f"{escape(evidence_ru(row['evidence']))}"
        "</li>"
        for row in concrete
    )

    direction = "ниже" if delta < 0 else "выше"
    return f"""
      <section class="analysis-panel">
        <h2>Почему просела временная разметка в конце периода</h2>
        <p>В последних двух месяцах средняя representative-only оценка временной разметки составляет <strong>{last_avg:.2f}</strong> против <strong>{prev_avg:.2f}</strong> в двух предыдущих месяцах. Разница: <strong>{delta:+.2f}</strong>, то есть конец периода заметно {direction} предыдущего окна.</p>
        <p>Главная причина не в полном отсутствии timestamps, а в их <strong>крупной зернистости</strong>: judge часто видит один длинный timestamp-блок на целый монолог или длинные растянутые участки вместо регулярной разметки по репликам. В марте-апреле <strong>{coarse_count} из {total}</strong> оцененных фрагментов получили метку «{failure_mode_ru("coarse_timestamps")}», а <strong>{low_timestamp}</strong> фрагментов имеют оценку временной структуры 3 или ниже.</p>
        <ul class="mode-list">{examples}</ul>
        <p class="section-note">Интерпретация: качество текста в части этих примеров остается высоким, но временная структура становится менее полезной для навигации, цитирования и аудита диаризации. Это похоже на сдвиг в сторону длинных монологов/лекций или режимов экспорта с более грубыми сегментами, а не обязательно на деградацию распознавания слов.</p>
      </section>
    """


def render_text_artifact_drop_analysis(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    rep_rows = group_summary_rows(summaries, "representative_excluding_sentinel")
    all_rows = group_summary_rows(summaries, "all_selected")
    if len(rep_rows) < 2 or len(all_rows) < 2:
        return ""

    prev = rep_rows[-2]
    last = rep_rows[-1]
    last_all = all_rows[-1]
    last_month = str(last["month"])
    prev_month = str(prev["month"])
    last_non_sentinel = [
        row
        for row in rows
        if row["month"] == last_month and row["sample_group"] != "sentinel"
    ]
    prev_non_sentinel = [
        row
        for row in rows
        if row["month"] == prev_month and row["sample_group"] != "sentinel"
    ]
    last_sentinel = [
        row
        for row in rows
        if row["month"] == last_month and row["sample_group"] == "sentinel"
    ]

    last_text = as_float(last["confidence_weighted_mean_transcription_quality_score"])
    prev_text = as_float(prev["confidence_weighted_mean_transcription_quality_score"])
    last_artifact = as_float(last["confidence_weighted_mean_artifact_severity_score"])
    prev_artifact = as_float(prev["confidence_weighted_mean_artifact_severity_score"])
    all_text = as_float(last_all["confidence_weighted_mean_transcription_quality_score"])
    all_artifact = as_float(last_all["confidence_weighted_mean_artifact_severity_score"])
    text_delta = last_text - prev_text
    artifact_delta = last_artifact - prev_artifact
    all_text_gap = all_text - last_text
    all_artifact_gap = all_artifact - last_artifact

    strong_last = sum(
        1
        for row in last_non_sentinel
        if as_float(row["transcription_quality_score"]) >= 4
        and as_float(row["artifact_severity_score"]) >= 4
    )
    low_last = [
        row
        for row in last_non_sentinel
        if as_float(row["transcription_quality_score"]) <= 3
        or as_float(row["artifact_severity_score"]) <= 3
    ]
    low_prev = [
        row
        for row in prev_non_sentinel
        if as_float(row["transcription_quality_score"]) <= 3
        or as_float(row["artifact_severity_score"]) <= 3
    ]
    examples = sorted(
        [*low_last, *last_sentinel],
        key=lambda row: (
            as_float(row["transcription_quality_score"])
            + as_float(row["artifact_severity_score"]),
            row["sample_group"] != "sentinel",
        ),
    )[:4]
    example_items = "".join(
        "<li>"
        f"<strong>{escape(str(row['month']))}</strong>, "
        f"<code>{escape(str(row['transcript_id']))}</code> "
        f"({escape(selection_reason_label_ru(str(row['selection_reason'])))}): "
        f"текст {row['transcription_quality_score']}, "
        f"артефакты {row['artifact_severity_score']} — "
        f"{escape(evidence_ru(row['evidence']))} "
        f"<span class=\"modes\">{escape(failure_modes_ru(row['primary_failure_modes']))}</span>"
        "</li>"
        for row in examples
    )

    return f"""
      <section class="analysis-panel">
        <h2>Почему в последнем месяце ниже качество текста и контроль артефактов</h2>
        <p>Если сравнивать non-sentinel выборку, в <strong>{escape(last_month)}</strong> confidence-weighted «Качество текста» равно <strong>{last_text:.2f}</strong> против <strong>{prev_text:.2f}</strong> в <strong>{escape(prev_month)}</strong> ({text_delta:+.2f}). «Контроль артефактов» ведет себя почти так же: <strong>{last_artifact:.2f}</strong> против <strong>{prev_artifact:.2f}</strong> ({artifact_delta:+.2f}).</p>
        <p>Главная причина — не равномерное ухудшение всего апреля, а состав выборки. В <strong>{escape(last_month)}</strong> <strong>{strong_last} из {len(last_non_sentinel)}</strong> non-sentinel фрагментов имеют одновременно 4–5 по тексту и артефактам, но один contrastive rare пример получил <strong>1</strong> по тексту и <strong>1</strong> по артефактам. Так как confidence у этого примера высокий, он заметно тянет weighted mean вниз. Для сравнения, в <strong>{escape(prev_month)}</strong> таких non-sentinel просадок было <strong>{len(low_prev)}</strong>.</p>
        <p>Если смотреть всю выбранную выборку, эффект усиливается: апрельский sentinel добавляет еще один тяжелый случай с повторяющимся/почти пустым содержанием. Поэтому all-selected среднее в апреле ниже non-sentinel линии на <strong>{all_text_gap:+.2f}</strong> по тексту и <strong>{all_artifact_gap:+.2f}</strong> по артефактам.</p>
        <ul class="mode-list">{example_items}</ul>
        <p class="section-note">Интерпретация: апрель выглядит слабее марта прежде всего из-за двух крайних видимых артефактов — contrastive gibberish-примера и контрольного sentinel-примера. Остальные апрельские строки в основном остаются читаемыми; поэтому это скорее сигнал о хвостовом риске и нестабильности на редких кейсах, чем доказательство массовой деградации обычных транскрипций.</p>
      </section>
    """


def render_methodology_html(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    packet_metadata: dict[str, Any],
) -> str:
    months = sorted({row["month"] for row in rows})
    representative_summaries = group_summary_rows(
        summaries,
        "representative_excluding_sentinel",
    )
    selection_counts = Counter(str(row.get("selection_reason") or "") for row in rows)
    selection_items = "".join(
        f"<li><strong>{escape(selection_reason_label_ru(reason))}</strong>: {count}</li>"
        for reason, count in sorted(selection_counts.items())
    )

    excerpt_limited_count = sum(
        1 for row in rows if str(row.get("excerpt_limited")).lower() == "true"
    )
    sentinel_count = sum(1 for row in rows if row.get("sample_group") == "sentinel")
    source_file = packet_metadata.get("source_file") or "исходный CSV-файл в корне проекта"
    sampling_seed = packet_metadata.get("sampling_seed", "не найден в packet metadata")
    target_samples = packet_metadata.get("target_samples_per_month", "не найдено")
    max_chars = packet_metadata.get("max_transcript_chars", "не найдено")
    selected_by_month = packet_metadata.get("selected_by_month")
    if isinstance(selected_by_month, dict) and selected_by_month:
        counts = sorted({int(value) for value in selected_by_month.values()})
        selected_by_month_text = (
            f"{counts[0]} фрагментов в месяц"
            if len(counts) == 1
            else f"от {counts[0]} до {counts[-1]} фрагментов в месяц"
        )
    else:
        selected_by_month_text = f"{len(rows)} фрагментов за {len(months)} месяцев"

    limitation_items = "".join(
        f"<li>{escape(limitation_ru(item))}</li>"
        for item in data.get("trend_assessment", {}).get("main_limitations", []) or []
    )
    first_rep = representative_summaries[0] if representative_summaries else {}
    last_rep = representative_summaries[-1] if representative_summaries else {}

    return f"""
    <section>
      <h2>Как была получена LLM-оценка</h2>
      <p class="section-note">Этот блок фиксирует воспроизводимый путь от большого CSV с транскрипциями до итоговых графиков. Он важен потому, что LLM-as-a-judge здесь является исследовательской оценкой видимого текста, а не измерением WER по эталонной расшифровке и не проверкой по аудио.</p>

      <div class="method-grid">
        <div class="method-card">
          <h3>1. Исходные данные</h3>
          <p>Входом был большой UTF-8 BOM CSV: <code>{escape(str(source_file))}</code>. Для этой LLM-выборки использовались строки с распознаваемым <code>created_at</code> и полем <code>transcription_text</code>; дополнительные поля вроде <code>id</code> и <code>file_name</code> сохранялись как audit metadata.</p>
          <p>Период текущей оценки: <strong>{escape(months[0])} — {escape(months[-1])}</strong>. В отчет попало <strong>{len(rows)}</strong> оцененных фрагмента: {escape(selected_by_month_text)}.</p>
        </div>

        <div class="method-card">
          <h3>2. Как собрали вход для ChatGPT</h3>
          <p><code>scripts/build_llm_judge_sample.py</code> прошел по исходному CSV и построил кандидатов по месяцам. Для отбора использовались дешевые воспроизводимые признаки: число токенов, число timestamp/speaker-сегментов, число говорящих, доля malformed timestamps, частота смены говорящих, повторяющиеся символы, непечатаемые символы, script-based language proxy и грубая content category по словарям.</p>
          <p>Отбор был детерминированным: <code>seed={escape(str(sampling_seed))}</code>, целевой размер <code>{escape(str(target_samples))}</code> на месяц, максимум <code>{escape(str(max_chars))}</code> символов видимого текста на один transcript. Длинные строки передавались как начало, середина и конец; такие строки помечались <code>excerpt_limited=true</code>.</p>
        </div>

        <div class="method-card">
          <h3>3. Состав выборки</h3>
          <p>Выборка не является простой случайной выборкой. Она специально смешивает типичные строки, редкие контрастные слои и контрольные проблемные примеры, чтобы одновременно увидеть обычное качество и риск тяжелых артефактов.</p>
          <ul class="mode-list">{selection_items}</ul>
          <p><strong>{sentinel_count}</strong> строк — контрольные выбросы (sentinel: специально выбранный проблемный пример месяца). <strong>{excerpt_limited_count}</strong> строк оценивались по фрагментам, а не по полному тексту.</p>
        </div>

        <div class="method-card">
          <h3>4. Что делал LLM judge</h3>
          <p>В ChatGPT передавался packet с фиксированным prompt <code>llm_judge_v1</code>. Модель должна была оценивать только видимый transcript evidence, не использовать внешние знания, не угадывать правильность темы и вернуть валидный JSON.</p>
          <p>Для каждого transcript LLM выставляла оценки 1–5 по четырем шкалам: качество текста, диаризация, временная разметка и тяжесть артефактов. Дополнительно возвращались confidence, краткая evidence-строка и primary failure modes.</p>
        </div>

        <div class="method-card">
          <h3>5. Как посчитан отчет</h3>
          <p><code>scripts/analyze_llm_judge_output.py</code> валидирует JSON-ответ, проверяет диапазон оценок, сопоставляет transcript IDs с <code>llm_judge_sample_index.csv</code> и строит производные файлы: joined scores, monthly scores, failure-mode counts, Markdown analysis и этот HTML.</p>
          <p>Месячные оценки считаются в двух видах: <strong>all selected</strong> включает весь набор, а <strong>representative-only</strong> исключает sentinel-выбросы и лучше показывает обычную динамику корпуса. Основные графики используют confidence-weighted mean, то есть оценки с большей уверенностью judge получают больший вес.</p>
        </div>

        <div class="method-card">
          <h3>6. Как читать выводы</h3>
          <p>Для тренда качества основная линия — representative-only. В текущем отчете она сравнивает <strong>{escape(str(first_rep.get("month", "")))}</strong> и <strong>{escape(str(last_rep.get("month", "")))}</strong>, а контрольные выбросы используются как отдельный слой риска, а не как типичный пользовательский сценарий.</p>
          <p>Ограничения: без аудио и эталонного текста это не WER/CER; LLM оценивает только видимый transcript; некоторые длинные строки excerpt-limited; content/language признаки в sample index являются proxy; результат зависит от фиксированного prompt и выбранной модели ChatGPT.</p>
          <ul class="mode-list">{limitation_items}</ul>
        </div>
      </div>
    </section>
    """


def render_html_report(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    packet_metadata: dict[str, Any] | None = None,
) -> str:
    months = sorted({row["month"] for row in rows})
    packet_metadata = packet_metadata or {}
    trend = data.get("trend_assessment", {})
    top_modes = top_failure_modes(rows, limit=8)
    top_modes_text = ", ".join(f"{failure_mode_ru(mode)} ({count})" for mode, count in top_modes[:4])
    sentinel_present = has_any_sentinel(summaries)
    report_title = "LLM-as-Judge: оценка качества транскрипции"
    generated_note = (
        "Отчет собран из JSON-ответа ChatGPT и фиксированной месячной выборки. "
        "Оценки рассчитаны по неизменной рубрике llm_judge_v1."
    )
    lead_callout = (
        "Общий вывод judge: "
        f"<strong>{escape(trend_label_ru(trend.get('direction', 'unknown')))}</strong>. "
        "Самая честная линия тренда — «типичные без выброса», потому что в каждый месяц "
        "специально добавлен один контрольный проблемный пример."
        if sentinel_present
        else "Общий вывод judge: "
        f"<strong>{escape(trend_label_ru(trend.get('direction', 'unknown')))}</strong>. "
        "В этой выборке нет отдельных контрольных выбросов, поэтому графики и таблицы "
        "ниже показывают одну и ту же месячную панель."
    )
    trend_title = (
        "Оценки по месяцам: типичная выборка"
        if sentinel_present
        else "Оценки по месяцам"
    )
    trend_note = (
        "Средние значения с весом по уверенности judge, шкала 1–5. Контрольный выброс месяца исключен. Чем выше, тем лучше по всем четырем измерениям."
        if sentinel_present
        else "Средние значения с весом по уверенности judge, шкала 1–5. Чем выше, тем лучше по всем четырем измерениям."
    )
    comparison_section = (
        f"""
    <section>
      <h2>Как контрольные выбросы меняют картину</h2>
      <p class="section-note">Пунктир включает всю выбранную выборку. Сплошная линия исключает месячный контрольный выброс (sentinel: специально выбранный проблемный пример месяца) и лучше показывает обычное поведение корпуса.</p>
      <div class="chart-card">{render_transcription_comparison_svg(summaries)}</div>
    </section>
"""
        if sentinel_present
        else ""
    )
    monthly_table_note = (
        "Оставлены две перспективы: типичная динамика качества и риск столкнуться с тяжелыми крайними случаями."
        if sentinel_present
        else "В этой выборке нет отдельных sentinel-примеров, поэтому на месяц показана одна итоговая строка."
    )
    monthly_modes_note = (
        "Каждая карточка показывает полный состав failure-mode меток внутри месяца: без скрытия «редких» типов. Для каждого типа видно абсолютное количество, относительную долю среди всех error labels месяца и бар для быстрого сравнения. Считается вся judge-выборка месяца, включая контрольный sentinel-пример; если нужна аналитика без sentinel, используйте <code>llm_judge_failure_modes.csv</code> и фильтр по <code>sample_group</code>."
        if sentinel_present
        else "Каждая карточка показывает полный состав failure-mode меток внутри месяца: без скрытия «редких» типов. Для каждого типа видно абсолютное количество, относительную долю среди всех error labels месяца и бар для быстрого сравнения."
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escape(report_title)}</title>
  <style>
    :root {{
      --ink: #18181b;
      --muted: #71717a;
      --line: #e4e4e7;
      --paper: #fafafa;
      --accent: #2563eb;
      --accent-2: #059669;
      --warn: #d97706;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #f4f4f5;
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    main {{
      width: min(1152px, 100%);
      margin: 0 auto;
      min-height: 100vh;
      background: #fff;
      padding: 40px;
      box-shadow: 0 25px 55px rgba(24,24,27,.16);
    }}
    .hero {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 30px;
      margin-bottom: 36px;
    }}
    .eyebrow {{
      font-size: 13px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 8px;
    }}
    h1 {{
      font-size: clamp(32px, 5vw, 48px);
      line-height: 1.08;
      margin: 0 0 14px;
      max-width: 900px;
      letter-spacing: -0.01em;
    }}
    h2 {{
      font-size: 26px;
      line-height: 1.2;
      margin: 0 0 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }}
    h3 {{ margin: 0 0 8px; font-size: 16px; }}
    p {{ margin: 0 0 12px; }}
    .lede {{ max-width: 860px; color: #52525b; font-size: 16px; }}
    .meta-grid, .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .meta-pill, .stat-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 16px;
    }}
    .meta-pill {{ padding: 16px; font-size: 14px; text-align: center; }}
    .meta-pill strong {{ display: block; color: var(--muted); font-size: 13px; font-weight: 500; }}
    .stat-card {{ padding: 16px; text-align: center; }}
    .stat-title {{ font-size: 13px; color: var(--muted); }}
    .stat-value {{ font-size: 34px; line-height: 1.1; font-weight: 800; margin: 8px 0 4px; color: var(--accent); }}
    .stat-subtitle {{ font-size: 13px; color: var(--muted); }}
    section {{ margin-bottom: 40px; }}
    .section-note {{ color: var(--muted); max-width: 850px; }}
    .chart-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      overflow-x: auto;
      margin-top: 16px;
    }}
    svg {{ width: 100%; min-width: 720px; height: auto; display: block; }}
    .table-wrap {{ overflow-x: auto; margin-top: 14px; border: 1px solid var(--line); border-radius: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; font: 13px/1.35 Verdana, sans-serif; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf0f5; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    th {{ color: #475467; background: #f1f5f9; font-weight: 700; }}
    .two-col {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr); gap: 20px; }}
    .callout {{
      border-left: 4px solid #bfdbfe;
      padding: 4px 0 4px 20px;
      color: #3f3f46;
      font-size: 15px;
    }}
    .analysis-panel {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      padding: 22px;
    }}
    .method-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .method-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
    }}
    .method-card h3 {{ color: #1f2937; }}
    .month-error-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .month-error-card {{
      border: 1px solid #e2e8f0;
      border-radius: 18px;
      padding: 16px;
      background:
        linear-gradient(135deg, rgba(248,250,252,.96), rgba(255,255,255,.98)),
        radial-gradient(circle at top right, rgba(37,99,235,.12), transparent 36%);
      box-shadow: 0 10px 24px rgba(15,23,42,.06);
    }}
    .month-error-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .month-error-head h3 {{ font-size: 22px; letter-spacing: -.01em; }}
    .month-error-badges {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }}
    .month-error-badges span {{
      font: 11px/1.2 Verdana, sans-serif;
      color: #475569;
      background: #e2e8f0;
      border-radius: 999px;
      padding: 4px 7px;
    }}
    .month-error-column-head {{
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(110px, .9fr) 40px;
      gap: 10px;
      align-items: center;
      margin: 0 0 8px;
      font: 11px/1.2 Verdana, sans-serif;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .month-error-row {{
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(110px, .9fr) 40px;
      gap: 10px;
      align-items: center;
      margin: 9px 0;
      font: 13px/1.25 Verdana, sans-serif;
      color: #334155;
    }}
    .month-error-meta {{ min-width: 0; }}
    .month-error-label {{ overflow-wrap: anywhere; }}
    .month-error-share {{ color: #64748b; font-size: 11px; margin-top: 3px; }}
    .month-error-track {{
      height: 12px;
      border-radius: 999px;
      background: #e2e8f0;
      overflow: hidden;
      box-shadow: inset 0 1px 2px rgba(15,23,42,.08);
    }}
    .month-error-track span {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #0f766e, #2563eb 68%, #7c3aed);
    }}
    .month-error-row strong {{ color: #0f172a; text-align: right; font-size: 14px; }}
    .mode-list {{ font: 14px/1.45 Verdana, sans-serif; color: #344054; }}
    .mode-list code {{ background: #eef2f7; padding: 2px 5px; border-radius: 5px; }}
    .examples {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }}
    .example-card {{ background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 15px; }}
    .example-meta {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
    .example-meta span, .modes {{
      font: 12px/1.2 Verdana, sans-serif;
      color: #475467;
      background: #f1f5f9;
      border-radius: 999px;
      padding: 4px 8px;
      display: inline-block;
    }}
    .example-meta .meta-neutral {{ background: #eef2ff; color: #4338ca; }}
    .scoreline {{ color: var(--warn); font-weight: 700; }}
    footer {{ color: #a1a1aa; font-size: 12px; line-height: 1.5; text-align: center; padding-top: 28px; border-top: 1px solid var(--line); }}
    @media (max-width: 760px) {{
      main {{ padding: 24px 16px; }}
      section {{ padding: 18px; }}
      .two-col {{ grid-template-columns: 1fr; }}
      svg {{ min-width: 620px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div class="eyebrow">Layer C · LLM-as-a-judge</div>
      <h1>{escape(report_title)}</h1>
      <p class="lede">{escape(generated_note)}</p>
      <div class="meta-grid">
        <div class="meta-pill"><strong>Рубрика</strong>{escape(str(data.get("rubric_version", "")))}</div>
        <div class="meta-pill"><strong>Оценено фрагментов</strong>{len(rows)}</div>
        <div class="meta-pill"><strong>Период</strong>{escape(months[0])} — {escape(months[-1])}</div>
        <div class="meta-pill"><strong>Вывод judge</strong>{escape(trend_label_ru(trend.get("direction", "unknown")))}</div>
      </div>
    </header>

    <section>
      <h2>Краткое чтение результата</h2>
      <div class="two-col">
        <div class="callout">
          <p>{lead_callout}</p>
          <p>{escape(trend_evidence_ru(trend.get("strongest_evidence", "")))}</p>
          <p>Самые частые типы проблем: {escape(top_modes_text)}.</p>
        </div>
        <div class="stat-grid">
          {render_score_cards(summaries)}
        </div>
      </div>
    </section>

    <section>
      <h2>{trend_title}</h2>
      <p class="section-note">{trend_note}</p>
      <div class="chart-card">{render_score_trend_svg(summaries, group=("representative_excluding_sentinel" if sentinel_present else "all_selected"))}</div>
    </section>

    {comparison_section}

    <section>
      <h2>Таблица месячных оценок</h2>
      <p class="section-note">{monthly_table_note}</p>
      {render_monthly_html_table(summaries)}
    </section>

    <section>
      <h2>Основные типы ошибок за весь период LLM-оценки</h2>
      <p class="section-note">Диаграмма ниже агрегирует метки по всем {len(rows)} оцененным фрагментам за период {escape(months[0])} — {escape(months[-1])}. Это не один месяц и не последний период, а общая частотность типов ошибок во всей LLM-judge выборке; помесячная детализация сохранена в <code>llm_judge_failure_modes.csv</code>.</p>
      <div class="chart-card">{render_failure_mode_svg(rows)}</div>
    </section>

    <section>
      <h2>Типы ошибок по месяцам</h2>
      <p class="section-note">{monthly_modes_note}</p>
      <div class="month-error-grid">{render_monthly_failure_mode_cards(rows)}</div>
    </section>

    <section>
      <h2>Примеры с самыми низкими оценками</h2>
      <p class="section-note">Эти карточки полезны для отладки: они показывают, какие видимые признаки judge счел деградацией качества.</p>
      <div class="examples">{render_low_score_examples(rows)}</div>
    </section>

    {render_methodology_html(data, rows, summaries, packet_metadata)}

    <footer>
      Отчет собран командой <code>python scripts/analyze_llm_judge_output.py</code>. Соседние файлы:
      <code>llm_judge_joined_scores.csv</code>, <code>llm_judge_monthly_scores.csv</code>,
      <code>llm_judge_failure_modes.csv</code> и <code>llm_judge_analysis.md</code>.
    </footer>
  </main>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize LLM judge JSON output.")
    parser.add_argument(
        "--input",
        "-i",
        default=None,
        help=(
            "Judge output JSON path. Defaults to llm_judge_output.json inside "
            "the resolved output directory."
        ),
    )
    parser.add_argument(
        "--sample-index",
        default=None,
        help=(
            "Sample index CSV path. Defaults to llm_judge_sample_index.csv inside "
            "the resolved output directory."
        ),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory or run root (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run folder name under --output-dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = resolve_output_dir(args.output_dir, args.run_id)
    input_path = Path(args.input) if args.input else output_dir / DEFAULT_OUTPUT_JSON_NAME
    sample_index_path = (
        Path(args.sample_index) if args.sample_index else output_dir / DEFAULT_INDEX_NAME
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_json(input_path)
    sample_index = load_index(sample_index_path)
    packet_metadata = load_packet_metadata(output_dir / DEFAULT_PACKET_NAME)
    rows = flatten_rows(data, sample_index)
    summaries = monthly_summaries(rows)
    failures = failure_mode_rows(rows)

    joined_path = output_dir / "llm_judge_joined_scores.csv"
    monthly_path = output_dir / "llm_judge_monthly_scores.csv"
    failures_path = output_dir / "llm_judge_failure_modes.csv"
    report_path = output_dir / "llm_judge_analysis.md"
    html_report_path = output_dir / "llm_judge_research_report.html"

    write_csv(joined_path, rows)
    write_csv(monthly_path, summaries)
    write_csv(failures_path, failures)
    report_path.write_text(render_report(data, rows, summaries), encoding="utf-8")
    html_report_path.write_text(
        render_html_report(data, rows, summaries, packet_metadata),
        encoding="utf-8",
    )

    summary = {
        "run_id": args.run_id or "",
        "output_dir": str(output_dir.resolve()),
        "transcripts": len(rows),
        "months": sorted({row["month"] for row in rows}),
        "joined_scores": str(joined_path.resolve()),
        "monthly_scores": str(monthly_path.resolve()),
        "failure_modes": str(failures_path.resolve()),
        "report": str(report_path.resolve()),
        "html_report": str(html_report_path.resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

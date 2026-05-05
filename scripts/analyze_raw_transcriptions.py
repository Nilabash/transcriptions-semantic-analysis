import csv
import json
import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUTPUT_PATH = Path("outputs/raw_transcriptions_llm_analysis.json")


KEYWORDS = {
    "work_business": [
        "клиент",
        "проект",
        "задач",
        "встреч",
        "созвон",
        "договор",
        "сделк",
        "бизнес",
        "команд",
        "маркет",
        "продаж",
        "office",
        "meeting",
        "project",
        "client",
        "task",
        "deal",
        "contract",
        "work",
        "team",
    ],
    "tech_it": [
        "код",
        "программ",
        "сервер",
        "баг",
        "ошибк",
        "api",
        "python",
        "javascript",
        "sql",
        "docker",
        "алгоритм",
        "данн",
        "deploy",
        "backend",
        "frontend",
        "debug",
        "github",
        "prompt",
        "llm",
        "model",
        "dataset",
    ],
    "education_learning": [
        "урок",
        "курс",
        "обуч",
        "школ",
        "универс",
        "экзам",
        "лекц",
        "lesson",
        "study",
        "course",
        "learn",
        "exam",
        "class",
        "homework",
    ],
    "personal_life": [
        "семь",
        "мам",
        "пап",
        "друз",
        "отношен",
        "дом",
        "поезд",
        "покуп",
        "здоров",
        "жизн",
        "wife",
        "husband",
        "family",
        "friend",
        "home",
        "trip",
        "health",
        "life",
    ],
    "media_creative": [
        "музык",
        "песн",
        "фильм",
        "видео",
        "сценар",
        "подкаст",
        "youtube",
        "тикток",
        "song",
        "music",
        "movie",
        "video",
        "podcast",
        "story",
        "script",
    ],
    "finance_legal": [
        "деньг",
        "оплат",
        "счет",
        "налог",
        "кредит",
        "банк",
        "юрист",
        "суд",
        "долг",
        "budget",
        "payment",
        "invoice",
        "tax",
        "bank",
        "loan",
        "legal",
    ],
    "support_ops": [
        "инструкц",
        "настрой",
        "помог",
        "поддерж",
        "проблем",
        "решен",
        "issue",
        "support",
        "setup",
        "fix",
        "configure",
        "install",
    ],
}

PRIMARY_PRIORITY = [
    "tech_it",
    "finance_legal",
    "work_business",
    "education_learning",
    "support_ops",
    "media_creative",
    "personal_life",
]

FALLBACK_BUCKETS = {"very_short_notes", "quick_messages", "general_speech"}

NOISE_PATTERNS = [
    re.compile(r"\b(ээ+|мм+|uh+|um+|aaa+|ага+)\b", re.IGNORECASE),
    re.compile(r"\[(noise|music|silence|applause)\]", re.IGNORECASE),
    re.compile(r"\b(неразборчиво|inaudible|unintelligible)\b", re.IGNORECASE),
]

STOPWORDS = {
    "это",
    "как",
    "что",
    "или",
    "для",
    "все",
    "только",
    "когда",
    "если",
    "уже",
    "надо",
    "будет",
    "после",
    "потому",
    "так",
    "просто",
    "очень",
    "меня",
    "тебя",
    "себя",
    "оно",
    "она",
    "они",
    "его",
    "and",
    "the",
    "you",
    "are",
    "was",
    "were",
    "not",
    "but",
    "for",
    "can",
    "has",
    "had",
    "this",
    "that",
    "have",
    "from",
    "your",
    "about",
    "there",
    "they",
    "them",
    "then",
    "also",
    "just",
    "into",
}


def parse_month_key(created_at: str) -> str | None:
    try:
        return datetime.strptime(created_at.strip(), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m")
    except Exception:
        return None


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-zА-Яа-яЁёІіЇїЄє'-]{3,}", text.lower())


def classify_content(text: str) -> list[str]:
    lower_text = text.lower()
    labels: list[str] = []
    for bucket, words in KEYWORDS.items():
        if any(word in lower_text for word in words):
            labels.append(bucket)
    if labels:
        return labels

    word_count = len(tokenize(text))
    if word_count < 8:
        return ["very_short_notes"]
    if word_count < 40:
        return ["quick_messages"]
    return ["general_speech"]


def classify_primary_content(text: str, labels: list[str]) -> str:
    if not labels:
        return "general_speech"
    if len(labels) == 1:
        return labels[0]

    token_list = tokenize(text)
    token_string = " ".join(token_list)
    score_by_label: dict[str, int] = {}
    for label in labels:
        if label in FALLBACK_BUCKETS:
            score_by_label[label] = 0
            continue
        score = 0
        for keyword in KEYWORDS.get(label, []):
            score += token_string.count(keyword)
        score_by_label[label] = score

    best_score = max(score_by_label.values()) if score_by_label else 0
    best_labels = [label for label, score in score_by_label.items() if score == best_score]

    for priority_label in PRIMARY_PRIORITY:
        if priority_label in best_labels:
            return priority_label

    for fallback_label in ("general_speech", "quick_messages", "very_short_notes"):
        if fallback_label in labels:
            return fallback_label

    return labels[0]


def extract_quality_features(text: str) -> dict[str, int]:
    body = (text or "").strip()
    if not body:
        return {
            "empty": 1,
            "placeholder": 0,
            "has_speaker": 0,
            "has_timestamp": 0,
            "malformed": 1,
            "noise": 0,
            "word_count": 0,
            "char_count": 0,
            "line_count": 0,
            "cyr": 0,
            "lat": 0,
        }

    has_speaker = int(bool(re.search(r"\[?SPEAKER_\d{2}\]?", body)))
    has_timestamp = int(
        bool(
            re.search(
                r"\[\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\]|\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\s*:",
                body,
            )
        )
    )
    placeholder = int(
        bool(re.search(r"\b(тест|test|sample|пример|пусто|без текста)\b", body, re.IGNORECASE))
    )
    malformed = int(
        (has_speaker and not has_timestamp)
        or ("--------------------------------------------------------------------------------" in body and not has_speaker)
    )
    noise = int(any(pattern.search(body) for pattern in NOISE_PATTERNS))

    tokens = tokenize(body)
    cyr = sum(1 for char in body if ("а" <= char.lower() <= "я") or (char.lower() in "ёіїє"))
    lat = sum(1 for char in body if "a" <= char.lower() <= "z")

    return {
        "empty": 0,
        "placeholder": placeholder,
        "has_speaker": has_speaker,
        "has_timestamp": has_timestamp,
        "malformed": malformed,
        "noise": noise,
        "word_count": len(tokens),
        "char_count": len(body),
        "line_count": body.count("\n") + 1,
        "cyr": cyr,
        "lat": lat,
    }


def resolve_input_csv(explicit_path: str | Path | None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)

    candidates = sorted(Path.cwd().glob("*.csv"))
    if not candidates:
        raise FileNotFoundError(
            "No CSV files found in the current directory. Pass --input to choose a file explicitly."
        )
    if len(candidates) > 1:
        listed = ", ".join(path.name for path in candidates)
        raise RuntimeError(
            f"Multiple CSV files found in the current directory: {listed}. "
            "Pass --input to choose one explicitly."
        )
    return candidates[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ad-hoc raw transcription summary outside the ta-batch pipeline."
    )
    parser.add_argument(
        "--input",
        "-i",
        default=None,
        help="CSV path. If omitted, auto-detect a single CSV in the current directory.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(OUTPUT_PATH),
        help=f"JSON output path (default: {OUTPUT_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    csv.field_size_limit(sys.maxsize)
    csv_path = resolve_input_csv(args.input)
    output_path = Path(args.output)

    monthly = defaultdict(
        lambda: {
            "n": 0,
            "sum_words": 0,
            "sum_chars": 0,
            "sum_lines": 0,
            "empty": 0,
            "placeholder": 0,
            "has_speaker": 0,
            "has_timestamp": 0,
            "malformed": 0,
            "noise": 0,
            "content_multi_label_hits": Counter(),
            "content_primary": Counter(),
            "top": Counter(),
            "lang_cyr_dom": 0,
            "lang_lat_dom": 0,
            "lang_mixed": 0,
        }
    )

    overall = {
        "n": 0,
        "sum_words": 0,
        "sum_chars": 0,
        "empty": 0,
        "placeholder": 0,
        "has_speaker": 0,
        "has_timestamp": 0,
        "malformed": 0,
        "noise": 0,
    }
    overall_content_multi_label_hits = Counter()
    overall_content_primary = Counter()
    overall_tokens = Counter()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            month = parse_month_key(row.get("created_at", ""))
            if not month:
                continue

            text = row.get("transcription_text") or ""
            quality = extract_quality_features(text)
            labels = classify_content(text)
            primary_label = classify_primary_content(text, labels)

            data = monthly[month]
            data["n"] += 1
            data["sum_words"] += quality["word_count"]
            data["sum_chars"] += quality["char_count"]
            data["sum_lines"] += quality["line_count"]

            for key in ("empty", "placeholder", "has_speaker", "has_timestamp", "malformed", "noise"):
                data[key] += quality[key]
                overall[key] += quality[key]

            for label in labels:
                data["content_multi_label_hits"][label] += 1
                overall_content_multi_label_hits[label] += 1

            data["content_primary"][primary_label] += 1
            overall_content_primary[primary_label] += 1

            tokens = [token for token in tokenize(text) if token not in STOPWORDS and len(token) <= 25]
            for token in tokens[:200]:
                data["top"][token] += 1
                overall_tokens[token] += 1

            if quality["cyr"] > quality["lat"] * 1.3:
                data["lang_cyr_dom"] += 1
            elif quality["lat"] > quality["cyr"] * 1.3:
                data["lang_lat_dom"] += 1
            else:
                data["lang_mixed"] += 1

            overall["n"] += 1
            overall["sum_words"] += quality["word_count"]
            overall["sum_chars"] += quality["char_count"]

    months = sorted(monthly.keys())
    if not months:
        raise RuntimeError("No valid rows with parseable created_at were found.")

    monthly_output = []
    for month in months:
        data = monthly[month]
        n = max(data["n"], 1)
        monthly_output.append(
            {
                "month": month,
                "n": data["n"],
                "avg_words": round(data["sum_words"] / n, 2),
                "avg_chars": round(data["sum_chars"] / n, 2),
                "avg_lines": round(data["sum_lines"] / n, 2),
                "speaker_share": round(data["has_speaker"] / n, 4),
                "timestamp_share": round(data["has_timestamp"] / n, 4),
                "malformed_share": round(data["malformed"] / n, 4),
                "noise_share": round(data["noise"] / n, 4),
                "empty_share": round(data["empty"] / n, 4),
                "placeholder_share": round(data["placeholder"] / n, 4),
                "lang_cyr_dom_share": round(data["lang_cyr_dom"] / n, 4),
                "lang_lat_dom_share": round(data["lang_lat_dom"] / n, 4),
                "lang_mixed_share": round(data["lang_mixed"] / n, 4),
                "primary_content_distribution": [
                    {
                        "label": label,
                        "count": count,
                        "share": round(count / n, 4),
                    }
                    for label, count in data["content_primary"].most_common()
                ],
                "multi_label_content_hits": [
                    {
                        "label": label,
                        "count": count,
                        "share_vs_rows": round(count / n, 4),
                    }
                    for label, count in data["content_multi_label_hits"].most_common(10)
                ],
                "top_tokens": data["top"].most_common(12),
            }
        )

    first = monthly_output[0]
    last = monthly_output[-1]
    trends = {
        "avg_words_delta": round(last["avg_words"] - first["avg_words"], 2),
        "speaker_share_delta_pp": round((last["speaker_share"] - first["speaker_share"]) * 100, 2),
        "timestamp_share_delta_pp": round((last["timestamp_share"] - first["timestamp_share"]) * 100, 2),
        "malformed_share_delta_pp": round((last["malformed_share"] - first["malformed_share"]) * 100, 2),
        "noise_share_delta_pp": round((last["noise_share"] - first["noise_share"]) * 100, 2),
        "empty_share_delta_pp": round((last["empty_share"] - first["empty_share"]) * 100, 2),
    }

    output = {
        "rows_analyzed": overall["n"],
        "date_range": [months[0], months[-1]],
        "content_taxonomy_notes": {
            "primary_content_distribution": "Exclusive single-label assignment per transcript; shares should sum to ~1.0 (rounding tolerance).",
            "multi_label_content_hits": "Non-exclusive keyword hits; one transcript can match multiple buckets. Shares can exceed 1.0 in total.",
        },
        "overall": {
            "avg_words": round(overall["sum_words"] / overall["n"], 2),
            "avg_chars": round(overall["sum_chars"] / overall["n"], 2),
            "speaker_share": round(overall["has_speaker"] / overall["n"], 4),
            "timestamp_share": round(overall["has_timestamp"] / overall["n"], 4),
            "malformed_share": round(overall["malformed"] / overall["n"], 4),
            "noise_share": round(overall["noise"] / overall["n"], 4),
            "empty_share": round(overall["empty"] / overall["n"], 4),
            "placeholder_share": round(overall["placeholder"] / overall["n"], 4),
            "primary_content_distribution": [
                {
                    "label": label,
                    "count": count,
                    "share": round(count / overall["n"], 4),
                }
                for label, count in overall_content_primary.most_common()
            ],
            "multi_label_content_hits": [
                {
                    "label": label,
                    "count": count,
                    "share_vs_rows": round(count / overall["n"], 4),
                }
                for label, count in overall_content_multi_label_hits.most_common(12)
            ],
            "top_tokens": overall_tokens.most_common(25),
        },
        "trends_first_to_last": trends,
        "monthly": monthly_output,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output_path.resolve()))


if __name__ == "__main__":
    main()

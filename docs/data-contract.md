# Data Contract

## Supported Input

The implemented pipeline accepts:

- CSV only
- UTF-8 text
- UTF-8 BOM is supported
- multiline quoted fields are required to stay RFC 4180-compatible

It does not read `.xlsx` directly.

If your source is in Excel, export it to CSV before running `ta-batch`.

## Required Columns

The CSV must contain these exact headers:

| Column | Required | Type in pipeline | Meaning |
|------|------|------|------|
| `id` | Yes | string | Row or transcription id |
| `telegram_user_internal_id` | Yes | string | Internal user key |
| `telegram_user_id` | Yes | string | Telegram user id |
| `created_at` | Yes | string | Source timestamp used for all time aggregation |
| `file_name` | Yes | string | Source file name or path-like reference |
| `transcription_text` | Yes | string | Full transcript body |

If any required column is missing, `ta-batch run` fails.

## `created_at`

Expected format:

```text
YYYY-MM-DD HH:MM:SS
```

Example:

```text
2024-01-15 10:00:00
```

Behavior:

- rows are read even if `created_at` cannot be parsed
- rows with invalid `created_at` are excluded from time aggregates
- the dropped-row count is written to `manifest.json` as `rows_dropped_null_ts`

## `transcription_text`

The parser is built for diarized transcripts with speaker markers and timestamps.

Accepted patterns include:

| Pattern | Example |
|------|------|
| Separator lines | `----------------------------------------` |
| Plain speaker header | `SPEAKER_00` |
| Bracketed speaker header | `[SPEAKER_00]` |
| Bracketed timestamp | `[00:00:00 - 00:00:02]` |
| Inline timestamp | `00:00:08 - 00:00:10: Hello` |

The parser supports:

- multiple speaker blocks
- repeated inline turns inside one speaker block
- transcripts without separator lines
- malformed timestamps, which are tracked by Layer A metrics

## Example Input

```csv
id,telegram_user_internal_id,telegram_user_id,created_at,file_name,transcription_text
u1,i1,tg1,2024-01-15 10:00:00,a.wav,"--------------------------------------------------------------------------------
SPEAKER_00
[00:00:00 - 00:00:02]
Hello there"
```

## Important Constraints

- `transcription_text` may contain many physical lines inside one CSV cell
- line count is not the same as row count
- naive line-based parsing will corrupt the file
- the pipeline assumes `id` is the first physical column for fast row counting during ETA inference

## File-Naming Notes

`file_name` is also used as metadata input for:

- file extension
- basename token count
- path depth

The column must exist, but the value may be empty.

## Spreadsheet Guidance

If analysts prepare or inspect the dataset in Excel:

1. Keep the exact header names.
2. Export to CSV before processing.
3. Do not split multiline transcript cells.
4. Preserve full timestamp strings in `created_at`.

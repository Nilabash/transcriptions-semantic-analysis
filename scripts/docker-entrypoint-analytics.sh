#!/bin/sh
set -e

resolve_input_csv() {
  if [ -n "${INPUT_CSV:-}" ]; then
    printf '%s\n' "$INPUT_CSV"
    return 0
  fi

  set -- /data/*.csv
  if [ "$1" = "/data/*.csv" ]; then
    echo "INPUT_CSV is not set and no top-level CSV files were found under /data." >&2
    echo "Set INPUT_CSV explicitly, for example: INPUT_CSV=/data/tests/fixtures/sample_multiline.csv" >&2
    return 1
  fi

  if [ "$#" -gt 1 ]; then
    echo "INPUT_CSV is not set and multiple top-level CSV files were found under /data." >&2
    echo "Set INPUT_CSV explicitly to choose one of:" >&2
    for candidate in "$@"; do
      echo "  $candidate" >&2
    done
    return 1
  fi

  printf '%s\n' "$1"
}

INPUT="$(resolve_input_csv)"
OUT="${OUTPUT_DIR:-/out}"
set -- ta-batch run -i "$INPUT" -o "$OUT"
if [ -n "${MAX_ROWS:-}" ]; then
  set -- "$@" --max-rows "$MAX_ROWS"
fi
if [ -n "${RUN_ID:-}" ]; then
  set -- "$@" --run-id "$RUN_ID"
fi
if [ -n "${BATCH_SIZE:-}" ]; then
  set -- "$@" --batch-size "$BATCH_SIZE"
fi
if [ -n "${TOTAL_ROWS:-}" ]; then
  set -- "$@" --total-rows "$TOTAL_ROWS"
fi
if [ "${PROGRESS:-}" = "0" ]; then
  set -- "$@" --no-progress
elif [ "${PROGRESS:-}" = "1" ]; then
  set -- "$@" --progress
fi
if [ "${INFER_TOTAL_ROWS:-}" = "0" ]; then
  set -- "$@" --no-infer-total-rows
elif [ "${INFER_TOTAL_ROWS:-}" = "1" ]; then
  set -- "$@" --infer-total-rows
fi
if [ "${LAYER_B:-}" = "0" ]; then
  set -- "$@" --no-layer-b
fi
if [ -n "${LANG_DETECT_MAX_CHARS:-}" ]; then
  set -- "$@" --lang-detect-max-chars "$LANG_DETECT_MAX_CHARS"
fi
if [ -n "${LANG_DETECT_LANGUAGES:-}" ]; then
  set -- "$@" --lang-detect-languages "$LANG_DETECT_LANGUAGES"
fi
if [ "${USER_STRATIFY:-}" = "0" ]; then
  set -- "$@" --no-user-stratify
fi
if [ "${EXPORT_REPORT:-}" = "0" ]; then
  set -- "$@" --no-export-report
fi
exec "$@"

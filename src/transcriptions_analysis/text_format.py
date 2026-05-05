"""Parse diarized transcription blocks (Layer A — structural)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Separator line: long dashed rule (observed: many consecutive hyphens).
_SEPARATOR_LINE = re.compile(r"^[-]{20,}\s*$")

# SPEAKER_00 on its own line, or [SPEAKER_00] (common in some ASR/Telegram dumps).
_SPEAKER_BRACKETED = re.compile(
    r"^\[\s*(SPEAKER_\d+|SPEAKER_[A-Z]{1,3})\s*\]\s*$",
    re.IGNORECASE,
)
_SPEAKER_PLAIN = re.compile(r"^(SPEAKER_\d+|SPEAKER_[A-Z]{1,3})\s*$", re.IGNORECASE)

# [HH:MM:SS - HH:MM:SS] with optional fractional seconds.
_TS_BRACKET = re.compile(
    r"\[\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*[-–—]\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*\]"
)

# Inline variant: "00:01:02 - 00:01:05: utterance text" (colon after end time, before body).
_TS_INLINE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*[-–—]\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*:\s?(.*)$"
)


def _parse_ts_fragment(s: str) -> tuple[int, int, int] | None:
    parts = s.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
        sec_part = parts[2]
        if "." in sec_part:
            sec_part = sec_part.split(".", 1)[0]
        sec = int(sec_part)
        return h, m, sec
    except ValueError:
        return None


def split_inline_timestamp_line(line: str) -> tuple[bool, bool, str] | None:
    """
    If ``line`` opens with ``hh:mm:ss - hh:mm:ss: body``, return
    ``(ts_ok, ts_bad, rest_after_colon)``.
    ``ts_ok`` True when both fragments parse; ``ts_bad`` True when the prefix
    looks like an inline range but times are invalid.

    Returns ``None`` when this is not an inline timestamp line.
    """
    m = _TS_INLINE.match(line)
    if not m:
        return None
    a = _parse_ts_fragment(m.group(1))
    b = _parse_ts_fragment(m.group(2))
    rest = m.group(3)
    if a and b:
        return (True, False, rest)
    return (False, True, rest)


def match_speaker_line(line: str) -> str | None:
    """Return canonical ``SPEAKER_*`` id when line is plain or ``[SPEAKER_*]`` header."""
    s = line.strip()
    mb = _SPEAKER_BRACKETED.match(s)
    if mb:
        return mb.group(1).upper()
    mp = _SPEAKER_PLAIN.match(s)
    if mp:
        return mp.group(1).upper()
    return None


def is_wellformed_timestamp_line(line: str) -> bool:
    """True for a valid bracketed range on the line OR a valid inline ``ts - ts: …`` prefix."""
    inline = split_inline_timestamp_line(line)
    if inline is not None and inline[0]:
        return True
    for m in _TS_BRACKET.finditer(line):
        a = _parse_ts_fragment(m.group(1))
        b = _parse_ts_fragment(m.group(2))
        if a and b:
            return True
    return False


@dataclass(frozen=True)
class ParsedSegment:
    speaker: str | None
    body_lines: list[str]
    has_timestamp: bool
    timestamp_line_malformed: bool


def count_separator_lines(text: str) -> int:
    """Count dashed separator lines (Layer A dashed-separator consistency)."""
    return sum(1 for line in text.splitlines() if _SEPARATOR_LINE.match(line))


def split_separator_lines(text: str) -> list[str]:
    """Split transcript into chunks separated by dashed separator lines."""
    lines = text.splitlines()
    chunks: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        if _SEPARATOR_LINE.match(line):
            if buf:
                chunks.append(buf)
                buf = []
            continue
        buf.append(line)
    if buf:
        chunks.append(buf)
    return ["\n".join(c).strip() for c in chunks if any(x.strip() for x in c)]


def parse_segments(text: str) -> list[ParsedSegment]:
    """Extract segments: speaker line + optional timestamp + body until next speaker/separator."""
    raw_chunks = split_separator_lines(text)
    segments: list[ParsedSegment] = []

    def flush_segment(
        speaker: str | None,
        body: list[str],
        ts_ok: bool,
        ts_bad: bool,
    ) -> None:
        body = [b for b in body]
        if speaker is None and not any(b.strip() for b in body) and not ts_ok:
            return
        segments.append(
            ParsedSegment(
                speaker=speaker,
                body_lines=body,
                has_timestamp=ts_ok,
                timestamp_line_malformed=ts_bad,
            )
        )

    for chunk in raw_chunks:
        current_speaker: str | None = None
        body: list[str] = []
        ts_ok = False
        ts_bad = False
        pending_ts_line = False

        for line in chunk.splitlines():
            sp_id = match_speaker_line(line)
            if sp_id is not None:
                if current_speaker is not None or body:
                    flush_segment(current_speaker, body, ts_ok, ts_bad)
                    body = []
                    ts_ok = False
                    ts_bad = False
                current_speaker = sp_id
                pending_ts_line = True
                continue

            if pending_ts_line:
                inline = split_inline_timestamp_line(line)
                if inline is not None:
                    ok, bad, rest = inline
                    ts_ok = ok
                    ts_bad = bad
                    pending_ts_line = False
                    if ok and rest.strip():
                        body.append(rest)
                    continue
                if _TS_BRACKET.search(line):
                    if is_wellformed_timestamp_line(line):
                        ts_ok = True
                        ts_bad = False
                    else:
                        ts_bad = True
                    pending_ts_line = False
                    continue
                if line.strip():
                    # Prose starts before any timestamp line → malformed TS for this speaker block
                    if _TS_BRACKET.search(line):
                        ts_bad = not is_wellformed_timestamp_line(line)
                    else:
                        ts_bad = True
                    pending_ts_line = False

                body.append(line)
                continue

            # New utterance within the same SPEAKER_* block ("00:01:02 - …: …" repeated)
            if current_speaker is not None:
                inline_next = split_inline_timestamp_line(line)
                if inline_next is not None:
                    flush_segment(current_speaker, body, ts_ok, ts_bad)
                    ok, bad, rest = inline_next
                    ts_ok = ok
                    ts_bad = bad
                    body = []
                    if ok and rest.strip():
                        body.append(rest)
                    continue

            body.append(line)

        flush_segment(current_speaker, body, ts_ok, ts_bad)

    # Fallback: no separators — treat whole text as one blob and scan for speaker blocks
    if not segments and text.strip():
        segments.extend(_parse_inline_blocks(text))

    return segments


def _parse_inline_blocks(text: str) -> list[ParsedSegment]:
    """When no dash separators, split on speaker headers."""
    lines = text.splitlines()
    segments: list[ParsedSegment] = []
    current_speaker: str | None = None
    body: list[str] = []
    ts_ok = False
    ts_bad = False
    pending_ts = False

    def flush() -> None:
        nonlocal current_speaker, body, ts_ok, ts_bad, pending_ts
        if current_speaker is None and not any(b.strip() for b in body):
            body = []
            ts_ok = ts_bad = False
            pending_ts = False
            return
        segments.append(
            ParsedSegment(
                speaker=current_speaker,
                body_lines=list(body),
                has_timestamp=ts_ok,
                timestamp_line_malformed=ts_bad,
            )
        )
        body = []
        ts_ok = ts_bad = False
        pending_ts = False

    for line in lines:
        if _SEPARATOR_LINE.match(line):
            flush()
            current_speaker = None
            continue
        sp_id = match_speaker_line(line)
        if sp_id is not None:
            flush()
            current_speaker = sp_id
            pending_ts = True
            continue
        if pending_ts:
            inline = split_inline_timestamp_line(line)
            if inline is not None:
                ok, bad, rest = inline
                ts_ok = ok
                ts_bad = bad
                pending_ts = False
                if ok and rest.strip():
                    body.append(rest)
                continue
            if _TS_BRACKET.search(line):
                ts_ok = is_wellformed_timestamp_line(line)
                ts_bad = not ts_ok
                pending_ts = False
                continue
            if line.strip():
                ts_bad = True
                pending_ts = False

            body.append(line)
            continue

        if current_speaker is not None:
            inline_next = split_inline_timestamp_line(line)
            if inline_next is not None:
                flush()
                ok, bad, rest = inline_next
                ts_ok = ok
                ts_bad = bad
                body = []
                if ok and rest.strip():
                    body.append(rest)
                continue

        body.append(line)
    flush()
    return segments


def segment_word_char_counts(segment: ParsedSegment) -> tuple[int, int]:
    """Return (char_count, word_count) for segment body (excluding speaker/ts lines)."""
    blob = "\n".join(segment.body_lines)
    words = [w for w in re.split(r"\s+", blob.strip()) if w]
    return len(blob), len(words)

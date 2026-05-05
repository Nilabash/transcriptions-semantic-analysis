"""File-name metadata for content characterization (§2.4 metadata-first)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


def derive_file_metadata(file_name: str | None) -> dict[str, Any]:
    """
    Derive extension, basename token count, and path depth from ``file_name``.

    - ``content_file_extension``: lowercased extension without dot, or empty string.
    - ``content_file_basename_token_count``: tokens from basename split on non-word chars.
    - ``content_file_path_depth``: number of parent path segments (0 for a plain filename).
    """
    if file_name is None:
        return {
            "content_file_extension": "",
            "content_file_basename_token_count": 0,
            "content_file_path_depth": 0,
        }

    s = str(file_name).strip()
    if not s:
        return {
            "content_file_extension": "",
            "content_file_basename_token_count": 0,
            "content_file_path_depth": 0,
        }

    normalized = s.replace("\\", "/")
    p = PurePosixPath(normalized)
    parts = [x for x in p.parts if x != "/"]
    depth = max(len(parts) - 1, 0) if parts else 0
    base = parts[-1] if parts else normalized.split("/")[-1]

    ext = ""
    if "." in base:
        stem, _, maybe_ext = base.rpartition(".")
        if maybe_ext and stem:
            ext = maybe_ext.lower()

    tokens = [t for t in re.split(r"\W+", base, flags=re.UNICODE) if t]
    token_count = len(tokens)

    return {
        "content_file_extension": ext,
        "content_file_basename_token_count": token_count,
        "content_file_path_depth": depth,
    }

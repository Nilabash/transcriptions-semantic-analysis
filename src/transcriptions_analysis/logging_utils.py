"""Structured key=value logging for batch jobs."""

from __future__ import annotations

import logging
import sys
from typing import Any


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger for stderr stream with a simple format."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def log_kv(**pairs: Any) -> None:
    """Emit one structured line key=value key=value ..."""
    parts = []
    for k, v in pairs.items():
        if v is None:
            continue
        s = str(v).replace("\n", " ").replace("\r", "")
        parts.append(f"{k}={s}")
    logging.getLogger("ta").info(" ".join(parts))

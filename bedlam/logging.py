"""Structured JSON logging. Every module outside the TUI logs through this.

CLAUDE.md bans bare `print` outside the TUI -- faults, probes and model calls
all emit structured events here instead, so the trace Bedlam writes is built
from the same log records a developer would see on a terminal.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """A logger that writes one JSON object per line to stderr.

    Safe to call repeatedly -- handlers are only attached once per name.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, message: str, /, **fields: Any) -> None:
    """Log one structured event. `fields` become top-level JSON keys."""
    logger.info(message, extra={"fields": fields})

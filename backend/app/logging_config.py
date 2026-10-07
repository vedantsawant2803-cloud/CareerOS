"""Logging configuration.

* Console-only structured logs (no file handlers → nothing to leak from disks).
* A redaction filter makes sure secret-looking values never reach the logs.
"""

from __future__ import annotations

import logging
import re
from logging.config import dictConfig

from app.config import Settings

SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|token|secret|password|bearer)\b\s*[=:]\s*\"\S+\""
)
REDACTED = r"\1=***REDACTED***"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class SecretRedactionFilter(logging.Filter):
    """Scrub obvious credential patterns from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = SECRET_PATTERN.sub(REDACTED, message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(settings: Settings) -> None:
    """Configure root logging for the API process."""
    level = settings.log_level.upper()
    if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        level = "INFO"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": LOG_FORMAT},
            },
            "filters": {
                "secret_redaction": {"()": SecretRedactionFilter},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["secret_redaction"],
                },
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": "WARNING" if settings.is_production else level,
                    "propagate": False,
                },
                "qdrant_client": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            },
        }
    )
    logging.getLogger(__name__).debug("Logging configured at level %s", level)

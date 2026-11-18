"""Rotating file logging setup with automatic secret redaction (NFR-SEC-01)."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from videocreator.secrets_store import SecretsStore, get_registered_secret_values

MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5

_URL_SECRET_PARAM_RE = re.compile(
    r"([?&](?:access_token|refresh_token|client_secret|api_key|key|token)=)([^&#\s'\"]+)",
    re.IGNORECASE,
)
_TG_BOT_URL_RE = re.compile(r"(https?://api\.telegram\.org/bot)([^/\s'\"]+)", re.IGNORECASE)


def redact_text(text: str, extra_secrets: list[str] | None = None) -> str:
    if not text:
        return text
    secrets = get_registered_secret_values()
    if extra_secrets:
        for s in extra_secrets:
            if s and len(s.strip()) >= 6:
                secrets.append(s.strip())
    result = _URL_SECRET_PARAM_RE.sub(r"\1***", text)
    result = _TG_BOT_URL_RE.sub(r"\1***", result)
    for secret in secrets:
        if secret and secret in result:
            result = result.replace(secret, "***")
    return result


class SecretRedactingFilter(logging.Filter):
    """Replaces any secret value present in log messages or arguments with '***'."""

    def __init__(self, secrets_store: SecretsStore | None = None) -> None:
        super().__init__()
        self.secrets_store = secrets_store

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets_store is not None:
            self.secrets_store._sync_redaction_cache()
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        redacted = redact_text(rendered)
        record.msg = redacted
        record.args = ()
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact_text(formatted)


def setup_logging(
    log_file: Path,
    secrets_store: SecretsStore | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("videocreator")
    logger.setLevel(level)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for flt in list(logger.filters):
        logger.removeFilter(flt)

    fmt = RedactingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    redactor = SecretRedactingFilter(secrets_store=secrets_store)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addFilter(redactor)
    logger.propagate = False

    # Prevent httpx/telegram/apscheduler from logging unredacted request URLs (e.g. bot tokens).
    for noisy_name in ("httpx", "httpcore"):
        noisy_logger = logging.getLogger(noisy_name)
        noisy_logger.setLevel(logging.WARNING)
    for ext_name in ("httpx", "httpcore", "telegram", "apscheduler"):
        ext_logger = logging.getLogger(ext_name)
        ext_logger.filters = [
            f for f in ext_logger.filters if not isinstance(f, SecretRedactingFilter)
        ]
        ext_logger.addFilter(redactor)
    root_logger = logging.getLogger()
    for root_handler in root_logger.handlers:
        root_handler.filters = [
            f for f in root_handler.filters if not isinstance(f, SecretRedactingFilter)
        ]
        root_handler.addFilter(redactor)
    return logger

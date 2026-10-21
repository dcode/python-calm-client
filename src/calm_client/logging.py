"""Logging configuration for the Calm client.

As a library, calm-client logs through the standard ``logging`` module under the
``calm_client`` logger, so it is silent unless the host application configures logging.
The CLI calls :func:`configure_logging` to get pretty console output and a JSON log file.

Either way, credentials never reach a log: request headers, passwords and tokens are
redacted by :func:`redact_sensitive`.
"""

from __future__ import annotations

import logging
import sys
import typing
from collections.abc import Mapping, MutableMapping
from logging.handlers import RotatingFileHandler

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer
from structlog.stdlib import ProcessorFormatter

LOGGER_NAME = "calm_client"
REDACTED = "<redacted>"

# header names (lower-case) and payload keys that carry credentials
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "x-session-token"})
_SENSITIVE_KEYS = frozenset(
    {"password", "access_token", "refresh_token", "id_token", "token", "session_token", "client_secret"}
)


def _redact_value(value: typing.Any) -> typing.Any:
    """Return a copy of a payload with credential fields masked."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if str(key).lower() in _SENSITIVE_KEYS else _redact_value(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str) and any(f'"{key}"' in value for key in _SENSITIVE_KEYS):
        # a raw (possibly truncated) JSON body that mentions a credential field
        return REDACTED
    return value


def redact_sensitive(
    _logger: typing.Any, _method: str, event_dict: MutableMapping[str, typing.Any]
) -> MutableMapping[str, typing.Any]:
    """Structlog processor that masks credentials in ``headers`` and ``body`` fields."""
    headers = event_dict.get("headers")
    if isinstance(headers, Mapping):
        event_dict["headers"] = {
            name: REDACTED if str(name).lower() in _SENSITIVE_HEADERS else value for name, value in headers.items()
        }
    if "body" in event_dict:
        event_dict["body"] = _redact_value(event_dict["body"])
    return event_dict


def configure_logging(*, level: int = logging.WARNING) -> None:
    """Configure structlog with the given log level (used by the CLI).

    Sets up:
    1. A RotatingFileHandler writing JSON logs to 'app.log' (10MB, 5 backups).
    2. A StreamHandler writing colored logs to sys.stdout (for redirection).
    """
    # Configure the standard logging module
    # We do NOT use basicConfig because we want specific handlers

    # 1. File Handler (JSON)
    file_handler = RotatingFileHandler("app.log", maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(logging.DEBUG)  # Always log debug to file if the root allows

    json_formatter = ProcessorFormatter(
        processor=JSONRenderer(sort_keys=True),
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ],
    )
    file_handler.setFormatter(json_formatter)

    # 2. Console Handler (Pretty)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    console_formatter = ProcessorFormatter(
        processor=ConsoleRenderer(),
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        ],
    )
    console_handler.setFormatter(console_formatter)

    # 3. Root Logger Setup
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything at root, handlers filter down

    # Remove existing handlers to avoid duplicates on re-configuration
    root_logger.handlers = []
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 4. Third-party Noise Reduction
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # 5. Structlog Configuration
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        redact_sensitive,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


_library_logger: typing.Any = None


def _resolve_logger() -> typing.Any:
    """Return the structlog logger when the CLI configured structlog, else a stdlib-backed one."""
    global _library_logger
    if structlog.is_configured():
        return structlog.get_logger(LOGGER_NAME)
    if _library_logger is None:
        _library_logger = structlog.wrap_logger(
            logging.getLogger(LOGGER_NAME),
            processors=[
                structlog.stdlib.filter_by_level,
                redact_sensitive,
                structlog.processors.KeyValueRenderer(key_order=["event"]),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
        )
    return _library_logger


class _LazyLogger:
    """Logger proxy that picks its backend on every call.

    Modules bind ``logger`` at import time, which can be before the CLI configures
    structlog; resolving per call keeps both library and CLI use correct.
    """

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(_resolve_logger(), name)


logger = _LazyLogger()

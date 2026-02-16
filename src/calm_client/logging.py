"""Logging configuration for the Calm client."""

from __future__ import annotations

import logging
import sys
import typing
from logging.handlers import RotatingFileHandler

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer
from structlog.stdlib import ProcessorFormatter

_logger: typing.Any = None


def configure_logging(*, level: int = logging.WARNING) -> None:
    """Configure structlog with the given log level.

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


def __getattr__(name: str) -> typing.Any:
    """Implement lazy loading for logger."""
    if name == "logger":
        global _logger
        if _logger is None:
            _logger = structlog.get_logger("calm_client")
        return _logger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

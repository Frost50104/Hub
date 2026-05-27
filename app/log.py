"""structlog configuration — JSON in prod, console in dev/local."""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_settings


def configure() -> None:
    settings = get_settings()
    is_console = settings.environment in ("dev", "local")

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if is_console
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

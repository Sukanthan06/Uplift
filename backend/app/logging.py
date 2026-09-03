"""Structured JSON logging (CLAUDE.md: structlog JSON logs, no OpenTelemetry).

configure_logging() is called once at process start (app/main.py for the
API, each script's __main__ block for CLI entry points). get_logger()
gives every service module a bound logger keyed by its own name.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Route stdlib logging through structlog and render every line as JSON."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # default=str: log fields routinely carry datetime/Decimal values
            # (scheduled_for, amount) that json.dumps can't serialize natively.
            structlog.processors.JSONRenderer(default=str),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    """Bound structlog logger for the given module name."""
    return structlog.get_logger(name)

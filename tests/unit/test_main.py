"""Unit tests for __main__.configure_logging.

Verifies that:
- The root logger is set to the requested level.
- Third-party AWS SDK / HTTP loggers (botocore, boto3, urllib3, s3transfer)
  are always clamped to WARNING regardless of the root level, preventing
  AWS temporary credentials and HTTP bodies from appearing in the log.
- An invalid level silently falls back to INFO.
- Repeated calls do not accumulate duplicate handlers.
"""

import logging
from collections.abc import Iterator

import pytest

from cairn_mcp.__main__ import configure_logging

_NOISY_LOGGERS: tuple[str, ...] = ("botocore", "boto3", "urllib3", "s3transfer")


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Snapshot and restore global logging state around each test."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    noisy_levels = {name: logging.getLogger(name).level for name in _NOISY_LOGGERS}
    yield
    root.setLevel(original_level)
    root.handlers[:] = original_handlers
    for name, level in noisy_levels.items():
        logging.getLogger(name).setLevel(level)


# ── Root logger level ──────────────────────────────────────────────────────────


def test_root_level_set_to_debug() -> None:
    """configure_logging('DEBUG') sets the root logger to DEBUG."""
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_root_level_set_to_info() -> None:
    """configure_logging('INFO') sets the root logger to INFO."""
    configure_logging("INFO")
    assert logging.getLogger().level == logging.INFO


def test_root_level_set_to_warning() -> None:
    """configure_logging('WARNING') sets the root logger to WARNING."""
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_root_level_set_to_error() -> None:
    """configure_logging('ERROR') sets the root logger to ERROR."""
    configure_logging("ERROR")
    assert logging.getLogger().level == logging.ERROR


def test_root_level_accepts_lowercase() -> None:
    """configure_logging('debug') normalises to DEBUG (case-insensitive)."""
    configure_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_invalid_level_falls_back_to_info() -> None:
    """configure_logging('TRACE') falls back to INFO — TRACE is not a valid level."""
    configure_logging("TRACE")
    assert logging.getLogger().level == logging.INFO


# ── Noisy logger suppression ───────────────────────────────────────────────────


@pytest.mark.parametrize("logger_name", list(_NOISY_LOGGERS))
def test_noisy_logger_clamped_to_warning_when_root_is_debug(logger_name: str) -> None:
    """Noisy logger is at WARNING even when root is DEBUG (credentials must not leak)."""
    configure_logging("DEBUG")
    assert logging.getLogger(logger_name).level == logging.WARNING


@pytest.mark.parametrize("logger_name", list(_NOISY_LOGGERS))
def test_noisy_logger_clamped_to_warning_when_root_is_info(logger_name: str) -> None:
    """Noisy logger is at WARNING when root is INFO."""
    configure_logging("INFO")
    assert logging.getLogger(logger_name).level == logging.WARNING


@pytest.mark.parametrize("logger_name", list(_NOISY_LOGGERS))
def test_noisy_logger_clamped_on_invalid_level_fallback(logger_name: str) -> None:
    """Noisy logger is at WARNING even when an invalid level triggers the INFO fallback."""
    configure_logging("TRACE")
    assert logging.getLogger(logger_name).level == logging.WARNING


# ── Handler management ─────────────────────────────────────────────────────────


def test_single_stderr_handler_added() -> None:
    """configure_logging adds exactly one StreamHandler to the root logger."""
    configure_logging("INFO")
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1


def test_repeated_calls_do_not_accumulate_handlers() -> None:
    """Calling configure_logging twice must not leave duplicate handlers."""
    configure_logging("INFO")
    configure_logging("WARNING")
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1

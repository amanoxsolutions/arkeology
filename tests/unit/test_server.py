"""Tests for server startup and logging configuration."""

import logging
import sys

import pytest

from cairn_mcp.__main__ import configure_logging


def test_configure_logging_debug_sets_level() -> None:
    """configure_logging('DEBUG') sets the root logger to DEBUG."""
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_info_sets_level() -> None:
    """configure_logging('INFO') sets the root logger to INFO."""
    configure_logging("INFO")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_warning_sets_level() -> None:
    """configure_logging('WARNING') sets the root logger to WARNING."""
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_error_sets_level() -> None:
    """configure_logging('ERROR') sets the root logger to ERROR."""
    configure_logging("ERROR")
    assert logging.getLogger().level == logging.ERROR


def test_configure_logging_invalid_falls_back_to_info() -> None:
    """configure_logging with an invalid level falls back to INFO."""
    configure_logging("TRACE")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_handler_goes_to_stderr() -> None:
    """Root logger has exactly one StreamHandler directed at stderr."""
    configure_logging("INFO")
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1
    assert stream_handlers[0].stream is sys.stderr


def test_configure_logging_only_one_handler_after_multiple_calls() -> None:
    """Calling configure_logging multiple times does not accumulate handlers."""
    configure_logging("INFO")
    configure_logging("DEBUG")
    configure_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1


@pytest.fixture(autouse=True)
def reset_root_logger() -> None:
    """Reset root logger handlers after each test to avoid cross-test pollution."""
    yield  # type: ignore[misc]
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)

"""Unit tests for __main__.configure_logging and __main__.main.

Verifies that:
- The root logger is set to the requested level.
- Third-party AWS SDK / HTTP loggers (botocore, boto3, urllib3, s3transfer)
  are always clamped to WARNING regardless of the root level, preventing
  AWS temporary credentials and HTTP bodies from appearing in the log.
- An invalid level silently falls back to INFO.
- Repeated calls do not accumulate duplicate handlers.
- main() surfaces a structured, actionable error (not a raw traceback) when
  AWS_PROFILE names a profile the credential chain cannot find (M-7).
"""

import logging
from collections.abc import Iterator

import botocore.exceptions
import pytest
from pytest_mock import MockerFixture

from arkeology.__main__ import configure_logging, main
from arkeology.config import Settings

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


# ── main(): bad AWS_PROFILE surfaces a structured error (M-7) ──────────────────


def _settings_with_bad_profile() -> Settings:
    return Settings(
        AWS_REGION="us-east-1",
        ARTIFACT_BUCKET="my-bucket",
        VECTORS_BUCKET="my-vectors",
        VECTORS_INDEX="my-index",
        AWS_PROFILE="does-not-exist-profile",
    )


def test_main_bad_profile_exits_cleanly_not_raw_traceback(
    mocker: MockerFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A boto3.Session ProfileNotFound during client construction is caught and exits
    with sys.exit(1) plus a structured, actionable critical log — not an uncaught
    ProfileNotFound propagating out of main() as a raw traceback.

    Uses capsys rather than caplog: main() calls configure_logging(), which replaces
    the root logger's handlers (including caplog's) with its own stderr StreamHandler.

    Red: before the M-7 fix, ProfileNotFound propagates uncaught — pytest.raises(SystemExit)
    fails because a different exception type escapes instead.
    """
    mocker.patch(
        "arkeology.__main__.load_settings",
        return_value=_settings_with_bad_profile(),
    )
    mocker.patch(
        "boto3.Session",
        side_effect=botocore.exceptions.ProfileNotFound(profile="does-not-exist-profile"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "does-not-exist-profile" in stderr
    assert "Traceback" not in stderr


def test_main_bad_profile_does_not_reach_startup_validation(
    mocker: MockerFixture,
) -> None:
    """A ProfileNotFound during client construction must prevent startup validation
    (and therefore any AWS call) from ever running."""
    mocker.patch(
        "arkeology.__main__.load_settings",
        return_value=_settings_with_bad_profile(),
    )
    mocker.patch(
        "boto3.Session",
        side_effect=botocore.exceptions.ProfileNotFound(profile="does-not-exist-profile"),
    )
    spy = mocker.patch("arkeology.__main__.validate_startup")

    with pytest.raises(SystemExit):
        main()

    assert spy.call_count == 0

"""Unit tests for cairn_mcp.failure_log.

Tests append_failure_entry() using tmp_path — no AWS calls.
"""

import json
import logging
from pathlib import Path

import pytest

from cairn_mcp.failure_log import append_failure_entry

# ---------------------------------------------------------------------------
# Base entry fixture
# ---------------------------------------------------------------------------

_BASE_ENTRY: dict = {
    "artifact_id": "artifacts/code-review-2026-05-30-fix-auth-bug",
    "title": "Fix auth bug",
    "type": "code_review",
    "tier": 2,
    "date": "2026-05-30",
    "failure_step": "bedrock_embed",
    "reason": "ThrottlingException: Rate exceeded",
    "timestamp": "2026-05-30T12:00:00Z",
}

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_append_creates_file_on_first_call(tmp_path: Path) -> None:
    """append_failure_entry on a non-existent file → creates file; one line."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, _BASE_ENTRY)

    assert log_path.exists()
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1


def test_append_writes_valid_json(tmp_path: Path) -> None:
    """append_failure_entry produces a line that is valid JSON."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, _BASE_ENTRY)

    lines = log_path.read_text().splitlines()
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict)


def test_append_twice_produces_two_lines(tmp_path: Path) -> None:
    """append_failure_entry called twice → two lines (append behaviour)."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "First failure"})
    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "Second failure"})

    lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2


def test_append_both_entries_valid_json(tmp_path: Path) -> None:
    """Both appended entries are valid JSON objects."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "First"})
    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "Second"})

    lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_entry_contains_all_required_fields(tmp_path: Path) -> None:
    """Each entry contains all required fields."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, _BASE_ENTRY)

    line = log_path.read_text().splitlines()[0]
    parsed = json.loads(line)
    required = [
        "artifact_id",
        "title",
        "type",
        "tier",
        "date",
        "failure_step",
        "reason",
        "timestamp",
    ]
    for field in required:
        assert field in parsed, f"Missing required field: {field}"


def test_entry_timestamp_is_string(tmp_path: Path) -> None:
    """timestamp field is a string (ISO-8601 compatible)."""
    log_path = tmp_path / "failures.jsonl"

    append_failure_entry(log_path, _BASE_ENTRY)

    parsed = json.loads(log_path.read_text().splitlines()[0])
    assert isinstance(parsed["timestamp"], str)
    assert len(parsed["timestamp"]) > 0


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


def test_nonexistent_directory_logs_stderr_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """append_failure_entry on a path in a non-existent directory → logs to stderr, no raise."""
    bad_path = tmp_path / "nonexistent_dir" / "failures.jsonl"

    with caplog.at_level(logging.ERROR):
        # Must not raise
        append_failure_entry(bad_path, _BASE_ENTRY)


def test_append_non_serializable_value_still_writes_entry(tmp_path: Path) -> None:
    """Entry containing a non-JSON-serializable value (e.g. Exception) → still written.

    json.dumps(default=str) must be used so a TypeError from an unserializable
    field does not silently swallow the whole failure record.
    """
    log_path = tmp_path / "failures.jsonl"
    entry_with_exception = {**_BASE_ENTRY, "raw_error": Exception("boom")}

    append_failure_entry(log_path, entry_with_exception)

    lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert "raw_error" in parsed
    assert "boom" in parsed["raw_error"]


def test_os_error_logs_stderr_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """append_failure_entry when OSError occurs → logs to stderr, does not raise."""
    log_path = tmp_path / "failures.jsonl"

    def _raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("Simulated disk full")

    monkeypatch.setattr("builtins.open", _raise_os_error)

    with caplog.at_level(logging.ERROR):
        # Must not raise
        append_failure_entry(log_path, _BASE_ENTRY)

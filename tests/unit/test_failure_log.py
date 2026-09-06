"""Unit tests for arkeology.failure_log.

Tests append_failure_entry() using tmp_path — no AWS calls.
"""

import json
import logging
import threading
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from arkeology import failure_log
from arkeology.failure_log import (
    append_failure_entry,
    build_failure_entry,
    rewrite_failure_log,
)

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


# ---------------------------------------------------------------------------
# Concurrency (no lock — concurrent writers can interleave/corrupt lines)
# ---------------------------------------------------------------------------


def test_concurrent_writers_are_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent append_failure_entry calls to the same log file must be
    serialized (e.g. via a file lock) — a second writer must not be able to complete
    its append while a first writer's append is still in flight. This is verified
    deterministically (no timing/sleep races): writer A is held mid-write, inside the
    presumed-locked critical section (after opening the file, before the actual
    fh.write()), via a controlled threading.Event(). [Corrected during implementation:
    the original version of this test blocked inside Path.open() itself, which is
    *before* any lock would be acquired — that injection point could never have
    detected mutual exclusion even with a correct fix, since two independent open()
    calls never contend on a flock held by neither yet. Blocking inside json.dumps()
    instead lands squarely inside the locked region.] Today, append_failure_entry has
    no locking at all, so writer B completes immediately regardless of writer A's
    in-flight write — with no lock, concurrent writers can interleave partial JSON
    lines and corrupt the log.
    """
    log_path = tmp_path / "failures.jsonl"
    writer_a_in_critical_section = threading.Event()
    release_writer_a = threading.Event()
    first_call_seen = threading.Event()

    orig_dumps = json.dumps

    def _slow_dumps(*args: object, **kwargs: object) -> str:
        result: str = orig_dumps(*args, **kwargs)  # type: ignore[arg-type]
        if not first_call_seen.is_set():
            first_call_seen.set()
            writer_a_in_critical_section.set()
            # Block here — simulating writer A holding the lock — until the test
            # explicitly releases it below.
            release_writer_a.wait(timeout=2)
        return result

    monkeypatch.setattr(json, "dumps", _slow_dumps)

    thread_a = threading.Thread(
        target=append_failure_entry, args=(log_path, {**_BASE_ENTRY, "reason": "A"})
    )
    thread_a.start()
    assert writer_a_in_critical_section.wait(timeout=2), "writer A never reached json.dumps()"

    writer_b_done = threading.Event()

    def _writer_b() -> None:
        append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "B"})
        writer_b_done.set()

    thread_b = threading.Thread(target=_writer_b)
    thread_b.start()
    # While writer A is deliberately blocked mid-write, a correctly-locked
    # implementation must prevent writer B from completing its append.
    completed_while_a_blocked = writer_b_done.wait(timeout=0.5)

    release_writer_a.set()
    thread_a.join(timeout=2)
    thread_b.join(timeout=2)

    assert not completed_while_a_blocked, (
        "writer B completed its append while writer A's write was still in flight — "
        "append_failure_entry has no mutual-exclusion lock, so concurrent writers can "
        "interleave and corrupt the log file"
    )


# ---------------------------------------------------------------------------
# T74.5 — rewrite_failure_log: truncate in place, and tolerate a vanished file
# ---------------------------------------------------------------------------


def test_rewrite_keeps_the_same_file_when_the_log_drains(tmp_path: Path) -> None:
    """A drained log is truncated in place, never unlinked.

    Unlinking under the lock loses the entry of any appender that opened the file
    before the unlink and is still waiting on the lock: its write lands in the
    unlinked inode and the artifact it names is never reconciled. Holding the same
    inode is what makes that append survive, which is why the identity — not merely
    the file's existence — is what this asserts.
    """
    log_path = tmp_path / "failures.jsonl"
    append_failure_entry(log_path, _BASE_ENTRY)
    inode_before = log_path.stat().st_ino

    remaining = rewrite_failure_log(log_path, lambda entries: [])

    assert remaining == []
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8") == ""
    assert log_path.stat().st_ino == inode_before


def _record_sizes_at_unlock(mocker: MockerFixture, log_path: Path) -> list[int]:
    """Capture the log's on-disk size at each ``LOCK_UN``, delegating to the real flock.

    The size at the moment the lock is dropped is the only observable that separates a
    write that reached disk inside the critical section from one still sitting in the
    buffer, waiting for ``close()`` to flush it after another writer already holds the
    lock.
    """
    real_flock = failure_log.fcntl.flock
    sizes: list[int] = []

    def _flock(fh: object, operation: int) -> None:
        if operation == failure_log.fcntl.LOCK_UN:
            sizes.append(log_path.stat().st_size)
        real_flock(fh, operation)

    mocker.patch.object(failure_log.fcntl, "flock", side_effect=_flock)
    return sizes


def test_append_flushes_the_entry_to_disk_before_releasing_the_lock(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """The appended line is on disk before the lock is dropped, not at ``close()``.

    A line still buffered when the lock goes is written outside the critical section,
    which is the interleaving the lock exists to prevent.
    """
    log_path = tmp_path / "failures.jsonl"
    sizes_at_unlock = _record_sizes_at_unlock(mocker, log_path)

    append_failure_entry(log_path, _BASE_ENTRY)

    assert log_path.stat().st_size > 0
    assert sizes_at_unlock == [log_path.stat().st_size]


def test_rewrite_flushes_retained_entries_to_disk_before_releasing_the_lock(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """The retained entries are on disk before the lock is dropped, not at ``close()``.

    ``writelines`` only buffers. With the flush deferred to ``close()``, an appender
    blocked on the lock wakes to a file the rewriter has already truncated, writes its
    line at offset 0, and the rewriter's deferred flush then lands on top of it — losing
    the entry, and with it any chance of the artifact it names being reconciled. That is
    the same loss truncating in place rather than unlinking exists to prevent.
    """
    log_path = tmp_path / "failures.jsonl"
    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "keep"})
    append_failure_entry(log_path, {**_BASE_ENTRY, "reason": "drop"})
    sizes_at_unlock = _record_sizes_at_unlock(mocker, log_path)

    remaining = rewrite_failure_log(
        log_path, lambda entries: [e for e in entries if e["reason"] == "keep"]
    )

    assert [entry["reason"] for entry in remaining] == ["keep"]
    assert log_path.stat().st_size > 0
    assert sizes_at_unlock == [log_path.stat().st_size]


def test_rewrite_treats_a_file_that_vanished_after_the_existence_check_as_empty(
    tmp_path: Path,
) -> None:
    """A concurrent run draining the log between ``exists()`` and ``open()`` is not an error.

    Two reconcile runs share one log file, so the window is real. A log that is simply
    gone means "no entries", and raising ``FileNotFoundError`` out of here fails the
    whole calling run over a state that is indistinguishable from an empty log.
    """
    log_path = tmp_path / "failures.jsonl"

    remaining = rewrite_failure_log(log_path, lambda entries: entries)

    assert remaining == []


# ---------------------------------------------------------------------------
# T74.1 — build_failure_entry carries the supersession token
# ---------------------------------------------------------------------------


def test_build_failure_entry_records_the_last_edited_ulid_when_supplied() -> None:
    """The entry carries the artifact's ``last_edited_ulid`` as it stood at failure time.

    It is the supersession token ``reconcile_index`` decides the ``references`` restore
    on, and the entry's only purpose for it — nothing else reads it. The single
    construction point is where it belongs, so no producer can record an entry without it.
    """
    entry = build_failure_entry(
        artifact_id="artifacts/code-review-2026-05-30-fix-auth-bug",
        title="Fix auth bug",
        artifact_type="code_review",
        tier=2,
        date="2026-05-30",
        failure_step="annotation_write",
        reason="simulated",
        references=["artifacts/some-adr"],
        last_edited_ulid="01ARZ3NDEKTSV4RRFFQ69G5FAV",
    )

    assert entry["last_edited_ulid"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_build_failure_entry_omits_the_last_edited_ulid_when_absent() -> None:
    """An artifact carrying no ULID records no token, and the field stays absent.

    An absent token means "no evidence of supersession", which ``reconcile_index``
    treats as a union — the pre-token behaviour. A falsy placeholder would instead
    compare unequal to every real ULID and discard the only surviving ``references``
    copy on every such entry.
    """
    entry = build_failure_entry(
        artifact_id="artifacts/code-review-2026-05-30-fix-auth-bug",
        title="Fix auth bug",
        artifact_type="code_review",
        tier=2,
        date="2026-05-30",
        failure_step="annotation_write",
        reason="simulated",
        references=["artifacts/some-adr"],
    )

    assert "last_edited_ulid" not in entry

"""arkeology.failure_log — append-only partial write failure log.

Writes structured JSON lines to a local .jsonl file when a partial write occurs
(S3 succeeded, Bedrock embed or put_vector failed). ``append_failure_entry`` never
raises — all file I/O errors are caught and logged to stderr.

Reads and prunes go through ``read_failure_entries`` and ``rewrite_failure_log``,
which share the exclusive lock the appender takes so a pruning pass cannot overwrite
an append it never saw.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover — POSIX-only stdlib module (e.g. absent on Windows)
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def append_failure_entry(path: Path, entry: dict[str, Any]) -> None:
    """Append a JSON line to the failure log at ``path``.

    Creates the file if it does not exist. All exceptions from file I/O are
    caught and logged to stderr — this function never raises.

    Args:
        path: Filesystem path to the .jsonl failure log.
        entry: Dict containing at minimum: artifact_id, title, type, tier,
            date, failure_step, reason, timestamp.
    """
    try:
        with path.open("a", encoding="utf-8") as fh:
            # ponytail: process/host-local flock — POSIX only, silently disabled on
            # platforms without `fcntl` (e.g. Windows; server assumes a POSIX host,
            # see AGENTS.md) rather than crashing the module, and does not coordinate
            # across NFS-mounted paths either way. Swap for a cross-platform/
            # network-safe lock (e.g. `filelock`) if either ceiling is ever hit.
            # Without it, concurrent writers' appends could interleave and corrupt
            # lines.
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(entry, default=str) + "\n")
            finally:
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception as exc:
        logger.error("Failed to write to failure log at %s: %s", path, exc)


def _parse_entries(text: str) -> list[dict[str, Any]]:
    """Parse JSONL ``text`` into entries, skipping blank and malformed lines."""
    entries: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed failure log line: %s", line)
    return entries


def read_failure_entries(path: Path) -> list[dict[str, Any]]:
    """Read every entry currently in the failure log at ``path``.

    Args:
        path: Filesystem path to the .jsonl failure log.

    Returns:
        The parsed entries, in file order. Malformed lines are logged and skipped.

    Raises:
        OSError: If the file cannot be read.
    """
    return _parse_entries(path.read_text(encoding="utf-8"))


def rewrite_failure_log(
    path: Path,
    transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Replace the failure log's contents with ``transform`` applied to them.

    The re-read and the write happen inside a single hold of the same exclusive lock
    ``append_failure_entry`` takes, so ``transform`` sees every entry another writer
    appended since the caller last read the log. A caller that instead wrote back a
    list it read minutes earlier would silently drop those appends — and the artifact
    each names would never be reconciled.

    ``transform`` runs while the lock is held: keep it pure and fast, and do no I/O
    in it.

    Args:
        path: Filesystem path to the .jsonl failure log. A missing file is a no-op.
        transform: Maps the entries currently on disk to the entries to retain.

    Returns:
        The retained entries. Empty when the log was drained or absent.

    Raises:
        OSError: If the file cannot be read or written.
    """
    if not path.exists():
        return []
    with path.open("r+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            remaining = transform(_parse_entries(fh.read()))
            if remaining:
                fh.seek(0)
                fh.truncate()
                fh.writelines(json.dumps(entry, default=str) + "\n" for entry in remaining)
            else:
                # ponytail: unlinked under the lock, so an append that already
                # completed is never lost — the re-read above saw it. Residual
                # window: an appender that opened the file before this unlink and
                # is still waiting on the lock writes into the unlinked inode. Close
                # it by having append_failure_entry compare os.fstat(fh).st_ino with
                # os.stat(path).st_ino once it holds the lock, and reopen on a
                # mismatch, if that loss is ever observed.
                path.unlink(missing_ok=True)
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
    return remaining

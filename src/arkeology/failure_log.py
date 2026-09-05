"""arkeology.failure_log — append-only partial write failure log.

Writes structured JSON lines to a local .jsonl file when a partial write occurs
(S3 succeeded, Bedrock embed or put_vector failed). ``append_failure_entry`` never
raises — all file I/O errors are caught and logged to stderr.

``build_failure_entry`` is the single construction point for the entry shape, shared
by the write path and the archive path so a field added for one producer cannot
silently miss the other.

Reads and prunes go through ``read_failure_entries`` and ``rewrite_failure_log``,
which share the exclusive lock the appender takes so a pruning pass cannot overwrite
an append it never saw.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover — POSIX-only stdlib module (e.g. absent on Windows)
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def build_failure_entry(
    *,
    artifact_id: str,
    title: str,
    artifact_type: str,
    tier: int,
    date: str,
    failure_step: str,
    reason: str,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    orphan_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Build one failure-log entry, stamped with the current time.

    The single construction point for the entry shape. Both producers — the write
    path and the archive path — go through it, so the two can never drift into
    recording different shapes for the same kind of failure.

    Args:
        artifact_id: S3 key of the artifact the failure concerns.
        title: Artifact title.
        artifact_type: Artifact type string.
        tier: Artifact tier.
        date: ISO-8601 date string.
        failure_step: Stage that failed (e.g. ``"bedrock_embed"``, ``"put_vector"``,
            ``"annotation_write"``, ``"orphan_vector_cleanup"``,
            ``"archive_vector_flip"``).
        reason: Human-readable failure reason.
        commit_refs: The link-field value a failed annotation write could not persist.
            Recorded because the entry is that value's only remaining source: the
            preceding object re-PUT cleared the object's annotations, and the vector
            copy holds at most the most-recent
            :data:`~arkeology.artifact.COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES`
            entries, so anything beyond that window is otherwise unrecoverable.
            Written uncapped and in full — the log is local JSONL, where size is not a
            constraint. Omitted from the entry when empty or ``None``; an absent field
            means "nothing to restore", never "clear the field".
        references: As ``commit_refs``, and in a strictly worse position: ``references``
            is not written to vector metadata at all, so no value of it survives a
            cleared annotation without this copy.
        orphan_keys: When a ``delete_vectors`` retry is exhausted, the exact list of
            stale vector keys that still need deleting. Included only when not
            ``None``; its presence (not a separate ``kind``/``type`` field) is what
            distinguishes this failure-log entry kind from every other, which is how
            ``reconcile_index``'s Phase 1 recognises it.

    Returns:
        The entry dict, ready to pass to :func:`append_failure_entry`.
    """
    entry: dict[str, Any] = {
        "artifact_id": artifact_id,
        "title": title,
        "type": artifact_type,
        "tier": tier,
        "date": date,
        "failure_step": failure_step,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if commit_refs:
        entry["commit_refs"] = list(commit_refs)
    if references:
        entry["references"] = list(references)
    if orphan_keys is not None:
        entry["orphan_keys"] = orphan_keys
    return entry


def append_failure_entry(path: Path, entry: dict[str, Any]) -> None:
    """Append a JSON line to the failure log at ``path``.

    Creates the file if it does not exist. All exceptions from file I/O are
    caught and logged to stderr — this function never raises.

    Args:
        path: Filesystem path to the .jsonl failure log.
        entry: Dict containing at minimum: artifact_id, title, type, tier,
            date, failure_step, reason, timestamp — normally built by
            :func:`build_failure_entry`.
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

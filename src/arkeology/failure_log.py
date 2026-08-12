"""arkeology.failure_log — append-only partial write failure log.

Writes structured JSON lines to a local .jsonl file when a partial write occurs
(S3 succeeded, Bedrock embed or put_vector failed). Never raises — all file I/O
errors are caught and logged to stderr.
"""

import json
import logging
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
            # lines (07-02 #19).
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(entry, default=str) + "\n")
            finally:
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception as exc:
        logger.error("Failed to write to failure log at %s: %s", path, exc)

"""cairn_mcp.failure_log — append-only partial write failure log.

Writes structured JSON lines to a local .jsonl file when a partial write occurs
(S3 succeeded, Bedrock embed or put_vector failed). Never raises — all file I/O
errors are caught and logged to stderr.
"""

import json
import logging
from pathlib import Path
from typing import Any

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
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.error("Failed to write to failure log at %s: %s", path, exc)

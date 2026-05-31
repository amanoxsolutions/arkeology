"""Shared test helpers for all unit tests.

Centralises _make_settings so a new env var requires only one edit.
"""

from pathlib import Path

import pytest

from cairn_mcp.config import Settings


def _make_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path | None = None,
    **overrides: str,
) -> Settings:
    """Build a Settings object with required env vars set, plus any overrides.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: If provided, sets FAILURE_LOG_PATH to a temp file (needed by
            reconcile and freshness tests).
        **overrides: Additional env vars to set before constructing Settings.
    """
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    if tmp_path is not None:
        monkeypatch.setenv("FAILURE_LOG_PATH", str(tmp_path / ".cairn_failures.jsonl"))
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()

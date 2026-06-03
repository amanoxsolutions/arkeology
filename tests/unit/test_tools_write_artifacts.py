"""Unit tests for cairn_mcp.tools.write_artifacts (Z1 — Cycle C, Red phase).

All tests import write_artifacts inside the function body and call pytest.fail if
the module does not exist yet, so that collection errors are avoided while the tests
are still properly Red (FAILED, not ERRORED) until the implementation is written.
"""

import json
import pathlib
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from tests.unit.conftest import _make_settings


def _make_descriptor(i: int, **overrides: Any) -> dict[str, Any]:
    """Build a valid artifact descriptor for test index *i*."""
    base: dict[str, Any] = {
        "type": "code_review",
        "team": "platform",
        "project": "cairn",
        "tier": 2,
        "date": "2026-06-03",
        "status": "active",
        "title": f"Artifact {i}",
        "description": f"Description for artifact {i}.",
        "content": f"## Summary\n\nContent for artifact {i}.",
        "visibility": "shared",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# C1 — 10-entry list, all valid → all written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_all_succeed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """10 valid artifact descriptors → all 10 entries in response carry written=True
    and sections_indexed.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(i) for i in range(10)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 10, f"Expected 10 result entries, got {len(results)}"
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"
        assert "sections_indexed" in entry, f"Missing sections_indexed in: {entry}"
        assert "artifact_id" in entry, f"Missing artifact_id in success entry: {entry}"
        assert entry.get("artifact_id"), f"artifact_id must be non-empty: {entry}"
        assert "error" not in entry, f"Unexpected error in success entry: {entry}"


# ---------------------------------------------------------------------------
# C2 — 1 invalid entry → error entry; all other 9 succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_invalid_entry_isolated(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Entry 4 (0-indexed) has an invalid type → that entry carries error+message;
    all other 9 entries carry written=True.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(i) for i in range(10)]
    # Inject an invalid type into entry index 4
    descriptors[4] = _make_descriptor(4, type="not_a_valid_type")

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 10, f"Expected 10 result entries, got {len(results)}"

    failed = results[4]
    assert "error" in failed, f"Expected error field in entry 4, got: {failed}"
    assert "message" in failed, f"Expected message field in entry 4, got: {failed}"

    for i, entry in enumerate(results):
        if i == 4:
            continue
        assert entry.get("written") is True, f"Entry {i} should be written=True, got: {entry}"


# ---------------------------------------------------------------------------
# C3 — ARTIFACT_CONCURRENCY=1 → sequential call order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_1_sequential_order(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """With ARTIFACT_CONCURRENCY=1, artifacts are processed one at a time.

    All embed calls for artifact N must complete before any embed call for artifact N+1
    starts. Verified by tracking which artifact's title appears in each embed text.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, ARTIFACT_CONCURRENCY="1")
    bedrock = FakeBedrockClient(dimension=1024)

    titles_in_embed_order: list[str] = []
    original_embed = bedrock.embed

    def tracking_embed(text: str, model_id: str, dimensions: int) -> list[float]:
        for line in text.split("\n"):
            if line.startswith("Title: "):
                titles_in_embed_order.append(line)
                break
        return original_embed(text, model_id, dimensions)

    mocker.patch.object(bedrock, "embed", side_effect=tracking_embed)

    # Use 3 artifacts with 1 section each for clear ordering
    descriptors = [_make_descriptor(i) for i in range(3)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    # With ARTIFACT_CONCURRENCY=1, embed calls must appear in artifact order:
    # all calls for "Artifact 0" before "Artifact 1", and so on.
    expected_order = [f"Title: Artifact {i}" for i in range(3)]
    assert titles_in_embed_order == expected_order, (
        f"Embed call order {titles_in_embed_order} does not match expected {expected_order}. "
        "ARTIFACT_CONCURRENCY=1 requires sequential processing."
    )


# ---------------------------------------------------------------------------
# C4 — Partial write failure → failure log entry AND error in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_partial_failure_logged_and_in_response(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pathlib.Path,
    mocker: pytest.MonkeyPatch,
) -> None:
    """When S3 write succeeds but put_vectors_batch fails for one artifact,
    that artifact appears as an error entry in the response AND a failure log entry
    is written (consistent with write_artifact behaviour — OQ1 resolved: yes).
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path), tmp_path=tmp_path)
    bedrock = FakeBedrockClient(dimension=1024)

    # Make put_vectors_batch fail for the second artifact (call index 1)
    call_count = 0
    original_pvb = vectors_client.put_vectors_batch

    def pvb_side_effect(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated vectors failure for artifact 1")
        return original_pvb(*args, **kwargs)

    mocker.patch.object(vectors_client, "put_vectors_batch", side_effect=pvb_side_effect)

    descriptors = [_make_descriptor(i) for i in range(3)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 3

    # The failed artifact must appear as an error entry
    failed_entries = [r for r in results if "error" in r]
    assert len(failed_entries) >= 1, "Expected at least one error entry for the failed artifact"

    # A failure log entry must have been written (consistent with write_artifact)
    assert log_path.exists(), "Failure log must be written for partial write failures"
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) >= 1, "Expected at least one failure log entry"


# ---------------------------------------------------------------------------
# C5 — ARTIFACT_CONCURRENCY bounds concurrent processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_2_all_succeed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """With ARTIFACT_CONCURRENCY=2, all 5 artifacts are still written successfully.

    This is a smoke test verifying the semaphore does not drop or duplicate entries.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, ARTIFACT_CONCURRENCY="2")
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(i) for i in range(5)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"

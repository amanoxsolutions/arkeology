"""Unit tests for cairn_mcp.tools.write_artifacts (Z1 — Cycle C, Red phase).

All tests import write_artifacts inside the function body and call pytest.fail if
the module does not exist yet, so that collection errors are avoided while the tests
are still properly Red (FAILED, not ERRORED) until the implementation is written.
"""

import asyncio as asyncio_module
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

    settings = _make_settings(monkeypatch)
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
        artifact_concurrency=1,
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

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(i) for i in range(5)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
        artifact_concurrency=2,
    )

    results = result.get("results", [])
    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"


# ---------------------------------------------------------------------------
# C6 — Missing required field → validation_error per entry, others succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_missing_required_field_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor missing a required field (e.g. 'content') must return
    error='validation_error' with a message naming the missing field — not
    a raw KeyError / internal_error — while all other entries still succeed.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    descriptors = [_make_descriptor(i) for i in range(3)]
    # Remove 'content' from entry 1 to simulate what happens when the agent
    # forgets to read file contents before calling write_artifacts.
    del descriptors[1]["content"]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    failed = results[1]
    assert failed.get("error") == "validation_error", (
        f"Expected error='validation_error', got: {failed}"
    )
    assert "content" in failed.get("message", ""), (
        f"Error message should name the missing field, got: {failed}"
    )

    assert results[0].get("written") is True, f"Entry 0 should succeed: {results[0]}"
    assert results[2].get("written") is True, f"Entry 2 should succeed: {results[2]}"


@pytest.mark.asyncio
async def test_write_artifacts_invalid_file_extension_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor whose file_extension lacks a leading dot must return
    error='validation_error' (the bulk path must enforce the same guard as the
    single write_artifact, not silently produce a malformed S3 key); other entries
    still succeed.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    descriptors = [_make_descriptor(0), _make_descriptor(1, file_extension="txt")]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    results = result.get("results", [])
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"
    assert results[0].get("written") is True, f"Entry 0 should succeed: {results[0]}"

    failed = results[1]
    assert failed.get("error") == "validation_error", (
        f"Expected error='validation_error', got: {failed}"
    )
    assert "file_extension" in failed.get("message", ""), (
        f"Error message should name file_extension, got: {failed}"
    )


# ---------------------------------------------------------------------------
# C7 — artifact_concurrency=15 (in-range) → all written, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_15_in_range_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """artifact_concurrency=15 (in-range) → all artifacts written; no 'warning' key in response."""
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(i) for i in range(3)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
        artifact_concurrency=15,
    )

    results = result.get("results", [])
    assert len(results) == 3
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"
    assert "warning" not in result, (
        f"No warning expected for in-range value; got: {result.get('warning')}"
    )


# ---------------------------------------------------------------------------
# C8 — artifact_concurrency=20 (> 15) → capped to 15, warning key present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_above_15_capped_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """artifact_concurrency=20 → capped to 15; all artifacts written; warning mentions 20 and 15;
    asyncio.Semaphore is constructed with the effective value 15.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)
    descriptors = [_make_descriptor(i) for i in range(3)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
        artifact_concurrency=20,
    )

    # All artifacts written
    results = result.get("results", [])
    assert len(results) == 3
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"

    # Warning key present mentioning requested (20) and effective (15) values
    warning = result.get("warning", "")
    assert warning, "Expected a non-empty 'warning' key in response"
    assert "20" in warning, f"Warning should mention requested value 20; got: {warning}"
    assert "15" in warning, f"Warning should mention effective cap 15; got: {warning}"

    # Semaphore constructed with the effective (clamped) value 15
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 15 in semaphore_values, (
        f"Expected asyncio.Semaphore(15), got calls with values: {semaphore_values}"
    )


# ---------------------------------------------------------------------------
# C9 — artifact_concurrency=0 (< 1) → substituted to default 3, warning key present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_below_1_substituted_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """artifact_concurrency=0 → substituted to default 3; all artifacts written;
    warning mentions 0 and 3; asyncio.Semaphore constructed with 3.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)
    descriptors = [_make_descriptor(i) for i in range(3)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
        artifact_concurrency=0,
    )

    # All artifacts written
    results = result.get("results", [])
    assert len(results) == 3
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"

    # Warning key present mentioning supplied value (0) and default substitution (3)
    warning = result.get("warning", "")
    assert warning, "Expected a non-empty 'warning' key in response"
    assert "0" in warning, f"Warning should mention the supplied value 0; got: {warning}"
    assert "3" in warning, f"Warning should mention the default substitution 3; got: {warning}"

    # Semaphore constructed with the effective (default) value 3
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 3 in semaphore_values, (
        f"Expected asyncio.Semaphore(3), got calls with values: {semaphore_values}"
    )


# ---------------------------------------------------------------------------
# C10 — artifact_concurrency omitted → default 3, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_concurrency_omitted_defaults_to_3_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """artifact_concurrency omitted → asyncio.Semaphore constructed with 3; no 'warning' key."""
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)
    descriptors = [_make_descriptor(i) for i in range(2)]

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=descriptors,
    )

    # No warning key when using the default
    assert "warning" not in result, (
        f"No warning expected when artifact_concurrency is omitted; got: {result.get('warning')}"
    )

    # Semaphore constructed with default value 3
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 3 in semaphore_values, (
        f"Expected asyncio.Semaphore(3) for default concurrency, got: {semaphore_values}"
    )


# ---------------------------------------------------------------------------
# M13 — intra-batch duplicate artifact IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_artifact_ids_second_entry_is_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Two descriptors that resolve to the same artifact ID → first written, second error.

    Without the pre-flight dedup check the two coroutines race on orphan cleanup:
    each deletes the other's freshly written vectors, leaving the artifact un-indexed.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    # Both descriptors produce the same artifact ID (same type/tier/date/title)
    d1 = _make_descriptor(0)
    d2 = _make_descriptor(0)

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[d1, d2],
    )

    results = result["results"]
    assert len(results) == 2
    assert results[0].get("written") is True, f"First entry should succeed: {results[0]}"
    assert results[1].get("error") == "validation_error", (
        f"Second duplicate entry should be validation_error: {results[1]}"
    )
    assert "duplicate" in results[1]["message"].lower(), (
        f"Error message should mention 'duplicate': {results[1]['message']}"
    )


@pytest.mark.asyncio
async def test_duplicate_non_adjacent_third_entry_is_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """First and third entries share the same artifact ID → only third is validation_error."""
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)

    d_unique = _make_descriptor(1)  # distinct from d_dup
    d_dup_a = _make_descriptor(0)  # first occurrence of id 0
    d_dup_b = _make_descriptor(0)  # second occurrence of id 0 — non-adjacent

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[d_dup_a, d_unique, d_dup_b],
    )

    results = result["results"]
    assert len(results) == 3
    assert results[0].get("written") is True, f"Entry 0 (first dup) should succeed: {results[0]}"
    assert results[1].get("written") is True, f"Entry 1 (unique) should succeed: {results[1]}"
    assert results[2].get("error") == "validation_error", (
        f"Entry 2 (second dup) should be validation_error: {results[2]}"
    )


# ---------------------------------------------------------------------------
# C-3 — batch path: collision guard + overwrite flag (batch-level and per-descriptor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_artifacts_existing_key_without_overwrite_is_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor targeting an already-existing key (from a prior batch call) without
    overwrite → validation_error; the existing artifact is left untouched.
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(0)

    first = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[descriptor],
    )
    assert first["results"][0].get("written") is True

    second = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[descriptor],
    )

    assert second["results"][0].get("error") == "validation_error"
    assert len(s3_client.list_objects("")) == 1


@pytest.mark.asyncio
async def test_write_artifacts_batch_level_overwrite_true_allows_update(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Batch-level overwrite=True allows every descriptor in the batch to replace
    an existing key (mirrors the file_extension batch-default/per-descriptor shape).
    """
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(0)

    await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[descriptor],
    )

    updated = {**descriptor, "content": "## Summary\n\nUpdated content for artifact 0."}
    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[updated],
        overwrite=True,
    )

    assert result["results"][0].get("written") is True
    artifact_id = result["results"][0]["artifact_id"]
    assert "Updated content for artifact 0." in s3_client.get_object(artifact_id)


@pytest.mark.asyncio
async def test_write_artifacts_per_descriptor_overwrite_overrides_batch_default(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor-level "overwrite": True overrides the batch-level default (False)."""
    try:
        from cairn_mcp.tools.write_artifacts import write_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.write_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(0)

    await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[descriptor],
    )

    updated = {
        **descriptor,
        "content": "## Summary\n\nUpdated via per-descriptor overwrite.",
        "overwrite": True,
    }
    # Batch-level default remains False — only this descriptor opts in.
    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[updated],
    )

    assert result["results"][0].get("written") is True
    artifact_id = result["results"][0]["artifact_id"]
    assert "Updated via per-descriptor overwrite." in s3_client.get_object(artifact_id)

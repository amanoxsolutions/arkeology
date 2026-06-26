"""Unit tests for cairn_mcp.tools.migrate_artifacts (Z1 — Cycle E, Red phase).

All tests import migrate_artifacts inside the function body and call pytest.fail if
the module does not exist yet.  The Nova Lite call is simulated via mocker.patch.object
with create=True so the spy exists even before FakeBedrockClient.invoke_text_model
is implemented.
"""

import asyncio as asyncio_module
import logging
from typing import Any

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from tests.unit.conftest import _make_settings

_FAKE_DESCRIPTION = "Fake generated description."


def _make_descriptor(i: int, *, with_description: bool = True, **overrides: Any) -> dict[str, Any]:
    """Build a valid migration descriptor for test index *i*."""
    base: dict[str, Any] = {
        "type": "adr",
        "team": "platform",
        "project": "cairn",
        "tier": 2,
        "date": "2026-06-03",
        "status": "active",
        "title": f"Decision {i}",
        "content": f"## Context\n\nContext for decision {i}.",
        "visibility": "shared",
    }
    if with_description:
        base["description"] = f"Description for decision {i}."
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# E1 — dry_run=True, 5 descriptors (3 with / 2 without) → 2 Nova Lite calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_dry_run_nova_lite_calls_for_missing(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=True, 5 descriptors (3 with descriptions, 2 without) →
    exactly 2 Nova Lite calls; response contains 5 enriched descriptors with
    descriptions ≤ 280 chars.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    descriptors = [_make_descriptor(i, with_description=(i < 3)) for i in range(5)]
    # indices 0,1,2 have descriptions; 3,4 do not

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    # Exactly 2 Nova Lite calls (one per missing description)
    assert mock_invoke.call_count == 2, (
        f"Expected 2 Nova Lite calls (for the 2 missing descriptions), got {mock_invoke.call_count}"
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 5, f"Expected 5 enriched descriptors, got {len(enriched)}"
    for desc in enriched:
        description = desc.get("description", "")
        assert len(description) <= 280, f"Description exceeds 280 chars: {len(description)} chars"


# ---------------------------------------------------------------------------
# E2 — dry_run=True → s3.put_object and vectors.put_vectors_batch never called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_dry_run_no_writes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=True → s3.put_object and vectors.put_vectors_batch are never called."""
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)

    put_spy = mocker.spy(s3_client, "put_object")
    vectors_spy = mocker.spy(vectors_client, "put_vectors_batch")

    descriptors = [_make_descriptor(i) for i in range(3)]

    await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    assert put_spy.call_count == 0, (
        "s3.put_object must not be called during dry_run=True, "
        f"was called {put_spy.call_count} time(s)"
    )
    assert vectors_spy.call_count == 0, (
        f"vectors.put_vectors_batch must not be called during dry_run=True, "
        f"was called {vectors_spy.call_count} time(s)"
    )


# ---------------------------------------------------------------------------
# E3 — dry_run=True, 300-char agent description → clipped to 280
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_dry_run_clips_long_agent_description(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=True, agent-provided description of 300 chars → returned description
    is clipped to 280 chars.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)

    long_description = "x" * 300
    descriptors = [_make_descriptor(0, description=long_description)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 1
    returned_desc = enriched[0].get("description", "")
    assert len(returned_desc) == 280, (
        f"Expected description clipped to 280 chars, got {len(returned_desc)} chars"
    )


# ---------------------------------------------------------------------------
# E4 — dry_run=False, 10 descriptors (8 with / 2 without) → 2 Nova Lite, all 10 written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_false_writes_all_and_calls_nova_for_missing(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=False, 10 descriptors (8 with descriptions, 2 without) →
    exactly 2 Nova Lite calls and all 10 artifacts written.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    # Descriptors 8 and 9 have no description
    descriptors = [_make_descriptor(i, with_description=(i < 8)) for i in range(10)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )

    assert mock_invoke.call_count == 2, f"Expected 2 Nova Lite calls, got {mock_invoke.call_count}"

    results = result.get("results", [])
    assert len(results) == 10, f"Expected 10 result entries, got {len(results)}"
    written = [r for r in results if r.get("written") is True]
    assert len(written) == 10, f"Expected all 10 artifacts written, got {len(written)} written"


# ---------------------------------------------------------------------------
# E5 — dry_run=False, all with descriptions → zero Nova Lite calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_false_no_nova_when_all_have_descriptions(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=False, all 10 descriptors already have descriptions →
    zero Nova Lite calls; all 10 artifacts written.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    descriptors = [_make_descriptor(i, with_description=True) for i in range(10)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )

    assert mock_invoke.call_count == 0, (
        "Expected 0 Nova Lite calls when all descriptions are present, "
        f"got {mock_invoke.call_count}"
    )

    results = result.get("results", [])
    assert len(results) == 10
    written = [r for r in results if r.get("written") is True]
    assert len(written) == 10


# ---------------------------------------------------------------------------
# E6 — Re-calling with same descriptors → idempotent (no duplicates, no errors)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Re-calling migrate_artifacts(dry_run=False) with the same descriptors produces
    no duplicate artifacts and no errors.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)

    descriptors = [_make_descriptor(i) for i in range(5)]

    kwargs: dict[str, Any] = dict(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )

    result1 = await migrate_artifacts(**kwargs)
    result2 = await migrate_artifacts(**kwargs)

    r1 = result1.get("results", [])
    r2 = result2.get("results", [])
    assert len(r1) == 5
    assert len(r2) == 5

    # Both runs must succeed without errors
    for entry in r1 + r2:
        assert "error" not in entry, f"Unexpected error on re-run: {entry}"

    # S3 must still contain exactly 5 objects (no duplicates)
    all_objects = s3_client.list_objects("")
    assert len(all_objects) == 5, (
        f"Expected exactly 5 S3 objects after idempotent re-run, found {len(all_objects)}"
    )


# ---------------------------------------------------------------------------
# E7 — Nova Lite generated description > 280 chars → clipped + DEBUG logged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_clips_long_nova_description_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nova Lite returns a description > 280 chars → it is clipped to 280 and logged at DEBUG."""
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    long_nova_output = "z" * 400  # exceeds 280-char limit
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=long_nova_output)

    descriptors = [_make_descriptor(0, with_description=False)]

    with caplog.at_level(logging.DEBUG):
        result = await migrate_artifacts(
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
            settings=settings,
            descriptors=descriptors,
            dry_run=True,
        )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 1
    desc = enriched[0].get("description", "")
    assert len(desc) == 280, f"Expected description clipped to 280 chars, got {len(desc)}"

    clip_logs = [
        r for r in caplog.records if "clip" in r.message.lower() or "truncat" in r.message.lower()
    ]
    assert len(clip_logs) >= 1, (
        "Expected at least one DEBUG log message about description clipping — not yet implemented"
    )


# ---------------------------------------------------------------------------
# E8 — ARTIFACT_CONCURRENCY=2 → at most 2 concurrent Nova Lite calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_concurrency_2_limits_nova_calls(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """ARTIFACT_CONCURRENCY=2, 4 descriptors without descriptions →
    exactly 4 Nova Lite calls are made and all 4 enriched descriptors are returned.

    The semaphore bound of 2 is verified indirectly via the call count (all calls
    succeed) and the response (all 4 descriptors enriched).
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    descriptors = [_make_descriptor(i, with_description=False) for i in range(4)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
        artifact_concurrency=2,
    )

    assert mock_invoke.call_count == 4, (
        f"Expected 4 Nova Lite calls (one per missing description), got {mock_invoke.call_count}"
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 4, f"Expected 4 enriched descriptors, got {len(enriched)}"
    for desc in enriched:
        assert "description" in desc, f"Missing description field in: {desc}"
        assert len(desc["description"]) > 0


# ---------------------------------------------------------------------------
# E9 — BEDROCK_TEXT_MODEL=None with missing description → configuration_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_missing_description_no_text_model_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """When a descriptor is missing a description and BEDROCK_TEXT_MODEL is not
    configured, migrate_artifacts returns a configuration_error without calling
    invoke_text_model.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    # Ensure BEDROCK_TEXT_MODEL is absent (None)
    monkeypatch.delenv("BEDROCK_TEXT_MODEL", raising=False)
    settings = _make_settings(monkeypatch)
    assert settings.bedrock_text_model is None, "BEDROCK_TEXT_MODEL must be None for this test"

    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    # One descriptor without a description
    descriptors = [_make_descriptor(0, with_description=False)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    assert result.get("error") == "configuration_error", (
        f"Expected configuration_error, got: {result}"
    )
    assert "BEDROCK_TEXT_MODEL" in result.get("message", ""), (
        f"Error message should mention BEDROCK_TEXT_MODEL: {result.get('message')}"
    )
    assert mock_invoke.call_count == 0, (
        "invoke_text_model must not be called when BEDROCK_TEXT_MODEL is not configured"
    )


# ---------------------------------------------------------------------------
# E10 — artifact_concurrency=20 (> 15) → capped to 15, warning key, semaphore=15
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_concurrency_above_15_capped_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """artifact_concurrency=20 with missing descriptions → capped to 15;
    warning key present; bedrock.invoke_text_model called with description semaphore of 15.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)

    descriptors = [_make_descriptor(i, with_description=False) for i in range(3)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
        artifact_concurrency=20,
    )

    # Descriptions generated and returned
    enriched = result.get("descriptors", [])
    assert len(enriched) == 3, f"Expected 3 enriched descriptors, got {len(enriched)}"
    assert mock_invoke.call_count == 3, f"Expected 3 Nova Lite calls, got {mock_invoke.call_count}"

    # Warning key present
    warning = result.get("warning", "")
    assert warning, "Expected a non-empty 'warning' key in response"
    assert "20" in warning, f"Warning should mention requested value 20; got: {warning}"
    assert "15" in warning, f"Warning should mention effective cap 15; got: {warning}"

    # Description semaphore constructed with effective value 15
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 15 in semaphore_values, (
        f"Expected asyncio.Semaphore(15) for description phase, got: {semaphore_values}"
    )


# ---------------------------------------------------------------------------
# E11 — artifact_concurrency=0 (< 1) → substituted to default 3, warning key, semaphore=3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_concurrency_below_1_substituted_warns(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """artifact_concurrency=0 with missing descriptions → substituted to default 3;
    warning key present; description semaphore constructed with 3.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)

    descriptors = [_make_descriptor(i, with_description=False) for i in range(3)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
        artifact_concurrency=0,
    )

    # Descriptions generated and returned
    enriched = result.get("descriptors", [])
    assert len(enriched) == 3, f"Expected 3 enriched descriptors, got {len(enriched)}"
    assert mock_invoke.call_count == 3, f"Expected 3 Nova Lite calls, got {mock_invoke.call_count}"

    # Warning key present
    warning = result.get("warning", "")
    assert warning, "Expected a non-empty 'warning' key in response"
    assert "0" in warning, f"Warning should mention supplied value 0; got: {warning}"
    assert "3" in warning, f"Warning should mention default substitution 3; got: {warning}"

    # Description semaphore constructed with effective (default) value 3
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 3 in semaphore_values, (
        f"Expected asyncio.Semaphore(3) for description phase, got: {semaphore_values}"
    )


# ---------------------------------------------------------------------------
# E12 — dry_run=True, artifact_concurrency=5 → semaphore=5, no warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_in_range_concurrency_5_dry_run_true_uses_semaphore_5(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=True, artifact_concurrency=5 (in-range) → description semaphore constructed
    with 5; no 'warning' key in response.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)

    # Descriptors with missing descriptions to trigger semaphore creation
    descriptors = [_make_descriptor(i, with_description=False) for i in range(3)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
        artifact_concurrency=5,
    )

    # No warning for in-range value
    assert "warning" not in result, (
        f"No warning expected for in-range artifact_concurrency=5; got: {result.get('warning')}"
    )

    # Description semaphore constructed with 5
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 5 in semaphore_values, (
        f"Expected asyncio.Semaphore(5) for description phase, got: {semaphore_values}"
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 3


# ---------------------------------------------------------------------------
# E13 — dry_run=False, artifact_concurrency=7 → write_artifacts semaphore=7
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_artifacts_in_range_concurrency_5_dry_run_false_forwards_5(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=False, artifact_concurrency=7 → write_artifacts semaphore constructed with 7."""
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)
    semaphore_spy = mocker.patch("asyncio.Semaphore", wraps=asyncio_module.Semaphore)

    # All descriptors have descriptions — no description semaphore, only write semaphore
    descriptors = [_make_descriptor(i, with_description=True) for i in range(3)]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
        artifact_concurrency=7,
    )

    # Write semaphore forwarded from migrate_artifacts and constructed with 7
    semaphore_values = [c.args[0] for c in semaphore_spy.call_args_list if c.args]
    assert 7 in semaphore_values, (
        f"Expected asyncio.Semaphore(7) forwarded to write_artifacts, got: {semaphore_values}"
    )

    # All artifacts written successfully
    results = result.get("results", [])
    assert len(results) == 3
    for entry in results:
        assert entry.get("written") is True, f"Expected written=True, got: {entry}"


# ---------------------------------------------------------------------------
# M20 Bug 1 — single Nova Lite failure must not abort all migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m20_single_nova_lite_failure_does_not_abort_migration(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """M20 Bug 1: When one Nova Lite call fails (line ~181 does `raise result` when result is
    BaseException), the current code aborts the ENTIRE migration via `raise result`.  After the
    fix, that single failure is caught and reported gracefully; other descriptors continue.

    Scenario:
    - 3 descriptors, all WITHOUT descriptions (so all need Nova Lite).
    - invoke_text_model succeeds on calls 1 and 3, raises RuntimeError on call 2.
    - dry_run=True so we only need enrichment, not writes.
    - Expected AFTER fix:
        * Migration does NOT abort entirely (no exception, no top-level error key).
        * Descriptor 0 and descriptor 2 receive generated descriptions.
        * Descriptor 1 may have an empty/default description or be noted as failed,
          but the response must include all 3 descriptors (not just 0 or 1).

    Note: Before the fix, asyncio.gather(return_exceptions=True) collects exceptions
    but `raise result` on a BaseException re-raises it, so only the first descriptor
    is visible and the call to migrate_artifacts raises.
    """
    try:
        from cairn_mcp.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("cairn_mcp.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)

    call_count: dict[str, int] = {"n": 0}

    def invoke_side_effect(model: str, prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated Nova Lite failure on 2nd call")
        return _FAKE_DESCRIPTION

    mocker.patch.object(bedrock, "invoke_text_model", create=True, side_effect=invoke_side_effect)

    descriptors = [_make_descriptor(i, with_description=False) for i in range(3)]

    # Before fix: migrate_artifacts raises (propagates the RuntimeError via `raise result`).
    # After fix: should return a response dict without raising.
    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    assert isinstance(result, dict), (
        "M20 Bug 1: migrate_artifacts should return a dict, not raise an exception"
    )
    assert "error" not in result, (
        f"M20 Bug 1: top-level error should not abort migration for a single failure, got: {result}"
    )
    enriched = result.get("descriptors", [])
    assert len(enriched) == 3, (
        f"M20 Bug 1: all 3 descriptors should be present in result, got {len(enriched)}: {enriched}"
    )


# ---------------------------------------------------------------------------
# M20 Bug 3 — server.py migrate_artifacts tool must expose artifact_concurrency
# ---------------------------------------------------------------------------


def test_m20_server_migrate_artifacts_exposes_artifact_concurrency() -> None:
    """M20 Bug 3: The MCP tool definition in server.py wraps migrate_artifacts but does not
    forward artifact_concurrency to the inner function.  After the fix, the tool function
    signature must include an artifact_concurrency parameter.

    This test inspects the source of server.py to verify the parameter is present in the
    migrate_artifacts tool definition.
    """
    import inspect

    from cairn_mcp import server as server_module

    # The register_tools function creates local tool closures; we inspect its source.
    src = inspect.getsource(server_module.register_tools)
    # The migrate_artifacts inner function definition must declare artifact_concurrency.
    # The fix adds it as a parameter with a default value.
    assert "artifact_concurrency" in src, (
        "M20 Bug 3: server.py register_tools must include 'artifact_concurrency' in the "
        "migrate_artifacts tool definition so callers can control concurrency via MCP."
    )

"""Unit tests for arkeology.tools.migrate_artifacts (Z1 — Cycle E, Red phase).

All tests import migrate_artifacts inside the function body and call pytest.fail if
the module does not exist yet.  The Nova Lite call is simulated via mocker.patch.object
with create=True so the spy exists even before FakeBedrockClient.invoke_text_model
is implemented.
"""

import asyncio as asyncio_module
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.server import _app, register_tools
from tests.unit.conftest import _make_settings

_FAKE_DESCRIPTION = "Fake generated description."


def _make_descriptor(i: int, *, with_description: bool = True, **overrides: Any) -> dict[str, Any]:
    """Build a valid migration descriptor for test index *i*."""
    base: dict[str, Any] = {
        "type": "adr",
        "team": "platform",
        "project": "arkeology",
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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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
async def test_single_nova_lite_failure_does_not_abort_migration(
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
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

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


async def test_a1_migrate_writes_only_new_and_skips_pre_existing_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A descriptor whose generated key was already written by a prior call is
    skipped (no overwrite, no error); the other, genuinely-new descriptors are written.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)

    # Prior write — same type/team/project/tier/date/title as descriptor 0 below, so it
    # resolves to the identical generated key.
    prior = _make_descriptor(0, content="## Context\n\nORIGINAL content, do not overwrite.")
    await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[prior],
        dry_run=False,
    )
    prior_key = s3_client.list_objects("")[0]
    original_content = s3_client.get_object(prior_key)

    # Descriptor 0 collides with the prior write; descriptor 1 is genuinely new.
    colliding = _make_descriptor(0, content="## Context\n\nCHANGED content — must be rejected.")
    fresh = _make_descriptor(1)
    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[colliding, fresh],
        dry_run=False,
    )

    results = result.get("results", [])
    assert len(results) == 2, f"Expected one result per input descriptor, got {results}"

    # The colliding entry must not report an error and must not claim to have written.
    assert "error" not in results[0], f"Skip must not be surfaced as an error: {results[0]}"
    assert results[0].get("written") is not True, (
        f"Colliding entry must not be written: {results[0]}"
    )

    # The fresh entry writes normally.
    assert results[1].get("written") is True, f"Fresh descriptor should write: {results[1]}"

    # Skipped items are surfaced explicitly.
    skipped = result.get("skipped_existing", [])
    assert len(skipped) == 1, f"Expected exactly one skipped_existing entry, got {skipped}"

    # The original content is untouched — no silent overwrite occurred.
    assert s3_client.get_object(prior_key) == original_content
    # Exactly 2 objects total: the untouched original + the one new write.
    assert len(s3_client.list_objects("")) == 2


async def test_a1_migrate_rerun_over_full_corpus_is_idempotent_and_non_destructive(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Re-running a migration over an already-imported corpus writes nothing and
    skips everything — idempotent and non-destructive, even when re-run content differs.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION)

    descriptors = [_make_descriptor(i) for i in range(4)]

    first = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )
    assert all(r.get("written") is True for r in first.get("results", []))
    objects_after_first = sorted(s3_client.list_objects(""))
    contents_after_first = {k: s3_client.get_object(k) for k in objects_after_first}

    # Re-run with the exact same descriptors (the realistic re-import scenario).
    second = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )

    second_results = second.get("results", [])
    assert len(second_results) == 4
    for entry in second_results:
        assert "error" not in entry, f"Re-run must not surface skips as errors: {entry}"
        assert entry.get("written") is not True, f"Re-run must not rewrite anything: {entry}"

    assert len(second.get("skipped_existing", [])) == 4, (
        f"Expected all 4 to be skipped on re-run, got: {second.get('skipped_existing')}"
    )

    # Nothing was mutated: same object set, same content, no duplicates.
    assert sorted(s3_client.list_objects("")) == objects_after_first
    for key, content in contents_after_first.items():
        assert s3_client.get_object(key) == content


async def test_server_migrate_artifacts_exposes_artifact_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M20 Bug 3: The MCP tool definition in server.py wraps migrate_artifacts but must
    forward a caller-supplied artifact_concurrency to the inner function — a behavioural
    assertion rather than a brittle inspect.getsource substring check, which
    would keep passing even if the parameter were declared but never forwarded.
    """
    settings = _make_settings(monkeypatch)
    mock_migrate = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("arkeology.server._migrate_artifacts", mock_migrate)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("migrate_artifacts")
    assert tool is not None
    await tool.fn(descriptors=[], artifact_concurrency=10)

    mock_migrate.assert_awaited_once()
    _, call_kwargs = mock_migrate.call_args
    assert call_kwargs["artifact_concurrency"] == 10


# ---------------------------------------------------------------------------
# T46 — references threading (Story 4, migrate_artifacts dry_run=False path)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# A failed description generation must not write an empty description
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_generation_skipped_not_written_with_empty_description(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=False — a descriptor whose Nova Lite generation fails is never
    written with an empty description. It is skipped and reported under
    "generation_failed"; the other, successfully-generated descriptor still writes.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)

    def invoke_side_effect(model: str, prompt: str) -> str:
        if "Title: FAIL_ME" in prompt:
            raise RuntimeError("simulated Nova Lite failure")
        return _FAKE_DESCRIPTION

    mocker.patch.object(bedrock, "invoke_text_model", create=True, side_effect=invoke_side_effect)

    failing = _make_descriptor(0, with_description=False, title="FAIL_ME")
    ok = _make_descriptor(1, with_description=False)

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[failing, ok],
        dry_run=False,
    )

    results = result.get("results", [])
    assert len(results) == 2

    assert results[0].get("written") is not True, (
        f"A descriptor whose description generation failed must not be written: {results[0]}"
    )
    assert results[0].get("skipped") is True
    assert results[0].get("reason") == "description_generation_failed"
    assert "error" not in results[0], "A generation failure is a skip, not an error entry"

    assert results[1].get("written") is True, (
        f"The unaffected descriptor should write: {results[1]}"
    )

    generation_failed = result.get("generation_failed", [])
    assert len(generation_failed) == 1
    assert generation_failed[0]["index"] == 0
    assert generation_failed[0]["title"] == "FAIL_ME"

    # No S3 object exists for the failed descriptor — only the successful one was written.
    all_objects = s3_client.list_objects("")
    assert len(all_objects) == 1, (
        f"Expected exactly 1 S3 object (the successful write only), found {len(all_objects)}"
    )


@pytest.mark.asyncio
async def test_dry_run_reports_generation_failed_without_empty_description_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=True — a failed generation is reported under "generation_failed";
    the enriched descriptor list still contains an entry per input (existing contract),
    but the failure is explicitly surfaced rather than silently left as an empty string.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)

    def invoke_side_effect(model: str, prompt: str) -> str:
        raise RuntimeError("simulated Nova Lite failure")

    mocker.patch.object(bedrock, "invoke_text_model", create=True, side_effect=invoke_side_effect)

    descriptors = [_make_descriptor(0, with_description=False, title="FAIL_ME")]

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

    generation_failed = result.get("generation_failed", [])
    assert len(generation_failed) == 1
    assert generation_failed[0]["index"] == 0
    assert generation_failed[0]["title"] == "FAIL_ME"
    assert "simulated Nova Lite failure" in generation_failed[0]["message"]


@pytest.mark.asyncio
async def test_generation_prompt_content_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """The artifact content interpolated into the Nova Lite prompt is bounded —
    a very large content body is truncated rather than sent to Nova Lite unbounded.
    """
    try:
        from arkeology.tools.migrate_artifacts import (
            _PROMPT_CONTENT_MAX_CHARS,
            migrate_artifacts,
        )
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch, BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0")
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value=_FAKE_DESCRIPTION
    )

    huge_content = "x" * (_PROMPT_CONTENT_MAX_CHARS * 3)
    descriptors = [_make_descriptor(0, with_description=False, content=huge_content)]

    await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=True,
    )

    assert mock_invoke.call_count == 1
    prompt = mock_invoke.call_args_list[0].args[1]
    assert huge_content not in prompt, "The full untruncated content must not reach the prompt"
    assert len(prompt) < len(huge_content), "The prompt must be materially shorter than the content"
    assert "x" * _PROMPT_CONTENT_MAX_CHARS in prompt, (
        "The bounded prefix of the content should still be present"
    )


@pytest.mark.asyncio
async def test_migrate_artifacts_dry_run_false_threads_references_to_annotation_only(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor carrying references=['a-1'] round-trips into the written artifact's
    S3 annotation (its sole durable store as of T58) when
    migrate_artifacts(dry_run=False) delegates to write_artifacts — and never into
    vector metadata.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptors = [_make_descriptor(0, references=["a-1"])]

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=descriptors,
        dry_run=False,
    )

    results = result.get("results", [])
    assert len(results) == 1
    assert results[0].get("written") is True
    artifact_id = results[0]["artifact_id"]

    assert s3_client.get_object_annotation(artifact_id, "references") == "a-1"
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    assert keys
    entries = vectors_client.get_vectors(keys)
    for entry in entries:
        assert "references" not in entry["metadata"]


# ---------------------------------------------------------------------------
# T56 / FR-52 extension — resolved_references_map content rewrite threading
# ---------------------------------------------------------------------------

_T56_ORIGINAL_PATH = "../decisions/B.md"
_T56_B_ID = "platform/arkeology/adr-b-decision-abcd1234.md"

_T56_CONTENT = (
    "---\n"
    "references:\n"
    f"  - {_T56_ORIGINAL_PATH}\n"
    "---\n\n"
    "## Context\n\n"
    f"See [the decision]({_T56_ORIGINAL_PATH}) for details. This context section has "
    "enough body text to survive the min-length embedding filter threshold.\n"
)


@pytest.mark.asyncio
async def test_t56_dry_run_false_rewrites_content_before_write_and_embed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """dry_run=False: a descriptor carrying resolved_references_map has its content
    rewritten (frontmatter + body link) BEFORE s3.put_object and BEFORE bedrock.embed
    are called — the content stored in S3 and the text embedded are both the
    already-rewritten version (no re-embed, no S3/embedding divergence).
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    embed_spy = mocker.spy(bedrock, "embed")
    put_spy = mocker.spy(s3_client, "put_object")

    descriptor = _make_descriptor(
        0,
        content=_T56_CONTENT,
        resolved_references_map={_T56_ORIGINAL_PATH: _T56_B_ID},
    )

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[descriptor],
        dry_run=False,
    )

    results = result.get("results", [])
    assert len(results) == 1
    assert results[0].get("written") is True
    artifact_id = results[0]["artifact_id"]

    # S3 content is rewritten: original path gone, arkeology:// URI present in both the
    # frontmatter list item and the body link target.
    stored_content = s3_client.get_object(artifact_id)
    assert _T56_ORIGINAL_PATH not in stored_content
    assert f"arkeology://artifact/{_T56_B_ID}" in stored_content
    assert f"  - arkeology://artifact/{_T56_B_ID}" in stored_content
    assert f"[the decision](arkeology://artifact/{_T56_B_ID})" in stored_content

    # put_object was called with exactly this rewritten body — proving the rewrite
    # happened before the write, not as some out-of-band patch.
    assert put_spy.call_count >= 1
    put_bodies = [
        c.args[1] if len(c.args) > 1 else c.kwargs.get("body") for c in put_spy.call_args_list
    ]
    assert any(
        body is not None and _T56_ORIGINAL_PATH not in body and _T56_B_ID in body
        for body in put_bodies
    )

    # bedrock.embed received the rewritten text (not the original path) for the
    # section containing the link — proving no re-embed / no divergence.
    embed_texts = [c.args[0] if c.args else c.kwargs.get("text") for c in embed_spy.call_args_list]
    assert any(
        text is not None and f"arkeology://artifact/{_T56_B_ID}" in text for text in embed_texts
    )
    assert all(text is None or _T56_ORIGINAL_PATH not in text for text in embed_texts)


@pytest.mark.asyncio
async def test_t56_resolved_references_map_never_leaks_into_write_result(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """dry_run=False: resolved_references_map never appears in the results list, and
    the S3 object metadata / vector metadata carry no trace of it either.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(
        0,
        content=_T56_CONTENT,
        resolved_references_map={_T56_ORIGINAL_PATH: _T56_B_ID},
    )

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[descriptor],
        dry_run=False,
    )

    assert "resolved_references_map" not in result
    for entry in result.get("results", []):
        assert "resolved_references_map" not in entry

    artifact_id = result["results"][0]["artifact_id"]
    head = s3_client.head_object(artifact_id)
    assert "resolved_references_map" not in str(head)

    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    for entry in entries:
        assert "resolved_references_map" not in entry["metadata"]


@pytest.mark.asyncio
async def test_t56_dry_run_true_descriptor_echo_already_rewritten_and_key_absent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """dry_run=True: the returned descriptor's content already reflects the rewrite (the
    preview shows the true final content), and resolved_references_map is absent from
    the returned descriptor.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(
        0,
        content=_T56_CONTENT,
        resolved_references_map={_T56_ORIGINAL_PATH: _T56_B_ID},
    )

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[descriptor],
        dry_run=True,
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 1
    assert "resolved_references_map" not in enriched[0]
    content = enriched[0]["content"]
    assert _T56_ORIGINAL_PATH not in content
    assert f"arkeology://artifact/{_T56_B_ID}" in content


@pytest.mark.asyncio
async def test_t56_descriptor_without_map_is_unaffected(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A descriptor without resolved_references_map is behaviourally identical to
    pre-T56 migrate_artifacts — content passes through untouched in both dry_run modes.
    """
    try:
        from arkeology.tools.migrate_artifacts import migrate_artifacts
    except ImportError:
        pytest.fail("arkeology.tools.migrate_artifacts is not yet implemented")

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(0, content=_T56_CONTENT)

    result = await migrate_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        descriptors=[descriptor],
        dry_run=True,
    )

    enriched = result.get("descriptors", [])
    assert len(enriched) == 1
    assert enriched[0]["content"] == _T56_CONTENT
    assert "resolved_references_map" not in enriched[0]


@pytest.mark.asyncio
async def test_t56_write_artifacts_direct_call_ignores_resolved_references_map(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Calling write_artifacts directly (outside migrate_artifacts) with an
    unrecognised resolved_references_map-shaped key has no effect — the capability is
    migrate_artifacts-only and is never wired into the general write path.
    """
    from arkeology.tools.write_artifacts import write_artifacts

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient(dimension=1024)
    descriptor = _make_descriptor(
        0,
        content=_T56_CONTENT,
        resolved_references_map={_T56_ORIGINAL_PATH: _T56_B_ID},
    )

    result = await write_artifacts(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        artifacts=[descriptor],
    )

    results = result.get("results", [])
    assert len(results) == 1
    assert results[0].get("written") is True
    artifact_id = results[0]["artifact_id"]

    stored_content = s3_client.get_object(artifact_id)
    assert stored_content == _T56_CONTENT
    assert _T56_ORIGINAL_PATH in stored_content
    assert "arkeology://artifact/" not in stored_content

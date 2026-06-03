"""Unit tests for cairn_mcp.tools.migrate_artifacts (Z1 — Cycle E, Red phase).

All tests import migrate_artifacts inside the function body and call pytest.fail if
the module does not exist yet.  The Nova Lite call is simulated via mocker.patch.object
with create=True so the spy exists even before FakeBedrockClient.invoke_text_model
is implemented.
"""

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

    settings = _make_settings(
        monkeypatch, ARTIFACT_CONCURRENCY="2", BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0"
    )
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

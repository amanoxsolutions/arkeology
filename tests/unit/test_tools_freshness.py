"""Unit tests for arkeology.tools.freshness.

Tests check_synthesis_freshness() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

import json
import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.errors import CredentialError
from arkeology.tools._search_helper import _NIN_EXCLUSION_BYTE_BUDGET
from arkeology.tools.freshness import check_synthesis_freshness
from tests.unit.conftest import _make_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIMENSION = 8
DUMMY_VEC = [1.0] + [0.0] * (DIMENSION - 1)


# ---------------------------------------------------------------------------
# Metadata factory helpers
# ---------------------------------------------------------------------------


def _synthesis_meta(
    artifact_id: str,
    date: str,
    source_artifacts: list[str],
    scope: str = "artifacts",
    status: str = "active",
) -> dict[str, Any]:
    """Build vector metadata for a synthesis artifact."""
    meta: dict[str, Any] = {
        "artifact_id": artifact_id,
        "scope": scope,
        "type": "synthesis",
        "status": status,
        "date": date,
        "title": "Test Synthesis",
        "team": "platform",
        "project": "arkeology",
        "tier": 3,
        "visibility": "shared",
        "description": "A test synthesis artifact.",
    }
    if source_artifacts:
        meta["source_artifacts"] = source_artifacts
    return meta


def _source_meta(
    artifact_id: str,
    date: str,
    status: str = "active",
    scope: str = "artifacts",
    tier: int = 2,
    visibility: str = "shared",
) -> dict[str, Any]:
    """Build vector metadata for a source artifact."""
    return {
        "artifact_id": artifact_id,
        "scope": scope,
        "type": "implementation_note",
        "status": status,
        "date": date,
        "title": "Test Source",
        "team": "platform",
        "project": "arkeology",
        "tier": tier,
        "visibility": visibility,
        "description": "A test source artifact.",
    }


_MALFORMED_S3_META: dict[str, str] = {
    "type": "synthesis",
    "team": "platform",
    "project": "arkeology",
    "tier": "3",
    "date": "2026-01-01",
    "status": "active",
    "title": "Malformed Synthesis",
    "visibility": "shared",
    "tags": "",
    "author_role": "",
    "description": "A synthesis with no source artifacts.",
    "source_artifacts": "",
}


# ---------------------------------------------------------------------------
# Helper: check whether a filter expression queries for a specific artifact_id
# ---------------------------------------------------------------------------


def _filter_matches_artifact_id(filter_expr: dict[str, Any], artifact_id: str) -> bool:
    """Return True iff filter_expr is a direct $eq lookup, or a batched $in lookup
    that includes, the given artifact_id (source lookups are batched into a single
    $in query rather than one $eq call per source)."""
    if "artifact_id" in filter_expr:
        clause = filter_expr["artifact_id"]
        if "$eq" in clause:
            return bool(clause["$eq"] == artifact_id)
        if "$in" in clause:
            return artifact_id in clause["$in"]
    if "$and" in filter_expr:
        return any(
            _filter_matches_artifact_id(clause, artifact_id) for clause in filter_expr["$and"]
        )
    return False


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


async def test_empty_state_no_synthesis_all_fresh(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """No synthesis artifacts in index → total_checked=0, all_fresh=True, all lists empty."""
    settings = _make_settings(monkeypatch)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["total_checked"] == 0
    assert result["all_fresh"] is True
    assert result["stale"] == []
    assert result["archived_sources"] == []
    assert result["missing_sources"] == []


# ---------------------------------------------------------------------------
# All-fresh state
# ---------------------------------------------------------------------------


async def test_all_fresh_two_sources_both_older_and_active(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """One synthesis, two sources both older than synthesis date, both active → all_fresh=True."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-all-fresh"
    src1_id = "artifacts/implementation-note-2026-01-01-source-a"
    src2_id = "artifacts/implementation-note-2026-02-01-source-b"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-06-01", [src1_id, src2_id]),
    )
    vectors_client_8.put_vector(src1_id, DUMMY_VEC, _source_meta(src1_id, "2026-01-01"))
    vectors_client_8.put_vector(src2_id, DUMMY_VEC, _source_meta(src2_id, "2026-02-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["all_fresh"] is True
    assert result["stale"] == []
    assert result["archived_sources"] == []


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


async def test_stale_source_newer_than_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis date 2026-01-01, source date 2026-06-01 → synthesis in stale."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-stale-by-date"
    src_id = "artifacts/implementation-note-2026-01-01-newer-source"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [src_id])
    )
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-06-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert synth_id in stale_ids
    stale_entry = next(e for e in result["stale"] if e["artifact_id"] == synth_id)
    assert src_id in stale_entry["stale_sources"]


async def test_stale_two_sources_only_newer_flagged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Two sources — one newer, one older than synthesis → only newer source in stale_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-partial-stale"
    newer_src = "artifacts/implementation-note-2026-01-01-newer"
    older_src = "artifacts/implementation-note-2026-01-01-older"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-03-01", [newer_src, older_src]),
    )
    vectors_client_8.put_vector(newer_src, DUMMY_VEC, _source_meta(newer_src, "2026-06-01"))
    vectors_client_8.put_vector(older_src, DUMMY_VEC, _source_meta(older_src, "2026-01-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None
    assert newer_src in stale_entry["stale_sources"]
    assert older_src not in stale_entry["stale_sources"]


async def test_stale_same_day_not_stale(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis date equals source date → NOT reported as stale."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-same-day"
    src_id = "artifacts/implementation-note-2026-03-15-same-day-src"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-03-15", [src_id])
    )
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-03-15"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert synth_id not in stale_ids


# ---------------------------------------------------------------------------
# Archived source detection
# ---------------------------------------------------------------------------


async def test_archived_source_flagged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis referencing source with status='inactive' → synthesis in archived_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-with-archived-source"
    src_id = "artifacts/adr-archived-decision"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", [src_id])
    )
    vectors_client_8.put_vector(
        src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01", status="inactive")
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    archived_ids = [e["artifact_id"] for e in result["archived_sources"]]
    assert synth_id in archived_ids
    archived_entry = next(e for e in result["archived_sources"] if e["artifact_id"] == synth_id)
    assert src_id in archived_entry["archived_sources"]


async def test_source_both_newer_and_archived_appears_in_both(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Source both newer AND archived → synthesis appears in both stale and archived_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-both-issues"
    src_id = "artifacts/adr-newer-and-archived"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [src_id])
    )
    vectors_client_8.put_vector(
        src_id, DUMMY_VEC, _source_meta(src_id, "2026-06-01", status="inactive")
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    archived_ids = [e["artifact_id"] for e in result["archived_sources"]]
    assert synth_id in stale_ids
    assert synth_id in archived_ids


# ---------------------------------------------------------------------------
# Missing source detection
# ---------------------------------------------------------------------------


async def test_missing_source_no_vector_entries(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis referencing source ID with no vector entries → source in missing_sources."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-with-missing-source"
    missing_src_id = "artifacts/nonexistent-source-xyz"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", [missing_src_id])
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    missing_entry = next(
        (e for e in result["missing_sources"] if e["artifact_id"] == synth_id), None
    )
    assert missing_entry is not None
    assert missing_src_id in missing_entry["missing_sources"]


async def test_missing_source_present_in_s3_but_no_vectors(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A source that exists in S3 but has NO vector index entries must still be reported
    missing (T22: 'a source ID returning no results from list_vectors_by_metadata SHALL be
    reported missing'), and freshness must perform NO S3 reads during the audit
    (T22: 'SHALL NOT fetch S3 content for freshness checks'). head_object must never be called.
    """
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-with-s3-only-source"
    s3_only_src_id = "artifacts/source-in-s3-not-indexed"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-06-01", [s3_only_src_id]),
    )

    # Simulate the source still existing in S3 (head_object would succeed) but absent from
    # the vector index. The old fallback would have read this and mis-classified it as present.
    head_spy = mocker.patch.object(
        s3_client, "head_object", return_value={"date": "2099-01-01", "status": "active"}
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    missing_entry = next(
        (e for e in result["missing_sources"] if e["artifact_id"] == synth_id), None
    )
    assert missing_entry is not None, "source absent from the index must be reported missing"
    assert s3_only_src_id in missing_entry["missing_sources"]
    assert head_spy.call_count == 0, "freshness must not read S3 (T22)"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def test_two_section_vectors_same_synthesis_counted_once(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Two section vectors for the same synthesis artifact_id → counted as one (total_checked=1)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-dedup-sections"
    src_id = "artifacts/implementation-note-2026-01-01-source"

    synth_meta = _synthesis_meta(synth_id, "2026-06-01", [src_id])
    vectors_client_8.put_vector(f"{synth_id}#overview", DUMMY_VEC, synth_meta)
    vectors_client_8.put_vector(f"{synth_id}#details", DUMMY_VEC, synth_meta)
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["total_checked"] == 1


async def test_same_source_referenced_by_two_syntheses_looked_up_once(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Same source referenced by two syntheses → list_vectors_by_metadata called once for that source."""  # noqa: E501
    settings = _make_settings(monkeypatch)
    synth1_id = "artifacts/synthesis-alpha"
    synth2_id = "artifacts/synthesis-beta"
    shared_src_id = "artifacts/implementation-note-2026-01-01-shared-source"

    vectors_client_8.put_vector(
        f"{synth1_id}#section", DUMMY_VEC, _synthesis_meta(synth1_id, "2026-06-01", [shared_src_id])
    )
    vectors_client_8.put_vector(
        f"{synth2_id}#section", DUMMY_VEC, _synthesis_meta(synth2_id, "2026-06-01", [shared_src_id])
    )
    vectors_client_8.put_vector(shared_src_id, DUMMY_VEC, _source_meta(shared_src_id, "2026-01-01"))

    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["total_checked"] == 2
    all_filter_calls = [call.args[0] for call in spy.call_args_list]
    source_specific_calls = [
        f for f in all_filter_calls if _filter_matches_artifact_id(f, shared_src_id)
    ]
    assert len(source_specific_calls) == 1


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


async def test_scope_gate_only_own_scope_synthesis_checked(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Fake has own-scope and foreign-scope synthesis vectors → total_checked is 1."""
    settings = _make_settings(monkeypatch)
    own_synth_id = "artifacts/synthesis-own-scope"
    foreign_synth_id = "other-team/synthesis-foreign-scope"
    src_id = "artifacts/implementation-note-2026-01-01-source"

    vectors_client_8.put_vector(
        f"{own_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(own_synth_id, "2026-06-01", [src_id], scope="artifacts"),
    )
    vectors_client_8.put_vector(
        f"{foreign_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(foreign_synth_id, "2026-06-01", [src_id], scope="other-team"),
    )
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["total_checked"] == 1


# ---------------------------------------------------------------------------
# Cross-scope gate on source lookups (non-negotiable rule)
# ---------------------------------------------------------------------------


async def test_cross_scope_gate_foreign_tier2_source_not_leaked(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A foreign tier-2 source is gated out: reported missing, never as stale/archived.

    Before the fix, freshness Step 6 looked up any source by bare artifact_id with no
    scope/tier/visibility gate — the exact non-negotiable-rule violation read_artifact
    and list_artifacts already guard against. A foreign tier-2 source that is newer
    than the synthesis AND archived must not leak its date/status: it must be
    classified inaccessible (== missing), not stale or archived.
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="other-team")
    synth_id = "artifacts/synthesis-foreign-tier2-source"
    foreign_src_id = "other-team/implementation-note-2026-01-01-foreign-tier2"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", [foreign_src_id]),
    )
    # Newer date (would be "stale") AND inactive (would be "archived") if leaked.
    vectors_client_8.put_vector(
        foreign_src_id,
        DUMMY_VEC,
        _source_meta(
            foreign_src_id,
            "2026-06-01",
            status="inactive",
            scope="other-team",
            tier=2,
            visibility="shared",
        ),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    archived_ids = [e["artifact_id"] for e in result["archived_sources"]]
    missing_entry = next(
        (e for e in result["missing_sources"] if e["artifact_id"] == synth_id), None
    )
    assert synth_id not in stale_ids, "foreign tier-2 source date must not be reported as stale"
    assert synth_id not in archived_ids, "foreign tier-2 source status must not be reported"
    assert missing_entry is not None, "gated-out foreign source must be classified missing"
    assert foreign_src_id in missing_entry["missing_sources"]


async def test_cross_scope_gate_foreign_tier3_shared_source_read_normally(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A foreign tier-3 'shared' source passes the gate and is read normally.

    Matches the same allowance as list.py: foreign + tier 3 + visibility=shared is
    the one case that must NOT be gated out.
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="other-team")
    synth_id = "artifacts/synthesis-foreign-tier3-shared-source"
    foreign_src_id = "other-team/adr-foreign-shared-decision"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", [foreign_src_id]),
    )
    vectors_client_8.put_vector(
        foreign_src_id,
        DUMMY_VEC,
        _source_meta(
            foreign_src_id,
            "2026-06-01",  # newer than synthesis → should be reported stale
            scope="other-team",
            tier=3,
            visibility="shared",
        ),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    missing_ids = [e["artifact_id"] for e in result["missing_sources"]]
    assert synth_id not in missing_ids, "foreign tier-3 shared source must not be missing"
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None, "foreign tier-3 shared source must be read normally"
    assert foreign_src_id in stale_entry["stale_sources"]


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_seven_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """All required fields always present in every non-error response."""
    settings = _make_settings(monkeypatch)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    required_fields = (
        "stale",
        "archived_sources",
        "missing_sources",
        "malformed",
        "deleted_malformed",
        "delete_failed",
        "total_checked",
        "all_fresh",
    )
    for field in required_fields:
        assert field in result, f"Missing required field '{field}' in response"


async def test_all_fresh_true_iff_all_issue_lists_empty(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """all_fresh is True iff stale, archived_sources, missing_sources, and malformed are all empty."""  # noqa: E501
    settings = _make_settings(monkeypatch)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    all_empty = (
        result["stale"] == []
        and result["archived_sources"] == []
        and result["missing_sources"] == []
        and result["malformed"] == []
    )
    assert result["all_fresh"] is all_empty


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_list_vectors_exception_returns_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Unexpected exception from list_vectors_by_metadata → {'error': 'internal_error', ...}."""
    settings = _make_settings(monkeypatch)
    mocker.patch.object(
        vectors_client_8,
        "list_vectors_by_metadata",
        side_effect=RuntimeError("Simulated unexpected failure in list_vectors_by_metadata"),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert result.get("error") == "internal_error"
    assert "message" in result


# ---------------------------------------------------------------------------
# Malformed synthesis — report only (confirm=False / default)
# ---------------------------------------------------------------------------


async def test_malformed_synthesis_no_confirm_reported_not_deleted(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis with empty source_artifacts, confirm=False → in malformed; NOT deleted."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-no-confirm"

    s3_client.put_object(synth_id, "Malformed synthesis content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=False
    )

    assert "error" not in result
    assert synth_id in result["malformed"]
    assert synth_id not in result["deleted_malformed"]
    # Artifact still exists in S3 and vectors
    assert synth_id in s3_client.list_objects("")
    vec_keys = vectors_client_8.list_vectors_by_metadata({"artifact_id": {"$eq": synth_id}})
    assert len(vec_keys) > 0


async def test_malformed_synthesis_makes_all_fresh_false(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis with empty source_artifacts → all_fresh is False."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-fresh-check"

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["all_fresh"] is False


# ---------------------------------------------------------------------------
# Malformed synthesis — deletion (confirm=True)
# ---------------------------------------------------------------------------


async def test_malformed_synthesis_confirm_true_deleted(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Synthesis with empty source_artifacts, confirm=True → in deleted_malformed; removed."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-to-delete"

    s3_client.put_object(synth_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert synth_id in result["deleted_malformed"]
    assert synth_id not in result["malformed"]
    assert synth_id not in s3_client.list_objects("")
    vec_keys = vectors_client_8.list_vectors_by_metadata({"artifact_id": {"$eq": synth_id}})
    assert len(vec_keys) == 0


async def test_malformed_and_stale_both_reported_in_same_response(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Two syntheses: one malformed, one valid with stale source → both issues in response."""
    settings = _make_settings(monkeypatch)
    malformed_id = "artifacts/synthesis-malformed-combined"
    stale_synth_id = "artifacts/synthesis-stale-combined"
    stale_src_id = "artifacts/implementation-note-2026-01-01-newer-combined"

    s3_client.put_object(malformed_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{malformed_id}#section", DUMMY_VEC, _synthesis_meta(malformed_id, "2026-01-01", [])
    )
    vectors_client_8.put_vector(
        f"{stale_synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(stale_synth_id, "2026-01-01", [stale_src_id]),
    )
    vectors_client_8.put_vector(stale_src_id, DUMMY_VEC, _source_meta(stale_src_id, "2026-06-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    stale_ids = [e["artifact_id"] for e in result["stale"]]
    assert malformed_id in result["deleted_malformed"]
    assert stale_synth_id in stale_ids
    vec_keys_stale = vectors_client_8.list_vectors_by_metadata(
        {"artifact_id": {"$eq": stale_synth_id}}
    )
    assert len(vec_keys_stale) > 0


async def test_malformed_deletion_vectors_before_s3(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Malformed synthesis deletion: delete_vectors is called before delete_object."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-order-check"
    call_order: list[str] = []

    original_delete_object = s3_client.delete_object
    original_delete_vectors = vectors_client_8.delete_vectors

    def track_delete_object(key: str) -> None:
        call_order.append(f"delete_object:{key}")
        return original_delete_object(key)

    def track_delete_vectors(keys: list[str]) -> None:
        call_order.append("delete_vectors")
        return original_delete_vectors(keys)

    mocker.patch.object(s3_client, "delete_object", side_effect=track_delete_object)
    mocker.patch.object(vectors_client_8, "delete_vectors", side_effect=track_delete_vectors)

    s3_client.put_object(synth_id, "Order check content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "delete_vectors" in call_order
    assert f"delete_object:{synth_id}" in call_order
    dv_idx = call_order.index("delete_vectors")
    do_idx = call_order.index(f"delete_object:{synth_id}")
    assert dv_idx < do_idx, (
        f"delete_vectors (index {dv_idx}) must be called before "
        f"delete_object (index {do_idx}); full order: {call_order}"
    )


async def test_confirm_true_all_malformed_all_fresh_true(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """One malformed synthesis, confirm=True → all_fresh is True after deletion."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-confirm-fresh"

    s3_client.put_object(synth_id, "Malformed synthesis content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert result["all_fresh"] is True
    assert synth_id in result["deleted_malformed"]
    assert result["malformed"] == []


# ---------------------------------------------------------------------------
# Spec 13 — CredentialError test coverage for freshness
# ---------------------------------------------------------------------------


async def test_credential_error_on_list_vectors_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """CredentialError from vectors.list_vectors_by_metadata → credential_error response."""
    settings = _make_settings(monkeypatch)
    mocker.patch.object(
        vectors_client_8,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert result.get("error") == "credential_error"


async def test_credential_error_on_s3_head_object_during_malformed_delete(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """During malformed-synthesis deletion (confirm=True) a CredentialError from
    s3.head_object → credential_error response. This is the ONLY freshness path that reads
    S3 (existence-confirm before delete); the source-metadata audit never reads S3 (T22).
    """
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-cred"
    # Malformed synthesis (no source_artifacts) → eligible for deletion when confirm=True.
    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        _synthesis_meta(synth_id, "2026-01-01", []),
    )
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# M14 — non-credential partial-delete: report in delete_failed and continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_credential_s3_delete_error_continues_and_reports_failed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Non-credential s3.delete_object error → artifact in delete_failed; loop continues.

    The second malformed synthesis must still be deleted even when the first S3 delete
    raises a non-credential error.  Before the fix the exception propagated and aborted
    the entire audit (T22 Boundary: 'report in failed and continue').
    """
    settings = _make_settings(monkeypatch)
    synth_a = "artifacts/synthesis-malformed-fail-a"
    synth_b = "artifacts/synthesis-malformed-fail-b"

    for sid in (synth_a, synth_b):
        s3_client.put_object(sid, "Malformed content.", {**_MALFORMED_S3_META})
        vectors_client_8.put_vector(
            f"{sid}#section", DUMMY_VEC, _synthesis_meta(sid, "2026-01-01", [])
        )

    original_delete = s3_client.delete_object

    def failing_delete(key: str) -> None:
        if key == synth_a:
            raise RuntimeError("simulated S3 delete failure")
        original_delete(key)

    mocker.patch.object(s3_client, "delete_object", side_effect=failing_delete)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert synth_a in result.get("delete_failed", []), (
        f"synth_a should be in delete_failed: {result}"
    )
    assert synth_b in result.get("deleted_malformed", []), (
        f"synth_b should be in deleted_malformed: {result}"
    )
    assert synth_a not in result.get("deleted_malformed", [])


@pytest.mark.asyncio
async def test_non_credential_vector_delete_error_reports_failed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Non-credential vectors.delete_vectors error → artifact in delete_failed, not deleted."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-vec-fail"

    s3_client.put_object(synth_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    mocker.patch.object(
        vectors_client_8,
        "delete_vectors",
        side_effect=RuntimeError("simulated vector delete failure"),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert synth_id in result.get("delete_failed", []), (
        f"synth_id should be in delete_failed: {result}"
    )
    assert synth_id not in result.get("deleted_malformed", [])


@pytest.mark.asyncio
async def test_delete_failed_makes_all_fresh_false(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A malformed synthesis whose vector deletion succeeds but whose S3 delete_object
    fails (J-2) must yield all_fresh=False, even though malformed is empty and the
    artifact is absent from malformed and present in delete_failed instead."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-delete-failed-fresh-check"

    s3_client.put_object(synth_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )

    mocker.patch.object(
        s3_client,
        "delete_object",
        side_effect=RuntimeError("simulated S3 delete failure"),
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert synth_id in result["delete_failed"]
    assert synth_id not in result["malformed"]
    assert result["malformed"] == []
    assert result["all_fresh"] is False, (
        f"all_fresh must be False when delete_failed is non-empty: {result}"
    )


@pytest.mark.asyncio
async def test_delete_failed_always_present_in_response(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """delete_failed field is always present in a non-error response (even when empty)."""
    settings = _make_settings(monkeypatch)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert "delete_failed" in result, f"delete_failed missing from response: {result}"
    assert result["delete_failed"] == []


# ---------------------------------------------------------------------------
# check_synthesis_freshness's blocking client calls are offloaded off the
# event loop
# ---------------------------------------------------------------------------


async def test_freshness_vector_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata and get_vectors execute on a worker thread, never on
    the calling event-loop thread, during a plain audit (confirm=False)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-off-loop"
    src_id = "artifacts/implementation-note-2026-01-01-off-loop"
    s3_client.put_object(synth_id, "Synthesis content.", {})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [src_id])
    )
    vectors_client_8.put_vector(f"{src_id}#section", DUMMY_VEC, _source_meta(src_id, "2026-01-01"))
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_list = vectors_client_8.list_vectors_by_metadata
    original_get_vectors = vectors_client_8.get_vectors

    def spy_list(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_list(*args, **kwargs)

    def spy_get_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_get_vectors(*args, **kwargs)

    mocker.patch.object(vectors_client_8, "list_vectors_by_metadata", side_effect=spy_list)
    mocker.patch.object(vectors_client_8, "get_vectors", side_effect=spy_get_vectors)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert seen_threads, "list_vectors_by_metadata/get_vectors were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "Vector calls ran on the event-loop thread — they must be offloaded"
    )


async def test_freshness_malformed_deletion_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """During malformed-synthesis deletion (confirm=True), delete_vectors, head_object,
    and delete_object all execute on a worker thread, never on the calling event-loop
    thread."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-malformed-off-loop"
    s3_client.put_object(synth_id, "Malformed content.", {**_MALFORMED_S3_META})
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-01-01", [])
    )
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_delete_vectors = vectors_client_8.delete_vectors
    original_head_object = s3_client.head_object
    original_delete_object = s3_client.delete_object

    def spy_delete_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_delete_vectors(*args, **kwargs)

    def spy_head_object(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_head_object(*args, **kwargs)

    def spy_delete_object(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_delete_object(*args, **kwargs)

    mocker.patch.object(vectors_client_8, "delete_vectors", side_effect=spy_delete_vectors)
    mocker.patch.object(s3_client, "head_object", side_effect=spy_head_object)
    mocker.patch.object(s3_client, "delete_object", side_effect=spy_delete_object)

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert "error" not in result
    assert synth_id in result["deleted_malformed"]
    assert seen_threads, "delete_vectors/head_object/delete_object were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "Deletion calls ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# Source lookups must be batched, not one query per unique source
# ---------------------------------------------------------------------------


async def test_freshness_multiple_distinct_sources_batches_lookup_not_one_per_source(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """check_synthesis_freshness must resolve all distinct source artifact ids across
    every synthesis with a bounded, batched vector-metadata query (mirroring list.py's
    cross-scope batching pattern via a single $in filter), not one
    list_vectors_by_metadata call per unique source_id (1+N queries)."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-multi-source"
    src_ids = [f"artifacts/implementation-note-2026-01-0{i}-source" for i in range(1, 4)]

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", src_ids)
    )
    for i, src_id in enumerate(src_ids, start=1):
        vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, f"2026-01-0{i}"))

    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert spy.call_count <= 2, (
        "Expected source lookups to be batched into a bounded number of "
        "list_vectors_by_metadata calls (one for synthesis discovery, one batched "
        f"$in query for all distinct sources) — got {spy.call_count} calls, "
        "indicating one query per unique source_id (1+N) rather than a single "
        "batched lookup"
    )


# ---------------------------------------------------------------------------
# Staleness by write recency (last_edited_ulid)
# ---------------------------------------------------------------------------

# Two ULIDs whose only requirement here is lexicographic order — a ULID's leading
# 48 bits are its write timestamp, so ordering them orders the writes.
_OLDER_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_NEWER_ULID = "01BRZ3NDEKTSV4RRFFQ69G5FAV"


async def test_stale_source_edited_after_synthesis_on_the_same_date(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A tier-3 source overwritten in place after the synthesis was built, on the same
    calendar date, is stale: its write is newer even though its date did not move.
    Comparing dates alone never reports it, so the synthesis silently describes content
    that no longer exists."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-same-date-newer-write"
    src_id = "artifacts/implementation-note-same-date-newer-write"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        {**_synthesis_meta(synth_id, "2026-03-15", [src_id]), "last_edited_ulid": _OLDER_ULID},
    )
    vectors_client_8.put_vector(
        src_id,
        DUMMY_VEC,
        {**_source_meta(src_id, "2026-03-15", tier=3), "last_edited_ulid": _NEWER_ULID},
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None
    assert src_id in stale_entry["stale_sources"]


async def test_source_written_before_synthesis_is_not_stale_despite_a_later_date(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A source carrying a later calendar date but written *before* the synthesis was
    already included in it, so it is not stale. The date is the artifact's subject date,
    not its write time; treating it as write time reports a synthesis that is perfectly
    current."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-later-dated-source"
    src_id = "artifacts/implementation-note-later-dated-source"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        {**_synthesis_meta(synth_id, "2026-01-01", [src_id]), "last_edited_ulid": _NEWER_ULID},
    )
    vectors_client_8.put_vector(
        src_id,
        DUMMY_VEC,
        {**_source_meta(src_id, "2026-06-01"), "last_edited_ulid": _OLDER_ULID},
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert synth_id not in [e["artifact_id"] for e in result["stale"]]


async def test_stale_falls_back_to_date_when_a_source_has_no_write_ulid(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """An artifact written before write ULIDs were recorded has none, so it cannot be
    compared by write recency. Staleness falls back to the dates rather than silently
    reporting every such source as fresh."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-ulid-fallback"
    src_id = "artifacts/implementation-note-ulid-fallback"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        {**_synthesis_meta(synth_id, "2026-01-01", [src_id]), "last_edited_ulid": _NEWER_ULID},
    )
    # No last_edited_ulid on the source at all.
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-06-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None
    assert src_id in stale_entry["stale_sources"]


# ---------------------------------------------------------------------------
# Source lookup filter size
# ---------------------------------------------------------------------------


async def test_source_lookup_chunks_the_in_filter_within_the_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """S3 Vectors rejects an oversized metadata-filter expression, so the source lookup
    must chunk its $in list to the same byte budget the search re-fetch loop bounds its
    $nin list to. A synthesis with enough sources to blow the budget must still resolve
    every one of them rather than failing the whole audit."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-many-sources"
    src_ids = [f"artifacts/implementation-note-2026-01-01-bulk-source-{i:03d}" for i in range(60)]

    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", src_ids)
    )
    for src_id in src_ids:
        vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    spy = mocker.spy(vectors_client_8, "list_vectors_by_metadata")

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["missing_sources"] == []
    in_lists = [
        call.args[0]["artifact_id"]["$in"]
        for call in spy.call_args_list
        if isinstance(call.args[0].get("artifact_id"), dict)
        and "$in" in call.args[0]["artifact_id"]
    ]
    assert in_lists, "the source lookup issued no $in filter at all"
    assert sum(len(chunk) for chunk in in_lists) >= len(src_ids)
    for chunk in in_lists:
        size = len(json.dumps(chunk).encode("utf-8"))
        assert size <= _NIN_EXCLUSION_BYTE_BUDGET, (
            f"an $in list of {size} bytes exceeds the filter-expression budget "
            f"of {_NIN_EXCLUSION_BYTE_BUDGET}"
        )


# ---------------------------------------------------------------------------
# T74.5 — a multi-section artifact is compared on its newest write, not an arbitrary one
# ---------------------------------------------------------------------------

_MIDDLE_ULID = "01AZZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize("stale_vector_first", [True, False])
async def test_stale_uses_the_newest_ulid_across_a_sources_vectors(
    stale_vector_first: bool,
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A source whose vectors disagree about ``last_edited_ulid`` is compared on the
    newest of them.

    After a partial overwrite whose stale-vector cleanup failed, one artifact carries
    vectors written under two different ULIDs. "First occurrence wins" then picks
    whichever the index happens to return first: land on the old one and the source
    reads as older than the synthesis, so real staleness is masked until a reconcile
    prunes the orphans. The newest write is the source's write recency, whatever order
    the query returns — which is why this runs both orders.
    """
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-multi-ulid-source"
    src_id = "artifacts/implementation-note-multi-ulid-source"

    vectors_client_8.put_vector(
        f"{synth_id}#section",
        DUMMY_VEC,
        {**_synthesis_meta(synth_id, "2026-03-15", [src_id]), "last_edited_ulid": _MIDDLE_ULID},
    )
    ordered_ulids = [_OLDER_ULID, _NEWER_ULID] if stale_vector_first else [_NEWER_ULID, _OLDER_ULID]
    for index, ulid in enumerate(ordered_ulids):
        vectors_client_8.put_vector(
            f"{src_id}#section-{index}",
            DUMMY_VEC,
            {**_source_meta(src_id, "2026-03-15"), "last_edited_ulid": ulid},
        )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    stale_entry = next((e for e in result["stale"] if e["artifact_id"] == synth_id), None)
    assert stale_entry is not None, (
        "the source's newest write is later than the synthesis, so the synthesis is stale"
    )
    assert src_id in stale_entry["stale_sources"]


@pytest.mark.parametrize("stale_vector_first", [True, False])
async def test_stale_uses_the_newest_ulid_across_a_syntheses_vectors(
    stale_vector_first: bool,
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A synthesis whose vectors disagree about ``last_edited_ulid`` is compared on the
    newest of them.

    The mirror of the source-side case, failing the other direction: pick the older of a
    synthesis's own vectors and a source written *before* the synthesis reads as written
    after it, reporting a synthesis that is genuinely current as stale. Both halves of
    the dedup need the same rule, so this runs both query orders too.
    """
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-multi-ulid-synthesis"
    src_id = "artifacts/implementation-note-source-of-multi-ulid-synthesis"

    ordered_ulids = [_OLDER_ULID, _NEWER_ULID] if stale_vector_first else [_NEWER_ULID, _OLDER_ULID]
    for index, ulid in enumerate(ordered_ulids):
        vectors_client_8.put_vector(
            f"{synth_id}#section-{index}",
            DUMMY_VEC,
            {**_synthesis_meta(synth_id, "2026-03-15", [src_id]), "last_edited_ulid": ulid},
        )
    vectors_client_8.put_vector(
        f"{src_id}#section",
        DUMMY_VEC,
        {**_source_meta(src_id, "2026-03-15"), "last_edited_ulid": _MIDDLE_ULID},
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert all(entry["artifact_id"] != synth_id for entry in result["stale"]), (
        "the synthesis's newest write is later than the source, so it is not stale"
    )


# ---------------------------------------------------------------------------
# A malformed synthesis record is skipped and counted, never fatal
# ---------------------------------------------------------------------------


def _unreadable_synthesis_meta() -> dict[str, Any]:
    """A synthesis vector with no usable ``artifact_id`` — the field the audit is keyed
    on, so the record cannot be audited, deduplicated, or reported at all."""
    meta = _synthesis_meta("artifacts/placeholder", "2026-06-01", ["artifacts/src"])
    del meta["artifact_id"]
    return meta


async def test_freshness_skips_an_unreadable_synthesis_and_audits_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """One unreadable record must not withhold the whole audit.

    Without the skip, indexing ``artifact_id`` raises, escapes to the catch-all, and the
    caller gets ``internal_error`` — learning nothing about any synthesis, not just the
    broken one.
    """
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-readable"
    src_id = "artifacts/implementation-note-2026-01-01-src"
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", [src_id])
    )
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))
    vectors_client_8.put_vector(
        "artifacts/unreadable#section", DUMMY_VEC, _unreadable_synthesis_meta()
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "error" not in result
    assert result["skipped_malformed_count"] == 1
    assert result["total_checked"] == 1, "a skipped record is not a synthesis that was audited"


async def test_freshness_skipped_record_denies_the_all_fresh_verdict(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A run that could not audit part of its input has not established that everything
    is fresh. ``all_fresh: True`` beside a non-zero skip count would be exactly the
    partial-result-that-looks-complete failure this key exists to prevent."""
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/unreadable#section", DUMMY_VEC, _unreadable_synthesis_meta()
    )

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert result["skipped_malformed_count"] == 1
    assert result["all_fresh"] is False


async def test_freshness_omits_the_skip_count_when_nothing_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """A ninth, conditional key: it does not join the eight a caller may read without a
    membership test, so it is absent rather than zero."""
    settings = _make_settings(monkeypatch)
    synth_id = "artifacts/synthesis-clean"
    src_id = "artifacts/implementation-note-2026-01-01-clean-src"
    vectors_client_8.put_vector(
        f"{synth_id}#section", DUMMY_VEC, _synthesis_meta(synth_id, "2026-06-01", [src_id])
    )
    vectors_client_8.put_vector(src_id, DUMMY_VEC, _source_meta(src_id, "2026-01-01"))

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8
    )

    assert "skipped_malformed_count" not in result
    assert result["all_fresh"] is True


async def test_freshness_never_deletes_a_skipped_record(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """``skipped_malformed_count`` and ``malformed`` name different conditions and must
    not be read as a pair. ``malformed`` lists syntheses audited successfully and found
    structurally invalid — the deletion candidates. A record too corrupt to identify is
    the last thing to hard-delete on, at any ``confirm`` value.
    """
    settings = _make_settings(monkeypatch)
    vectors_client_8.put_vector(
        "artifacts/unreadable#section", DUMMY_VEC, _unreadable_synthesis_meta()
    )
    delete_vectors = mocker.spy(vectors_client_8, "delete_vectors")
    delete_object = mocker.spy(s3_client, "delete_object")

    result = await check_synthesis_freshness(
        settings=settings, s3=s3_client, vectors=vectors_client_8, confirm=True
    )

    assert result["skipped_malformed_count"] == 1
    assert result["deleted_malformed"] == []
    assert delete_vectors.call_count == 0
    assert delete_object.call_count == 0

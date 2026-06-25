"""Unit tests for cairn_mcp.tools.freshness.

Tests check_synthesis_freshness() using moto-backed S3ClientImpl + VectorsClientImpl.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.freshness import check_synthesis_freshness
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
        "project": "cairn",
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
        "project": "cairn",
        "tier": 2,
        "visibility": "shared",
        "description": "A test source artifact.",
    }


_MALFORMED_S3_META: dict[str, str] = {
    "type": "synthesis",
    "team": "platform",
    "project": "cairn",
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
    """Return True iff filter_expr is a direct $eq lookup for the given artifact_id."""
    if "artifact_id" in filter_expr:
        eq_val = filter_expr["artifact_id"].get("$eq")
        return eq_val == artifact_id
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
# Response structure
# ---------------------------------------------------------------------------


async def test_response_always_has_all_seven_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """All 7 fields always present in every non-error response."""
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

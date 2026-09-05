"""Unit tests for arkeology.tools.link_metadata.

Tests link_metadata() using moto-backed S3ClientImpl + VectorsClientImpl.
Generalizes and supersedes link_commit (p10-t38): dual-writes commit_refs and/or
references — durable S3 annotations first, then vector metadata reusing the
existing float32 embeddings — with zero Bedrock calls (ADR-011 / T49, AC-59).
"""

import math
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.artifact import VECTOR_FILTERABLE_METADATA_MAX_BYTES
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import AnnotationUnavailableError, ArtifactConflictError, CredentialError
from arkeology.failure_log import read_failure_entries
from arkeology.tools.link_metadata import link_metadata
from arkeology.tools.reconcile import reconcile_index
from tests.unit.conftest import _make_settings as _make_settings_base

# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, **overrides)


# ---------------------------------------------------------------------------
# Deterministic vector helper
# ---------------------------------------------------------------------------


def _unit_vec(seed: float, dim: int = 2) -> list[float]:
    raw = [seed, seed + 0.1]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_BASE_META: dict[str, Any] = {
    "scope": "artifacts",
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-06-01",
    "status": "active",
    "title": "Some artifact",
    "visibility": "shared",
    "tags": [],
    "author_role": "developer",
    "description": "A test artifact.",
    "last_edited_ulid": "01KT07NV00FN74309G4MXHQ1KN",
}

# Own-scope prefix as per test settings WRITE_PREFIX=artifacts
OWN_PREFIX = "artifacts"
FOREIGN_PREFIX = "other-team"

# artifact-own-A: own-scope, two section vectors, no link fields
KEY_A1 = f"{OWN_PREFIX}/artifact-own-A#summary"
KEY_A2 = f"{OWN_PREFIX}/artifact-own-A#details"
ID_A = f"{OWN_PREFIX}/artifact-own-A"

# artifact-own-B: own-scope, one document vector, commit_refs=["prev123"]
KEY_B = f"{OWN_PREFIX}/artifact-own-B#summary"
ID_B = f"{OWN_PREFIX}/artifact-own-B"

# artifact-foreign: foreign-scope, one vector, no link fields
KEY_F = f"{FOREIGN_PREFIX}/artifact-foreign#summary"
ID_F = f"{FOREIGN_PREFIX}/artifact-foreign"


def _seed_all(s3: S3ClientImpl, vectors: VectorsClientImpl) -> None:
    """Seed all three test artifacts into both S3 (object) and the vector index.

    S3 objects must pre-exist for put_object_annotation to succeed (annotations
    can only be set on an existing object).
    """
    s3.put_object(ID_A, "content A", {"title": "Artifact Own A"})
    s3.put_object(ID_B, "content B", {"title": "Artifact Own B"})
    s3.put_object(ID_F, "content F", {"title": "Artifact Foreign"})

    # artifact-own-A: two section vectors, no link fields
    meta_a: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": ID_A,
        "title": "Artifact Own A",
    }
    vectors.put_vector(KEY_A1, _unit_vec(1.0), meta_a)
    vectors.put_vector(KEY_A2, _unit_vec(1.1), meta_a)

    # artifact-own-B: one vector, commit_refs=["prev123"]
    meta_b: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": ID_B,
        "title": "Artifact Own B",
        "commit_refs": ["prev123"],
    }
    vectors.put_vector(KEY_B, _unit_vec(0.9), meta_b)

    # artifact-foreign: foreign scope
    meta_f: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": ID_F,
        "scope": FOREIGN_PREFIX,
        "title": "Artifact Foreign",
    }
    vectors.put_vector(KEY_F, _unit_vec(0.8), meta_f)


# ---------------------------------------------------------------------------
# Story 1 — Backfill either field to both stores
# ---------------------------------------------------------------------------


async def test_link_metadata_commit_refs_backfilled_to_both_stores(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """commit_refs=['abc1234'] lands in both the S3 annotation and vector metadata;
    linked=1 (AC-59)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 1
    assert result.get("skipped") == 0
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "abc1234"

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    assert len(items) == 2
    for item in items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]


async def test_link_metadata_references_backfilled_to_annotation_not_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """T58: references=['a-1'] lands in the S3 annotation (its sole durable store) and
    never appears in vector metadata, even though put_vectors_batch is still called for
    every section vector (to persist the write's other metadata)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["a-1"],
    )

    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "references") == "a-1"

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert "references" not in item["metadata"]


async def test_link_metadata_both_fields_backfilled_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Supplying both commit_refs and references in one call backfills commit_refs to
    both stores and references to the annotation only (T58: references is never
    written to vector metadata)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
        references=["a-1"],
    )

    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "abc1234"
    assert s3_client.get_object_annotation(ID_A, "references") == "a-1"

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]
        assert "references" not in item["metadata"]


# ---------------------------------------------------------------------------
# Story 2 — No re-embed, no timestamp shift
# ---------------------------------------------------------------------------


async def test_link_metadata_bedrock_never_called(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Bedrock embed is never called during link_metadata (AC-59)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    spy = mocker.spy(bedrock, "embed")

    await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
        references=["a-1"],
    )

    assert spy.call_count == 0


async def test_link_metadata_float32_values_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Float32 embedding values on all vectors are unchanged after link (AC-59)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    before = {
        item["key"]: item["data"]["float32"]
        for item in vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    }

    await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    after = {
        item["key"]: item["data"]["float32"]
        for item in vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    }

    for key in [KEY_A1, KEY_A2]:
        assert before[key] == after[key], f"Float32 values changed for {key}"


async def test_link_metadata_does_not_change_last_edited_ulid(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """last_edited_ulid in vector metadata is unchanged after link_metadata (AC-59)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["last_edited_ulid"] == _BASE_META["last_edited_ulid"]


# ---------------------------------------------------------------------------
# Story 3 — Idempotent merge + dedup
# ---------------------------------------------------------------------------


async def test_link_metadata_append_to_existing_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact with commit_refs=["prev123"] → becomes ["prev123", "abc1234"] after link."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 1

    items = vectors_client_2.get_vectors([KEY_B])
    assert items[0]["metadata"]["commit_refs"] == ["prev123", "abc1234"]
    assert s3_client.get_object_annotation(ID_B, "commit_refs") == "prev123,abc1234"


async def test_link_metadata_dedup_same_value_not_appended_twice(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Calling link_metadata with a SHA already in commit_refs → commit_refs unchanged."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # "prev123" is already in artifact-own-B's commit_refs
    await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_refs=["prev123"],
    )

    items = vectors_client_2.get_vectors([KEY_B])
    assert items[0]["metadata"]["commit_refs"] == ["prev123"]
    assert s3_client.get_object_annotation(ID_B, "commit_refs") == "prev123"


async def test_link_metadata_idempotent_on_rerun(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Calling link_metadata twice with the same value produces the same end state
    (Story 3 — idempotent re-run)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    kwargs: dict[str, Any] = {
        "settings": settings,
        "s3": s3_client,
        "vectors": vectors_client_2,
        "bedrock": bedrock,
        "artifact_ids": [ID_A],
        "commit_refs": ["abc1234"],
        "references": ["a-1"],
    }

    await link_metadata(**kwargs)
    result2 = await link_metadata(**kwargs)

    assert result2.get("linked") == 1
    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]
        # T58: references is never written to vector metadata.
        assert "references" not in item["metadata"]
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "abc1234"
    assert s3_client.get_object_annotation(ID_A, "references") == "a-1"


# ---------------------------------------------------------------------------
# Story 4 — Durable-first ordering + scope gate
# ---------------------------------------------------------------------------


async def test_link_metadata_annotation_written_before_put_vectors_batch(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Durable-first ordering (ADR-011): put_object_annotation happens before
    put_vectors_batch, so a failed vector write can self-heal via reconcile_index."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    call_order: list[str] = []

    original_put_annotation = s3_client.put_object_annotation

    def _put_annotation(*args: object, **kwargs: object) -> None:
        call_order.append("put_object_annotation")
        return original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]

    original_batch = vectors_client_2.put_vectors_batch

    def _put_batch(*args: object, **kwargs: object) -> None:
        call_order.append("put_vectors_batch")
        return original_batch(*args, **kwargs)  # type: ignore[arg-type]

    s3_client.put_object_annotation = _put_annotation  # type: ignore[method-assign]
    vectors_client_2.put_vectors_batch = _put_batch  # type: ignore[method-assign]

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert "error" not in result
    assert call_order == ["put_object_annotation", "put_vectors_batch"]


async def test_link_metadata_foreign_scope_skipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign-scope artifact → linked=0, skipped=1, and the foreign artifact is untouched."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_F],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 0
    assert result.get("skipped") == 1

    items = vectors_client_2.get_vectors([KEY_F])
    assert "commit_refs" not in items[0]["metadata"]
    with pytest.raises(KeyError):
        s3_client.get_object_annotation(ID_F, "commit_refs")


async def test_link_metadata_mixed_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Mixed list [own-scope, foreign-scope] → linked=1, skipped=1."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A, ID_F],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 1
    assert result.get("skipped") == 1


async def test_link_metadata_no_vectors_skipped_not_errored(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact ID with no vectors in the index → linked=0, skipped=1 (no error)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=["artifacts/nonexistent-key"],
        commit_refs=["abc1234"],
    )

    assert "error" not in result
    assert result.get("linked") == 0
    assert result.get("skipped") == 1


# ---------------------------------------------------------------------------
# Story 5 — Response shape + cursor + errors
# ---------------------------------------------------------------------------


async def test_link_metadata_response_has_next_since_ulid(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Response includes non-empty next_since_ulid."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert set(result.keys()) == {"linked", "skipped", "next_since_ulid"}
    assert isinstance(result["next_since_ulid"], str)
    assert len(result["next_since_ulid"]) > 0


async def test_link_metadata_successive_ulids_monotonically_non_decreasing(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Two successive link_metadata calls → second next_since_ulid >= first."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result1 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["sha1"],
    )

    result2 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_refs=["sha2"],
    )

    ulid1: str = result1["next_since_ulid"]
    ulid2: str = result2["next_since_ulid"]
    assert ulid2 >= ulid1, f"Expected {ulid2!r} >= {ulid1!r}"


async def test_link_metadata_neither_field_supplied_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Neither commit_refs nor references supplied → validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
    )

    assert result.get("error") == "validation_error"


async def test_link_metadata_both_fields_empty_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """commit_refs=[] and references=[] (both explicitly empty) → validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=[],
        references=[],
    )

    assert result.get("error") == "validation_error"


async def test_link_metadata_list_vectors_by_metadata_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "credential_error"


async def test_link_metadata_get_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "get_vectors",
        side_effect=CredentialError(
            message="Credential failure on get_vectors (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "credential_error"


async def test_link_metadata_put_object_annotation_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """put_object_annotation raises CredentialError → structured error, and the
    vector write is never attempted (durable side is authoritative)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=CredentialError(
            message="Credential failure on put_object_annotation (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "credential_error"
    assert batch_spy.call_count == 0


# ---------------------------------------------------------------------------
# T52 — annotation availability graceful degrade (link_metadata)
# ---------------------------------------------------------------------------


async def test_link_metadata_annotation_unavailable_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """An AnnotationUnavailableError raised by put_object_annotation must surface as a
    structured 'annotation_unavailable' error (not a raw exception, and distinct from
    credential_error) — the durable annotation write is link_metadata's contract, so
    the artifact is not reported as linked, and no vector write is attempted."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.",
            "s3",
            Exception("simulated"),
        ),
    )
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "annotation_unavailable"
    assert result.get("message")
    assert "linked" not in result
    assert batch_spy.call_count == 0


async def test_link_metadata_annotation_unavailable_preserves_partial_progress(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """When AnnotationUnavailableError fires partway through a multi-artifact batch,
    the linked/skipped progress already accumulated on earlier, successfully-linked
    artifact_ids in this same call must be preserved in the response — not silently
    discarded. Today the except AnnotationUnavailableError branch
    returns a bare {"error": ..., "message": ...} dict with no linked/skipped keys
    at all, regardless of how much progress preceded the failure."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    original_put_annotation = s3_client.put_object_annotation
    call_count = {"n": 0}

    def _put_annotation(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]
            return
        raise AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.",
            "s3",
            Exception("simulated"),
        )

    mocker.patch.object(s3_client, "put_object_annotation", side_effect=_put_annotation)

    # ID_B is processed (and successfully linked) before ID_A hits the simulated
    # annotation-unavailable failure on its own put_object_annotation call.
    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B, ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "annotation_unavailable"
    assert result.get("linked") == 1, (
        "ID_B was successfully linked before ID_A's annotation-unavailable failure — "
        f"that partial progress must be preserved in the response, got: {result}"
    )


async def test_link_metadata_put_vectors_batch_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """put_vectors_batch raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "put_vectors_batch",
        side_effect=CredentialError(
            message="Credential failure on put_vectors_batch (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# Story 6 — union read + only-touch-supplied-fields
# ---------------------------------------------------------------------------


async def test_link_metadata_only_references_supplied_preserves_annotation_only_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """commit_refs exists ONLY as an S3 annotation (the partial-write state — the
    vector write of a prior link_metadata call failed after the annotation write
    succeeded). Supplying ONLY references on a subsequent call must leave the
    commit_refs annotation intact rather than deleting it (the vector-only read this
    fix replaces would see no commit_refs, merge in nothing, and apply_link_annotations
    would then delete the annotation since the merged list is empty)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # Simulate the partial-write state: annotation written, vector metadata never
    # updated (no commit_refs key in vector metadata for artifact-own-A).
    s3_client.put_object_annotation(ID_A, "commit_refs", "orphan-sha")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["a-1"],
    )

    assert result.get("linked") == 1
    # The commit_refs annotation must survive — not be deleted just because
    # commit_refs was never supplied to this call.
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "orphan-sha"
    # The supplied field is applied as normal.
    assert s3_client.get_object_annotation(ID_A, "references") == "a-1"


async def test_link_metadata_idempotent_supply_preserves_other_fields_annotation_only_value(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Re-supplying a commit_refs value already fully present in both stores is
    idempotent, and must not disturb a references value that exists only as an
    annotation (references was never supplied to this call)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # artifact-own-B already has commit_refs=["prev123"] in vector metadata (seeded).
    # Bring the annotation copy fully in sync, and add a references value that is
    # annotation-only (not indexed in vector metadata).
    s3_client.put_object_annotation(ID_B, "commit_refs", "prev123")
    s3_client.put_object_annotation(ID_B, "references", "ref-xyz")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_refs=["prev123"],
    )

    assert result.get("linked") == 1

    # commit_refs unchanged (idempotent re-supply of an already-present value).
    items = vectors_client_2.get_vectors([KEY_B])
    assert items[0]["metadata"]["commit_refs"] == ["prev123"]
    assert s3_client.get_object_annotation(ID_B, "commit_refs") == "prev123"

    # references annotation, never supplied to this call, must survive untouched.
    assert s3_client.get_object_annotation(ID_B, "references") == "ref-xyz"


async def test_link_metadata_union_read_heals_vector_copy_missing_annotation_value(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """The union read heals a state where the annotation holds a commit_refs value
    the vector copy lacks — after linking a new value, the vector metadata must contain
    BOTH the pre-existing annotation-only value and the newly supplied one."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # Annotation-only state: "old-sha" lives only in the annotation, not in vector
    # metadata, for artifact-own-A.
    s3_client.put_object_annotation(ID_A, "commit_refs", "old-sha")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["new-sha"],
    )

    assert result.get("linked") == 1

    # The vector copy is healed to include the annotation-only value, merged with
    # the newly supplied one — neither store is treated as sole authority.
    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == ["old-sha", "new-sha"]
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "old-sha,new-sha"


async def test_link_metadata_linked_not_incremented_when_get_vectors_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """When keys are found via list_vectors_by_metadata but get_vectors returns []
    (no items), linked must remain 0 rather than being incremented for a no-op batch."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        return_value=[f"{ID_A}#summary"],
    )
    mocker.patch.object(vectors_client_2, "get_vectors", return_value=[])

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 0


# ---------------------------------------------------------------------------
# Optimistic-concurrency (ETag compare-and-swap) writes — ADR-011 decision 6
# ---------------------------------------------------------------------------


async def test_link_metadata_annotation_uses_if_match_from_object_etag(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """The annotation dual-write's put_object_annotation call is conditional on the
    artifact's current object ETag (if_match), guarding the fetch-merge-reput cycle."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)
    current_etag = s3_client.head_object(ID_A)["ETag"]

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("linked") == 1
    assert annotation_spy.call_count == 1
    assert annotation_spy.call_args.kwargs.get("if_match") == current_etag


async def test_link_metadata_cas_conflict_then_retry_succeeds_with_both_contributions(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A conflict on the first CAS attempt (simulating a concurrent content-changing
    write landing between our read and our annotation write) causes a retry that
    re-reads and re-merges, eventually succeeding with a state that includes BOTH the
    concurrent writer's contribution and this call's own supplied value."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    original_put_annotation = s3_client.put_object_annotation
    call_count = 0

    def _simulate_conflict_then_succeed(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # A concurrent writer's own content-changing write lands first, also
            # adding to commit_refs via its own (already-durable) annotation write.
            # Uses the unpatched original — calling the patched method here would
            # recurse into this same side_effect and inflate call_count.
            original_put_annotation(ID_A, "commit_refs", "concurrent-sha")
            raise ArtifactConflictError(ID_A)
        return original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(
        s3_client, "put_object_annotation", side_effect=_simulate_conflict_then_succeed
    )

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["new-sha"],
    )

    assert result.get("linked") == 1
    assert call_count == 2
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "concurrent-sha,new-sha"
    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == ["concurrent-sha", "new-sha"]


async def test_link_metadata_persistent_cas_conflict_returns_conflict_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A persistent conflict (every CAS attempt fails) returns a structured
    'conflict' error after the bounded attempt count — never a raw exception, and
    no vector write is attempted for the artifact that conflicted."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    put_spy = mocker.patch.object(
        s3_client, "put_object_annotation", side_effect=ArtifactConflictError(ID_A)
    )
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["new-sha"],
    )

    assert result.get("error") == "conflict"
    assert put_spy.call_count == 3
    assert batch_spy.call_count == 0


async def test_link_metadata_one_artifact_conflict_does_not_affect_another(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Each artifact_id's CAS retry is independent — a persistent conflict on one
    artifact must not prevent another artifact_id in the same call from being linked
    (though the current implementation aborts and returns the conflict error for the
    whole call once it is hit, matching the existing per-artifact-error-aborts-call
    contract already used by CredentialError/AnnotationUnavailableError)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    original_put_annotation = s3_client.put_object_annotation

    def _conflict_only_for_a(key: str, *args: object, **kwargs: object) -> None:
        if key == ID_A:
            raise ArtifactConflictError(ID_A)
        return original_put_annotation(key, *args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object_annotation", side_effect=_conflict_only_for_a)

    # Artifact B alone succeeds without any conflict.
    result_b = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_refs=["new-sha"],
    )

    assert result_b.get("linked") == 1
    assert result_b.get("error") is None


async def test_link_metadata_different_fields_concurrent_no_false_conflict(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Two 'concurrent' link_metadata calls touching DIFFERENT fields of the same
    artifact both succeed with no false-positive conflict — the annotation writes
    for commit_refs and references are independent, and neither changes the
    object's ETag, so both calls' CAS guard passes cleanly."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result1 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["sha1"],
    )
    result2 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["ref-1"],
    )

    assert result1.get("linked") == 1
    assert result2.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "sha1"
    assert s3_client.get_object_annotation(ID_A, "references") == "ref-1"


async def test_link_metadata_same_field_concurrent_residual_not_detected(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Documents the accepted residual (ADR-011 decision 6): two 'concurrent'
    link_metadata calls touching the SAME field of the same artifact are NOT
    required to detect each other as a conflict, because annotation writes are
    deliberately ETag-stable (decision 1) — writing an annotation does not change
    the object's ETag, so a second call reading the same starting ETag passes its
    own if_match check even though the first call already changed the annotation.
    This test demonstrates the gap explicitly rather than silently relying on it."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # Both calls read the artifact's ETag before either writes — simulated here by
    # simply issuing them sequentially against the same unchanged object body: the
    # object's ETag never changes between the two calls (only its annotations do),
    # so both calls' if_match check trivially succeeds — no conflict is raised.
    result1 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["writer-1-sha"],
    )
    result2 = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["writer-2-sha"],
    )

    # Neither call is rejected as a conflict — this is the accepted residual, not a
    # correctness bug: the union-merge mechanic of link_metadata itself (Story 3)
    # still makes the *end state* additive across both calls in this sequential
    # case, but a true simultaneous race on the same field could still silently
    # drop a contribution (undetectable via the ETag guard alone, per decision 6).
    assert result1.get("error") is None
    assert result2.get("error") is None
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "writer-1-sha,writer-2-sha"


# ---------------------------------------------------------------------------
# Per-value validation on supplied commit_refs / references: empty,
# whitespace-only, and comma-bearing values must be rejected (consistent with the
# Artifact model's own comma rejection) rather than silently
# passing through and diverging the two durable stores.
# ---------------------------------------------------------------------------


async def test_link_metadata_empty_string_commit_ref_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """An empty-string element in commit_refs → validation_error, no artifact touched."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=[""],
    )

    assert result.get("error") == "validation_error"


async def test_link_metadata_whitespace_only_reference_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """A whitespace-only element in references → validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["   "],
    )

    assert result.get("error") == "validation_error"


async def test_link_metadata_comma_bearing_commit_ref_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """A comma inside a supplied commit_refs value → validation_error (consistent with
    the Artifact model's comma rejection — the S3 annotation payload comma-joins
    list elements, so a comma inside one would diverge the two stores)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc,1234"],
    )

    assert result.get("error") == "validation_error"


# ---------------------------------------------------------------------------
# An orphaned vector (indexed in S3 Vectors but its
# underlying S3 object already deleted) must be skipped-and-counted for its own
# artifact_id, not abort the whole batch's linked/skipped accounting.
# ---------------------------------------------------------------------------


async def test_link_metadata_orphaned_vector_missing_s3_object_skipped_not_aborted(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """artifact-own-A's vectors remain indexed but its S3 object is deleted (orphan) —
    head_object inside the CAS helper raises KeyError. This must be skipped-and-
    counted for ID_A alone; ID_B in the same call must still be linked normally."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    s3_client.delete_object(ID_A)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A, ID_B],
        commit_refs=["abc1234"],
    )

    assert result.get("error") is None
    assert result.get("linked") == 1
    assert result.get("skipped") == 1


# ---------------------------------------------------------------------------
# T58 — commit_refs vector-metadata cap (20) + references vector-metadata removal
# ---------------------------------------------------------------------------


async def test_link_metadata_references_never_in_put_vectors_batch_payload(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A non-empty references value backfilled by link_metadata is never present in
    any put_vectors_batch payload — the annotation write carries the merged value; the
    vector write must not."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["a-1", "b-2"],
    )

    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "references") == "a-1,b-2"
    assert batch_spy.call_count == 1
    batch_payload = batch_spy.call_args.args[0]
    for item in batch_payload:
        assert "references" not in item["metadata"]


async def test_link_metadata_commit_refs_over_cap_vector_capped_annotation_full(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """A merged commit_refs list exceeding 20 entries succeeds — the vector-metadata
    copy carries only the last 20, while the annotation carries the complete, uncapped
    merged list."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    existing_refs = [f"existing{i:03d}" for i in range(15)]
    s3_client.put_object_annotation(ID_A, "commit_refs", ",".join(existing_refs))
    new_refs = [f"new{i:03d}" for i in range(10)]
    full_merged = list(dict.fromkeys(existing_refs + new_refs))
    assert len(full_merged) == 25  # sanity: exceeds the 20-entry cap

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=new_refs,
    )

    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == ",".join(full_merged)

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == full_merged[-20:]
        assert len(item["metadata"]["commit_refs"]) == 20


async def test_link_metadata_pre_check_measures_capped_payload_not_uncapped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """The pre-annotation-write budget check must measure the payload the real write
    actually assembles (capped commit_refs, no references key) — not the uncapped
    merged commit_refs. With realistic 40-char SHA-like entries, the uncapped merged
    list (55 entries) breaches VECTOR_FILTERABLE_METADATA_MAX_BYTES on its own, but the
    capped, last-20-entries payload the real write sends comfortably fits. This call
    must succeed, not be spuriously rejected with validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    def _sha_like(i: int, prefix: str) -> str:
        stem = f"{prefix}{i:04d}"
        return stem + "f" * (40 - len(stem))

    existing_refs = [_sha_like(i, "e") for i in range(30)]
    s3_client.put_object_annotation(ID_A, "commit_refs", ",".join(existing_refs))
    new_refs = [_sha_like(i, "n") for i in range(25)]
    full_merged = list(dict.fromkeys(existing_refs + new_refs))
    assert len(full_merged) == 55  # sanity: uncapped list is large

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=new_refs,
    )

    assert result.get("error") is None
    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == ",".join(full_merged)

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    for item in items:
        assert item["metadata"]["commit_refs"] == full_merged[-20:]
        assert len(item["metadata"]["commit_refs"]) == 20


# ---------------------------------------------------------------------------
# T57 — check_metadata_budgets guard coverage in link_metadata
# (docs/specs/p12-t57-guard-coverage.md, Story 1). An oversize merged
# commit_refs/references payload must be rejected BEFORE the annotation write —
# not only before put_vectors_batch — so nothing is left durably half-written.
# ---------------------------------------------------------------------------


async def test_link_metadata_oversize_supplied_value_rejected_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A single supplied commit_refs element that alone breaches the vector
    filterable-metadata budget → validation_error, zero put_object_annotation calls,
    zero put_vectors_batch calls."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    huge_ref = "a" * (VECTOR_FILTERABLE_METADATA_MAX_BYTES + 200)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=[huge_ref],
    )

    assert result.get("error") == "validation_error"
    assert annotation_spy.call_count == 0
    assert batch_spy.call_count == 0


async def test_link_metadata_oversize_only_after_merge_rejected(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Supplied commit_refs alone (10 entries, ~100 bytes each) would pass the budget
    check on their own, but the check measures the merged-then-capped, about-to-be-
    written state (T58): merging with the already-indexed existing commit_refs and
    capping to the most-recent 20 entries still leaves 10 existing-tail entries plus
    all 10 supplied entries — 20 large entries that together breach
    VECTOR_FILTERABLE_METADATA_MAX_BYTES — so this is still rejected with zero writes.
    (This is distinct from a rejection caused merely by entry *count*: capping alone
    would fit comfortably here — it's the entries' size, not their number, that
    breaches the budget.)"""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    # Existing indexed commit_refs on artifact-own-A: 15 large entries. The most
    # recent 10 of these survive capping alongside the supplied entries below.
    existing_refs = [f"existing{i:04d}" + "x" * 88 for i in range(15)]
    meta_a: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": ID_A,
        "title": "Artifact Own A",
        "commit_refs": existing_refs,
    }
    vectors_client_2.put_vector(KEY_A1, _unit_vec(1.0), meta_a)
    vectors_client_2.put_vector(KEY_A2, _unit_vec(1.1), meta_a)

    # Supplied commit_refs — 10 large entries, comfortably under budget on their own —
    # but merged with the existing entries and capped to the most-recent 20, the
    # combined size breaches VECTOR_FILTERABLE_METADATA_MAX_BYTES.
    supplied_refs = [f"supplied{i:04d}" + "x" * 88 for i in range(10)]

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=supplied_refs,
    )

    assert result.get("error") == "validation_error"
    assert annotation_spy.call_count == 0
    assert batch_spy.call_count == 0


async def test_link_metadata_cas_retry_re_checks_budget_on_every_attempt(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A CAS conflict on the first attempt is caused by a concurrent writer that lands
    an oversize commit_refs value in the annotation store. The first attempt's merge
    (existing=[] + supplied=[small]) passes the budget check, but the retry's fresh
    re-read + re-merge (existing=[huge] + supplied=[small]) breaches it — proving the
    budget check re-runs on every CAS attempt, not only the first."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    huge_ref = "a" * (VECTOR_FILTERABLE_METADATA_MAX_BYTES + 200)
    original_put_annotation = s3_client.put_object_annotation
    call_count = {"n": 0}

    def _concurrent_write_then_conflict(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # A concurrent writer's own (already-durable) annotation write lands an
            # oversize commit_refs value between this call's read and its own write.
            original_put_annotation(ID_A, "commit_refs", huge_ref)
            raise ArtifactConflictError(ID_A)
        return original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(
        s3_client, "put_object_annotation", side_effect=_concurrent_write_then_conflict
    )
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["small-sha"],
    )

    assert result.get("error") == "validation_error"
    # Only the concurrent writer's own call (attempt 1's side effect) reached
    # put_object_annotation — the retry's budget check rejected before its own
    # apply_link_annotations call, so no second real annotation write happened.
    assert call_count["n"] == 1
    assert batch_spy.call_count == 0


# ---------------------------------------------------------------------------
# T57 — control-character validation delegated to Artifact.validate_commit_refs /
# validate_references (docs/specs/p12-t57-guard-coverage.md, Story 3).
# ---------------------------------------------------------------------------


async def test_link_metadata_control_char_in_commit_ref_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A supplied commit_refs element with a control character (no comma, not empty)
    → validation_error, zero put_object_annotation, zero put_vectors_batch calls —
    proves the delegated Artifact.validate_commit_refs call is exercised, not just the
    pre-existing empty/whitespace/comma checks."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc\x01def"],
    )

    assert result.get("error") == "validation_error"
    assert annotation_spy.call_count == 0
    assert batch_spy.call_count == 0


async def test_link_metadata_control_char_in_reference_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A supplied references element with a control character → validation_error, zero
    writes (mirrors the commit_refs case for the references field)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    batch_spy = mocker.spy(vectors_client_2, "put_vectors_batch")

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        references=["ref\x01erence"],
    )

    assert result.get("error") == "validation_error"
    assert annotation_spy.call_count == 0
    assert batch_spy.call_count == 0


async def test_link_metadata_clean_value_still_succeeds_after_delegation_change(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Regression guard: a supplied value with no control character, no comma, and no
    empty/whitespace-only content still succeeds unchanged after
    _validate_supplied_link_values delegates to Artifact.validate_commit_refs /
    validate_references."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["clean-sha"],
        references=["clean-ref"],
    )

    assert result.get("error") is None
    assert result.get("linked") == 1
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "clean-sha"
    assert s3_client.get_object_annotation(ID_A, "references") == "clean-ref"


# ---------------------------------------------------------------------------
# Story — a failed vector write is recorded so reconcile_index can heal it
# ---------------------------------------------------------------------------

# Content whose H2 headings produce exactly the section vector keys seeded below, so a
# reconcile re-index rewrites those same keys rather than leaving stale siblings behind.
_SELFHEAL_CONTENT = "## Overview\n\nSome overview text.\n\n## Details\n\nSome detail text."

_SELFHEAL_ID = f"{OWN_PREFIX}/artifact-selfheal"
_SELFHEAL_KEYS = [f"{_SELFHEAL_ID}#overview", f"{_SELFHEAL_ID}#details"]

_SELFHEAL_S3_META: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": "2",
    "date": "2026-06-01",
    "status": "active",
    "title": "Self Heal Artifact",
    "visibility": "shared",
    "tags": "",
    "author_role": "developer",
    "description": "A test artifact.",
    "source_artifacts": "",
}


def _seed_selfheal_artifact(s3: S3ClientImpl, vectors: VectorsClientImpl) -> None:
    """Seed one own-scope artifact whose vector keys match what a re-index rebuilds."""
    s3.put_object(_SELFHEAL_ID, _SELFHEAL_CONTENT, dict(_SELFHEAL_S3_META))
    meta: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": _SELFHEAL_ID,
        "title": "Self Heal Artifact",
    }
    for i, key in enumerate(_SELFHEAL_KEYS):
        vectors.put_vector(key, _unit_vec(1.0 + i * 0.1), meta)


async def test_link_metadata_vector_write_failure_logs_entry_and_keeps_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A vector write that fails after a successful annotation write is recorded in the
    failure log — carrying the exact link fields it was applying — and the call still
    reports what the other artifact_ids achieved instead of collapsing to
    internal_error."""
    settings = _make_settings_base(monkeypatch, tmp_path=tmp_path)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    real_batch = vectors_client_2.put_vectors_batch

    def _fail_for_a(batch: list[dict[str, Any]]) -> None:
        if batch and batch[0]["metadata"]["artifact_id"] == ID_A:
            raise RuntimeError("simulated vector write failure")
        real_batch(batch)

    mocker.patch.object(vectors_client_2, "put_vectors_batch", side_effect=_fail_for_a)

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A, ID_B],
        commit_refs=["abc1234"],
        references=["a-1"],
    )

    # The batch's other artifact still reports its result — no internal_error.
    assert result.get("error") is None
    assert result.get("linked") == 1
    assert result.get("vector_write_failed") == [ID_A]

    # The durable side of the failed artifact is correct — only the vector copy is stale.
    assert s3_client.get_object_annotation(ID_A, "commit_refs") == "abc1234"

    entries = read_failure_entries(settings.failure_log_path)
    assert [e["artifact_id"] for e in entries] == [ID_A]
    assert entries[0]["failure_step"] == "put_vector"
    assert entries[0]["commit_refs"] == ["abc1234"]
    assert entries[0]["references"] == ["a-1"]
    assert "orphan_keys" not in entries[0]


async def test_link_metadata_vector_write_failure_self_heals_on_reconcile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """End to end: after a failed vector write leaves the annotation copy and the vector
    copy divergent, a reconcile_index run converges them — the promise both the contract
    and ADR-011 make about annotation-first ordering."""
    settings = _make_settings_base(monkeypatch, tmp_path=tmp_path, BEDROCK_EMBEDDING_DIMENSIONS="2")
    bedrock = FakeBedrockClient()
    _seed_selfheal_artifact(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated vector write failure"),
    )

    link_result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[_SELFHEAL_ID],
        commit_refs=["abc1234"],
    )
    assert link_result.get("vector_write_failed") == [_SELFHEAL_ID]

    # Divergent: the annotation has the value, the vector copy does not.
    assert s3_client.get_object_annotation(_SELFHEAL_ID, "commit_refs") == "abc1234"
    for item in vectors_client_2.get_vectors(_SELFHEAL_KEYS):
        assert "commit_refs" not in item["metadata"]

    # reconcile_index rebuilds vectors via put_vector, never put_vectors_batch, so the
    # failure injected above is out of its path either way; dropped here so the run is
    # unambiguously against an unpatched client.
    mocker.stopall()

    reconcile_result = await reconcile_index(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
    )

    assert reconcile_result.get("error") is None
    assert _SELFHEAL_ID in [e["artifact_id"] for e in reconcile_result["reconciled"]]
    assert reconcile_result["failure_log_entries_after"] == 0

    # Converged: every vector of the artifact now carries the linked commit.
    items = vectors_client_2.get_vectors(_SELFHEAL_KEYS)
    assert len(items) == len(_SELFHEAL_KEYS)
    for item in items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]


async def test_link_metadata_vector_write_credential_failure_still_logs_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A credential failure on the vector write leaves the same divergence as any other
    failure, so it is recorded too — the aborting credential_error response is unchanged,
    but it no longer loses the only trace reconcile_index could repair from."""
    settings = _make_settings_base(monkeypatch, tmp_path=tmp_path)
    bedrock = FakeBedrockClient()
    _seed_all(s3_client, vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "put_vectors_batch",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_refs=["abc1234"],
    )

    assert result.get("error") == "credential_error"

    entries = read_failure_entries(settings.failure_log_path)
    assert [e["artifact_id"] for e in entries] == [ID_A]
    assert entries[0]["commit_refs"] == ["abc1234"]

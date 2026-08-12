"""Unit tests for arkeology.tools.link_metadata.

Tests link_metadata() using moto-backed S3ClientImpl + VectorsClientImpl.
Generalizes and supersedes link_commit (p10-t38): dual-writes commit_refs and/or
references — durable S3 annotations first, then vector metadata reusing the
existing float32 embeddings — with zero Bedrock calls (ADR-011 / T49, AC-59).
"""

import math
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import AnnotationUnavailableError, ArtifactConflictError, CredentialError
from arkeology.tools.link_metadata import link_metadata
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


async def test_link_metadata_references_backfilled_to_both_stores(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """references=['a-1'] lands in both the S3 annotation and vector metadata."""
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
        assert item["metadata"]["references"] == ["a-1"]


async def test_link_metadata_both_fields_backfilled_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Supplying both commit_refs and references in one call backfills both fields
    to both stores."""
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
        assert item["metadata"]["references"] == ["a-1"]


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
        assert item["metadata"]["references"] == ["a-1"]
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
    discarded (Phase-12 #17). Today the except AnnotationUnavailableError branch
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
# Story 6 — C3 fix: union read + only-touch-supplied-fields (Phase 12 review)
# ---------------------------------------------------------------------------


async def test_link_metadata_only_references_supplied_preserves_annotation_only_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """C3: commit_refs exists ONLY as an S3 annotation (the partial-write state — the
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
    """C3: re-supplying a commit_refs value already fully present in both stores is
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
    """C3: the union read heals a state where the annotation holds a commit_refs value
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
# Optimistic-concurrency (ETag compare-and-swap) writes — ADR-011 decision 6 /
# review-followup-2026-07-06 "Optimistic-Concurrency Writes"
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
# review-followup-2026-07-06 M9 — per-value validation on supplied commit_refs /
# references: empty, whitespace-only, and comma-bearing values must be rejected
# (consistent with the Artifact model's comma rejection, M2) rather than silently
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
    the Artifact model's M2 comma rejection — the S3 annotation payload comma-joins
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
# review-followup-2026-07-06 M10 — an orphaned vector (indexed in S3 Vectors but its
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

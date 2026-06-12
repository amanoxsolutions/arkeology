"""Unit tests for cairn_mcp.tools.link_commit.

Tests link_commit() using moto-backed VectorsClientImpl.
No S3 or Bedrock calls — vectors are seeded directly into the index.
"""

import math
from typing import Any

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.link_commit import link_commit
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
    "project": "cairn",
    "tier": 2,
    "date": "2026-06-01",
    "status": "active",
    "title": "Some artifact",
    "visibility": "shared",
    "feature_tags": [],
    "author_role": "developer",
    "description": "A test artifact.",
    "last_edited_ulid": "01KT07NV00FN74309G4MXHQ1KN",
}

# Own-scope prefix as per test settings WRITE_PREFIX=artifacts
OWN_PREFIX = "artifacts"
FOREIGN_PREFIX = "other-team"

# artifact-own-A: own-scope, two section vectors, no commit_refs
KEY_A1 = f"{OWN_PREFIX}/artifact-own-A#summary"
KEY_A2 = f"{OWN_PREFIX}/artifact-own-A#details"
ID_A = f"{OWN_PREFIX}/artifact-own-A"

# artifact-own-B: own-scope, one document vector, commit_refs=["prev123"]
KEY_B = f"{OWN_PREFIX}/artifact-own-B#summary"
ID_B = f"{OWN_PREFIX}/artifact-own-B"

# artifact-foreign: foreign-scope, one vector, no commit_refs
KEY_F = f"{FOREIGN_PREFIX}/artifact-foreign#summary"
ID_F = f"{FOREIGN_PREFIX}/artifact-foreign"


def _seed_all(vectors: VectorsClientImpl) -> None:
    """Seed all three test artifacts into the vector index."""
    # artifact-own-A: two section vectors, no commit_refs
    meta_a: dict[str, Any] = {
        **_BASE_META,
        "artifact_id": ID_A,
        "title": "Artifact Own A",
        "commit_refs": [],
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
        "commit_refs": [],
    }
    vectors.put_vector(KEY_F, _unit_vec(0.8), meta_f)


# ---------------------------------------------------------------------------
# Linking: basic success
# ---------------------------------------------------------------------------


async def test_link_commit_linked_1_skipped_0(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """link_commit on own-scope artifact → linked=1, skipped=0."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert result.get("linked") == 1
    assert result.get("skipped") == 0
    assert result.get("commit_sha") == "abc1234"


async def test_link_commit_all_section_vectors_updated(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Both section vectors of artifact-own-A carry commit_refs=["abc1234"] after link."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    items = vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    assert len(items) == 2
    for item in items:
        assert item["metadata"]["commit_refs"] == ["abc1234"], (
            f"Expected ['abc1234'] on {item['key']}, got {item['metadata']['commit_refs']}"
        )


async def test_link_commit_float32_values_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Float32 embedding values on all vectors are unchanged after link."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    before = {
        item["key"]: item["data"]["float32"]
        for item in vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    }

    await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    after = {
        item["key"]: item["data"]["float32"]
        for item in vectors_client_2.get_vectors([KEY_A1, KEY_A2])
    }

    for key in [KEY_A1, KEY_A2]:
        assert before[key] == after[key], f"Float32 values changed for {key}"


async def test_link_commit_bedrock_never_called(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Bedrock embed is never called during link_commit."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    spy = mocker.spy(bedrock, "embed")

    await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert spy.call_count == 0


# ---------------------------------------------------------------------------
# Append and deduplicate
# ---------------------------------------------------------------------------


async def test_link_commit_append_to_existing_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact with commit_refs=["prev123"] → becomes ["prev123", "abc1234"] after link."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_sha="abc1234",
    )

    assert result.get("linked") == 1

    items = vectors_client_2.get_vectors([KEY_B])
    assert items[0]["metadata"]["commit_refs"] == ["prev123", "abc1234"]


async def test_link_commit_dedup_same_sha(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Calling link_commit with a SHA already in commit_refs → commit_refs unchanged."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    # "prev123" is already in artifact-own-B's commit_refs
    await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_sha="prev123",
    )

    items = vectors_client_2.get_vectors([KEY_B])
    assert items[0]["metadata"]["commit_refs"] == ["prev123"]


# ---------------------------------------------------------------------------
# Scope gate
# ---------------------------------------------------------------------------


async def test_link_commit_foreign_scope_skipped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign-scope artifact → linked=0, skipped=1."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_F],
        commit_sha="abc1234",
    )

    assert result.get("linked") == 0
    assert result.get("skipped") == 1


async def test_link_commit_mixed_list(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Mixed list [own-scope, foreign-scope] → linked=1, skipped=1."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A, ID_F],
        commit_sha="abc1234",
    )

    assert result.get("linked") == 1
    assert result.get("skipped") == 1


# ---------------------------------------------------------------------------
# Missing artifact
# ---------------------------------------------------------------------------


async def test_link_commit_nonexistent_key_skipped(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Artifact ID with no vectors in index → linked=0, skipped=1 (no error)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=["artifacts/nonexistent-key"],
        commit_sha="abc1234",
    )

    assert result.get("linked") == 0
    assert result.get("skipped") == 1


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


async def test_link_commit_response_has_next_since_ulid(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Response includes non-empty next_since_ulid."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert "next_since_ulid" in result
    assert isinstance(result["next_since_ulid"], str)
    assert len(result["next_since_ulid"]) > 0


async def test_link_commit_successive_ulids_monotonically_increasing(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Two successive link_commit calls → second next_since_ulid >= first."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    result1 = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="sha1",
    )

    result2 = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_B],
        commit_sha="sha2",
    )

    ulid1: str = result1["next_since_ulid"]
    ulid2: str = result2["next_since_ulid"]
    assert ulid2 >= ulid1, f"Expected {ulid2!r} >= {ulid1!r}"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_list_vectors_by_metadata_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Credential failure (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert "error" in result
    assert result["error"] == "credential_error"


async def test_get_vectors_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_vectors raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "get_vectors",
        side_effect=CredentialError(
            message="Credential failure on get_vectors (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert "error" in result
    assert result["error"] == "credential_error"


async def test_put_vectors_batch_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """put_vectors_batch raises CredentialError → structured error response."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    _seed_all(vectors_client_2)

    mocker.patch.object(
        vectors_client_2,
        "put_vectors_batch",
        side_effect=CredentialError(
            message="Credential failure on put_vectors_batch (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await link_commit(
        settings=settings,
        s3=None,
        vectors=vectors_client_2,
        bedrock=bedrock,
        artifact_ids=[ID_A],
        commit_sha="abc1234",
    )

    assert "error" in result
    assert result["error"] == "credential_error"

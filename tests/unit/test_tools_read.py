"""Unit tests for arkeology.tools.read.

Tests read_artifact() using moto-backed S3ClientImpl with pre-seeded objects.
"""

import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError
from arkeology.tools.read import read_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------

_BASE_METADATA: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": "2",
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "visibility": "shared",
    "tags": "auth,security",
    "author_role": "developer",
    "description": "Review of the auth module.",
}


def _seed_objects(s3: S3ClientImpl) -> None:
    """Seed S3 with representative objects for read_artifact tests."""
    content = "## Summary\n\nAll looks good."

    # own-scope tier 2 shared
    s3.put_object(
        "artifacts/t2-shared",
        content,
        {**_BASE_METADATA, "tier": "2", "visibility": "shared"},
    )

    # own-scope tier 2 hidden
    s3.put_object(
        "artifacts/t2-hidden",
        content,
        {**_BASE_METADATA, "tier": "2", "visibility": "hidden"},
    )

    # own-scope tier 3 shared
    s3.put_object(
        "artifacts/t3-shared",
        content,
        {**_BASE_METADATA, "tier": "3", "visibility": "shared"},
    )

    # own-scope tier 3 hidden
    s3.put_object(
        "artifacts/t3-hidden",
        content,
        {**_BASE_METADATA, "tier": "3", "visibility": "hidden"},
    )

    # foreign-scope tier 2 shared — access DENIED
    s3.put_object(
        "other-team/t2-foreign-shared",
        content,
        {**_BASE_METADATA, "tier": "2", "visibility": "shared", "team": "network"},
    )

    # foreign-scope tier 3 shared — access ALLOWED
    s3.put_object(
        "other-team/t3-foreign-shared",
        content,
        {**_BASE_METADATA, "tier": "3", "visibility": "shared", "team": "network"},
    )

    # foreign-scope tier 3 hidden — access DENIED
    s3.put_object(
        "other-team/t3-foreign-hidden",
        content,
        {**_BASE_METADATA, "tier": "3", "visibility": "hidden", "team": "network"},
    )


# ---------------------------------------------------------------------------
# Happy path — own scope
# ---------------------------------------------------------------------------


async def test_own_scope_tier2_shared_returns_content(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """own-scope tier 2 shared → response contains 'content' field."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert "content" in result
    assert result["content"] == "## Summary\n\nAll looks good."


async def test_own_scope_tier3_shared_returned(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """own-scope tier 3 shared → returned successfully."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t3-shared")

    assert "content" in result


async def test_own_scope_tier3_hidden_returned(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """own-scope tier 3 hidden → returned (no gate on own scope)."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t3-hidden")

    assert "content" in result


async def test_foreign_scope_tier3_shared_returned(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """foreign-scope tier 3 shared → returned with full content."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="other-team/t3-foreign-shared"
    )

    assert "content" in result
    assert result["content"] == "## Summary\n\nAll looks good."


async def test_all_metadata_fields_present_in_response(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """All metadata fields present: type, team, project, tier, date, status, title,
    visibility, tags, author_role, description, content."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    for field in [
        "type",
        "team",
        "project",
        "tier",
        "date",
        "status",
        "title",
        "visibility",
        "tags",
        "author_role",
        "description",
        "content",
    ]:
        assert field in result, f"Missing field: {field}"


async def test_tags_deserialized_to_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """tags in response is a list (deserialized from comma-separated string)."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert isinstance(result["tags"], list)
    assert "auth" in result["tags"]
    assert "security" in result["tags"]


async def test_tier_in_response_is_int(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """tier in response is an int, not a string."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert isinstance(result["tier"], int)
    assert result["tier"] == 2


async def test_author_role_present_when_set(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """author_role field is present and matches the stored value."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert result["author_role"] == "developer"


async def test_author_role_absent_in_metadata_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """author_role absent from metadata → response has None or empty value."""
    settings = _make_settings(monkeypatch)
    metadata_no_role = {k: v for k, v in _BASE_METADATA.items() if k != "author_role"}
    s3_client.put_object("artifacts/no-role", "Content.", metadata_no_role)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/no-role")

    assert result.get("author_role") is None


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def test_foreign_tier2_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """foreign-scope tier 2 → access-denied error; get_object was NEVER called."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)
    spy_get = mocker.spy(s3_client, "get_object")

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="other-team/t2-foreign-shared"
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    called_keys = [call.args[0] for call in spy_get.call_args_list]
    assert "other-team/t2-foreign-shared" not in called_keys


async def test_foreign_tier3_hidden_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """foreign-scope tier 3 hidden → access-denied error."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="other-team/t3-foreign-hidden"
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str


async def test_unknown_scope_artifact_id_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """artifact_id with prefix matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="unknown-scope/some-artifact"
    )

    assert "error" in result or result.get("error_type") is not None


async def test_access_denied_differs_from_not_found_in_message(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """Access-denied and not-found errors are clearly distinguishable."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    denied_result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="other-team/t2-foreign-shared"
    )
    notfound_result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/nonexistent"
    )

    assert denied_result != notfound_result


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


async def test_own_scope_missing_object_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """Valid own-scope artifact_id but object not in S3 → structured not-found error."""
    settings = _make_settings(monkeypatch)

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/nonexistent"
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_artifact_id_scope_prefix_not_matched_as_substring(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """write_prefix='dev', artifact_id='dev/review' must NOT match scope 'dev/review-v2'."""
    settings = _make_settings(monkeypatch, WRITE_PREFIX="dev")
    s3_client.put_object("dev/review", "Content.", {**_BASE_METADATA, "tier": "2"})

    result_correct = await read_artifact(s3=s3_client, settings=settings, artifact_id="dev/review")
    assert "content" in result_correct


async def test_artifact_id_with_no_slash_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """artifact_id with no '/' in it → no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="noslash")

    assert "error" in result or result.get("error_type") is not None


async def test_head_object_key_error_returns_not_found_not_exception(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """head_object raises KeyError (missing) → not-found error, not unhandled exception."""
    settings = _make_settings(monkeypatch)

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/missing-obj"
    )

    assert isinstance(result, dict)
    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_head_object_credential_failure_no_get_object_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """head_object CredentialError → structured error; get_object NOT called."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    spy_get = mocker.spy(s3_client, "get_object")
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="Credential failure on head_object (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert "error" in result or result.get("error_type") is not None
    assert spy_get.call_count == 0


async def test_get_object_credential_failure_after_gate_passes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """get_object CredentialError after gate passes → structured error."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    mocker.patch.object(
        s3_client,
        "get_object",
        side_effect=CredentialError(
            message="Credential failure on get_object (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# T4: author_role stored as empty string → response is None
# ---------------------------------------------------------------------------


async def test_author_role_empty_string_in_metadata_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """author_role stored as '' (empty string) in S3 metadata → response has None, not ''."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/empty-role",
        "Content.",
        {**_BASE_METADATA, "author_role": ""},
    )

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/empty-role"
    )

    assert result["author_role"] is None, (
        f"Expected None for empty author_role, got {result['author_role']!r}"
    )


# ---------------------------------------------------------------------------
# T5: source_artifacts deserialized from comma-joined string to list
# ---------------------------------------------------------------------------


async def test_source_artifacts_deserialized_to_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """source_artifacts stored as 'adr-one,adr-two' in S3 → response is ['adr-one', 'adr-two']."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/with-sources",
        "Content.",
        {**_BASE_METADATA, "source_artifacts": "adr-one,adr-two"},
    )

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/with-sources"
    )

    assert result["source_artifacts"] == ["adr-one", "adr-two"]


# ---------------------------------------------------------------------------
# T36 — commit_refs read from vector metadata, last_edited_ulid from S3
# ---------------------------------------------------------------------------


async def test_read_commit_refs_single_sha_from_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """commit_refs: ['abc1234'] in vector metadata → response returns ['abc1234'].

    Write-time path: SHA was stored at write time alongside the artifact.
    """
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-vector-ref", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/with-vector-ref#section-0",
        vector=[1.0, 0.0],
        metadata={"artifact_id": "artifacts/with-vector-ref", "commit_refs": ["abc1234"]},
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/with-vector-ref",
    )

    assert result["commit_refs"] == ["abc1234"]


async def test_read_commit_refs_multiple_shas_from_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """commit_refs: ['prev123', 'new456'] in vector metadata → response returns both SHAs.

    Simulates post-link_commit state where S3 object metadata has no commit_refs at all.
    """
    settings = _make_settings(monkeypatch)
    # S3 object metadata intentionally has no commit_refs key — link_commit only updates vectors
    s3_client.put_object("artifacts/post-link-commit", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/post-link-commit#section-0",
        vector=[0.0, 1.0],
        metadata={
            "artifact_id": "artifacts/post-link-commit",
            "commit_refs": ["prev123", "new456"],
        },
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/post-link-commit",
    )

    assert result["commit_refs"] == ["prev123", "new456"]


async def test_read_commit_refs_returns_empty_list_when_vectors_is_none(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """vectors=None → commit_refs is [] (graceful degradation when client not injected)."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/no-vectors-client", "Content.", {**_BASE_METADATA})

    result = await read_artifact(
        s3=s3_client,
        vectors=None,
        settings=settings,
        artifact_id="artifacts/no-vectors-client",
    )

    assert result["commit_refs"] == []


async def test_read_commit_refs_returns_empty_list_when_no_vector_entries(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """list_vectors_by_metadata returns [] (artifact not indexed) → commit_refs is []."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/not-indexed", "Content.", {**_BASE_METADATA})
    # No vectors seeded for this artifact_id

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/not-indexed",
    )

    assert result["commit_refs"] == []


async def test_read_commit_refs_credential_error_from_list_vectors_by_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata raises CredentialError → structured error returned.

    No raw exception must escape to the MCP caller.
    """
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/cred-fail", "Content.", {**_BASE_METADATA})
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=CredentialError(
            message="Simulated credential failure on list_vectors_by_metadata.",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/cred-fail",
    )

    assert "error" in result
    assert result["error"] == "credential_error"


async def test_read_non_credential_vector_error_degrades_to_empty_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Non-credential error from list_vectors_by_metadata → read succeeds with commit_refs=[].

    commit_refs are supplementary — a transient vector failure must not abort
    an otherwise-successful read and return an error response.
    """
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/vec-error", "Content.", {**_BASE_METADATA})
    mocker.patch.object(
        vectors_client_2,
        "list_vectors_by_metadata",
        side_effect=RuntimeError("Simulated transient vector failure"),
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/vec-error",
    )

    # Read must succeed — no "error" key
    assert "error" not in result, f"Expected success but got error: {result}"
    assert result["artifact_id"] == "artifacts/vec-error"
    # commit_refs degrades gracefully to []
    assert result["commit_refs"] == []


async def test_read_references_from_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """references: ['adr-one'] in vector metadata → response returns ['adr-one']."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-reference", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/with-reference#section-0",
        vector=[1.0, 0.0],
        metadata={"artifact_id": "artifacts/with-reference", "references": ["adr-one"]},
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/with-reference",
    )

    assert result["references"] == ["adr-one"]


async def test_read_references_returns_empty_list_when_absent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """No 'references' key in vector metadata → response returns []."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/no-reference", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/no-reference#section-0",
        vector=[1.0, 0.0],
        metadata={"artifact_id": "artifacts/no-reference"},
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/no-reference",
    )

    assert result["references"] == []


async def test_read_references_returns_empty_list_when_vectors_is_none(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """vectors=None → references is [] (graceful degradation when client not injected)."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/no-vectors-client-ref", "Content.", {**_BASE_METADATA})

    result = await read_artifact(
        s3=s3_client,
        vectors=None,
        settings=settings,
        artifact_id="artifacts/no-vectors-client-ref",
    )

    assert result["references"] == []


async def test_read_last_edited_ulid_present(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """last_edited_ulid in S3 metadata → returned in response."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/with-ulid",
        "Content.",
        {**_BASE_METADATA, "last_edited_ulid": "01JXXXXXXXXXXXXXXXXXXXXXXXXX"},
    )

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/with-ulid")

    assert result["last_edited_ulid"] == "01JXXXXXXXXXXXXXXXXXXXXXXXXX"


async def test_read_last_edited_ulid_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """last_edited_ulid absent from S3 metadata → response has None, not an error."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/legacy-no-ulid",
        "Content.",
        {**_BASE_METADATA},
    )

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/legacy-no-ulid"
    )

    assert "last_edited_ulid" in result
    assert result["last_edited_ulid"] is None


# ---------------------------------------------------------------------------
# T55 (M-5, Story 4) — non-ASCII title round-trips identically via read_artifact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "non_ascii_title",
    ["日本語のタイトル", "Заголовок на русском", "café — la révision"],
)
async def test_non_ascii_title_read_back_identically(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    non_ascii_title: str,
) -> None:
    """A non-Latin title, seeded exactly as S3ClientImpl.put_object would transport-encode
    it, is decoded back to the original by read_artifact — never silently ASCII-stripped
    to '' or otherwise damaged."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "artifacts/non-ascii-title",
        "Content.",
        {**_BASE_METADATA, "title": non_ascii_title},
    )

    result = await read_artifact(
        s3=s3_client, settings=settings, artifact_id="artifacts/non-ascii-title"
    )

    assert result["title"] == non_ascii_title


# ---------------------------------------------------------------------------
# M-8 — read_artifact's blocking client calls are offloaded off the event loop
# ---------------------------------------------------------------------------


async def test_read_s3_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    mocker: MockerFixture,
) -> None:
    """head_object and get_object execute on a worker thread, never on the calling
    event-loop thread — proves the calls are routed through asyncio.to_thread."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_head = s3_client.head_object
    original_get = s3_client.get_object

    def spy_head(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_head(*args, **kwargs)

    def spy_get(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_get(*args, **kwargs)

    mocker.patch.object(s3_client, "head_object", side_effect=spy_head)
    mocker.patch.object(s3_client, "get_object", side_effect=spy_get)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert "content" in result
    assert seen_threads, "head_object/get_object were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "S3 calls ran on the event-loop thread — they must be offloaded"
    )


async def test_read_vector_calls_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """list_vectors_by_metadata and get_vectors (commit_refs/references lookup) execute
    on a worker thread, never on the calling event-loop thread."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/with-vector-ref", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/with-vector-ref#section-0",
        vector=[1.0, 0.0],
        metadata={"artifact_id": "artifacts/with-vector-ref", "commit_refs": ["abc1234"]},
    )
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    original_list = vectors_client_2.list_vectors_by_metadata
    original_get_vectors = vectors_client_2.get_vectors

    def spy_list(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_list(*args, **kwargs)

    def spy_get_vectors(*args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original_get_vectors(*args, **kwargs)

    mocker.patch.object(vectors_client_2, "list_vectors_by_metadata", side_effect=spy_list)
    mocker.patch.object(vectors_client_2, "get_vectors", side_effect=spy_get_vectors)

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/with-vector-ref",
    )

    assert result["commit_refs"] == ["abc1234"]
    assert seen_threads, "list_vectors_by_metadata/get_vectors were never called"
    assert all(t is not main_thread for t in seen_threads), (
        "Vector calls ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# M5 — cross-scope reference filtering (ADR-012)
# ---------------------------------------------------------------------------


async def test_read_cross_scope_reference_filtering_drops_unreadable_target(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared artifact referencing a foreign tier-2 target → target
    dropped from the returned references list."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "other-team/t3-with-refs",
        "Content.",
        {**_BASE_METADATA, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors_client_2.put_vector(
        key="other-team/t3-with-refs#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "other-team/t3-with-refs",
            "references": ["other-team/hidden-target"],
        },
    )
    vectors_client_2.put_vector(
        key="other-team/hidden-target#section-0",
        vector=[0.0, 1.0],
        metadata={"artifact_id": "other-team/hidden-target", "tier": 2, "visibility": "shared"},
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="other-team/t3-with-refs",
    )

    assert result["references"] == []


async def test_read_cross_scope_reference_filtering_keeps_readable_target(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared artifact referencing a foreign tier-3-shared target →
    target kept in the returned references list."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "other-team/t3-with-refs2",
        "Content.",
        {**_BASE_METADATA, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors_client_2.put_vector(
        key="other-team/t3-with-refs2#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "other-team/t3-with-refs2",
            "references": ["other-team/shared-target"],
        },
    )
    vectors_client_2.put_vector(
        key="other-team/shared-target#section-0",
        vector=[0.0, 1.0],
        metadata={"artifact_id": "other-team/shared-target", "tier": 3, "visibility": "shared"},
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="other-team/t3-with-refs2",
    )

    assert result["references"] == ["other-team/shared-target"]


async def test_read_own_scope_references_unfiltered(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Own-scope artifact referencing an otherwise-unreadable target → never filtered;
    the reference is returned as-is regardless of the target's own accessibility."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/own-with-refs", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/own-with-refs#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "artifacts/own-with-refs",
            "references": ["other-team/hidden-target-x"],
        },
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/own-with-refs",
    )

    assert result["references"] == ["other-team/hidden-target-x"]


async def test_read_cross_scope_reference_missing_target_stripped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared artifact referencing a target with no matching vector
    entry (deleted or never existed) → target stripped, fail safe."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "other-team/t3-with-refs3",
        "Content.",
        {**_BASE_METADATA, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors_client_2.put_vector(
        key="other-team/t3-with-refs3#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "other-team/t3-with-refs3",
            "references": ["other-team/does-not-exist"],
        },
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="other-team/t3-with-refs3",
    )

    assert result["references"] == []


async def test_read_cross_scope_reference_resolving_into_own_scope_kept(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """Foreign tier-3-shared artifact referencing a target in the reader's own scope →
    kept, even though no vector entry exists for that own-scope target."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object(
        "other-team/t3-with-refs4",
        "Content.",
        {**_BASE_METADATA, "tier": "3", "visibility": "shared", "team": "network"},
    )
    vectors_client_2.put_vector(
        key="other-team/t3-with-refs4#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "other-team/t3-with-refs4",
            "references": ["artifacts/own-hidden-target"],
        },
    )

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="other-team/t3-with-refs4",
    )

    assert result["references"] == ["artifacts/own-hidden-target"]


async def test_read_own_scope_reference_filtering_issues_no_extra_vector_query(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Own-scope read → reference filtering is skipped entirely; list_vectors_by_metadata
    is called exactly once (the pre-existing Step 4 commit_refs/references lookup)."""
    settings = _make_settings(monkeypatch)
    s3_client.put_object("artifacts/own-with-refs-spy", "Content.", {**_BASE_METADATA})
    vectors_client_2.put_vector(
        key="artifacts/own-with-refs-spy#section-0",
        vector=[1.0, 0.0],
        metadata={
            "artifact_id": "artifacts/own-with-refs-spy",
            "references": ["other-team/some-target"],
        },
    )
    spy = mocker.spy(vectors_client_2, "list_vectors_by_metadata")

    result = await read_artifact(
        s3=s3_client,
        vectors=vectors_client_2,
        settings=settings,
        artifact_id="artifacts/own-with-refs-spy",
    )

    assert result["references"] == ["other-team/some-target"]
    assert spy.call_count == 1

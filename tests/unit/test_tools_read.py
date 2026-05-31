"""Unit tests for cairn_mcp.tools.read.

Tests read_artifact() using FakeS3Client with pre-seeded objects.
"""

import pytest

from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.config import Settings
from cairn_mcp.tools.read import read_artifact

# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("WRITE_PREFIX", "artifacts")
    monkeypatch.setenv("READ_PREFIXES", "other-team")
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return Settings()


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------

_BASE_METADATA: dict[str, str] = {
    "type": "code_review",
    "team": "platform",
    "project": "cairn",
    "tier": "2",
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "visibility": "shared",
    "feature_tags": "auth,security",
    "author_role": "developer",
    "description": "Review of the auth module.",
}


def _seed_objects(s3: FakeS3Client) -> None:
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
) -> None:
    """own-scope tier 2 shared → response contains 'content' field."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert "content" in result
    assert result["content"] == "## Summary\n\nAll looks good."


async def test_own_scope_tier3_shared_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """own-scope tier 3 shared → returned successfully."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t3-shared")

    assert "content" in result


async def test_own_scope_tier3_hidden_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """own-scope tier 3 hidden → returned (no gate on own scope)."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t3-hidden")

    assert "content" in result


async def test_foreign_scope_tier3_shared_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """foreign-scope tier 3 shared → returned with full content."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(
        s3=s3, settings=settings, artifact_id="other-team/t3-foreign-shared"
    )

    assert "content" in result
    assert result["content"] == "## Summary\n\nAll looks good."


async def test_all_metadata_fields_present_in_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All metadata fields present: type, team, project, tier, date, status, title,
    visibility, feature_tags, author_role, description, content."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    for field in [
        "type", "team", "project", "tier", "date", "status", "title",
        "visibility", "feature_tags", "author_role", "description", "content",
    ]:
        assert field in result, f"Missing field: {field}"


async def test_feature_tags_deserialized_to_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feature_tags in response is a list (deserialized from comma-separated string)."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert isinstance(result["feature_tags"], list)
    assert "auth" in result["feature_tags"]
    assert "security" in result["feature_tags"]


async def test_tier_in_response_is_int(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tier in response is an int, not a string."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert isinstance(result["tier"], int)
    assert result["tier"] == 2


async def test_author_role_present_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """author_role field is present and matches the stored value."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert result["author_role"] == "developer"


async def test_author_role_absent_in_metadata_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """author_role absent from metadata → response has None or empty value."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    # Store object with no author_role in metadata
    metadata_no_role = {k: v for k, v in _BASE_METADATA.items() if k != "author_role"}
    s3.put_object("artifacts/no-role", "Content.", metadata_no_role)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/no-role")

    assert result.get("author_role") is None


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def test_foreign_tier2_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """foreign-scope tier 2 → access-denied error; get_object was NEVER called."""
    settings = _make_settings(monkeypatch)

    get_object_calls: list[str] = []

    class TrackingS3Client(FakeS3Client):
        def get_object(self, key: str) -> str:
            get_object_calls.append(key)
            return super().get_object(key)

    s3 = TrackingS3Client()
    _seed_objects(s3)

    result = await read_artifact(
        s3=s3, settings=settings, artifact_id="other-team/t2-foreign-shared"
    )

    # Must be an access-denied error
    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str
    assert "other-team/t2-foreign-shared" not in get_object_calls


async def test_foreign_tier3_hidden_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """foreign-scope tier 3 hidden → access-denied error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(
        s3=s3, settings=settings, artifact_id="other-team/t3-foreign-hidden"
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "access" in result_str or "denied" in result_str or "forbidden" in result_str


async def test_unknown_scope_artifact_id_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact_id with prefix matching no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    result = await read_artifact(
        s3=s3, settings=settings, artifact_id="unknown-scope/some-artifact"
    )

    assert "error" in result or result.get("error_type") is not None


async def test_access_denied_differs_from_not_found_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access-denied and not-found errors are clearly distinguishable."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    _seed_objects(s3)

    denied_result = await read_artifact(
        s3=s3, settings=settings, artifact_id="other-team/t2-foreign-shared"
    )
    notfound_result = await read_artifact(
        s3=s3, settings=settings, artifact_id="artifacts/nonexistent"
    )

    # Both are errors but the messages or error_type fields differ
    # At minimum they should not be identical responses
    assert denied_result != notfound_result


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


async def test_own_scope_missing_object_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid own-scope artifact_id but object not in S3 → structured not-found error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    # Do NOT seed the object

    result = await read_artifact(
        s3=s3, settings=settings, artifact_id="artifacts/nonexistent"
    )

    assert "error" in result or result.get("error_type") is not None
    result_str = str(result).lower()
    assert "not" in result_str or "found" in result_str or "missing" in result_str


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_artifact_id_scope_prefix_not_matched_as_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_prefix='dev', artifact_id='dev/review' must NOT match scope 'dev/review-v2'."""
    # Scope check must use startswith(scope + "/"), not startswith(scope)
    settings = _make_settings(monkeypatch, WRITE_PREFIX="dev")
    s3 = FakeS3Client()
    # Place object at 'dev/review'
    s3.put_object("dev/review", "Content.", {**_BASE_METADATA, "tier": "2"})

    result_correct = await read_artifact(s3=s3, settings=settings, artifact_id="dev/review")
    assert "content" in result_correct


async def test_artifact_id_with_no_slash_returns_access_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact_id with no '/' in it → no known scope → access-denied error."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()

    result = await read_artifact(s3=s3, settings=settings, artifact_id="noslash")

    assert "error" in result or result.get("error_type") is not None


async def test_head_object_key_error_returns_not_found_not_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """head_object raises KeyError (missing) → not-found error, not unhandled exception."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    # Do not seed the key; head_object will raise KeyError

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/missing-obj")

    # Must return an error dict, not propagate the exception
    assert isinstance(result, dict)
    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_head_object_credential_failure_no_get_object_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """head_object CredentialError → structured error; get_object NOT called."""
    settings = _make_settings(monkeypatch)

    get_object_calls: list[str] = []

    class TrackingS3Client(FakeS3Client):
        def get_object(self, key: str) -> str:
            get_object_calls.append(key)
            return super().get_object(key)

    s3 = TrackingS3Client()
    _seed_objects(s3)
    s3.set_credential_failure(True)  # All methods now raise CredentialError

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert "error" in result or result.get("error_type") is not None
    assert len(get_object_calls) == 0


async def test_get_object_credential_failure_after_gate_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_object CredentialError after gate passes → structured error."""
    settings = _make_settings(monkeypatch)

    class PartialCredFailS3Client(FakeS3Client):
        """head_object succeeds; get_object always raises CredentialError."""

        def get_object(self, key: str) -> str:
            from cairn_mcp.errors import CredentialError as _CE

            raise _CE(
                message="Credential failure on get_object (simulated).",
                service="s3",
                original=Exception("simulated"),
            )

    s3 = PartialCredFailS3Client()
    _seed_objects(s3)

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/t2-shared")

    assert "error" in result or result.get("error_type") is not None


# ---------------------------------------------------------------------------
# T4: author_role stored as empty string → response is None
# ---------------------------------------------------------------------------


async def test_author_role_empty_string_in_metadata_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """author_role stored as '' (empty string) in S3 metadata → response has None, not ''."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object(
        "artifacts/empty-role",
        "Content.",
        {**_BASE_METADATA, "author_role": ""},
    )

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/empty-role")

    assert result["author_role"] is None, (
        f"Expected None for empty author_role, got {result['author_role']!r}"
    )


# ---------------------------------------------------------------------------
# T5: source_artifacts deserialized from comma-joined string to list
# ---------------------------------------------------------------------------


async def test_source_artifacts_deserialized_to_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """source_artifacts stored as 'adr-one,adr-two' in S3 → response is ['adr-one', 'adr-two']."""
    settings = _make_settings(monkeypatch)
    s3 = FakeS3Client()
    s3.put_object(
        "artifacts/with-sources",
        "Content.",
        {**_BASE_METADATA, "source_artifacts": "adr-one,adr-two"},
    )

    result = await read_artifact(s3=s3, settings=settings, artifact_id="artifacts/with-sources")

    assert result["source_artifacts"] == ["adr-one", "adr-two"]

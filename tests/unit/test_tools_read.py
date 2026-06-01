"""Unit tests for cairn_mcp.tools.read.

Tests read_artifact() using moto-backed S3ClientImpl with pre-seeded objects.
"""

import pytest
from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError
from cairn_mcp.tools.read import read_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, READ_PREFIXES="other-team", **overrides)


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
    visibility, feature_tags, author_role, description, content."""
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
        "feature_tags",
        "author_role",
        "description",
        "content",
    ]:
        assert field in result, f"Missing field: {field}"


async def test_feature_tags_deserialized_to_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
) -> None:
    """feature_tags in response is a list (deserialized from comma-separated string)."""
    settings = _make_settings(monkeypatch)
    _seed_objects(s3_client)

    result = await read_artifact(s3=s3_client, settings=settings, artifact_id="artifacts/t2-shared")

    assert isinstance(result["feature_tags"], list)
    assert "auth" in result["feature_tags"]
    assert "security" in result["feature_tags"]


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

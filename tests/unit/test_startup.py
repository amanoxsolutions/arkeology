"""Unit tests for the startup validation sequence.

All five checks are tested via moto-backed clients — no real AWS calls are made.
Tests verify the correct StartupValidationError check field and that failing
checks prevent subsequent checks from running.
"""

import logging

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.errors import CredentialError, StartupValidationError
from cairn_mcp.startup import validate_startup


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Provide a valid Settings instance for tests."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    return Settings()


@pytest.fixture
def settings_with_read_prefix(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with a foreign read prefix configured."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    monkeypatch.setenv("READ_PREFIXES", "network/")
    return Settings()


# ── All checks pass ────────────────────────────────────────────────────────────


def test_all_checks_pass(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """All healthy moto-backed clients → validate_startup returns None with no exception."""
    bedrock = FakeBedrockClient(dimension=1024)
    result = validate_startup(
        settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock
    )
    assert result is None


# ── Check 1: Credential check ──────────────────────────────────────────────────


def test_check1_credential_failure_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 credential failure → StartupValidationError with check='credentials'."""
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.check == "credentials"


def test_check1_failure_prevents_subsequent_checks(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Credential failure stops validation — vectors.describe_index is never called."""
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    spy = mocker.spy(vectors_client, "describe_index")
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert spy.call_count == 0


# ── Check 2: Write prefix access ───────────────────────────────────────────────


def test_check2_write_access_denied_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Write probe raises non-credential error → StartupValidationError check='write_prefix'."""
    mocker.patch.object(s3_client, "put_object", side_effect=PermissionError("write denied"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.check == "write_prefix"


def test_check2_read_access_denied_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Write probe succeeds but read fails → StartupValidationError check='write_prefix'."""
    mocker.patch.object(s3_client, "get_object", side_effect=KeyError("probe key"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.check == "write_prefix"


# ── Check 3: Read prefix access ────────────────────────────────────────────────


def test_check3_read_prefix_not_readable_raises_startup_error(
    settings_with_read_prefix: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """list_objects raises for foreign prefix → StartupValidationError check='read_prefix'."""
    mocker.patch.object(s3_client, "list_objects", side_effect=PermissionError("list denied"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )
    assert exc_info.value.check == "read_prefix"


def test_check3_skipped_when_no_read_prefixes(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """No READ_PREFIXES configured → check 3 is skipped, no error."""
    assert settings.read_prefixes_list == []
    bedrock = FakeBedrockClient()
    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


# ── Check 4: Vector index existence ───────────────────────────────────────────


def test_check4_index_missing_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_no_index: VectorsClientImpl,
) -> None:
    """describe_index raises VectorIndexNotFoundError → StartupValidationError."""
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings,
            s3=s3_client,
            vectors=vectors_client_no_index,
            bedrock=bedrock,
        )
    assert exc_info.value.check == "vector_index"


# ── Check 5: Embedding model dimension vs index dimension ─────────────────────


def test_check5_dimension_mismatch_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Default BEDROCK_EMBEDDING_DIMENSIONS=1024 but index reports 512 → mismatch error."""
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": 512})
    bedrock = FakeBedrockClient(dimension=1024)
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.check == "vector_index_dimension"
    assert "512" in exc_info.value.message
    assert "1024" in exc_info.value.message


def test_check5_passes_when_dimensions_match(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS=1024 (default) and index=1024 → passes."""
    bedrock = FakeBedrockClient(dimension=1024)
    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


def test_check5_no_bedrock_embed_call_ever(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Check 5 never calls bedrock.embed — dimension comes from settings."""
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(bedrock, "embed")
    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert spy.call_count == 0, "bedrock.embed must never be called during startup"


# ── Credential error mid-startup propagates ────────────────────────────────────


def test_credential_error_in_check3_propagates(
    settings_with_read_prefix: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """CredentialError raised during check 3 propagates as-is (not wrapped)."""
    mocker.patch.object(
        s3_client,
        "list_objects",
        side_effect=CredentialError(
            message="Creds expired mid-session",
            service="s3",
            original=Exception("expired"),
        ),
    )
    bedrock = FakeBedrockClient()
    with pytest.raises(CredentialError):
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )


# ── Check 5: BEDROCK_EMBEDDING_DIMENSIONS override ────────────────────────────


def test_check5_explicit_dimensions_override_skips_registry_and_probe(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS=2048 with index reporting 2048 → passes; no embed call."""
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "2048")
    settings_custom = Settings()
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": 2048})

    bedrock = FakeBedrockClient(dimension=2048)
    spy = mocker.spy(bedrock, "embed")
    validate_startup(
        settings=settings_custom, s3=s3_client, vectors=vectors_client, bedrock=bedrock
    )
    assert spy.call_count == 0, "bedrock.embed must never be called during startup"


def test_check5_explicit_dimensions_override_mismatch_raises(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS=512 but index reports 2048 → mismatch error."""
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "512")
    settings_custom = Settings()
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": 2048})
    bedrock = FakeBedrockClient(dimension=512)
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_custom, s3=s3_client, vectors=vectors_client, bedrock=bedrock
        )
    assert exc_info.value.check == "vector_index_dimension"
    assert "512" in exc_info.value.message
    assert "2048" in exc_info.value.message


# ── Spec 05: Exception chaining (__cause__) ───────────────────────────────────


def test_check2_write_probe_failure_chains_cause(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Write probe raises → __cause__ is the original exception."""
    mocker.patch.object(s3_client, "put_object", side_effect=PermissionError("write denied"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_check2_delete_probe_failure_logs_warning_not_raises(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Delete probe failure logs a warning but does NOT raise StartupValidationError."""
    mocker.patch.object(s3_client, "delete_object", side_effect=PermissionError("delete denied"))
    bedrock = FakeBedrockClient()
    with caplog.at_level(logging.WARNING, logger="cairn_mcp.startup"):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert any("_cairn_mcp_startup_probe" in r.message for r in caplog.records)


def test_check3_read_prefix_failure_chains_cause(
    settings_with_read_prefix: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Read-prefix probe raises → __cause__ is the original exception."""
    mocker.patch.object(s3_client, "list_objects", side_effect=PermissionError("list denied"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_check4_vector_index_missing_chains_cause(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client_no_index: VectorsClientImpl,
) -> None:
    """VectorIndexNotFoundError → __cause__ is the original exception."""
    from cairn_mcp.errors import VectorIndexNotFoundError

    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings,
            s3=s3_client,
            vectors=vectors_client_no_index,
            bedrock=bedrock,
        )
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, VectorIndexNotFoundError)


# ── Spec 16: Bad dimension string ─────────────────────────────────────────────


def test_check5_nan_dimension_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """describe_index returns dimensions='nan' → StartupValidationError."""
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": "nan"})
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert "nan" in exc_info.value.message.lower()


def test_check5_none_dimension_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """describe_index returns dimensions=None → StartupValidationError."""
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": None})
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


def test_check1_credential_failure_chains_cause(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """CredentialError in check 1 → __cause__ is the original exception."""
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=PermissionError("no creds"),
        ),
    )
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, CredentialError)

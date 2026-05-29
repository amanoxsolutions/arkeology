"""Unit tests for the startup validation sequence.

All five checks are tested via fake clients — no real AWS calls are made.
Tests verify the correct StartupValidationError check field and that failing
checks prevent subsequent checks from running.

Written before startup.py existed (TDD Red state).
"""

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
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


def test_all_checks_pass(settings: Settings) -> None:
    """All healthy fakes → validate_startup returns None with no exception."""
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=1024)
    bedrock = FakeBedrockClient(dimension=1024)
    result = validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert result is None


# ── Check 1: Credential check ──────────────────────────────────────────────────


def test_check1_credential_failure_raises_startup_error(settings: Settings) -> None:
    """S3 credential failure → StartupValidationError with check='credentials'."""
    s3 = FakeS3Client()
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "credentials"


def test_check1_failure_prevents_subsequent_checks(settings: Settings) -> None:
    """Credential failure stops validation — vectors.describe_index is never called."""
    s3 = FakeS3Client()
    s3.set_credential_failure(True)

    call_tracker: list[str] = []

    class TrackingVectorsClient(FakeVectorsClient):
        def describe_index(self) -> dict:  # type: ignore[override]
            call_tracker.append("describe_index")
            return super().describe_index()

    vectors = TrackingVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError):
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert "describe_index" not in call_tracker


# ── Check 2: Write prefix access ───────────────────────────────────────────────


def test_check2_write_access_denied_raises_startup_error(settings: Settings) -> None:
    """Write probe raises non-credential error → StartupValidationError check='write_prefix'."""

    class WriteDeniedS3(FakeS3Client):
        def put_object(self, key: str, body: str, metadata: dict) -> None:  # type: ignore[override]
            if "_cairn_mcp_startup_probe" in key:
                raise PermissionError("write denied")
            super().put_object(key, body, metadata)

    s3 = WriteDeniedS3()
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "write_prefix"


def test_check2_read_access_denied_raises_startup_error(settings: Settings) -> None:
    """Write probe succeeds but read fails → StartupValidationError check='write_prefix'."""

    class ReadDeniedS3(FakeS3Client):
        def get_object(self, key: str) -> str:
            if "_cairn_mcp_startup_probe" in key:
                raise KeyError(key)
            return super().get_object(key)

    s3 = ReadDeniedS3()
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "write_prefix"


# ── Check 3: Read prefix access ────────────────────────────────────────────────


def test_check3_read_prefix_not_readable_raises_startup_error(
    settings_with_read_prefix: Settings,
) -> None:
    """list_objects raises for foreign prefix → StartupValidationError check='read_prefix'."""

    class ListDeniedS3(FakeS3Client):
        def list_objects(self, prefix: str) -> list[str]:
            if prefix == "network/":
                raise PermissionError("list denied")
            return super().list_objects(prefix)

    s3 = ListDeniedS3()
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )
    assert exc_info.value.check == "read_prefix"


def test_check3_skipped_when_no_read_prefixes(settings: Settings) -> None:
    """No READ_PREFIXES configured → check 3 is skipped, no error."""
    assert settings.read_prefixes_list == []
    s3 = FakeS3Client()
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    # Should not raise
    validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)


# ── Check 4: Vector index existence ───────────────────────────────────────────


def test_check4_index_missing_raises_startup_error(settings: Settings) -> None:
    """describe_index raises VectorIndexNotFoundError → StartupValidationError."""
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(index_missing=True)
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "vector_index"


# ── Check 5: Embedding model dimension vs index dimension ─────────────────────


def test_check5_dimension_mismatch_raises_startup_error(settings: Settings) -> None:
    """Index dim=512 but Titan v2 expects 1024 → dimension mismatch error."""
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=512)
    bedrock = FakeBedrockClient(dimension=1024)
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "vector_index_dimension"
    # Both dimensions should be mentioned in the message
    assert "512" in exc_info.value.message
    assert "1024" in exc_info.value.message


def test_check5_passes_known_model_registry(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Titan model in registry, index dim=1024 → no bedrock.embed call needed."""
    # Titan v2 has dimension 1024 in registry → no probe needed
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=1024)

    embed_called: list[bool] = []

    class TrackingBedrock(FakeBedrockClient):
        def embed(self, text: str, model_id: str) -> list[float]:
            embed_called.append(True)
            return super().embed(text, model_id)

    bedrock = TrackingBedrock(dimension=1024)
    validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)
    assert not embed_called, "Known model should not trigger a probe embed call"


def test_check5_passes_unknown_model_uses_probe(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown model → probe embed call used to determine dimension."""
    monkeypatch.setenv("BEDROCK_EMBEDDING_MODEL", "custom-model:v1")
    settings_custom = Settings()

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=1024)
    bedrock = FakeBedrockClient(dimension=1024)
    # Should pass: probe returns 1024-dim vector, index is 1024
    validate_startup(settings=settings_custom, s3=s3, vectors=vectors, bedrock=bedrock)


def test_check5_unknown_model_dimension_mismatch_raises(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown model probe returns 512-dim, index is 1024 → mismatch error."""
    monkeypatch.setenv("BEDROCK_EMBEDDING_MODEL", "custom-model:v1")
    settings_custom = Settings()

    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=1024)
    bedrock = FakeBedrockClient(dimension=512)  # probe will return 512-dim vector
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings_custom, s3=s3, vectors=vectors, bedrock=bedrock)
    assert exc_info.value.check == "vector_index_dimension"


# ── Credential error mid-startup propagates ────────────────────────────────────


def test_credential_error_in_check3_propagates(
    settings_with_read_prefix: Settings,
) -> None:
    """CredentialError raised during check 3 propagates as-is (not wrapped)."""

    class CredFailAfterCheck2(FakeS3Client):
        _call_count = 0

        def list_objects(self, prefix: str) -> list[str]:
            self._call_count += 1
            if prefix == "network/":
                raise CredentialError(
                    message="Creds expired mid-session",
                    service="s3",
                    original=Exception("expired"),
                )
            return super().list_objects(prefix)

    s3 = CredFailAfterCheck2()
    vectors = FakeVectorsClient()
    bedrock = FakeBedrockClient()
    with pytest.raises(CredentialError):
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

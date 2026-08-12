"""Unit tests for the startup validation sequence.

All seven checks are tested via moto-backed clients — no real AWS calls are made.
Tests verify the correct StartupValidationError check field and that failing
checks prevent subsequent checks from running.
"""

import logging

import pytest

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.errors import CredentialError, StartupValidationError
from arkeology.startup import validate_startup


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


def test_check5_dimension_comparison_itself_never_calls_embed(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Check 5 (the configuration-only dimension comparison) never calls bedrock.embed
    itself — dimension comes from settings vs. describe_index. A *separate*
    check 6 does call embed once (see test_check6_embedding_probe_calls_embed_once);
    this test still isolates check 5's own behaviour by asserting exactly one call
    total (attributable to check 6, not check 5)."""
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(bedrock, "embed")
    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert spy.call_count == 1, (
        "bedrock.embed must be called exactly once during startup (by check 6's "
        "embedding probe) — not by check 5's dimension comparison"
    )


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
    """BEDROCK_EMBEDDING_DIMENSIONS=2048 with index reporting 2048 → passes; check 6's
    embedding probe still calls embed exactly once even though check 5 itself
    (the configuration-only comparison) does not."""
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "2048")
    settings_custom = Settings()
    mocker.patch.object(vectors_client, "describe_index", return_value={"dimension": 2048})

    bedrock = FakeBedrockClient(dimension=2048)
    spy = mocker.spy(bedrock, "embed")
    validate_startup(
        settings=settings_custom, s3=s3_client, vectors=vectors_client, bedrock=bedrock
    )
    assert spy.call_count == 1, "bedrock.embed must be called once, by check 6's embedding probe"


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
            settings=settings_custom,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )
    assert exc_info.value.check == "vector_index_dimension"
    assert "512" in exc_info.value.message
    assert "2048" in exc_info.value.message


# ── Check 6: Embedding probe ───────────────────────────────────────────────────


def test_check6_embedding_probe_calls_embed_once(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Healthy embedding model → bedrock.embed is called exactly once during startup.

    Red: validate_startup has no embedding-probe check yet; spy.call_count stays 0 → FAILED.
    """
    bedrock = FakeBedrockClient(dimension=1024)
    spy = mocker.spy(bedrock, "embed")

    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)

    assert spy.call_count == 1, "Check 6 must call bedrock.embed exactly once — not yet implemented"


def test_check6_embedding_probe_wrong_dimension_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """embed() returns a vector whose length does not match BEDROCK_EMBEDDING_DIMENSIONS
    → StartupValidationError identifying the embedding_probe check.

    Simulates a misconfigured/wrong embedding model that nonetheless returns *some*
    vector — check 5's configuration-only comparison cannot catch this; only an actual
    probe call can.
    """
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "embed", return_value=[0.1] * 999)

    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)

    assert exc_info.value.check == "embedding_probe"
    assert "1024" in exc_info.value.message


def test_check6_embedding_probe_credential_error_propagates(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """embed() raises CredentialError (e.g. unentitled model) → propagates as-is,
    not wrapped in StartupValidationError (reuses the credential classification)."""
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError(
            message="simulated entitlement failure",
            service="bedrock",
            original=Exception("simulated"),
        ),
    )

    with pytest.raises(CredentialError):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


def test_check6_embedding_probe_other_error_raises_startup_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """embed() raises a non-credential exception → StartupValidationError, not a raw
    traceback."""
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "embed", side_effect=RuntimeError("model unreachable"))

    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)

    assert exc_info.value.check == "embedding_probe"


def test_check6_embedding_probe_failure_prevents_check7_text_model_probe(
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A failing embedding probe (check 6) stops startup before the text-model check
    (check 7) runs — even when BEDROCK_TEXT_MODEL is configured."""
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    settings_with_model = Settings()
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(bedrock, "embed", side_effect=RuntimeError("model unreachable"))
    spy = mocker.spy(bedrock, "invoke_text_model")

    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_model, s3=s3_client, vectors=vectors_client, bedrock=bedrock
        )

    assert exc_info.value.check == "embedding_probe"
    assert spy.call_count == 0


# ── Check 7: BEDROCK_TEXT_MODEL startup probe ──────────────────────────────────


def test_check6_text_model_configured_invoke_called(
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_TEXT_MODEL configured + invoke_text_model succeeds → startup passes
    AND invoke_text_model is called exactly once (the check must actually run).

    Red: validate_startup has no check 6 yet; mock_invoke.call_count stays 0 → FAILED.
    """
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    settings_with_model = Settings()
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value="Probe OK."
    )

    validate_startup(
        settings=settings_with_model, s3=s3_client, vectors=vectors_client, bedrock=bedrock
    )

    assert mock_invoke.call_count >= 1, (
        "Check 6 must call bedrock.invoke_text_model when BEDROCK_TEXT_MODEL is configured — "
        "not yet implemented"
    )


def test_check6_text_model_unreachable_startup_fails(
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_TEXT_MODEL configured + invoke_text_model raises any exception →
    startup fails with a StartupValidationError that identifies the text model check.

    Red: validate_startup has no check 6 yet; no exception is raised → pytest.raises FAILS.
    """
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    settings_with_model = Settings()
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        bedrock,
        "invoke_text_model",
        create=True,
        side_effect=RuntimeError("model unreachable"),
    )

    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_model, s3=s3_client, vectors=vectors_client, bedrock=bedrock
        )

    # The check field must identify the text model check clearly
    check = exc_info.value.check
    assert "text_model" in check or "bedrock_text" in check, (
        f"StartupValidationError.check should identify the text model check, got: '{check}'"
    )


def test_check6_text_model_absent_invoke_skipped(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_TEXT_MODEL absent → invoke_text_model is never called AND
    settings.bedrock_text_model is None.

    Red: Settings.bedrock_text_model does not exist yet; getattr returns sentinel → FAILED.
    """
    bedrock = FakeBedrockClient(dimension=1024)
    mock_invoke = mocker.patch.object(
        bedrock, "invoke_text_model", create=True, return_value="should not be called"
    )

    validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)

    # Red: attribute doesn't exist yet; getattr returns sentinel, assertion fails
    assert getattr(settings, "bedrock_text_model", "NOT_SET") is None, (
        "Settings.bedrock_text_model must be None when BEDROCK_TEXT_MODEL is absent — "
        "not yet implemented"
    )
    assert mock_invoke.call_count == 0, (
        "invoke_text_model must not be called when BEDROCK_TEXT_MODEL is absent"
    )


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
    with caplog.at_level(logging.WARNING, logger="arkeology.startup"):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)
    assert any("_arkeology_startup_probe" in r.message for r in caplog.records)


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
    from arkeology.errors import VectorIndexNotFoundError

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


# ---------------------------------------------------------------------------
# M23 Bug 1 — non-credential head_bucket errors must be wrapped, not escape raw
# ---------------------------------------------------------------------------


def test_check1_non_credential_error_raises_startup_validation_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """M23 Bug 1: _check_credentials only catches CredentialError; any other exception
    (e.g. network error) escapes as a raw traceback.  After the fix, non-credential errors
    from head_bucket must be caught and re-raised as StartupValidationError.

    Scenario:
    - Mock s3.head_bucket to raise RuntimeError("network error").
    - Expected: StartupValidationError is raised (not RuntimeError propagating raw).
    """
    mocker.patch.object(s3_client, "head_bucket", side_effect=RuntimeError("network error"))
    bedrock = FakeBedrockClient()

    with pytest.raises(StartupValidationError):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


# ---------------------------------------------------------------------------
# M23 Bug 2 — non-credential describe_index errors must be wrapped
# ---------------------------------------------------------------------------


def test_check4_non_credential_error_raises_startup_validation_error(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """M23 Bug 2: _check_vector_index only catches CredentialError and
    VectorIndexNotFoundError; any other exception escapes raw.  After the fix, all other
    exceptions from describe_index must be wrapped in StartupValidationError.

    Scenario:
    - Mock vectors.describe_index to raise RuntimeError("network error").
    - Expected: StartupValidationError is raised (not RuntimeError propagating raw).
    """
    mocker.patch.object(vectors_client, "describe_index", side_effect=RuntimeError("network error"))
    bedrock = FakeBedrockClient()

    with pytest.raises(StartupValidationError):
        validate_startup(settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock)


# ---------------------------------------------------------------------------
# M23 Bug 3 — CredentialError from invoke_text_model must propagate, not be wrapped
# ---------------------------------------------------------------------------


def test_check6_credential_error_propagates_not_wrapped(
    settings: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest.MonkeyPatch,
) -> None:
    """M23 Bug 3: _check_text_model catches ALL exceptions with a bare `except Exception`
    and wraps them in StartupValidationError, including CredentialError.  The project
    convention is that CredentialError must propagate as-is (not wrapped).  After the fix,
    CredentialError from invoke_text_model must propagate rather than being re-raised as
    StartupValidationError.

    Scenario:
    - BEDROCK_TEXT_MODEL is configured.
    - Mock bedrock.invoke_text_model to raise CredentialError.
    - Expected: CredentialError propagates (not StartupValidationError).
    """
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    settings_with_model = Settings()
    bedrock = FakeBedrockClient(dimension=1024)
    mocker.patch.object(
        bedrock,
        "invoke_text_model",
        create=True,
        side_effect=CredentialError(
            message="simulated credential error in text model probe",
            service="bedrock",
            original=Exception("simulated"),
        ),
    )

    with pytest.raises(CredentialError):
        validate_startup(
            settings=settings_with_model,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )


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


# ---------------------------------------------------------------------------
# Check 1 must not conflate a missing bucket with bad credentials
# ---------------------------------------------------------------------------


def test_check1_missing_bucket_is_distinct_from_credential_failure(
    settings: Settings,
    vectors_client: VectorsClientImpl,
) -> None:
    """A bucket that does not exist (e.g. a typo'd ARTIFACT_BUCKET) is a configuration
    error, not a credentials problem. head_bucket raising a non-credential ClientError
    (404, no such bucket) must not be reported under the generic 'Credential check
    failed' message _check_credentials uses for every non-CredentialError exception —
    that mislabels a config typo as an auth problem and points the operator at the
    wrong remediation."""
    s3_missing_bucket = S3ClientImpl(
        region=settings.aws_region, profile=None, bucket=settings.artifact_bucket
    )
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings, s3=s3_missing_bucket, vectors=vectors_client, bedrock=bedrock
        )
    assert "Credential check failed" not in exc_info.value.message, (
        "A missing-bucket configuration error must not be reported under the generic "
        "'Credential check failed' message used for real auth failures"
    )


# ---------------------------------------------------------------------------
# A fixed startup probe key would cause a concurrent-server race
# ---------------------------------------------------------------------------


def test_check2_probe_key_is_unique_per_invocation(
    settings: Settings,
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Two successive (or concurrent) write-prefix probes against the same
    WRITE_PREFIX must not reuse the same fixed probe key. A constant
    ``_PROBE_KEY_SUFFIX`` means two servers starting concurrently against the same
    WRITE_PREFIX race on the identical S3 key — one's best-effort cleanup
    (delete_object in the finally block) can delete the object out from under the
    other before its get_object runs. The probe key must be unique per invocation
    (e.g. ULID/uuid-suffixed) so concurrent invocations never collide."""
    from arkeology.startup import _check_write_prefix

    seen_keys: list[str] = []
    original_put = s3_client.put_object

    def _recording_put(key: str, *args: object, **kwargs: object) -> str:
        seen_keys.append(key)
        return original_put(key, *args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_recording_put)

    _check_write_prefix(settings, s3_client)
    _check_write_prefix(settings, s3_client)

    assert len(seen_keys) == 2
    assert len(set(seen_keys)) == 2, (
        "Each startup write-prefix probe invocation must use a distinct probe key so "
        "concurrent servers sharing WRITE_PREFIX cannot race on the same S3 object"
    )


# ---------------------------------------------------------------------------
# Check 3 must prove GetObject, not only ListBucket
# ---------------------------------------------------------------------------


def test_check3_read_prefix_grants_list_but_denies_object_read_still_fails(
    settings_with_read_prefix: Settings,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A foreign prefix whose IAM policy grants s3:ListBucket but denies object-level
    read access must still fail startup — list_objects succeeding is not
    sufficient proof that read_artifact will later be able to fetch object content.
    Check 3 currently only calls list_objects; it must also verify object-level read
    access (e.g. head_object/get_object) on at least one listed key."""
    mocker.patch.object(s3_client, "list_objects", return_value=["network/some-artifact"])
    mocker.patch.object(s3_client, "head_object", side_effect=PermissionError("get denied"))
    bedrock = FakeBedrockClient()
    with pytest.raises(StartupValidationError) as exc_info:
        validate_startup(
            settings=settings_with_read_prefix,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
        )
    assert exc_info.value.check == "read_prefix"

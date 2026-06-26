"""Unit tests for cairn_mcp.errors — Spec 16 CairnError base class."""

from cairn_mcp.errors import (
    CredentialError,
    StartupValidationError,
    VectorIndexNotFoundError,
)


def test_credential_error_is_cairn_error() -> None:
    """CredentialError is a subclass of CairnError base."""
    err = CredentialError(message="expired", service="s3", original=Exception("x"))
    # After spec 16 implementation, CairnError will exist
    from cairn_mcp.errors import CairnError  # type: ignore[attr-defined]

    assert isinstance(err, CairnError)


def test_startup_validation_error_is_cairn_error() -> None:
    """StartupValidationError is a subclass of CairnError base."""
    err = StartupValidationError(check="credentials", message="bad creds")
    from cairn_mcp.errors import CairnError  # type: ignore[attr-defined]

    assert isinstance(err, CairnError)


def test_vector_index_not_found_error_is_cairn_error() -> None:
    """VectorIndexNotFoundError is a subclass of CairnError base."""
    err = VectorIndexNotFoundError(index_name="idx", bucket_name="bkt")
    from cairn_mcp.errors import CairnError  # type: ignore[attr-defined]

    assert isinstance(err, CairnError)


def test_configuration_error_is_cairn_error() -> None:
    """ConfigurationError is a subclass of CairnError."""
    from cairn_mcp.errors import CairnError, ConfigurationError

    err = ConfigurationError(message="bad config", fields=["BEDROCK_EMBEDDING_MODEL"])
    assert isinstance(err, CairnError)


def test_configuration_error_stores_message_and_fields() -> None:
    """ConfigurationError exposes message and fields attributes."""
    from cairn_mcp.errors import ConfigurationError

    err = ConfigurationError(
        message="Configuration error", fields=["BEDROCK_EMBEDDING_MODEL", "WRITE_PREFIX"]
    )
    assert err.message == "Configuration error"
    assert err.fields == ["BEDROCK_EMBEDDING_MODEL", "WRITE_PREFIX"]


def test_configuration_error_fields_defaults_to_empty_list() -> None:
    """ConfigurationError with no fields argument → fields == []."""
    from cairn_mcp.errors import ConfigurationError

    err = ConfigurationError(message="bad config")
    assert err.fields == []


def test_except_credential_error_still_catches() -> None:
    """except CredentialError still catches a CredentialError instance."""
    err = CredentialError(message="test", service="s3", original=Exception("x"))
    try:
        raise err
    except CredentialError as caught:
        assert caught is err

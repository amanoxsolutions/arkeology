"""Unit tests for arkeology.errors — Spec 16 ArkeologyError base class."""

from arkeology.errors import (
    CredentialError,
    StartupValidationError,
    VectorIndexNotFoundError,
)


def test_credential_error_is_arkeology_error() -> None:
    """CredentialError is a subclass of ArkeologyError base."""
    err = CredentialError(message="expired", service="s3", original=Exception("x"))
    # After spec 16 implementation, ArkeologyError will exist
    from arkeology.errors import ArkeologyError  # type: ignore[attr-defined]

    assert isinstance(err, ArkeologyError)


def test_startup_validation_error_is_arkeology_error() -> None:
    """StartupValidationError is a subclass of ArkeologyError base."""
    err = StartupValidationError(check="credentials", message="bad creds")
    from arkeology.errors import ArkeologyError  # type: ignore[attr-defined]

    assert isinstance(err, ArkeologyError)


def test_vector_index_not_found_error_is_arkeology_error() -> None:
    """VectorIndexNotFoundError is a subclass of ArkeologyError base."""
    err = VectorIndexNotFoundError(index_name="idx", bucket_name="bkt")
    from arkeology.errors import ArkeologyError  # type: ignore[attr-defined]

    assert isinstance(err, ArkeologyError)


def test_configuration_error_is_arkeology_error() -> None:
    """ConfigurationError is a subclass of ArkeologyError."""
    from arkeology.errors import ArkeologyError, ConfigurationError

    err = ConfigurationError(message="bad config", fields=["BEDROCK_EMBEDDING_MODEL"])
    assert isinstance(err, ArkeologyError)


def test_configuration_error_stores_message_and_fields() -> None:
    """ConfigurationError exposes message and fields attributes."""
    from arkeology.errors import ConfigurationError

    err = ConfigurationError(
        message="Configuration error", fields=["BEDROCK_EMBEDDING_MODEL", "WRITE_PREFIX"]
    )
    assert err.message == "Configuration error"
    assert err.fields == ["BEDROCK_EMBEDDING_MODEL", "WRITE_PREFIX"]


def test_configuration_error_fields_defaults_to_empty_list() -> None:
    """ConfigurationError with no fields argument → fields == []."""
    from arkeology.errors import ConfigurationError

    err = ConfigurationError(message="bad config")
    assert err.fields == []


def test_except_credential_error_still_catches() -> None:
    """except CredentialError still catches a CredentialError instance."""
    err = CredentialError(message="test", service="s3", original=Exception("x"))
    try:
        raise err
    except CredentialError as caught:
        assert caught is err


def test_annotation_not_found_error_is_a_key_error() -> None:
    """``AnnotationNotFoundError`` must be catchable as ``KeyError``.

    ``health_check``'s annotation probe and startup check 3's per-read-prefix probe
    both ``except KeyError`` to mean "not found, so the call was permitted", and the
    frozen acceptance criteria for the annotation client say it raises ``KeyError``.
    Subclassing is what keeps all of that true without editing any of them.
    """
    from arkeology.errors import AnnotationNotFoundError

    assert issubclass(AnnotationNotFoundError, KeyError)
    try:
        raise AnnotationNotFoundError("artifacts/a.md")
    except KeyError as caught:
        assert isinstance(caught, AnnotationNotFoundError)


def test_object_not_found_error_is_a_key_error() -> None:
    """``ObjectNotFoundError`` must be catchable as ``KeyError``, for the same reason."""
    from arkeology.errors import ObjectNotFoundError

    assert issubclass(ObjectNotFoundError, KeyError)
    try:
        raise ObjectNotFoundError("artifacts/a.md")
    except KeyError as caught:
        assert isinstance(caught, ObjectNotFoundError)


def test_the_two_not_found_types_are_not_each_other() -> None:
    """The distinction is the whole point: catching one must not catch the other.

    ``annotations._read_one`` catches ``AnnotationNotFoundError`` alone and returns
    ``[]``. If ``ObjectNotFoundError`` were a subclass of it, a deleted object would
    once again read as an artifact that genuinely has no links.
    """
    from arkeology.errors import AnnotationNotFoundError, ObjectNotFoundError

    assert not issubclass(ObjectNotFoundError, AnnotationNotFoundError)
    assert not issubclass(AnnotationNotFoundError, ObjectNotFoundError)

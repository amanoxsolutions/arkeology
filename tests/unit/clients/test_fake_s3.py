"""Unit tests for FakeS3Client — full interface coverage."""

import pytest

from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.errors import CredentialError


def test_put_get_round_trip() -> None:
    """put_object then get_object returns the same content."""
    client = FakeS3Client()
    client.put_object("artifacts/foo.md", "hello world", {"type": "review"})
    assert client.get_object("artifacts/foo.md") == "hello world"


def test_get_object_missing_key_raises_key_error() -> None:
    """get_object on absent key raises KeyError."""
    client = FakeS3Client()
    with pytest.raises(KeyError):
        client.get_object("nonexistent/key.md")


def test_head_object_missing_key_raises_key_error() -> None:
    """head_object on absent key raises KeyError."""
    client = FakeS3Client()
    with pytest.raises(KeyError):
        client.head_object("nonexistent/key.md")


def test_head_object_returns_metadata() -> None:
    """head_object returns stored metadata."""
    client = FakeS3Client()
    client.put_object("artifacts/bar.md", "content", {"type": "adr", "status": "active"})
    meta = client.head_object("artifacts/bar.md")
    assert meta["type"] == "adr"
    assert meta["status"] == "active"


def test_list_objects_returns_matching_keys() -> None:
    """list_objects with prefix returns only matching keys."""
    client = FakeS3Client()
    client.put_object("team/review-001.md", "a", {})
    client.put_object("team/review-002.md", "b", {})
    client.put_object("other/adr-001.md", "c", {})
    result = client.list_objects("team/")
    assert sorted(result) == ["team/review-001.md", "team/review-002.md"]


def test_list_objects_returns_empty_when_no_match() -> None:
    """list_objects returns empty list when no keys match prefix."""
    client = FakeS3Client()
    client.put_object("team/review-001.md", "a", {})
    result = client.list_objects("other/")
    assert result == []


def test_head_bucket_succeeds() -> None:
    """head_bucket succeeds when credentials are valid."""
    client = FakeS3Client()
    client.head_bucket("my-bucket")  # should not raise


def test_delete_object_removes_key() -> None:
    """delete_object removes the key; subsequent get_object raises KeyError."""
    client = FakeS3Client()
    client.put_object("artifacts/foo.md", "content", {})
    client.delete_object("artifacts/foo.md")
    with pytest.raises(KeyError):
        client.get_object("artifacts/foo.md")


def test_delete_object_missing_key_does_not_raise() -> None:
    """delete_object on absent key does not raise."""
    client = FakeS3Client()
    client.delete_object("nonexistent/key.md")  # should not raise


def test_credential_failure_put_object() -> None:
    """put_object raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.put_object("artifacts/foo.md", "content", {})


def test_credential_failure_get_object() -> None:
    """get_object raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.put_object("artifacts/foo.md", "content", {})
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.get_object("artifacts/foo.md")


def test_credential_failure_head_object() -> None:
    """head_object raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.head_object("artifacts/foo.md")


def test_credential_failure_list_objects() -> None:
    """list_objects raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.list_objects("artifacts/")


def test_credential_failure_head_bucket() -> None:
    """head_bucket raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.head_bucket("my-bucket")


def test_credential_failure_delete_object() -> None:
    """delete_object raises CredentialError when credential failure is set."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError):
        client.delete_object("artifacts/foo.md")


def test_credential_failure_can_be_cleared() -> None:
    """Credential failure can be cleared; subsequent calls succeed."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    client.set_credential_failure(False)
    client.put_object("artifacts/foo.md", "content", {})  # should not raise


# ---------------------------------------------------------------------------
# Spec 01 — Missing error codes + NoCredentialsError → CredentialError
# ---------------------------------------------------------------------------


def test_credential_error_message_contains_service() -> None:
    """CredentialError from fake S3 mentions 's3' as the service (spec 17)."""
    client = FakeS3Client()
    client.set_credential_failure(True)
    with pytest.raises(CredentialError) as exc_info:
        client.get_object("artifacts/foo.md")
    assert exc_info.value.service == "s3"


# ---------------------------------------------------------------------------
# Spec 06 — Lexicographic order + 403 handling
# ---------------------------------------------------------------------------


def test_list_objects_lexicographic_order() -> None:
    """list_objects returns keys in lexicographic order."""
    client = FakeS3Client()
    client.put_object("b/key", "b", {})
    client.put_object("a/key", "a", {})
    client.put_object("c/key", "c", {})
    result = client.list_objects("")
    assert result == ["a/key", "b/key", "c/key"]


def test_list_objects_empty() -> None:
    """list_objects on empty store returns []."""
    client = FakeS3Client()
    assert client.list_objects("any-prefix/") == []

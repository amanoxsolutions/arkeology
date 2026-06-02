"""Unit tests for S3ClientImpl and VectorsClientImpl batch operations.

Uses the `s3_client` / `vectors_client` fixtures from conftest (moto-backed).
"""

import botocore.exceptions
import pytest

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.errors import CredentialError

# ---------------------------------------------------------------------------
# S3ClientImpl — metadata ASCII sanitization
# ---------------------------------------------------------------------------


def test_put_object_ascii_metadata_unchanged(s3_client: S3ClientImpl) -> None:
    """ASCII metadata values are stored and retrieved unchanged (baseline)."""
    metadata = {"title": "Plain ASCII Title", "artifact_type": "adr"}
    s3_client.put_object(key="test/plain.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/plain.md")
    assert stored["title"] == "Plain ASCII Title"
    assert stored["artifact_type"] == "adr"


def test_put_object_unicode_em_dash_sanitized(s3_client: S3ClientImpl) -> None:
    """Metadata with an em dash (U+2014) succeeds; stored title drops the em dash."""
    metadata = {"title": "A title \u2014 with em dash", "artifact_type": "adr"}
    # Must not raise ParamValidationError
    s3_client.put_object(key="test/emdash.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/emdash.md")
    assert "\u2014" not in stored["title"]
    assert "title" in stored["title"].lower() or "A title" in stored["title"]


def test_put_object_accented_letters_normalized(s3_client: S3ClientImpl) -> None:
    """Metadata with accented letters (café) succeeds; é is normalized to e."""
    metadata = {"title": "caf\u00e9", "artifact_type": "note"}
    s3_client.put_object(key="test/accented.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/accented.md")
    assert stored["title"] == "cafe"


# ---------------------------------------------------------------------------
# T26 — VectorsClientImpl.put_vectors_batch
# ---------------------------------------------------------------------------


def test_put_vectors_batch_single_chunk(
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch with 3 items → exactly one underlying put_vectors API call."""
    spy = mocker.spy(vectors_client._client, "put_vectors")
    items = [
        {
            "key": f"key-{i}",
            "vector": [0.1] * 1024,
            "metadata": {"artifact_id": f"art-{i}", "scope": "artifacts"},
        }
        for i in range(3)
    ]
    vectors_client.put_vectors_batch(items)
    assert spy.call_count == 1


def test_put_vectors_batch_chunked_at_500(
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch with 501 items → two underlying put_vectors calls (500 + 1)."""
    spy = mocker.spy(vectors_client._client, "put_vectors")
    items = [
        {
            "key": f"key-{i}",
            "vector": [0.1] * 1024,
            "metadata": {"artifact_id": f"art-{i}", "scope": "artifacts"},
        }
        for i in range(501)
    ]
    vectors_client.put_vectors_batch(items)
    assert spy.call_count == 2


def test_put_vectors_batch_empty_list(
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch with empty list → no API call; no exception raised."""
    spy = mocker.spy(vectors_client._client, "put_vectors")
    vectors_client.put_vectors_batch([])
    assert spy.call_count == 0


def test_put_vectors_batch_credential_error(
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch raises CredentialError when the underlying call fails with credentials."""
    # Patch the boto3-level put_vectors to simulate expired credentials
    cred_exc = botocore.exceptions.ClientError(
        {
            "Error": {
                "Code": "InvalidClientTokenId",
                "Message": "The security token included in the request is invalid.",
            }
        },
        "PutVectors",
    )
    mocker.patch.object(vectors_client._client, "put_vectors", side_effect=cred_exc)
    items = [
        {
            "key": "k1",
            "vector": [0.1] * 1024,
            "metadata": {"artifact_id": "art-1", "scope": "artifacts"},
        }
    ]
    with pytest.raises(CredentialError):
        vectors_client.put_vectors_batch(items)

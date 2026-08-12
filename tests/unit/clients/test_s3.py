"""Unit tests for S3ClientImpl and VectorsClientImpl batch operations.

Uses the `s3_client` / `vectors_client` fixtures from conftest (moto-backed).
"""

import botocore.exceptions
import pytest

from arkeology.artifact import decode_metadata_value
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.errors import ArtifactCollisionError, CredentialError

# ---------------------------------------------------------------------------
# S3ClientImpl — metadata transport encoding (T55: lossless, not lossy ASCII-strip)
# ---------------------------------------------------------------------------


def test_put_object_ascii_metadata_unchanged(s3_client: S3ClientImpl) -> None:
    """ASCII metadata values are stored and retrieved unchanged (baseline)."""
    metadata = {"title": "Plain ASCII Title", "artifact_type": "adr"}
    s3_client.put_object(key="test/plain.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/plain.md")
    assert stored["title"] == "Plain ASCII Title"
    assert stored["artifact_type"] == "adr"


def test_put_object_unicode_em_dash_percent_encoded_lossless(s3_client: S3ClientImpl) -> None:
    """Metadata with an em dash (U+2014) succeeds; the stored (transport-encoded) value is
    ASCII-only but decodes back to the original em dash \u2014, which is preserved rather
    than dropped (T55 replaces the old NFKD-ASCII-strip, which silently destroyed non-Latin
    content)."""
    metadata = {"title": "A title \u2014 with em dash", "artifact_type": "adr"}
    # Must not raise ParamValidationError
    s3_client.put_object(key="test/emdash.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/emdash.md")
    stored["title"].encode("ascii")  # raises UnicodeEncodeError if non-ASCII leaked through
    assert decode_metadata_value(stored["title"]) == "A title \u2014 with em dash"


def test_put_object_accented_letters_percent_encoded_lossless(s3_client: S3ClientImpl) -> None:
    """Metadata with accented letters (caf\u00e9) round-trips losslessly: transport-encoded
    to ASCII on the wire, but decode_metadata_value recovers the original \u00e9, not a
    stripped 'e'."""
    metadata = {"title": "caf\u00e9", "artifact_type": "note"}
    s3_client.put_object(key="test/accented.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/accented.md")
    stored["title"].encode("ascii")  # raises UnicodeEncodeError if non-ASCII leaked through
    assert decode_metadata_value(stored["title"]) == "caf\u00e9"


def test_put_object_literal_percent_sign_round_trips(s3_client: S3ClientImpl) -> None:
    """A literal '%' in a metadata value (which collides with the escape character used for
    transport encoding) round-trips losslessly."""
    metadata = {"title": "100% done", "artifact_type": "adr"}
    s3_client.put_object(key="test/percent.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/percent.md")
    assert decode_metadata_value(stored["title"]) == "100% done"


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


# ---------------------------------------------------------------------------
# S3ClientImpl — head_object error mapping
# ---------------------------------------------------------------------------


def test_head_object_404_raises_key_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """head_object for a missing key (404) → KeyError (not-found semantics preserved)."""
    not_found_exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}},
        "HeadObject",
    )
    mocker.patch.object(s3_client._s3, "head_object", side_effect=not_found_exc)
    with pytest.raises(KeyError):
        s3_client.head_object("missing/key.md")


def test_head_object_403_raises_credential_error_not_key_error(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """head_object returning 403 (Access Denied) → CredentialError, not KeyError.

    S3 HEAD requests return HTTP 403 with no body when the caller lacks
    s3:GetObject permission.  This is a permission problem, not a missing key.
    """
    forbidden_exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}},
        "HeadObject",
    )
    mocker.patch.object(s3_client._s3, "head_object", side_effect=forbidden_exc)
    with pytest.raises(CredentialError):
        s3_client.head_object("some/key.md")


# ---------------------------------------------------------------------------
# A-2 — S3ClientImpl.put_object conditional-create mode (IfNoneMatch: "*")
# ---------------------------------------------------------------------------


def test_put_object_if_none_match_succeeds_for_new_key(s3_client: S3ClientImpl) -> None:
    """A conditional-create put against a key that does not yet exist succeeds normally."""
    s3_client.put_object(
        key="test/fresh.md", body="content", metadata={"title": "Fresh"}, if_none_match=True
    )
    assert s3_client.get_object("test/fresh.md") == "content"


def test_put_object_if_none_match_raises_collision_on_existing_key(
    s3_client: S3ClientImpl,
) -> None:
    """A conditional-create put against an already-existing key raises ArtifactCollisionError
    and leaves the existing object untouched (the S3 request is rejected atomically —
    moto 5.2.2 enforces IfNoneMatch on PutObject with HTTP 412 PreconditionFailed)."""
    s3_client.put_object(key="test/exists.md", body="original", metadata={})

    with pytest.raises(ArtifactCollisionError) as exc_info:
        s3_client.put_object(
            key="test/exists.md", body="replacement", metadata={}, if_none_match=True
        )

    assert exc_info.value.key == "test/exists.md"
    assert s3_client.get_object("test/exists.md") == "original"


def test_put_object_without_if_none_match_overwrites_existing_key(
    s3_client: S3ClientImpl,
) -> None:
    """Default behaviour (if_none_match=False) still performs an unconditional overwrite."""
    s3_client.put_object(key="test/overwrite.md", body="original", metadata={})
    s3_client.put_object(key="test/overwrite.md", body="replacement", metadata={})
    assert s3_client.get_object("test/overwrite.md") == "replacement"


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

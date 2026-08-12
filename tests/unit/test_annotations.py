"""Unit tests for arkeology.annotations — shared annotation encode/decode/apply/read helpers.

These helpers centralise the annotation-backed durable storage of the mutable link
fields (commit_refs, references) per ADR-011 (T47). They are consumed directly by
the write path (T47) and are designed to be reused, unmodified, by reconcile_index
(T48) and link_metadata (T49).
"""

import pytest

from arkeology.annotations import (
    COMMIT_REFS_ANNOTATION,
    REFERENCES_ANNOTATION,
    apply_link_annotations,
    decode_link_list,
    encode_link_list,
    read_current_link_fields,
    read_link_annotations,
)
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.errors import ArtifactConflictError, CredentialError

# ---------------------------------------------------------------------------
# encode_link_list / decode_link_list
# ---------------------------------------------------------------------------


def test_encode_link_list_comma_joins_values() -> None:
    """encode_link_list(['a', 'b']) produces the comma-joined payload 'a,b'."""
    assert encode_link_list(["a", "b"]) == "a,b"


def test_encode_link_list_single_value_has_no_comma() -> None:
    """encode_link_list(['abc1234']) produces the bare value with no separator."""
    assert encode_link_list(["abc1234"]) == "abc1234"


def test_encode_link_list_empty_returns_empty_string() -> None:
    """encode_link_list([]) produces an empty string."""
    assert encode_link_list([]) == ""


def test_decode_link_list_splits_on_comma() -> None:
    """decode_link_list('a,b') round-trips back to ['a', 'b']."""
    assert decode_link_list("a,b") == ["a", "b"]


def test_decode_link_list_single_value() -> None:
    """decode_link_list('abc1234') round-trips back to ['abc1234']."""
    assert decode_link_list("abc1234") == ["abc1234"]


def test_decode_link_list_empty_string_returns_empty_list() -> None:
    """decode_link_list('') returns [] rather than [''] (empty payload, not one blank entry)."""
    assert decode_link_list("") == []


def test_decode_link_list_interior_double_comma_drops_empty_element() -> None:
    """A malformed/hand-edited payload with a double comma ('a,,b') must not surface
    a blank entry in the middle of the decoded list (defensive)."""
    assert decode_link_list("a,,b") == ["a", "b"]


def test_decode_link_list_trailing_comma_drops_empty_element() -> None:
    """A malformed/hand-edited payload with a trailing comma ('a,') must not surface
    a trailing blank entry (defensive)."""
    assert decode_link_list("a,") == ["a"]


# ---------------------------------------------------------------------------
# apply_link_annotations
# ---------------------------------------------------------------------------


def test_apply_link_annotations_writes_non_empty_fields(s3_client: S3ClientImpl) -> None:
    """Non-empty commit_refs/references are written and readable back as their
    comma-joined payload via the raw client."""
    s3_client.put_object(key="artifacts/a1.md", body="content", metadata={"title": "A1"})

    apply_link_annotations(
        s3_client,
        "artifacts/a1.md",
        commit_refs=["abc1234"],
        references=["a-1", "b-2"],
    )

    assert s3_client.get_object_annotation("artifacts/a1.md", COMMIT_REFS_ANNOTATION) == "abc1234"
    assert s3_client.get_object_annotation("artifacts/a1.md", REFERENCES_ANNOTATION) == "a-1,b-2"


def test_apply_link_annotations_deletes_empty_fields(s3_client: S3ClientImpl) -> None:
    """An empty list for a field deletes (rather than writes) its annotation — mirrors
    the vector-metadata omit-when-empty rule."""
    s3_client.put_object(key="artifacts/a2.md", body="content", metadata={"title": "A2"})
    s3_client.put_object_annotation("artifacts/a2.md", COMMIT_REFS_ANNOTATION, "stale")

    apply_link_annotations(s3_client, "artifacts/a2.md", commit_refs=[], references=[])

    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/a2.md", COMMIT_REFS_ANNOTATION)
    with pytest.raises(KeyError):
        s3_client.get_object_annotation("artifacts/a2.md", REFERENCES_ANNOTATION)


def test_apply_link_annotations_calls_put_for_non_empty_and_delete_for_empty(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """apply_link_annotations puts the non-empty field and deletes the empty one —
    verified by spying on the underlying client calls (not just the end state).
    Also asserts if_match defaults to None
    (unconditional) when the caller does not supply a compare-and-swap token."""
    s3_client.put_object(key="artifacts/a3.md", body="content", metadata={"title": "A3"})
    put_spy = mocker.spy(s3_client, "put_object_annotation")
    delete_spy = mocker.spy(s3_client, "delete_object_annotation")

    apply_link_annotations(s3_client, "artifacts/a3.md", commit_refs=["abc1234"], references=[])

    put_spy.assert_called_once_with(
        "artifacts/a3.md", COMMIT_REFS_ANNOTATION, "abc1234", if_match=None
    )
    delete_spy.assert_called_once_with("artifacts/a3.md", REFERENCES_ANNOTATION, if_match=None)


def test_apply_link_annotations_threads_if_match_to_both_calls(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """apply_link_annotations(if_match=...) passes the same token through to both
    the put- and delete-annotation calls it makes internally (ADR-011 decision 6)."""
    s3_client.put_object(key="artifacts/a3b.md", body="content", metadata={"title": "A3b"})
    token = s3_client.head_object("artifacts/a3b.md")["ETag"]
    put_spy = mocker.spy(s3_client, "put_object_annotation")
    delete_spy = mocker.spy(s3_client, "delete_object_annotation")

    apply_link_annotations(
        s3_client,
        "artifacts/a3b.md",
        commit_refs=["abc1234"],
        references=[],
        if_match=token,
    )

    put_spy.assert_called_once_with(
        "artifacts/a3b.md", COMMIT_REFS_ANNOTATION, "abc1234", if_match=token
    )
    delete_spy.assert_called_once_with("artifacts/a3b.md", REFERENCES_ANNOTATION, if_match=token)


def test_apply_link_annotations_stale_if_match_raises_conflict(
    s3_client: S3ClientImpl,
) -> None:
    """apply_link_annotations(if_match=<stale ETag>) raises ArtifactConflictError,
    propagated unchanged from the underlying client call."""
    s3_client.put_object(key="artifacts/a3c.md", body="content", metadata={"title": "A3c"})
    stale_etag = '"0000000000000000000000000000000"'

    with pytest.raises(ArtifactConflictError):
        apply_link_annotations(
            s3_client,
            "artifacts/a3c.md",
            commit_refs=["abc1234"],
            references=[],
            if_match=stale_etag,
        )


def test_apply_link_annotations_credential_error_propagates(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A CredentialError from put_object_annotation propagates unchanged — never
    swallowed or converted."""
    s3_client.put_object(key="artifacts/a4.md", body="content", metadata={"title": "A4"})
    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=CredentialError("expired", "s3", Exception("boom")),
    )

    with pytest.raises(CredentialError):
        apply_link_annotations(s3_client, "artifacts/a4.md", commit_refs=["abc1234"], references=[])


# ---------------------------------------------------------------------------
# read_link_annotations
# ---------------------------------------------------------------------------


def test_read_link_annotations_returns_values_when_present(s3_client: S3ClientImpl) -> None:
    """read_link_annotations returns the decoded (commit_refs, references) tuple when
    both annotations are present."""
    s3_client.put_object(key="artifacts/a5.md", body="content", metadata={"title": "A5"})
    apply_link_annotations(
        s3_client, "artifacts/a5.md", commit_refs=["abc1234"], references=["a-1"]
    )

    commit_refs, references = read_link_annotations(s3_client, "artifacts/a5.md")

    assert commit_refs == ["abc1234"]
    assert references == ["a-1"]


def test_read_link_annotations_returns_empty_lists_when_absent(s3_client: S3ClientImpl) -> None:
    """read_link_annotations returns ([], []) for an object with no annotations at all —
    covers both a never-annotated object and one whose annotations were cleared by an
    overwrite."""
    s3_client.put_object(key="artifacts/a6.md", body="content", metadata={"title": "A6"})

    commit_refs, references = read_link_annotations(s3_client, "artifacts/a6.md")

    assert commit_refs == []
    assert references == []


def test_read_link_annotations_credential_error_propagates(
    s3_client: S3ClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A CredentialError from get_object_annotation propagates unchanged."""
    s3_client.put_object(key="artifacts/a7.md", body="content", metadata={"title": "A7"})
    mocker.patch.object(
        s3_client,
        "get_object_annotation",
        side_effect=CredentialError("expired", "s3", Exception("boom")),
    )

    with pytest.raises(CredentialError):
        read_link_annotations(s3_client, "artifacts/a7.md")


# ---------------------------------------------------------------------------
# read_current_link_fields — vector-metadata side must union across ALL section
# vectors, not just the first
# ---------------------------------------------------------------------------


def test_read_current_link_fields_unions_vector_metadata_across_all_section_vectors(
    s3_client: S3ClientImpl,
    vectors_client_2: VectorsClientImpl,
) -> None:
    """An artifact with multiple section vectors, where a link field is only set on a
    NON-first section vector (in list_vectors_by_metadata's return order), must still
    have that value included in the union — sampling only the first vector's metadata
    silently drops link-field state living on any other section vector."""
    s3_client.put_object(key="artifacts/multi.md", body="content", metadata={"title": "Multi"})

    base_meta = {"artifact_id": "artifacts/multi.md", "scope": "artifacts"}
    vectors_client_2.put_vector("artifacts/multi.md#alpha", [0.1, 0.2], dict(base_meta))
    vectors_client_2.put_vector(
        "artifacts/multi.md#beta",
        [0.3, 0.4],
        {**base_meta, "commit_refs": ["abc1234"], "references": ["ref-1"]},
    )

    commit_refs, references = read_current_link_fields(
        s3_client, vectors_client_2, "artifacts/multi.md"
    )

    assert commit_refs == ["abc1234"]
    assert references == ["ref-1"]

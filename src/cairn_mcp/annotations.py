"""cairn_mcp.annotations — shared helpers for the annotation-backed durable copy of
the mutable link fields (``commit_refs``, ``references``).

ADR-011 moves the durable copy of ``commit_refs`` and ``references`` from
vector-metadata-only to S3 object annotations: a named payload, mutable in place via
``PutObjectAnnotation`` (unlike S3 user-defined metadata, which is immutable after
upload), that does not disturb the object body, its write-time timestamp, or its
embeddings.

This module centralises the annotation names, the comma-joined list encoding, and
the apply/read operations so the write path (T47), ``link_metadata`` (T49), and
``reconcile_index`` (T48) share one implementation rather than three divergent ones.
"""

from cairn_mcp.clients.interfaces import S3ClientInterface

# Annotation names — one annotation per field (ADR-011 decision 1).
COMMIT_REFS_ANNOTATION = "commit_refs"
REFERENCES_ANNOTATION = "references"


def encode_link_list(values: list[str]) -> str:
    """Encode a link-field list as its comma-joined annotation payload.

    Args:
        values: The list to encode (may be empty).

    Returns:
        The comma-joined payload. ``[]`` encodes to ``""``.
    """
    return ",".join(values)


def decode_link_list(payload: str) -> list[str]:
    """Decode a comma-joined annotation payload back into a list of strings.

    Args:
        payload: The raw annotation payload (may be empty).

    Returns:
        The decoded list. An empty payload decodes to ``[]`` (never ``[""]``).
    """
    if not payload:
        return []
    return payload.split(",")


def apply_link_annotations(
    s3: S3ClientInterface,
    key: str,
    *,
    commit_refs: list[str],
    references: list[str],
) -> None:
    """Write (or clear) the ``commit_refs`` / ``references`` annotations on an object.

    A non-empty list is written as its comma-joined payload; an empty list deletes
    the corresponding annotation — mirroring the vector-metadata omit-when-empty
    rule. ``delete_object_annotation`` is a silent no-op when the annotation is
    already absent, so this is safe to call unconditionally on every write.

    Args:
        s3: S3 client.
        key: S3 object key.
        commit_refs: Final (already merged, where applicable) commit_refs list.
        references: Final (already merged, where applicable) references list.

    Raises:
        CredentialError: If credentials are invalid or expired.
    """
    for name, values in (
        (COMMIT_REFS_ANNOTATION, commit_refs),
        (REFERENCES_ANNOTATION, references),
    ):
        if values:
            s3.put_object_annotation(key, name, encode_link_list(values))
        else:
            s3.delete_object_annotation(key, name)


def read_link_annotations(s3: S3ClientInterface, key: str) -> tuple[list[str], list[str]]:
    """Read the durable ``commit_refs`` / ``references`` annotations for an object.

    Args:
        s3: S3 client.
        key: S3 object key.

    Returns:
        ``(commit_refs, references)`` — each ``[]`` when the corresponding
        annotation is absent (covers both a never-annotated object and one whose
        annotations were cleared by a subsequent overwrite).

    Raises:
        CredentialError: If credentials are invalid or expired.
    """
    return (
        _read_one(s3, key, COMMIT_REFS_ANNOTATION),
        _read_one(s3, key, REFERENCES_ANNOTATION),
    )


def _read_one(s3: S3ClientInterface, key: str, annotation_name: str) -> list[str]:
    """Read and decode a single named annotation, defaulting to ``[]`` when absent."""
    try:
        payload = s3.get_object_annotation(key, annotation_name)
    except KeyError:
        return []
    return decode_link_list(payload)

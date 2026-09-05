"""arkeology.annotations — shared helpers for the annotation-backed durable copy of
the mutable link fields (``commit_refs``, ``references``).

ADR-011 moves the durable copy of ``commit_refs`` and ``references`` from
vector-metadata-only to S3 object annotations: a named payload, mutable in place via
``PutObjectAnnotation`` (unlike S3 user-defined metadata, which is immutable after
upload), that does not disturb the object body, its write-time timestamp, or its
embeddings.

This module centralises the annotation names, the comma-joined list encoding, and
the apply/read operations so the write path (T47), ``link_metadata`` (T49), and
``reconcile_index`` (T48) share one implementation rather than three divergent ones.

Annotations are the **sole source of truth** for both fields. The vector-metadata copy of
``commit_refs`` is a derived filter index — written so the index can answer "which
artifacts carry commit ref X" as a server-side filter clause, never read back as
authority. ``references`` is not written to vector metadata at all.

``read_link_annotations`` therefore raises rather than returning empty on a failed read:
every read-modify-write cycle on the link fields (an overwriting ``write_artifact``,
``archive_artifact``'s status re-PUT, ``reconcile_index``'s vector rebuild) writes the
value it read straight back, so an empty result caused by a transient failure would be
written over good data.
"""

from arkeology.clients.interfaces import S3ClientInterface

# Annotation names — one annotation per field (ADR-011 decision 1).
COMMIT_REFS_ANNOTATION = "commit_refs"
REFERENCES_ANNOTATION = "references"

# Bounded compare-and-swap retry count for every read-modify-write cycle on the durable
# link-field state (ADR-011 decision 6): write.py's overwrite path, link_metadata's
# per-artifact fetch-merge-reput, and archive_artifact's status re-PUT. "Roughly three
# attempts" per the frozen decision; shared here so the three call sites do not each
# define their own magic number.
CAS_MAX_ATTEMPTS = 3


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
        Empty elements from a malformed/hand-edited payload (e.g. a double or
        trailing comma) are dropped rather than surfaced as blank entries.
    """
    if not payload:
        return []
    return [item for item in payload.split(",") if item]


def merge_link_field(existing: list[str], supplied: list[str]) -> list[str]:
    """Merge ``supplied`` values into ``existing``, deduplicating and order-preserving.

    The single union rule for both mutable link fields, shared by ``link_metadata``'s
    fetch-merge-reput and ``reconcile_index``'s restore of the copy a failed annotation
    write recorded on its failure-log entry. Both combine two partial views of the same
    field and must never let one side drop a value the other holds.

    Args:
        existing: The current value of the field — typically the durable annotation
            value (:func:`read_link_annotations`), which is its sole source of truth.
        supplied: The values to merge in (may be empty, in which case the existing value
            is returned unchanged, only deduplicated).

    Returns:
        The merged, deduplicated, order-preserving list.
    """
    return list(dict.fromkeys(existing + supplied))


def apply_link_annotations(
    s3: S3ClientInterface,
    key: str,
    *,
    commit_refs: list[str],
    references: list[str],
    if_match: str | None = None,
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
        if_match: When set, threaded through to both the put- and delete-annotation
            calls as their ``if_match`` parameter (sent as boto3's ``ObjectIfMatch``)
            — the optimistic-concurrency compare-and-swap token captured from the
            preceding conditional object write (ADR-011 decision 6). ``None`` (the
            default) preserves today's unconditional behaviour.

    Raises:
        ArtifactConflictError: If ``if_match`` is set and does not match the
            object's current ETag (HTTP 412 PreconditionFailed) on either call.
        CredentialError: If credentials are invalid or expired.
    """
    for name, values in (
        (COMMIT_REFS_ANNOTATION, commit_refs),
        (REFERENCES_ANNOTATION, references),
    ):
        if values:
            s3.put_object_annotation(key, name, encode_link_list(values), if_match=if_match)
        else:
            s3.delete_object_annotation(key, name, if_match=if_match)


def read_link_annotations(s3: S3ClientInterface, key: str) -> tuple[list[str], list[str]]:
    """Read the durable ``commit_refs`` / ``references`` annotations for an object.

    This is the sole read path for the current link-field state. It never degrades a
    failure to ``[]``: an empty result means the annotations really are absent, so any
    failure — credential, annotation-unavailable, or transient — propagates to the
    caller instead of being written back over good data by a read-modify-write cycle.

    Args:
        s3: S3 client.
        key: S3 object key.

    Returns:
        ``(commit_refs, references)`` — each ``[]`` when the corresponding
        annotation is absent (covers both a never-annotated object and one whose
        annotations were cleared by a subsequent overwrite).

    Raises:
        AnnotationUnavailableError: If annotations are unavailable for this bucket or
            the caller lacks the required IAM permission (post-startup IAM drift — the
            startup gate rejects a deployment that never had them).
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

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

Neither store is sole authority for the current link-field state: an
annotation-unavailable deployment (graceful degrade) can hold values in vector metadata
only, and a partial dual-write can leave the annotation copy ahead of the vector copy.
``read_current_link_fields`` below
implements the operator-approved union-of-both-stores authority model — the current
state is always the order-preserving dedup union of both stores, so no read path ever
reduces the fields.
"""

import logging

from arkeology.clients.interfaces import S3ClientInterface, VectorsClientInterface
from arkeology.errors import CredentialError

logger = logging.getLogger(__name__)

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
        existing: The current value of the field — typically the order-preserving dedup
            union of both durable stores (:func:`read_current_link_fields`), so neither
            store is treated as sole authority.
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


def read_current_link_fields(
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    artifact_id: str,
) -> tuple[list[str], list[str]]:
    """Return the current ``commit_refs`` / ``references`` as the union of both stores.

    Per the operator-approved union-of-both-stores authority model, neither the S3
    annotation copy nor the S3 Vectors metadata copy is sole authority for the mutable
    link fields — the current state is the order-preserving dedup union of both. This
    closes two data-loss paths that existed when either store was treated as
    authoritative on its own:

    - An annotation-unavailable deployment (graceful degrade) holds link fields in
      vector metadata only; a naive annotation-only read reports them as absent, and a
      caller that rebuilds vector metadata from that (``reconcile_index``) would erase
      the only durable copy.
    - A partial dual-write (e.g. an interrupted ``link_metadata`` call) can leave the
      annotation copy ahead of the vector copy; a naive vector-only read would miss the
      newer annotation value and a subsequent overwrite would drop it (``PutObject``
      clears annotations).

    The annotation side degrades gracefully on failures that are not
    :class:`~arkeology.errors.CredentialError` (annotations are a feature-level concern
    per ADR-011 decision 5 — an unsupported region/bucket type, ``AccessDenied``, etc.
    must never abort the caller); a ``CredentialError`` is re-raised, never swallowed,
    because it signals a general authentication failure that is very likely to also
    break the surrounding operation and must not be silently treated as "no link
    fields".

    Args:
        s3: S3 client, used to read the durable annotation copy.
        vectors: S3 Vectors client, used to read the indexed vector-metadata copy.
        artifact_id: Full S3 key / vector-metadata ``artifact_id`` of the artifact.

    Returns:
        ``(commit_refs, references)`` — the order-preserving dedup union of the
        annotation values (first) and the vector-metadata values (second). Each is
        ``[]`` when the field is absent from both stores.

    Raises:
        CredentialError: If credentials are invalid or expired while reading either
            store.
    """
    try:
        annotation_commit_refs, annotation_references = read_link_annotations(s3, artifact_id)
    except CredentialError:
        raise
    except Exception:
        logger.warning(
            "Failed to read link annotations for %s; falling back to the vector-metadata "
            "copy only for this store",
            artifact_id,
            exc_info=True,
        )
        annotation_commit_refs, annotation_references = [], []

    vector_commit_refs, vector_references = _read_vector_link_fields(vectors, artifact_id)

    commit_refs = list(dict.fromkeys(annotation_commit_refs + vector_commit_refs))
    references = list(dict.fromkeys(annotation_references + vector_references))
    return commit_refs, references


def _read_vector_link_fields(
    vectors: VectorsClientInterface, artifact_id: str
) -> tuple[list[str], list[str]]:
    """Read the ``commit_refs`` / ``references`` currently indexed in vector metadata.

    Unions across ALL of the artifact's section vectors, not just the first key
    returned by ``list_vectors_by_metadata`` — a multi-section artifact indexes one
    vector per section, and a link field written by an earlier ``link_metadata`` call
    (or backfilled by ``reconcile_index``) may live on any one of them, not
    necessarily whichever key happens to sort first.

    Args:
        vectors: S3 Vectors client.
        artifact_id: The artifact's vector-metadata ``artifact_id`` (== S3 key).

    Returns:
        ``(commit_refs, references)`` — the order-preserving dedup union across every
        section vector's metadata. Each is ``[]`` when no vectors are indexed for this
        artifact yet, or when the field is absent from every fetched vector's metadata.

    Raises:
        CredentialError: If credentials are invalid or expired.
    """
    keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    if not keys:
        return [], []
    entries = vectors.get_vectors(keys, include_data=False)
    commit_refs: list[str] = []
    references: list[str] = []
    for entry in entries:
        metadata = entry.get("metadata", {})
        raw_commit_refs = metadata.get("commit_refs", [])
        raw_references = metadata.get("references", [])
        if isinstance(raw_commit_refs, list):
            commit_refs.extend(str(r) for r in raw_commit_refs)
        if isinstance(raw_references, list):
            references.extend(str(r) for r in raw_references)
    return list(dict.fromkeys(commit_refs)), list(dict.fromkeys(references))

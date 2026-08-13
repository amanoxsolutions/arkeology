"""Calibrates check_metadata_budgets's local filterable-metadata approximation against
AWS's real S3 Vectors PutVectors accounting.

Context (see docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-
and-self-heal.md and docs/specs/p12-t55-metadata-validation.md's "Budget nominal units"
Open Question): a real 57-file migration incident produced an artifact whose
``commit_refs``/``references`` payload passed the local ``json.dumps``-based
``check_metadata_budgets`` approximation (~1,722 measured bytes, under the local 2,048-byte
filterable-metadata threshold) but was rejected by the real AWS ``PutVectors`` call. This
file closes that named-but-never-run gap: it calls ``VectorsClientImpl.put_vector`` directly
against real AWS — bypassing ``check_metadata_budgets`` entirely — and binary-searches over
``commit_refs`` list length to find AWS's real rejection boundary, then compares it against
what the local approximation would have measured for the same payload.

This is a diagnostic/calibration test, not a regression guard: it does not assert a specific
byte count (AWS's internal accounting is not a contract), only that the boundary search
converges to a well-defined pass/fail edge and reports the real numbers via logging so a
human (or a future D2 implementation) can pick a calibrated buffer.

Run with ``-s --log-cli-level=INFO`` to see the calibration findings on stdout.
"""

from __future__ import annotations

import hashlib
import json
import logging

import botocore.exceptions
import pytest

from arkeology.artifact import NON_FILTERABLE_METADATA_KEYS, VECTOR_FILTERABLE_METADATA_MAX_BYTES
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings

logger = logging.getLogger(__name__)

# Sanity cap on the exponential search phase — real AWS boundary is expected in the low
# hundreds of entries at most (each ~43-byte JSON-encoded SHA1 hex string against a 2 KB
# budget); this only guards against an infinite loop if AWS's real behaviour is wildly
# different from what the ADR's incident data suggests.
_MAX_PROBE_ENTRIES = 8192


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Session-scoped Settings constructed after the top-level conftest's load_env and
    isolate_run_scope autouse fixtures have run."""
    return Settings()


@pytest.fixture(scope="session")
def vectors(settings: Settings) -> VectorsClientImpl:
    """Session-scoped real S3 Vectors client."""
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


def _sha1_commit_refs(n: int) -> list[str]:
    """``n`` distinct, realistic 40-hex-char git-SHA-shaped strings (SHA-1 hex digest is
    exactly 40 hex chars — the same shape as a real git commit SHA)."""
    return [hashlib.sha1(str(i).encode("utf-8")).hexdigest() for i in range(n)]


def _local_filterable_bytes(vector_metadata: dict[str, object]) -> int:
    """Reproduce check_metadata_budgets's filterable-subset byte measurement exactly,
    without calling it directly (it raises on breach instead of returning a count, so a
    passing payload's byte count can't be read off it). Uses the same
    NON_FILTERABLE_METADATA_KEYS classification the shipped guard uses, so this can never
    drift on *which* keys count — only reproduces the arithmetic already inlined in
    artifact.py:213-224.
    """
    filterable = {
        key: value
        for key, value in vector_metadata.items()
        if key not in NON_FILTERABLE_METADATA_KEYS
    }
    return len(json.dumps(filterable, ensure_ascii=False).encode("utf-8"))


def _base_vector_metadata(settings: Settings) -> dict[str, object]:
    """Realistic filterable metadata for a tier-2 code_review artifact, matching the shape
    write.py's ``_write_artifact_inner`` assembles (artifact.py:371-395) minus commit_refs,
    which the calibration loop varies."""
    return {
        "artifact_id": f"{settings.write_prefix}/code_review/2026-08-13-calibration-probe",
        "scope": settings.write_prefix,
        "type": "code_review",
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-08-13",
        "status": "active",
        "visibility": "shared",
        "last_edited_ulid": "01K2C3D4E5F6G7H8J9K0M1N2P3",
        "tags": ["platform", "calibration"],
    }


def _attempt(
    vectors: VectorsClientImpl, key: str, vector: list[float], vector_metadata: dict[str, object]
) -> str | None:
    """Try a real put_vector call. Returns None on success, or the AWS error code on a
    ValidationException rejection. Any other ClientError is re-raised — only a
    ValidationException is treated as "budget probe result", everything else is a real
    infrastructure problem the test must surface, not swallow.
    """
    try:
        vectors.put_vector(key, vector, vector_metadata)
    except botocore.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            return code
        raise
    return None


@pytest.mark.integration
def test_commit_refs_filterable_metadata_boundary_against_real_aws(
    settings: Settings, vectors: VectorsClientImpl
) -> None:
    """Binary-searches the exact commit_refs entry count at which real AWS PutVectors
    starts rejecting filterable metadata as oversize, then compares that boundary's local
    json.dumps approximation against AWS's real accounting.
    """
    key = f"{settings.write_prefix}/calibration/commit-refs-budget-probe"
    dimension = settings.bedrock_embedding_dimensions
    # A zero-norm vector is itself rejected by AWS's cosine-distance index with the same
    # ValidationException code this probe is searching for on metadata size — so an
    # all-zero vector would make _attempt misclassify every call as a budget rejection.
    # Matches the non-zero unit-vector convention used by tests/integration/clients/
    # test_vectors_client.py and test_vectors_filter_semantics.py.
    vector = [1.0] + [0.0] * (dimension - 1)
    base_metadata = _base_vector_metadata(settings)

    def metadata_for(n: int) -> dict[str, object]:
        # Mirrors write.py:392 (`if refs: vector_metadata["commit_refs"] = refs`) — AWS
        # rejects empty-array metadata values outright, independent of size, so the key
        # must be omitted rather than sent as an empty list when n == 0.
        if n == 0:
            return dict(base_metadata)
        return {**base_metadata, "commit_refs": _sha1_commit_refs(n)}

    def try_n(n: int) -> bool:
        error_code = _attempt(vectors, key, vector, metadata_for(n))
        return error_code is None

    try:
        # Sanity: baseline (zero commit_refs) must pass, or the probe metadata itself is
        # already oversize and the search below is meaningless.
        assert try_n(0), "baseline filterable metadata (no commit_refs) was rejected by AWS"

        # Exponential search for an upper bound that fails.
        max_passing = 0
        min_failing = 1
        while try_n(min_failing):
            max_passing = min_failing
            min_failing *= 2
            assert min_failing <= _MAX_PROBE_ENTRIES, (
                f"commit_refs boundary not found within {_MAX_PROBE_ENTRIES} entries — "
                "AWS accounting for this payload shape may differ far more than expected"
            )

        # Binary search the exact edge between max_passing (last known pass) and
        # min_failing (first known fail).
        while min_failing - max_passing > 1:
            mid = (max_passing + min_failing) // 2
            if try_n(mid):
                max_passing = mid
            else:
                min_failing = mid

        passing_metadata = metadata_for(max_passing)
        failing_metadata = metadata_for(min_failing)
        passing_local_bytes = _local_filterable_bytes(passing_metadata)
        failing_local_bytes = _local_filterable_bytes(failing_metadata)

        logger.info(
            "AWS real PutVectors filterable-metadata boundary: "
            "commit_refs=%d entries PASSES (local approx=%d bytes), "
            "commit_refs=%d entries REJECTED (local approx=%d bytes); "
            "local VECTOR_FILTERABLE_METADATA_MAX_BYTES=%d",
            max_passing,
            passing_local_bytes,
            min_failing,
            failing_local_bytes,
            VECTOR_FILTERABLE_METADATA_MAX_BYTES,
        )

        # The search must converge to a well-defined, adjacent pass/fail edge.
        assert min_failing == max_passing + 1
        assert max_passing >= 1, "AWS rejected even a single commit_refs entry — unexpected"
        # The rejected payload's local approximation must be strictly larger than the
        # passing payload's — otherwise the boundary search itself is broken.
        assert failing_local_bytes > passing_local_bytes
    finally:
        vectors.delete_vectors([key])

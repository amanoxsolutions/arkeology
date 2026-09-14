"""Calibrates the real cost of answering "which vectors belong to this artifact" with the
two S3 Vectors primitives the client already exposes.

Context — the scan pages ``ListVectors`` over the whole index and filters client-side
while ``query_vectors`` filters server-side; see backlog item B-12 for the analysis:
``VectorsClientImpl.list_vectors_by_metadata`` pages ``ListVectors`` over the *entire*
index with ``returnMetadata=True`` and applies the filter in-process, because the
ListVectors API has no server-side metadata filter — its own docstring says so. Every
per-artifact lookup in the tree (delete, archive, purge, freshness, reconcile,
propose_commit_links, link_metadata, _reference_filter) therefore pays a full-index scan
to find a handful of keys. ``VectorsClientImpl.query_vectors`` in the same client *does*
pass its filter server-side, so the proposed substitution answers the same question with
one ``QueryVectors`` call carrying an ``artifact_id $eq`` filter and a ``top_k`` large
enough that the similarity ranking cannot truncate the matching set.

This is a diagnostic/calibration test, not a regression guard. It asserts nothing about
timings, index size, or page counts — those are AWS-side observations, not contracts,
exactly as test_calibration_vector_metadata_budget.py treats AWS's byte accounting. The
one thing it *does* assert is the property that would justify the substitution at all, and
that no moto-based unit test can establish: against real AWS, both primitives return the
**same set of vector keys** for the same artifact, and that set matches the vector count
the write itself reported.

The decision-relevant figures it reports via logging:

* **The total number of vectors the scan pulls back with metadata — the operator's entire
  index size.** This is the single most important number here: the scan's cost grows with
  it, the filtered query's does not.
* How many ``ListVectors`` pages that scan walks.
* The one ``QueryVectors`` call the candidate makes, and how many vectors come back.
* Whether the query response was *short* of ``top_k`` (proof nothing was truncated, which
  is what the whole proposed design rests on) or exactly ``top_k`` (completeness
  unprovable).
* Median wall-clock for each, over a few repeats — reported last, because latency is noisy
  and machine-dependent.

A second, smaller artifact is seeded so the contrast is visible in the numbers: the scan
pulls the whole index whichever artifact it is asked about, while the query pulls only
the matching vectors.

Cleanup is the session-scoped ``isolate_run_scope`` teardown in conftest.py, which deletes
every S3 object and vector written under the ephemeral ``integration-tests/<run-id>``
prefix — this file writes nowhere else and adds no cleanup of its own.

Run with ``-s --log-cli-level=INFO`` to see the calibration findings.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.write import write_artifact

logger = logging.getLogger(__name__)

# Enough samples for a median to mean something without turning a calibration run into a
# benchmark suite — each scan sample is a full pass over the operator's index.
_REPEATS = 3


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Session-scoped Settings constructed after the top-level conftest's load_env and
    isolate_run_scope autouse fixtures have run."""
    return Settings()


@pytest.fixture(scope="session")
def s3(settings: Settings) -> S3ClientImpl:
    return S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )


@pytest.fixture(scope="session")
def vectors(settings: Settings) -> VectorsClientImpl:
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


@pytest.fixture(scope="session")
def bedrock(settings: Settings) -> BedrockClientImpl:
    return BedrockClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
    )


@dataclass
class _Measurement:
    """One timed answer to "which vectors belong to this artifact", plus what it cost."""

    keys: frozenset[str]
    api_calls: int
    vectors_returned: int
    seconds: float


@contextmanager
def _counting(vectors: VectorsClientImpl, method: str) -> Iterator[list[int]]:
    """Count AWS calls and vectors returned for one botocore method, as a ``[calls,
    vectors]`` pair.

    Wraps the method on the boto3 client instance for the duration of the block. Neither
    ``list_vectors_by_metadata`` nor ``query_vectors`` reports how many pages it walked or
    how many vectors it pulled back before filtering, and those are precisely the numbers
    this calibration exists to obtain — so the count has to be taken at the transport
    boundary. The original attribute is restored on exit.
    """
    boto_client = vectors._client  # noqa: SLF001 — measuring the transport is the point
    original = getattr(boto_client, method)
    counts = [0, 0]

    def wrapper(**kwargs: Any) -> Any:
        response = original(**kwargs)
        counts[0] += 1
        counts[1] += len(response.get("vectors", []))
        return response

    setattr(boto_client, method, wrapper)
    try:
        yield counts
    finally:
        setattr(boto_client, method, original)


def _measure_scan(vectors: VectorsClientImpl, artifact_id: str) -> _Measurement:
    """Today's path: page the whole index with metadata, filter client-side."""
    with _counting(vectors, "list_vectors") as counts:
        started = time.perf_counter()
        keys = vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
        elapsed = time.perf_counter() - started
    return _Measurement(frozenset(keys), counts[0], counts[1], elapsed)


def _measure_query(
    vectors: VectorsClientImpl, artifact_id: str, probe: list[float], top_k: int
) -> _Measurement:
    """The candidate: one QueryVectors call with a server-side artifact_id filter."""
    with _counting(vectors, "query_vectors") as counts:
        started = time.perf_counter()
        results = vectors.query_vectors(probe, top_k, {"artifact_id": {"$eq": artifact_id}})
        elapsed = time.perf_counter() - started
    return _Measurement(frozenset(item["key"] for item in results), counts[0], counts[1], elapsed)


def _content(sections: int) -> str:
    """Markdown with ``sections`` distinct headings, each body comfortably past the
    default EMBED_MIN_SECTION_LENGTH so every section earns its own vector."""
    return "\n\n".join(
        f"## Section {n}\n\nCalibration body text for section {n} of the per-artifact "
        f"vector lookup probe, long enough to clear the minimum section length filter."
        for n in range(1, sections + 1)
    )


async def _seed(
    *,
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
    title: str,
    sections: int,
) -> tuple[str, int]:
    """Write one artifact under the ephemeral run prefix; return its id and the number of
    vectors the write reports having indexed."""
    result = await write_artifact(
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        settings=settings,
        type="code_review",
        team="platform",
        project="arkeology",
        tier=2,
        date="2026-09-14",
        status="active",
        title=title,
        description="Seeded by the per-artifact vector lookup calibration.",
        content=_content(sections),
        visibility="shared",
        tags=["calibration"],
    )
    assert "error" not in result, f"seeding {title!r} failed: {result}"
    return result["artifact_id"], result["sections_indexed"]


@pytest.mark.integration
async def test_per_artifact_lookup_scan_versus_filtered_query(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Both primitives must answer "which vectors belong to this artifact" identically;
    what it costs each of them to do so is reported, not asserted.
    """
    dimension = settings.bedrock_embedding_dimensions
    # Cosine distance against a zero vector is undefined, and this client *raises*
    # VectorDistanceMissingError when a result arrives with no distance — so a degenerate
    # probe would surface as an error rather than a bad measurement. Same non-zero unit
    # vector convention as test_calibration_vector_metadata_budget.py.
    probe = [1.0] + [0.0] * (dimension - 1)
    # +1 is deliberate headroom: an artifact holds EITHER section vectors OR a single
    # document-level fallback, never both (see _reindex_artifact in tools/reconcile.py),
    # so its vector count cannot exceed embed_max_sections. A response shorter than top_k
    # is therefore proof nothing was truncated — the proof rule the proposed design rests
    # on, and the thing this test records below.
    top_k = settings.embed_max_sections + 1

    large_id, large_indexed = await _seed(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        title="Per-artifact lookup calibration large",
        sections=6,
    )
    small_id, small_indexed = await _seed(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        title="Per-artifact lookup calibration small",
        sections=2,
    )

    for artifact_id, indexed in ((large_id, large_indexed), (small_id, small_indexed)):
        scans = [_measure_scan(vectors, artifact_id) for _ in range(_REPEATS)]
        queries = [_measure_query(vectors, artifact_id, probe, top_k) for _ in range(_REPEATS)]

        last_query = queries[-1]
        complete = len(last_query.keys) < top_k

        logger.info(
            "Per-artifact vector lookup for %s (write reported %d vectors indexed):\n"
            "  INDEX SIZE — vectors pulled back with metadata per scan: %d\n"
            "  scan (ListVectors, client-side filter): %d pages, %d vectors transferred, "
            "%d matched\n"
            "  query (QueryVectors, server-side artifact_id filter, top_k=%d): %d call, "
            "%d vectors transferred, %d matched\n"
            "  completeness: %s\n"
            "  median wall-clock over %d repeats — scan %.3fs, query %.3fs",
            artifact_id,
            indexed,
            scans[-1].vectors_returned,
            scans[-1].api_calls,
            scans[-1].vectors_returned,
            len(scans[-1].keys),
            top_k,
            last_query.api_calls,
            last_query.vectors_returned,
            len(last_query.keys),
            (
                f"PROVEN COMPLETE — response held {len(last_query.keys)} < top_k={top_k}"
                if complete
                else f"UNPROVABLE — response hit top_k={top_k} exactly, may be truncated"
            ),
            _REPEATS,
            statistics.median(m.seconds for m in scans),
            statistics.median(m.seconds for m in queries),
        )

        # The property the substitution stands or falls on: every sample of either
        # primitive agrees on the same key set. Comparing the collected sets against each
        # other AND against the independently-known vector count means a narrowed or
        # empty result fails here rather than passing on a weaker "both non-empty" check.
        key_sets = {m.keys for m in scans} | {m.keys for m in queries}
        assert len(key_sets) == 1, (
            f"scan and filtered query disagree about {artifact_id}: {key_sets}"
        )
        assert len(key_sets.pop()) == indexed

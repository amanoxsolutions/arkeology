"""Integration tests pinning real S3 Vectors QueryVectors server-side filter semantics.

The moto ``query_vectors`` extension in
tests/unit/conftest.py filters using the exact same production
``arkeology.clients.filter.matches_filter`` function that
``VectorsClientImpl.query_vectors`` hands to boto3 as the ``filter`` request
parameter. That makes the unit suite circular for anything QueryVectors
evaluates **server-side**: if ``matches_filter``'s assumptions about AWS's
real filter semantics were wrong, the moto-backed unit tests could never
catch it, because the same (possibly wrong) function defines both sides of
the comparison.

This file breaks that circularity by calling the real
``VectorsClientImpl.query_vectors`` — which passes ``filter_expr`` straight
through to the real AWS QueryVectors API — and asserting the documented (and,
where undocumented, empirically observed) real-AWS behaviour for each
semantic the codebase relies on:

  1. ``$eq`` on a list-valued metadata field is list-membership (documented:
     https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html
     — "When comparing with an array metadata value, returns true if the
     input value matches any element in the array.").
  2. The plain-equality shorthand ``{"field": value}`` (no operator) is
     accepted and behaves as ``$eq`` (documented, same page: "When you don't
     specify an operator, S3 Vectors automatically uses the $eq operator.").
  3. ``$gte`` on a *string* field (as ``propose_commit_links`` shapes its
     ``last_edited_ulid`` bound, via ``arkeology.clients.filter.matches_filter``
     — see that tool's module docstring for why this filter shape never
     actually reaches QueryVectors in production today). AWS's own operator
     table documents ``$gte`` as Number-only; this test empirically pins
     what the real QueryVectors API actually does when given a String
     operand instead of erroring from the docstring's claim, closing the gap
     the moto extension cannot: moto's extension reuses ``matches_filter``,
     which happily does a Python string comparison regardless of what AWS
     really does.
  4. Behaviour at/over the documented Top-K cap (10,000 per
     https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html).
  5. Behaviour with a filter expression far larger than the ~2 KB filterable
     metadata budget ``tools/_search_helper.py``'s ``_NIN_EXCLUSION_BYTE_BUDGET``
     is conservatively sized against (AWS documents "Filterable metadata per
     vector: Up to 2 KB" but does not separately document a *filter
     expression* size cap — this test pins what actually happens).

Findings are recorded in each test's docstring/comments once observed against
real AWS: these assertions must "pin" real behaviour rather than merely
re-assert the production filter's own logic.
"""

import math
import os
import uuid

import botocore.exceptions
import pytest

from arkeology.clients.vectors import VectorsClientImpl

pytestmark = pytest.mark.integration


def _unit_vec(dimension: int) -> list[float]:
    values = [1.0] + [0.0] * (dimension - 1)
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


@pytest.fixture(scope="session")
def index_dimension() -> int:
    return int(os.environ.get("BEDROCK_EMBEDDING_DIMENSIONS", "1024"))


@pytest.fixture
def vectors_client() -> VectorsClientImpl:
    region = os.environ["AWS_REGION"]
    bucket = os.environ["VECTORS_BUCKET"]
    index = os.environ["VECTORS_INDEX"]
    profile = os.environ.get("AWS_PROFILE")
    return VectorsClientImpl(region=region, profile=profile, bucket=bucket, index=index)


@pytest.fixture
def probe_key() -> str:
    return f"_arkeology_filter_semantics_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# 1. $eq on a list-valued metadata field is list-membership
# ---------------------------------------------------------------------------


def test_eq_on_array_metadata_field_is_list_membership(
    vectors_client: VectorsClientImpl, probe_key: str, index_dimension: int
) -> None:
    """Real AWS: {"tags": {"$eq": "x"}} matches a vector whose "tags" is a list containing "x".

    This is the exact shape build_user_filters() in _search_helper.py emits for
    tag filtering (one $eq clause per tag). Pinned against real QueryVectors,
    not the moto extension's matches_filter self-simulation.
    """
    vec = _unit_vec(index_dimension)
    vectors_client.put_vector(probe_key, vec, {"tags": ["alpha", "beta"]})
    try:
        results = vectors_client.query_vectors(
            vec, top_k=10, filter_expr={"tags": {"$eq": "alpha"}}
        )
        assert any(r["key"] == probe_key for r in results), (
            "real AWS QueryVectors did not match $eq against a list-element — "
            "list-membership semantics not confirmed"
        )

        # Sanity: a value NOT in the list must not match.
        non_matching = vectors_client.query_vectors(
            vec, top_k=10, filter_expr={"tags": {"$eq": "gamma"}}
        )
        assert not any(r["key"] == probe_key for r in non_matching)
    finally:
        vectors_client.delete_vectors([probe_key])


# ---------------------------------------------------------------------------
# 2. Plain-equality shorthand
# ---------------------------------------------------------------------------


def test_plain_equality_shorthand_matches(
    vectors_client: VectorsClientImpl, probe_key: str, index_dimension: int
) -> None:
    """Real AWS: {"field": value} (no operator) behaves as {"field": {"$eq": value}}."""
    vec = _unit_vec(index_dimension)
    vectors_client.put_vector(probe_key, vec, {"status": "active"})
    try:
        results = vectors_client.query_vectors(vec, top_k=10, filter_expr={"status": "active"})
        assert any(r["key"] == probe_key for r in results), (
            "real AWS QueryVectors did not accept the plain-equality shorthand"
        )

        non_matching = vectors_client.query_vectors(
            vec, top_k=10, filter_expr={"status": "inactive"}
        )
        assert not any(r["key"] == probe_key for r in non_matching)
    finally:
        vectors_client.delete_vectors([probe_key])


# ---------------------------------------------------------------------------
# 3. $gte on a string (ULID) field
# ---------------------------------------------------------------------------


def test_gte_on_string_ulid_field_real_behaviour(
    vectors_client: VectorsClientImpl, index_dimension: int
) -> None:
    """Pin real QueryVectors behaviour for $gte with a String operand on a ULID field.

    CONFIRMED against real AWS S3 Vectors:
    QueryVectors REJECTS $gte with a String operand —
    ``botocore.errorfactory.ValidationException: ... Invalid filter``. This
    confirms the AWS docs' operator table ("$gte: Number" only) is accurate,
    NOT merely conservative/incomplete documentation. arkeology.clients.filter
    .matches_filter's $gte implementation does a plain Python string
    comparison (no type restriction) and is therefore only ever safe to use
    on a String field because its sole ULID-range caller,
    ``list_vectors_by_metadata`` (used by ``propose_commit_links``), filters
    entirely client-side and never reaches QueryVectors' ``filter`` parameter.
    If ``$gte`` on a string ever needs to be pushed server-side (e.g. a future
    optimisation of ``list_vectors_by_metadata`` to use QueryVectors), that
    change would need a numeric encoding of the ULID timestamp, not the raw
    string. Do not weaken this assertion — if AWS's behaviour ever changes,
    update this docstring's finding rather than loosening the assertion.
    """
    low_key = f"_arkeology_filter_semantics_{uuid.uuid4().hex}_low"
    vec = _unit_vec(index_dimension)
    low_ulid = "01KDVDNA00FN74309G4MXHQ1KK"  # 2026-01-01
    mid_ulid = "01KJKB3Q00FN74309G4MXHQ1KM"  # 2026-03-01 — the $gte bound

    vectors_client.put_vector(low_key, vec, {"last_edited_ulid": low_ulid})
    try:
        with pytest.raises(botocore.exceptions.ClientError) as exc_info:
            vectors_client.query_vectors(
                vec, top_k=10, filter_expr={"last_edited_ulid": {"$gte": mid_ulid}}
            )
        code = exc_info.value.response.get("Error", {}).get("Code", "")
        assert code == "ValidationException", (
            f"expected the confirmed real-AWS rejection code 'ValidationException', "
            f"got {code!r}: {exc_info.value}"
        )
    finally:
        vectors_client.delete_vectors([low_key])


# ---------------------------------------------------------------------------
# 4. Top-K cap (documented: up to 10,000 per QueryVectors request)
# ---------------------------------------------------------------------------


def test_top_k_over_documented_cap_is_rejected(
    vectors_client: VectorsClientImpl, probe_key: str, index_dimension: int
) -> None:
    """topK=10001 (one over the documented 10,000 cap) is rejected by real AWS.

    Pins the ceiling _search_helper.py / search.py's effective_top_k must never
    be allowed to reach, independent of any moto simulation (moto's extension
    does not enforce this cap at all — see _backend_query_vectors, which slices
    scored[:top_k] unconditionally).
    """
    vec = _unit_vec(index_dimension)
    vectors_client.put_vector(probe_key, vec, {})
    try:
        with pytest.raises(botocore.exceptions.ClientError) as exc_info:
            vectors_client.query_vectors(vec, top_k=10_001, filter_expr=None)
        code = exc_info.value.response.get("Error", {}).get("Code", "")
        assert code, f"expected a structured ClientError code, got: {exc_info.value}"
    finally:
        vectors_client.delete_vectors([probe_key])


# ---------------------------------------------------------------------------
# 5. Oversized filter expression
# ---------------------------------------------------------------------------


def test_oversized_filter_expression_behaviour(
    vectors_client: VectorsClientImpl, index_dimension: int
) -> None:
    """Pin real AWS behaviour for a filter expression far exceeding the ~2 KB budget
    _search_helper.py's _NIN_EXCLUSION_BYTE_BUDGET is conservatively sized against.

    AWS documents "Filterable metadata per vector: Up to 2 KB" but does not
    separately document a filter-EXPRESSION size cap for QueryVectors. This test
    sends a $nin clause with enough entries to exceed 2 KB of JSON and records
    whether AWS rejects it (confirming a real cap exists and the budget is
    load-bearing) or accepts it (in which case the budget is a defensive
    client-side choice with no corresponding server-side cap at this size).
    Either result is asserted explicitly — this must not be a silent try/except.

    CONFIRMED against real AWS S3 Vectors:
    a ~4 KB $nin filter expression is ACCEPTED without error — AWS enforces no
    filter-expression size cap at this size (at least none distinct from the
    documented 2 KB *per-vector* filterable-metadata limit, which bounds what
    a single vector can carry, not what a query filter can contain). The
    _NIN_EXCLUSION_BYTE_BUDGET guard in _search_helper.py therefore
    remains a defensive, not empirically-required-at-this-size, choice — kept
    for safety margin against a larger, undocumented cap the search re-fetch
    loop's unbounded growth could otherwise hit at scale.
    """
    excluded_key = f"_arkeology_filter_semantics_{uuid.uuid4().hex}_excluded"
    included_key = f"_arkeology_filter_semantics_{uuid.uuid4().hex}_included"
    vec = _unit_vec(index_dimension)
    # ~4 KB of JSON — comfortably over the 2 KB filterable-metadata-per-vector
    # budget the codebase's byte budget mirrors.
    oversized_exclusion = [f"artifacts/oversized-filter-probe-{i:04d}" for i in range(150)]
    assert len(oversized_exclusion) == 150
    excluded_artifact_id = oversized_exclusion[0]
    oversized_filter = {"artifact_id": {"$nin": oversized_exclusion}}

    vectors_client.put_vector(excluded_key, vec, {"artifact_id": excluded_artifact_id})
    vectors_client.put_vector(
        included_key, vec, {"artifact_id": "artifacts/oversized-filter-not-excluded"}
    )
    try:
        results = vectors_client.query_vectors(vec, top_k=10, filter_expr=oversized_filter)
        keys = {r["key"] for r in results}
        assert included_key in keys, (
            "expected the non-excluded artifact_id to survive the oversized $nin filter"
        )
        assert excluded_key not in keys, (
            "expected the excluded artifact_id to be filtered out by the oversized $nin filter"
        )
    finally:
        vectors_client.delete_vectors([excluded_key, included_key])

"""Calibrates whether a filtered, paged ``QueryVectors`` in ``ENHANCED`` query mode is an
exhaustive per-artifact vector lookup — the question the aws-backend-selection ADR put to it
before it chose numbered vector keys. The answer, measured on 2026-11-12, was no: above 10
vectors an artifact came back short, silently. The ADR therefore reads every vector of an
artifact by key, and this file is kept as the instrument that measured it.

The planned per-artifact lookup sends ``{"artifact_id": {"$eq": id}}`` (or ``$in`` over at most
100 ids) with any fixed query vector, ``topK`` 10,000 and ``returnMetadata``, and follows
``nextToken`` until it is absent. AWS documents that pre-filtering gives "higher recall", not
that every match comes back, so three properties are measured here against real AWS at a
realistic index size:

1. **Exhaustiveness** — the filtered query returns every vector written for the artifact(s).
2. **Paging** — an artifact holding more than one page of vectors (a page holds at most 100)
   arrives complete across its pages, and the token is absent only once the last match has
   been delivered.
3. **Read-after-write** — a vector written immediately before the query is returned by it; if
   not at once, how long it takes (polled up to ``_RAW_POLL_CAP_SECONDS``).

Each lookup runs twice: with ``queryMode="ENHANCED"`` — which AWS supports on a ``CLASSIC``
index precisely so that an index can be tested before its mode is changed — and with
``queryMode`` omitted, i.e. the index's own mode, for comparison. This file never calls
``UpdateIndexMode``.

Where a lookup comes back short, three diagnostics separate the possible causes: every target
key is read back by ``GetVectors`` first (so "not stored" is ruled out by evidence, not
assumed); the same lookups are repeated with the artifact's *own* vector and with an unrelated
random vector as the probe (does completeness depend on the probe?); and the short lookups are
re-polled for several minutes after seeding (is it indexing lag?). The ``$in`` lookup runs both
at 100 real-length ids and at the most ids whose filter fits AWS's filter byte limit.

Data is synthetic (random unit vectors derived from each key, no Bedrock call), written only
under the run-scoped ``integration-tests/<run-id>`` prefix that ``isolate_run_scope`` in
conftest.py installs, with keys and metadata shaped like the server's at the time
(``{artifact_id}#{slug}``, the shape before numbered keys; ``artifact_id`` and ``scope`` as
``write_artifact`` stores them). Ground truth is the set of keys
this file wrote — no whole-index scan. Every key written is recorded in a ledger *before* its
batch is sent, and the ``index`` fixture's teardown deletes the whole ledger by key and then
confirms with ``GetVectors`` that none remains, whether the test passed or failed.

This is a diagnostic/calibration test, not a regression guard, like the other calibration files
here: it asserts only that it wrote inside the run scope and left nothing behind. Every finding —
the ``ENHANCED`` shortfalls, timings, page counts, the diagnostics and the default-mode results —
is logged as one ``CALIBRATION_SUMMARY`` JSON block, and any ``ENHANCED`` shortfall is listed
again in a WARNING line.

Requires a botocore whose service model declares ``QueryVectors.queryMode``; the test is
skipped otherwise. The locked version does not, so run it with a newer one layered on top::

    uv run --with 'boto3==1.44.1' --with 'botocore==1.44.1' \\
        pytest tests/integration/test_calibration_enhanced_filtered_query.py \\
        -m integration -s --log-cli-level=INFO
"""

import hashlib
import json
import logging
import random
import statistics
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import boto3
import botocore
import pytest
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from arkeology.config import Settings

logger = logging.getLogger(__name__)

# ── API limits (https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html)
_TOP_K = 10_000  # Top-K results per QueryVectors request
_MAX_PAGE_SIZE = 100  # Results per page in a QueryVectors response
_PUT_BATCH = 500  # Vectors per PutVectors call
_DELETE_BATCH = 500  # Vectors per DeleteVectors call
_GET_BATCH = 100  # Vectors per GetVectors call
# Not in the limits page; the ValidationException a 100-id $in drew on 2026-11-12 states it:
# "Filter must have at most 10240 bytes".
_FILTER_MAX_BYTES = 10_240
# A token that kept coming back past top-K would loop forever; one page beyond the most top-K
# can fill is the point at which it is reported instead.
_MAX_PAGES = _TOP_K // _MAX_PAGE_SIZE + 1

# ── Cost guard: the run aborts rather than exceed either ceiling.
_WRITE_CEILING = 50_000
_QUERY_CEILING = 2_000

# ── Data plan. Background vectors are never looked up individually: 460 x 25 = 11,500, of
# which the $in lookup borrows at most 49 artifacts (1,225 vectors), so every lookup still
# runs against at least 10,000 vectors outside the artifacts it asks about.
_BACKGROUND_ARTIFACTS = 460
_BACKGROUND_VECTORS_EACH = 25
_SMALL_TARGETS = 50
_SMALL_TARGET_SIZES = (2, 25)
_LARGE_TARGET_VECTORS = 300
_IN_LOOKUP_IDS = 100
_REPEATS = 3
_RAW_TRIALS = 5
_RAW_NEW_ARTIFACT_VECTORS = 3
_RAW_BASE_VECTORS = 5
_RAW_ADDED_VECTORS = 2
_RAW_POLL_CAP_SECONDS = 30.0
_RAW_BACKOFF_SECONDS = (0.1, 0.2, 0.4, 0.8)  # then 1.0 s per poll until the cap
_SETTLE_UNTIL_SECONDS = 480.0  # re-poll short lookups until this long after seeding
_SETTLE_INTERVAL_SECONDS = 60.0
_SEED = 20_261_112

_RUN_PREFIX_ROOT = "integration-tests/"
_ENHANCED = "ENHANCED"


# ── Measuring wrapper ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Lookup:
    """One filtered, paged QueryVectors lookup: what came back, page by page."""

    keys: list[str]
    page_sizes: list[int]
    token_after_page: list[bool]
    page_seconds: list[float]
    seconds: float
    retries: int
    error: str | None = None


class _Index:
    """Thin measuring wrapper over one S3 Vectors index.

    Every key is added to ``written`` before its batch is sent, so a batch that fails half-way
    is still torn down; every query is counted against ``_QUERY_CEILING``.
    """

    def __init__(
        self, client: BaseClient, bucket: str, index: str, dimension: int, mode: str
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._index = index
        self.dimension = dimension
        self.mode = mode
        # Any fixed query vector serves a filtered lookup; a zero vector would leave cosine
        # distance undefined, so the same non-zero unit vector as the sibling calibrations.
        self.probe = [1.0] + [0.0] * (dimension - 1)
        self.written: list[str] = []
        self.batch_of: dict[str, int] = {}
        self.queries = 0
        self._batches = 0

    def put(self, items: Sequence[tuple[str, dict[str, object]]]) -> None:
        for chunk in _chunks(items, _PUT_BATCH):
            self.written.extend(key for key, _ in chunk)
            if len(self.written) > _WRITE_CEILING:
                raise RuntimeError(f"cost guard: more than {_WRITE_CEILING} vector writes")
            self.batch_of.update((key, self._batches) for key, _ in chunk)
            self._batches += 1
            self._client.put_vectors(
                vectorBucketName=self._bucket,
                indexName=self._index,
                vectors=[
                    {
                        "key": key,
                        "data": {"float32": _vector_for(key, self.dimension)},
                        "metadata": metadata,
                    }
                    for key, metadata in chunk
                ],
            )

    def stored_artifact_ids(self, keys: Sequence[str]) -> dict[str, object]:
        """Read ``keys`` back by key: which are stored, and the artifact_id each one carries."""
        found: dict[str, object] = {}
        for chunk in _chunks(keys, _GET_BATCH):
            response = self._client.get_vectors(
                vectorBucketName=self._bucket,
                indexName=self._index,
                keys=list(chunk),
                returnData=False,
                returnMetadata=True,
            )
            found.update(
                (item["key"], (item.get("metadata") or {}).get("artifact_id"))
                for item in response.get("vectors", [])
            )
        return found

    def lookup(
        self,
        artifact_ids: Sequence[str],
        query_mode: str | None,
        probe: list[float] | None = None,
    ) -> _Lookup:
        """The planned per-artifact lookup: filter on artifact_id, top-K 10,000, page to the end."""
        request: dict[str, object] = {
            "vectorBucketName": self._bucket,
            "indexName": self._index,
            "topK": _TOP_K,
            "queryVector": {"float32": probe if probe is not None else self.probe},
            "filter": _artifact_filter(artifact_ids),
            "returnMetadata": True,
        }
        if query_mode is not None:
            request["queryMode"] = query_mode
        return self._paged_query(request)

    def scoped_search(self, scope: str, query_mode: str | None) -> _Lookup:
        """A top-10 semantic search filtered to one whole scope — the ADR asks for its latency
        alongside the lookup's, since pre-filtering a broad filter may move it either way."""
        request: dict[str, object] = {
            "vectorBucketName": self._bucket,
            "indexName": self._index,
            "topK": 10,
            "queryVector": {"float32": self.probe},
            "filter": {"scope": {"$eq": scope}},
            "returnMetadata": True,
            "returnDistance": True,
        }
        if query_mode is not None:
            request["queryMode"] = query_mode
        return self._paged_query(request)

    def _paged_query(self, request: dict[str, object]) -> _Lookup:
        keys: list[str] = []
        page_sizes: list[int] = []
        token_after_page: list[bool] = []
        page_seconds: list[float] = []
        retries = 0
        error: str | None = None
        started = time.perf_counter()
        while True:
            self.queries += 1
            if self.queries > _QUERY_CEILING:
                raise RuntimeError(f"cost guard: more than {_QUERY_CEILING} queries")
            page_started = time.perf_counter()
            try:
                response = self._client.query_vectors(**request)
            except ClientError as exc:
                details = exc.response.get("Error", {})
                error = f"{details.get('Code')}: {details.get('Message')}"
                break
            page_seconds.append(time.perf_counter() - page_started)
            retries += response.get("ResponseMetadata", {}).get("RetryAttempts", 0)
            vectors = response.get("vectors", [])
            keys.extend(item["key"] for item in vectors)
            page_sizes.append(len(vectors))
            token = response.get("nextToken")
            token_after_page.append(bool(token))
            if not token or len(page_sizes) >= _MAX_PAGES:
                break
            request["nextToken"] = token
        return _Lookup(
            keys=keys,
            page_sizes=page_sizes,
            token_after_page=token_after_page,
            page_seconds=page_seconds,
            seconds=time.perf_counter() - started,
            retries=retries,
            error=error,
        )

    def delete_written(self) -> tuple[int, int]:
        """Delete every key in the ledger; return (keys deleted, keys still present after)."""
        keys = list(dict.fromkeys(self.written))
        for chunk in _chunks(keys, _DELETE_BATCH):
            self._client.delete_vectors(
                vectorBucketName=self._bucket, indexName=self._index, keys=list(chunk)
            )
        return len(keys), len(self.stored_artifact_ids(keys))


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _artifact_filter(artifact_ids: Sequence[str]) -> dict[str, object]:
    if len(artifact_ids) == 1:
        return {"artifact_id": {"$eq": artifact_ids[0]}}
    return {"artifact_id": {"$in": list(artifact_ids)}}


def _filter_bytes(artifact_ids: Sequence[str]) -> int:
    """The filter's size as botocore sends it: its JSON body serializer uses json.dumps'
    default ``", "`` / ``": "`` separators. Counting the compact form instead under-counts by
    about a byte per id: on 2026-11-12 a 94-id filter of 10,160 compact bytes (10,255 as
    sent) was rejected — consistent with AWS counting the filter as sent, not yet shown to
    be the rule, since no $in at or under 10,240 bytes as sent has been run yet."""
    return len(json.dumps(_artifact_filter(artifact_ids)).encode())


def _vector_for(key: str, dimension: int) -> list[float]:
    """The vector stored under ``key``, derived from the key alone — so a target's own vectors
    can be regenerated as probes without keeping twelve thousand of them in memory."""
    rng = random.Random(key)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(dimension)]
    norm = sum(x * x for x in raw) ** 0.5
    # Four decimals keep a 500-vector PutVectors payload near 4 MiB instead of ~10 MiB.
    return [round(x / norm, 4) for x in raw]


def _declares_query_mode(client: BaseClient) -> bool:
    operation = client.meta.service_model.operation_model("QueryVectors")
    return "queryMode" in operation.input_shape.members


# ── Data plan ─────────────────────────────────────────────────────────────────


@dataclass
class _Plan:
    """Ground truth: every artifact this run writes, and exactly which keys it holds."""

    scope: str
    truth: dict[str, set[str]] = field(default_factory=dict)
    background: list[str] = field(default_factory=list)
    small: list[str] = field(default_factory=list)
    large: str = ""
    raw_base: dict[tuple[int, int], str] = field(default_factory=dict)
    items: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def artifact(self, role: str, number: int, vector_count: int) -> str:
        artifact_id = _artifact_id(self.scope, role, number)
        self.truth[artifact_id] = set()
        self.items.extend(self.vectors(artifact_id, "section", vector_count))
        return artifact_id

    def vectors(
        self, artifact_id: str, slug: str, count: int
    ) -> list[tuple[str, dict[str, object]]]:
        """``count`` new vectors for ``artifact_id``, recorded in the ground truth."""
        start = len(self.truth[artifact_id])
        items = [
            (f"{artifact_id}#{slug}-{n:03d}", _metadata(artifact_id, self.scope))
            for n in range(start, start + count)
        ]
        self.truth[artifact_id].update(key for key, _ in items)
        return items


def _artifact_id(scope: str, role: str, number: int) -> str:
    """Shaped like write_artifact's: ``{write_prefix}/{type}-{date}-{slug}-{hash8}.md``."""
    slug = f"calibration-{role}-{number:04d}"
    digest = hashlib.sha256(slug.encode()).hexdigest()[:8]
    return f"{scope}/code_review-2026-11-12-{slug}-{digest}.md"


def _metadata(artifact_id: str, scope: str) -> dict[str, object]:
    """The filterable fields write_artifact stores, with the same types (tier is an int)."""
    return {
        "artifact_id": artifact_id,
        "scope": scope,
        "type": "code_review",
        "tier": 2,
        "status": "active",
        "visibility": "shared",
        "date": "2026-11-12",
    }


def _build_plan(scope: str, rng: random.Random, mode_count: int) -> _Plan:
    plan = _Plan(scope=scope)
    for n in range(_BACKGROUND_ARTIFACTS):
        plan.background.append(plan.artifact("background", n, _BACKGROUND_VECTORS_EACH))
    for n in range(_SMALL_TARGETS):
        plan.small.append(plan.artifact("target", n, rng.randint(*_SMALL_TARGET_SIZES)))
    plan.large = plan.artifact("large", 0, _LARGE_TARGET_VECTORS)
    for mode_index in range(mode_count):
        for trial in range(_RAW_TRIALS):
            plan.raw_base[(mode_index, trial)] = plan.artifact(
                f"raw-base-m{mode_index}", trial, _RAW_BASE_VECTORS
            )
    # Interleave artifacts across batches, as concurrent writers would.
    rng.shuffle(plan.items)
    return plan


# ── Summaries ─────────────────────────────────────────────────────────────────


def _completeness(lookup: _Lookup, expected: set[str]) -> dict[str, object]:
    returned = set(lookup.keys)
    return {
        "expected": len(expected),
        "returned": len(returned & expected),
        "foreign": len(returned - expected),
        "duplicates": len(lookup.keys) - len(returned),
        "pages": len(lookup.page_sizes),
        "page_sizes": lookup.page_sizes,
        "token_after_page": lookup.token_after_page,
        "error": lookup.error,
    }


def _is_complete(lookup: _Lookup, expected: set[str]) -> bool:
    return (
        lookup.error is None
        and set(lookup.keys) == expected
        and len(lookup.keys) == len(expected)
        and all(size <= _MAX_PAGE_SIZE for size in lookup.page_sizes)
    )


def _recall_rows(
    lookups: dict[str, list[_Lookup]], truth: dict[str, set[str]]
) -> dict[str, object]:
    """Per-artifact recall over a set of single-artifact lookups."""
    rows = [
        {
            "artifact": artifact_id.rsplit("/", 1)[1],
            "expected": len(truth[artifact_id]),
            "returned_per_rep": [len(set(lk.keys) & truth[artifact_id]) for lk in runs],
            "errors": [lk.error for lk in runs if lk.error],
            "foreign": sum(len(set(lk.keys) - truth[artifact_id]) for lk in runs),
        }
        for artifact_id, runs in lookups.items()
    ]
    recalls = [
        len(set(lk.keys) & truth[artifact_id]) / len(truth[artifact_id])
        for artifact_id, runs in lookups.items()
        for lk in runs
    ]
    incomplete = [
        row
        for row in rows
        if row["errors"] or row["foreign"] or min(row["returned_per_rep"]) < row["expected"]
    ]
    complete_sizes = sorted(row["expected"] for row in rows if row not in incomplete)
    return {
        "artifacts": len(rows),
        "lookups": len(recalls),
        "complete_lookups": sum(1 for recall in recalls if recall == 1.0),
        "mean_recall": round(statistics.fmean(recalls), 4) if recalls else None,
        "min_recall": round(min(recalls), 4) if recalls else None,
        "largest_always_complete_artifact": complete_sizes[-1] if complete_sizes else None,
        "smallest_incomplete_artifact": min((row["expected"] for row in incomplete), default=None),
        "below_100_percent": incomplete,
    }


def _latency(samples: Sequence[float]) -> dict[str, float | int]:
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)
    p95 = (
        statistics.quantiles(ordered, n=20, method="inclusive")[18]
        if len(ordered) > 1
        else ordered[0]
    )
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered) * 1000, 1),
        "p95_ms": round(p95 * 1000, 1),
        "max_ms": round(ordered[-1] * 1000, 1),
    }


def _await_visibility(
    index: _Index,
    artifact_id: str,
    expected: set[str],
    new_keys: set[str],
    query_mode: str | None,
    written_at: float,
) -> dict[str, object]:
    """Poll from the moment the write returned until every *new* key is returned — the
    read-after-write question — and report separately whether the whole artifact came back,
    which is the exhaustiveness question and must not be mistaken for lag."""
    backoff = iter(_RAW_BACKOFF_SECONDS)
    attempts = 0
    while True:
        query_started = time.perf_counter()
        lookup = index.lookup([artifact_id], query_mode)
        attempts += 1
        returned = set(lookup.keys)
        visible = lookup.error is None and new_keys <= returned
        if visible or time.perf_counter() - written_at > _RAW_POLL_CAP_SECONDS:
            return {
                "new_keys_visible": visible,
                "immediate": visible and attempts == 1,
                "attempts": attempts,
                "delay_s": round(query_started - written_at, 3) if visible else None,
                "new_keys_missing": len(new_keys - returned),
                "whole_artifact": f"{len(returned & expected)}/{len(expected)}",
                "error": lookup.error,
            }
        time.sleep(next(backoff, 1.0))


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def index(integration_settings: Settings) -> Iterator[_Index]:
    """The measuring wrapper; its teardown deletes every key it wrote and confirms none
    remains — run whether the test passed, failed or errored."""
    settings = integration_settings
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    client = session.client(
        "s3vectors", config=Config(retries={"mode": "standard", "max_attempts": 10})
    )
    if not _declares_query_mode(client):
        pytest.skip(
            f"botocore {botocore.__version__} does not declare QueryVectors.queryMode — run "
            "with a newer boto3/botocore layered on top (see this module's docstring)"
        )
    description = client.get_index(
        vectorBucketName=settings.vectors_bucket, indexName=settings.vectors_index
    )["index"]
    harness = _Index(
        client,
        settings.vectors_bucket,
        settings.vectors_index,
        dimension=description["dimension"],
        mode=description.get("indexMode", "CLASSIC"),
    )
    yield harness
    deleted, remaining = harness.delete_written()
    logger.info(
        "CALIBRATION_TEARDOWN deleted %d vector keys written by this run (%d writes recorded); "
        "%d still present on a GetVectors re-check",
        deleted,
        len(harness.written),
        remaining,
    )
    assert remaining == 0, f"{remaining} calibration vectors survived teardown"


# ── The calibration ───────────────────────────────────────────────────────────


@pytest.mark.integration
def test_calibrate_enhanced_filtered_query_as_per_artifact_lookup(
    integration_settings: Settings, index: _Index
) -> None:
    scope = integration_settings.write_prefix
    # The run scope is the only place this file may write; refuse anything else outright.
    assert scope.startswith(_RUN_PREFIX_ROOT), f"refusing to write outside the run scope: {scope}"

    rng = random.Random(_SEED)
    modes: list[tuple[str, str | None]] = [
        (_ENHANCED, _ENHANCED),
        (f"default ({index.mode})", None),
    ]
    plan = _build_plan(scope, rng, len(modes))

    # ── Seed, then prove by key that every target vector is stored as written.
    seed_started = time.perf_counter()
    index.put(plan.items)
    seeded_at = time.perf_counter()
    logger.info(
        "Seeded %d vectors over %d artifacts in %.1fs",
        len(plan.items),
        len(plan.truth),
        seeded_at - seed_started,
    )
    targets = [*plan.small, plan.large]
    target_keys = sorted(key for artifact_id in targets for key in plan.truth[artifact_id])
    stored = index.stored_artifact_ids(target_keys)
    ground_truth_check = {
        "target_keys_written": len(target_keys),
        "stored": len(stored),
        "artifact_id_mismatches": sum(
            1 for key, artifact_id in stored.items() if not key.startswith(f"{artifact_id}#")
        ),
    }
    logger.info("Ground-truth check: %s", ground_truth_check)

    in_ids = [*plan.small, plan.large, *plan.background[: _IN_LOOKUP_IDS - _SMALL_TARGETS - 1]]
    assert len(in_ids) == _IN_LOOKUP_IDS
    fit_ids = list(in_ids)
    while _filter_bytes(fit_ids) > _FILTER_MAX_BYTES:
        fit_ids.pop()
    in_sets = {
        "in_100_ids": (in_ids, set().union(*(plan.truth[a] for a in in_ids))),
        "in_fit_ids": (fit_ids, set().union(*(plan.truth[a] for a in fit_ids))),
    }

    # ── Repetitions with the fixed probe. Modes interleave within each repetition so that any
    # settling of freshly written vectors affects both alike.
    small: dict[str, dict[str, list[_Lookup]]] = {label: {} for label, _ in modes}
    large: dict[str, list[_Lookup]] = {label: [] for label, _ in modes}
    in_lookups: dict[str, dict[str, list[_Lookup]]] = {
        label: {name: [] for name in in_sets} for label, _ in modes
    }
    scoped: dict[str, list[_Lookup]] = {label: [] for label, _ in modes}
    rep_offsets: list[float] = []
    for _ in range(_REPEATS):
        rep_offsets.append(round(time.perf_counter() - seeded_at, 1))
        for label, query_mode in modes:
            for artifact_id in plan.small:
                small[label].setdefault(artifact_id, []).append(
                    index.lookup([artifact_id], query_mode)
                )
            large[label].append(index.lookup([plan.large], query_mode))
            for name, (ids, _expected) in in_sets.items():
                in_lookups[label][name].append(index.lookup(ids, query_mode))
            scoped[label].append(index.scoped_search(scope, query_mode))

    # ── Probe dependence: the same lookups with the artifact's own vector as the probe, and
    # with an unrelated random one. Only artifacts the fixed probe could have short-changed.
    probe_offset = round(time.perf_counter() - seeded_at, 1)
    probe_rng = random.Random(_SEED + 1)
    probed = [a for a in targets if len(plan.truth[a]) > 10]
    own_probe: dict[str, dict[str, list[_Lookup]]] = {label: {} for label, _ in modes}
    random_probe: dict[str, dict[str, list[_Lookup]]] = {label: {} for label, _ in modes}
    for label, query_mode in modes:
        for artifact_id in probed:
            own = _vector_for(sorted(plan.truth[artifact_id])[0], index.dimension)
            unrelated = _vector_for(f"probe-{probe_rng.random()}", index.dimension)
            own_probe[label][artifact_id] = [index.lookup([artifact_id], query_mode, own)]
            random_probe[label][artifact_id] = [index.lookup([artifact_id], query_mode, unrelated)]

    # ── Read-after-write.
    raw: dict[str, list[dict[str, object]]] = {label: [] for label, _ in modes}
    for mode_index, (label, query_mode) in enumerate(modes):
        for trial in range(_RAW_TRIALS):
            fresh_id = _artifact_id(scope, f"raw-new-m{mode_index}", trial)
            plan.truth[fresh_id] = set()
            fresh_items = plan.vectors(fresh_id, "section", _RAW_NEW_ARTIFACT_VECTORS)
            index.put(fresh_items)
            fresh = _await_visibility(
                index,
                fresh_id,
                plan.truth[fresh_id],
                {key for key, _ in fresh_items},
                query_mode,
                time.perf_counter(),
            )
            base_id = plan.raw_base[(mode_index, trial)]
            added_items = plan.vectors(base_id, "added", _RAW_ADDED_VECTORS)
            index.put(added_items)
            grown = _await_visibility(
                index,
                base_id,
                plan.truth[base_id],
                {key for key, _ in added_items},
                query_mode,
                time.perf_counter(),
            )
            raw[label].append({"trial": trial, "new_artifact": fresh, "existing_artifact": grown})

    # ── Settling: re-poll every ENHANCED lookup still short, until _SETTLE_UNTIL_SECONDS after
    # seeding or until none is short — separates indexing lag from a structural limit.
    short = {
        a
        for a in targets
        if not _is_complete(
            (large[_ENHANCED] if a == plan.large else small[_ENHANCED][a])[-1], plan.truth[a]
        )
    }
    settle: list[dict[str, object]] = []
    while short and time.perf_counter() - seeded_at < _SETTLE_UNTIL_SECONDS:
        time.sleep(_SETTLE_INTERVAL_SECONDS)
        offset = round(time.perf_counter() - seeded_at, 1)
        returned = {a: set(index.lookup([a], _ENHANCED).keys) & plan.truth[a] for a in short}
        recovered = sorted(len(plan.truth[a]) for a in short if returned[a] == plan.truth[a])
        settle.append(
            {
                "offset_after_seed_s": offset,
                "polled": len(short),
                "now_complete": len(recovered),
                "still_short": len(short) - len(recovered),
                "large_returned": len(returned.get(plan.large, set())),
                "short_returned_total": sum(len(keys) for keys in returned.values()),
            }
        )
        short = {a for a in short if returned[a] != plan.truth[a]}

    # ── Summary.
    large_keys = {label: [set(lk.keys) for lk in runs] for label, runs in large.items()}
    enhanced_large_returned = set().union(*large_keys[_ENHANCED])
    missing_large = plan.truth[plan.large] - enhanced_large_returned
    summary: dict[str, object] = {
        "boto3": boto3.__version__,
        "botocore": botocore.__version__,
        "region": integration_settings.aws_region,
        "index_mode": index.mode,
        "dimension": index.dimension,
        "scope": scope,
        "vectors_written": len(index.written),
        "artifacts_written": len(plan.truth),
        "background_vectors": _BACKGROUND_ARTIFACTS * _BACKGROUND_VECTORS_EACH,
        "seed_seconds": round(seeded_at - seed_started, 1),
        "repetition_offsets_after_seed_s": rep_offsets,
        "probe_phase_offset_after_seed_s": probe_offset,
        "ground_truth_check": ground_truth_check,
        "in_lookup_sizes": {
            name: {"ids": len(ids), "filter_bytes": _filter_bytes(ids), "vectors": len(expected)}
            for name, (ids, expected) in in_sets.items()
        },
        "large_same_keys_every_rep_and_mode": len(
            {frozenset(keys) for runs in large_keys.values() for keys in runs}
        )
        == 1,
        "large_missing_by_put_batch": dict(
            sorted(Counter(index.batch_of[k] for k in missing_large).items())
        ),
        "large_returned_by_put_batch": dict(
            sorted(Counter(index.batch_of[k] for k in enhanced_large_returned).items())
        ),
        "settle_enhanced": settle,
    }
    modes_summary: dict[str, object] = {}
    for label, _ in modes:
        all_lookups = [
            *(lk for runs in small[label].values() for lk in runs),
            *large[label],
            *(lk for runs in in_lookups[label].values() for lk in runs),
        ]
        modes_summary[label] = {
            "small_targets_fixed_probe": _recall_rows(small[label], plan.truth),
            "large_target": [_completeness(lk, plan.truth[plan.large]) for lk in large[label]],
            "in_lookups": {
                name: [_completeness(lk, in_sets[name][1]) for lk in runs]
                for name, runs in in_lookups[label].items()
            },
            "own_vector_probe": _recall_rows(own_probe[label], plan.truth),
            "random_probe": _recall_rows(random_probe[label], plan.truth),
            "read_after_write": raw[label],
            "latency": {
                "eq_single_artifact": _latency(
                    [lk.seconds for runs in small[label].values() for lk in runs]
                ),
                "eq_large_artifact_all_pages": _latency([lk.seconds for lk in large[label]]),
                "in_fit_ids_all_pages": _latency(
                    [lk.seconds for lk in in_lookups[label]["in_fit_ids"]]
                ),
                "per_page": _latency([s for lk in all_lookups for s in lk.page_seconds]),
                "scoped_search_top10": _latency([lk.seconds for lk in scoped[label]]),
            },
            "retries": sum(lk.retries for lk in (*all_lookups, *scoped[label])),
            "scoped_search_errors": [lk.error for lk in scoped[label] if lk.error],
        }
    summary["modes"] = modes_summary
    summary["queries_sent"] = index.queries
    logger.info("CALIBRATION_SUMMARY\n%s", json.dumps(summary, indent=2))

    # ── The ENHANCED properties the earlier lookup design stood on, reported, not asserted:
    # the 2026-11-12 run found them false, which is why the ADR reads by key instead.
    enhanced = modes_summary[_ENHANCED]
    shortfalls = [
        f"ENHANCED fixed probe: {row['artifact']} returned {row['returned_per_rep']} of "
        f"{row['expected']} (errors {row['errors']}, foreign {row['foreign']})"
        for row in enhanced["small_targets_fixed_probe"]["below_100_percent"]
    ]
    shortfalls += [
        f"ENHANCED: large artifact rep {rep}: {_completeness(lk, plan.truth[plan.large])}"
        for rep, lk in enumerate(large[_ENHANCED])
        if not _is_complete(lk, plan.truth[plan.large])
    ]
    shortfalls += [
        f"ENHANCED: {name} rep {rep}: {_completeness(lk, in_sets[name][1])}"
        for name, runs in in_lookups[_ENHANCED].items()
        for rep, lk in enumerate(runs)
        if not _is_complete(lk, in_sets[name][1])
    ]
    shortfalls += [
        f"ENHANCED: read-after-write trial {trial['trial']} {kind}: {trial[kind]}"
        for trial in raw[_ENHANCED]
        for kind in ("new_artifact", "existing_artifact")
        if not trial[kind]["immediate"]
    ]
    if shortfalls:
        logger.warning("ENHANCED shortfalls:\n%s", "\n".join(shortfalls))

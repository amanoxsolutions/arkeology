---
type: feature-spec
feature: moto-migration
created: 2026-06-01
status: ready
---

# Migrate unit tests from hand-rolled fakes to moto

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Unit tests for S3 and S3 Vectors use hand-rolled in-memory fakes (`FakeS3Client`,
`FakeVectorsClient`) instead of moto, violating the project's testing convention (testing
skill: "Mock AWS services with moto"). Additionally, `FakeVectorsClient.query_vectors` returns
scores in `[0, 2]` (shifted cosine similarity) while `VectorsClientImpl.query_vectors` returns
scores in `[-1, 1]` (`1.0 − cosine_distance`), making score assertions in unit tests unreliable
and inconsistent with production behaviour. Both issues must be resolved before v0.1.0.

## User Stories

### Story 1 — S3 mocked with moto (P1)

All unit tests that currently inject `FakeS3Client` instead inject an `S3ClientImpl` instance
backed by moto. `FakeS3Client` and its test file are deleted.

**Acceptance criteria:**
- Given the `@mock_aws` decorator active and a real S3 bucket pre-created, when a tool test
  calls any S3 operation through `S3ClientImpl`, then the call succeeds against moto without
  hitting real AWS.
- Given `fake_s3.py` deleted, when `uv run ruff check src/ tests/` runs, then there are no
  import errors.

### Story 2 — S3 Vectors mocked with moto + `query_vectors` extension (P1)

All unit tests that currently inject `FakeVectorsClient` instead inject a `VectorsClientImpl`
instance backed by moto. A `query_vectors` extension is patched onto moto's
`S3VectorsBackend` to cover the one unimplemented operation. `FakeVectorsClient` and its test
file are deleted.

**Acceptance criteria:**
- Given the `@mock_aws` decorator active, a real vector bucket and index pre-created, and
  vectors written via `put_vectors`, when `VectorsClientImpl.query_vectors` is called, then it
  returns results ranked by cosine similarity without hitting real AWS.
- Given `fake_vectors.py` deleted, when `uv run ruff check src/ tests/` runs, then there are
  no import errors.

### Story 3 — Score range aligned between unit and production (P1)

The `query_vectors` moto extension returns `score = 1.0 − cosine_distance` (i.e. cosine
similarity), range `[−1, 1]`, matching `VectorsClientImpl` exactly.

**Acceptance criteria:**
- Given two identical unit vectors stored and queried, when `query_vectors` is called via the
  moto-backed `VectorsClientImpl`, then the returned score is `1.0`.
- Given two orthogonal vectors stored and queried, when `query_vectors` is called, then the
  returned score is `0.0`.
- Given `test_all_scores_in_valid_range` updated to assert `−1.0 ≤ score ≤ 1.0`, when the
  unit test suite runs, then it passes.

### Story 4 — AGENTS.md documents the convention (P1)

AGENTS.md is updated so future contributors know to use moto, know `query_vectors` is patched
via extension, and know `FakeBedrockClient` is kept intentionally.

**Acceptance criteria:**
- Given a developer reads AGENTS.md, they can find: (a) the moto convention for AWS mocking,
  (b) where the `query_vectors` extension lives and why it exists, (c) why `FakeBedrockClient`
  is kept despite the moto convention.

## Requirements

- WHEN a unit test requires an S3 client THE SYSTEM SHALL provide an `S3ClientImpl` instance
  backed by moto via a shared pytest fixture.
- WHEN a unit test requires a Vectors client THE SYSTEM SHALL provide a `VectorsClientImpl`
  instance backed by moto (with `query_vectors` patched) via a shared pytest fixture.
- WHEN `query_vectors` is called on the moto-backed client THE SYSTEM SHALL return results
  ordered by `score = 1.0 − cosine_distance` descending, applying the `filter_expr` via
  `cairn_mcp.clients.filter.matches_filter`.
- WHEN a test needs to simulate a credential error on S3 or Vectors THE SYSTEM SHALL use
  `mocker.patch.object` to raise `CredentialError` on the specific client method under test.
- WHEN a test needs to track call counts on a client method THE SYSTEM SHALL use
  `mocker.spy` or `mocker.patch.object(…, wraps=…)`.
- WHEN a test needs to simulate a partial failure (e.g. `put_vector` raises) THE SYSTEM SHALL
  use `mocker.patch.object(…, side_effect=…)`.

## Boundaries

**Always:**
- `FakeBedrockClient` is kept — moto's `invoke_model` returns a generic stub, not
  deterministic per-text embedding vectors; the hash-derived unit vectors in `FakeBedrockClient`
  are required for search ordering assertions.
- `src/cairn_mcp/clients/filter.py` is kept — reused by both the `query_vectors` moto
  extension and `VectorsClientImpl.list_vectors_by_metadata`.
- All tests must pass `uv run pytest tests/unit/ -q -m 'not integration'` after migration.
- ruff check, ruff format, and mypy must all be clean after migration.
- The moto `query_vectors` extension must be applied once, in `tests/unit/conftest.py`, before
  any test session begins — not per-test or per-file.

**Ask First:**
- If the moto `S3VectorsBackend` internal data structure for stored vectors cannot be
  determined from moto source inspection, ask before implementing the extension.

**Never:**
- Do not reintroduce hand-rolled fakes for S3 or S3 Vectors.
- Do not use `unittest.mock.MagicMock` as a drop-in for entire client objects — use
  `mocker.patch.object` on specific methods only.
- Do not modify any integration test — this spec covers unit tests only.
- Do not change any tool source code in `src/cairn_mcp/` — this is a test infrastructure
  change only.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Modify | Add `moto[s3,s3vectors]>=5.0` to `[dependency-groups] dev`; add `boto3-stubs[s3vectors]` to the boto3-stubs extras |
| `tests/unit/conftest.py` | Modify | Add `mock_aws` fixture (function-scoped), `s3_client` and `vectors_client` fixtures backed by moto; apply `query_vectors` extension to `S3VectorsBackend` at module load |
| `tests/unit/clients/test_fake_vectors.py` | Delete | Replaced by `test_moto_query_vectors_extension.py` |
| `tests/unit/clients/test_fake_s3.py` | Delete | moto is maintained by its own test suite; no value in re-testing it here |
| `tests/unit/clients/test_moto_query_vectors_extension.py` | Create | Tests for the `query_vectors` extension: score for identical vectors = 1.0, score for orthogonal vectors = 0.0, results ranked descending, filter_expr respected, top_k respected |
| `src/cairn_mcp/clients/fakes/fake_s3.py` | Delete | Replaced by moto |
| `src/cairn_mcp/clients/fakes/fake_vectors.py` | Delete | Replaced by moto + extension |
| `tests/unit/test_startup.py` | Modify | Replace `FakeS3Client` / `FakeVectorsClient` with moto-backed clients from fixtures; replace `set_credential_failure(True)` with `mocker.patch.object`; replace `FakeVectorsClient(index_missing=True)` by not creating the index in the fixture |
| `tests/unit/test_tools_write.py` | Modify | Replace `FakeS3Client` / `FakeVectorsClient` with moto-backed clients; replace `TrackingVectors` subclass with `mocker.spy`; replace credential failure simulation with `mocker.patch.object` |
| `tests/unit/test_tools_search.py` | Modify | Replace `FakeVectorsClient` with moto-backed client; update any score assertions to `[−1, 1]` range |
| `tests/unit/test_tools_read.py` | Modify | Replace `FakeS3Client` with moto-backed client |
| `tests/unit/test_tools_list.py` | Modify | Replace `FakeVectorsClient` with moto-backed client |
| `tests/unit/test_tools_archive.py` | Modify | Replace `FakeVectorsClient` with moto-backed client |
| `tests/unit/test_tools_delete.py` | Modify | Replace `FakeS3Client` / `FakeVectorsClient` with moto-backed clients |
| `tests/unit/test_tools_purge.py` | Modify | Replace `FakeS3Client` / `FakeVectorsClient` with moto-backed clients |
| `tests/unit/test_tools_health.py` | Modify | Replace `FakeS3Client` / `FakeVectorsClient` with moto-backed clients; replace `set_credential_failure` with `mocker.patch.object` |
| `tests/unit/test_tools_reconcile.py` | Modify | Replace fakes with moto-backed clients; replace `TrackingVectors` and `ExplodingVectors` subclasses with `mocker.spy` / `mocker.patch.object` |
| `tests/unit/test_tools_synthesise.py` | Modify | Replace `FakeVectorsClient` with moto-backed client |
| `tests/unit/test_tools_freshness.py` | Modify | Replace `FakeVectorsClient` with moto-backed client |
| `AGENTS.md` | Modify | Update Repository Structure table (remove `fake_s3.py`, `fake_vectors.py`; add `test_moto_query_vectors_extension.py`); update Working Conventions; add moto testing convention to a new Testing Conventions section; fix score range in High-Friction Areas (currently says `[0.0, 1.0]`, must be `[−1, 1]`) |

## Testing Approach

This spec is TDD. The extension is new logic; it is written test-first. The test migrations
are transformations of existing tests; they follow the existing test behaviour.

**Red phase — write and confirm failing:**

1. `tests/unit/clients/test_moto_query_vectors_extension.py` — write tests for the
   `query_vectors` extension before implementing it:
   - `test_identical_vectors_score_equals_one` — identical query and stored vector → `score == 1.0`
   - `test_orthogonal_vectors_score_equals_zero` — orthogonal vectors → `score == 0.0`
   - `test_results_ordered_by_score_descending` — multiple vectors → results are ranked descending
   - `test_filter_expr_excludes_non_matching` — filter_expr removes non-matching vectors
   - `test_top_k_limits_results` — only top_k results returned
   - `test_empty_index_returns_empty_list` — no stored vectors → empty result

   Run `uv run pytest tests/unit/clients/test_moto_query_vectors_extension.py -q` — must fail
   (RED) because the extension does not exist yet.

**Green phase — implement then migrate:**

2. Implement the `query_vectors` extension in `tests/unit/conftest.py` (see pattern below).
   Run the new tests — must pass (GREEN).

3. Migrate test files one at a time. After each file, run the full unit suite to catch
   regressions. Suggested order: `test_startup.py` → `test_tools_health.py` →
   `test_tools_write.py` → `test_tools_read.py` → `test_tools_search.py` →
   `test_tools_list.py` → `test_tools_archive.py` → `test_tools_delete.py` →
   `test_tools_purge.py` → `test_tools_reconcile.py` → `test_tools_synthesise.py` →
   `test_tools_freshness.py`.

4. Delete `fake_s3.py`, `fake_vectors.py`, `test_fake_s3.py`, `test_fake_vectors.py`.
   Run `uv run ruff check src/ tests/` — must be clean.

5. Update `AGENTS.md`. Run the full quality gate:
   ```bash
   uv run pytest tests/unit/ -q -m 'not integration'
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run mypy src/
   ```

**Implementation patterns for the developer:**

### conftest.py — `query_vectors` extension and fixtures

```python
import math
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from cairn_mcp.clients.filter import matches_filter
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _moto_query_vectors(
    self: Any,
    vector_bucket_name: str,
    index_name: str,
    query_vector: list[float],
    top_k: int,
    filter_expr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Moto extension: cosine similarity search over moto's in-memory vector store.

    Score = 1.0 - cosine_distance = cosine_similarity, range [-1, 1].
    Matches VectorsClientImpl.query_vectors score semantics exactly.
    """
    # NOTE: inspect moto's S3VectorsBackend internals to find the correct
    # attribute path for stored vectors (e.g. self.vector_buckets[...].indexes[...].vectors).
    # Adjust the access pattern below to match the moto source.
    bucket = self.vector_buckets[vector_bucket_name]
    index = bucket.indexes[index_name]
    candidates = []
    for key, entry in index.vectors.items():
        meta = entry.metadata or {}
        if filter_expr is not None and not matches_filter(meta, filter_expr):
            continue
        vec = entry.data["float32"]
        cosine_dist = 1.0 - _cosine_similarity(query_vector, vec)
        candidates.append({"key": key, "distance": cosine_dist, "metadata": meta})
    candidates.sort(key=lambda r: float(r["distance"]))
    results = candidates[:top_k]
    # Convert to the response shape VectorsClientImpl.query_vectors expects:
    # {"key": ..., "score": 1.0 - distance, "metadata": ...}
    # NOTE: VectorsClientImpl already applies `score = 1.0 - distance` from the boto3
    # response, so the extension must return {"distance": value} not {"score": value}.
    return [{"key": r["key"], "distance": r["distance"], "metadata": r["metadata"]}
            for r in results]


# Apply the extension once at import time.
from moto.s3vectors.models import S3VectorsBackend  # noqa: E402
S3VectorsBackend.query_vectors = _moto_query_vectors


@pytest.fixture
def aws_mock():
    """Activate moto for all AWS services for the duration of the test."""
    with mock_aws():
        yield


@pytest.fixture
def s3_client(aws_mock, settings):
    """S3ClientImpl backed by moto. Bucket pre-created."""
    boto3.client("s3", region_name=settings.aws_region).create_bucket(
        Bucket=settings.artifact_bucket,
        CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
    )
    return S3ClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.artifact_bucket,
    )


@pytest.fixture
def vectors_client(aws_mock, settings):
    """VectorsClientImpl backed by moto. Vector bucket and index pre-created."""
    s3v = boto3.client("s3vectors", region_name=settings.aws_region)
    s3v.create_vector_bucket(vectorBucketName=settings.vectors_bucket)
    s3v.create_index(
        vectorBucketName=settings.vectors_bucket,
        indexName=settings.vectors_index,
        dataType="float32",
        dimension=1024,
        distanceMetric="cosine",
    )
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )
```

### Credential error simulation (replaces `set_credential_failure`)

```python
# Before
s3 = FakeS3Client()
s3.set_credential_failure(True)

# After — patch the specific method under test
from cairn_mcp.errors import CredentialError

def test_credential_error_on_head_bucket(mocker, s3_client, vectors_client, bedrock, settings):
    mocker.patch.object(
        s3_client, "head_bucket",
        side_effect=CredentialError(message="expired", service="s3", original=Exception()),
    )
    ...
```

### Missing index simulation (replaces `FakeVectorsClient(index_missing=True)`)

```python
# After — use a fixture that does NOT create the index
@pytest.fixture
def vectors_client_no_index(aws_mock, settings):
    s3v = boto3.client("s3vectors", region_name=settings.aws_region)
    s3v.create_vector_bucket(vectorBucketName=settings.vectors_bucket)
    # Index intentionally not created
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=None,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )
```

### Call tracking (replaces `TrackingVectors` subclass)

```python
# Before
class TrackingVectors(FakeVectorsClient):
    def __init__(self): super().__init__(); self.put_calls = 0
    def put_vector(self, *a, **kw): self.put_calls += 1; super().put_vector(*a, **kw)

# After
spy = mocker.spy(vectors_client, "put_vector")
# ... run tool ...
assert spy.call_count == expected
```

### Partial failure simulation (replaces `ExplodingVectors` subclass)

```python
# Before
class ExplodingVectors(FakeVectorsClient):
    def put_vector(self, *a, **kw): raise Exception("simulated failure")

# After
mocker.patch.object(vectors_client, "put_vector", side_effect=Exception("simulated failure"))
```

## Open Questions

- [ ] **moto S3VectorsBackend internals**: The `query_vectors` extension accesses moto's
  in-memory vector store via `self.vector_buckets[...].indexes[...].vectors`. The developer
  must inspect the moto S3 Vectors source at the installed version to confirm the exact
  attribute path before implementing. If the path differs, adjust the extension accordingly.
- [ ] **`us-east-1` bucket creation**: boto3/moto requires no `CreateBucketConfiguration`
  for `us-east-1`. If `settings.aws_region` is `us-east-1` in tests, remove the
  `LocationConstraint` from the `s3_client` fixture. Confirm the region used in tests.

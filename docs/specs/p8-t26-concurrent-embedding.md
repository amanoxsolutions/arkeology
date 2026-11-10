---
type: Spec
id: p8-t26-concurrent-embedding
title: Write Performance P1 — Concurrent Embedding + Batched put_vectors
description: Introduces concurrent section embedding via asyncio and a single batched put_vectors call per artifact, reducing per-artifact write time from N×(embed+put) to ceil(N/SECTION_CONCURRENCY)×embed + 1×put.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-02T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T15:56:54Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Write Performance P1 — Concurrent Embedding + Batched put_vectors

## TL;DR

`write_artifact` embeds sections serially (one Bedrock call then one `put_vector` call per
section), making a 8-section document cost 8 × embed + 8 × put ≈ 3.6 s in ideal conditions.
This spec introduces concurrent section embedding via `asyncio.to_thread` + `asyncio.gather`
(with a configurable semaphore) and collapses all `put_vector` calls per artifact into a single
batched `put_vectors` call — reducing per-artifact write time from `N × (embed + put)` to
`ceil(N / SECTION_CONCURRENCY) × embed + 1 × put`.

## Open Questions

- Should `put_vectors_batch` chunk silently (recommended) or raise if item count > 500?
  Recommendation: silent chunking — consistent with the existing `delete_vectors` behaviour
  and defensive against any future removal of `EMBED_MAX_SECTIONS`.

## 1. Problem Statement

The brainstorming session (2026-06-01) identified RC-1 (sequential embedding) and RC-2
(one `put_vector` call per section) as the two dominant latency contributors. For a 10-document
migration with 8 sections each, the sequential path takes 24–344 s depending on Bedrock
throttle rate. Concurrent embedding reduces embed time from `N × latency` to
`ceil(N / semaphore) × latency`; batched `put_vectors` eliminates `N − 1` network round-trips
per artifact. Combined, the per-artifact write time drops roughly 5× without any interface
change visible to callers.

All four user stories this spec states are P1: a single artifact with multiple sections writes
faster, a Bedrock failure on any section aborts the entire artifact atomically, concurrency is
bounded by a configurable semaphore, and the document-level fallback (no sections) is unchanged.

## 2. Rules — Concurrent section embedding

### R1 — Sections are embedded concurrently, bounded by the semaphore

When `write_artifact` processes a document with one or more `##` sections, it embeds all
sections concurrently using `asyncio.to_thread` + `asyncio.gather` limited by an
`asyncio.Semaphore(settings.section_concurrency)` — up to `SECTION_CONCURRENCY` at a time — so
an operator can avoid Bedrock throttling by limiting concurrent embed calls.

**Example**

- Given a document with 8 `##` sections and `SECTION_CONCURRENCY=5`, when `write_artifact` is
  called, then `bedrock.embed` is invoked 8 times.
- Given `SECTION_CONCURRENCY=2` and a 6-section document, when `write_artifact` is called, then
  at most 2 `bedrock.embed` calls are in-flight simultaneously (verifiable by the order in which
  a spy records calls relative to a small artificial delay in tests).

Source: —

### R2 — All embedding results are gathered before success or failure is decided

When gathering embeddings, `write_artifact` uses `return_exceptions=True` to collect all results
before deciding on success or failure.

Source: —

### R3 — A failed section embedding aborts the whole artifact atomically

If any section embedding fails, the tool does not partially index the artifact: no vectors are
written if any embed raises an exception.

| Any gathered result is… | `write_artifact` … |
|---|---|
| a `CredentialError` | returns `{"error": "credential_error", "message": ..., "artifact_id": ...}` without calling `put_vectors_batch` |
| any other exception | writes a failure log entry and returns `{"error": "partial_write", "message": ..., "artifact_id": ...}` without calling `put_vectors_batch` |

**Example**

- Given a document with 3 sections where the second embed raises an exception, when
  `write_artifact` returns, then `vectors.put_vectors_batch` is never called, the failure log
  receives an entry, and the response contains `{"error": "partial_write", "artifact_id": ...}`.
- Given a CredentialError on any embed, when `write_artifact` returns, then the response contains
  `{"error": "credential_error", ...}` and no vectors are written.

Source: —

## 3. Rules — Batched vector write

### R4 — One batched `put_vectors_batch` call per artifact

When all embeddings succeed, `write_artifact` calls `vectors.put_vectors_batch` exactly once per
artifact with all (key, embedding, metadata) tuples — for an 8-section document, a single
`put_vectors` API call indexes all 8 vectors.

**Example**

- Given a document with 8 `##` sections and `SECTION_CONCURRENCY=5`, when `write_artifact` is
  called, then `vectors.put_vectors_batch` is invoked exactly once with 8 entries.
- Given the same document, when `write_artifact` returns successfully, then the response contains
  `sections_indexed == 8` as before.

Source: —

### R5 — `put_vectors_batch` chunks at 500 items

When `put_vectors_batch` is called with more than 500 items, it chunks the list into batches of
at most 500 (matching the S3 Vectors `PutVectors` API limit).

Source: —

## 4. Rules — Configuration and fallback

### R6 — `SECTION_CONCURRENCY` defaults to 5 and must be at least 1

When `SECTION_CONCURRENCY` is absent from the environment, it defaults to 5. When
`SECTION_CONCURRENCY` is set to a value less than 1, it is rejected at startup with a clear
validation error.

**Example**

- Given `SECTION_CONCURRENCY=0` or a non-positive integer, when the server starts, then config
  validation raises a clear error before accepting any requests.

Source: —

### R7 — The document-level fallback (no sections) is unchanged

An artifact with no `##` headings uses a single document-level embed. When `write_artifact`
processes a document with no `##` sections, it retains the existing document-level fallback
behaviour unchanged (one embed, one vector); the concurrency change does not alter this path.

**Example**

- Given content with no `##` sections, when `write_artifact` is called, then exactly one
  `bedrock.embed` call is made and one `vectors.put_vectors_batch` call is made with a single
  entry.

Source: —

## 5. Boundaries

**Always:**

- `asyncio.to_thread` (Python 3.9+ stdlib) is preferred over `loop.run_in_executor(None, ...)`.
  Both are equivalent; `asyncio.to_thread` is cleaner at the call site.
- The `BedrockClientInterface.embed` signature stays synchronous — wrapping happens at the call
  site in `write.py`, not inside the client. This isolates the concurrency change to the tool
  layer.
- `put_vectors_batch` is a new method on `VectorsClientInterface` (Protocol). The existing
  `put_vector` method is retained for use by other callers (orphan-cleanup path is unaffected).
- The chunk limit for `put_vectors_batch` is 500 (confirmed S3 Vectors `PutVectors` API limit).
  In practice `EMBED_MAX_SECTIONS` (default 20 per P3 spec) means chunking is never triggered,
  but the implementation must be correct for documents that exceed 500 sections.
- Vector metadata remains identical to today: same fields, same types, same encoding.
- Orphan-cleanup logic (Step 8 in `_write_artifact_inner`) is unaffected by this spec.

**Ask First:**

- Whether `put_vectors_batch` should silently chunk or raise if item count exceeds 500 when
  `EMBED_MAX_SECTIONS` is in place. (Default recommendation: silently chunk — defensive and
  correct regardless of section cap.)

**Never:**

- Do not change `BedrockClientInterface.embed` to `async def` in this spec — that is a V2
  concern (A2 from brainstorming). The sync method is called from a thread pool here.
- Do not inline the semaphore as a hard-coded constant — it must read from
  `settings.section_concurrency`.
- Do not remove or replace the document-level fallback path for no-section artifacts.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_s3.py` | Modify | Add `put_vectors_batch` tests on `VectorsClientImpl` via moto (written first — Red) |
| `tests/unit/test_tools_write.py` | Modify | Add concurrent-embedding and batch-put tests; update existing embed/put call-count assertions (written first — Red) |
| `src/arkeology/clients/interfaces.py` | Modify | Add `put_vectors_batch` method to `VectorsClientInterface` Protocol |
| `src/arkeology/clients/vectors.py` | Modify | Implement `put_vectors_batch` (chunk at 500, delegate to `self._client.put_vectors`) |
| `src/arkeology/config.py` | Modify | Add `SECTION_CONCURRENCY` field (int, default 5) with validator ≥ 1; add `section_concurrency` property |
| `src/arkeology/tools/write.py` | Modify | Replace section `for` loop with `asyncio.to_thread` + `asyncio.gather`; call `put_vectors_batch` instead of per-section `put_vector`; propagate semaphore from settings |

### Contracts

None.

### Testing Approach

**TDD cycle A (client layer):** write `put_vectors_batch` tests in `test_s3.py` first (Red) →
implement `put_vectors_batch` in `vectors.py` + add to interface (Green).

**TDD cycle B (tool layer):** update `test_tools_write.py` first (Red) → implement
concurrent embedding + batch put in `write.py` (Green).

---

**`tests/unit/clients/test_s3.py` — new tests:**

- `test_put_vectors_batch_single_chunk` — call `put_vectors_batch` with 3 items; assert
  `VectorsClientImpl` makes exactly one underlying `put_vectors` API call containing all 3.
- `test_put_vectors_batch_chunked_at_500` — call `put_vectors_batch` with 501 items; assert
  two underlying `put_vectors` calls (500 + 1). Use `mocker.spy` on the boto3 client.
- `test_put_vectors_batch_empty_list` — call with empty list; assert no API call is made and
  no exception is raised.
- `test_put_vectors_batch_credential_error` — patch the underlying `put_vectors` to raise a
  credential error; assert `CredentialError` is raised.

**`tests/unit/test_tools_write.py` — new and modified tests:**

New tests (concurrent path):
- `test_write_sections_embeds_all_concurrently` — use `mocker.spy(fake_bedrock, "embed")`
  to confirm 8 `embed` calls are made for an 8-section document; assert
  `put_vectors_batch` is called once (spy on the vectors client).
- `test_write_sections_batch_put_called_once` — 5-section doc; assert
  `vectors.put_vectors_batch` call count is 1 (not 5).
- `test_write_any_embed_failure_aborts_atomically` — configure `FakeBedrockClient` to fail
  on the 2nd call; assert `put_vectors_batch` is never called and the response contains
  `"error": "partial_write"`.
- `test_write_embed_credential_error_aborts` — configure a `CredentialError` on embed;
  assert response `"error" == "credential_error"` and no vectors written.
- `test_write_sections_semaphore_default` — smoke test that a 10-section write completes
  without error under default `SECTION_CONCURRENCY=5`.

Existing tests to update:
- Any test that currently asserts `vectors.put_vector` call count should be updated to
  assert `vectors.put_vectors_batch` call count instead.
- Tests that previously relied on `put_vector` being called N times per N sections must be
  updated to expect exactly one `put_vectors_batch` call with N items.

**Config tests (`tests/unit/test_config.py`) — additions:**
- `test_section_concurrency_default` — Settings without `SECTION_CONCURRENCY` → defaults to 5.
- `test_section_concurrency_zero_invalid` — `SECTION_CONCURRENCY=0` → `ValidationError`.
- `test_section_concurrency_negative_invalid` — `SECTION_CONCURRENCY=-1` → `ValidationError`.

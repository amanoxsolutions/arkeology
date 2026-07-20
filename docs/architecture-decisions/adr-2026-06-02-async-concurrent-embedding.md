---
type: adr
title: Async Semaphore-Bounded Concurrent Embedding
description: Records the move from a serial embedding loop to bounded concurrent embedding using asyncio.gather with asyncio.Semaphore, and the companion change to batch section vectors into a single put_vectors_batch call per artifact.
tags: []
timestamp: 2026-06-02T00:00:00Z
okf_version: "0.1"
status: accepted
references: []
authored:
  by: architect
  date: "2026-06-02"
revised:
  by: tech-writer
  date: "2026-07-05"
---

# Async Semaphore-Bounded Concurrent Embedding

## Description

Embedding each artifact section requires an independent call to Amazon Bedrock. This decision
records the move from a serial embedding loop to bounded concurrent embedding using
`asyncio.gather` with `asyncio.Semaphore`, and the companion change to batch all resulting
section vectors into a single `put_vectors_batch` call per artifact.

## Status

Accepted

## Context

The original write path (Phases 1–7) used a sequential `for` loop over sections: each section
was embedded with `await bedrock.embed(...)` then written with `vectors.put_vector(...)` before
the next section began. For an artifact with 8 sections this meant 8 serial Bedrock round-trips
before the write could complete.

The write latency target (NFR-13) requires `write_artifact` to complete in under 2 seconds
wall-clock time for a typical artifact with ≤ 20 sections. With serial embedding, each Bedrock
call contributes 100–300 ms, making the target unreachable for anything beyond 3–4 sections.

At the same time, Bedrock has rate limits (Titan Text Embeddings v2: 6,000 RPM, 300,000 TPM
in eu-central-1). Unbounded concurrent calls from multiple agents or multiple bulk-write
operations risk hitting those limits simultaneously. A thundering-herd retry scenario — where
multiple throttled calls all retry at the same instant — can amplify a transient quota event
into a sustained failure. Jitter on the retry sleep in `bedrock.py` addresses this.

The `write_artifacts` and `migrate_artifacts` bulk tools introduced in Phase 9 added a second
concurrency level: multiple artifacts processed concurrently. The maximum simultaneous Bedrock
calls is the product `ARTIFACT_CONCURRENCY × SECTION_CONCURRENCY`. At defaults (3 × 5 = 15)
the server operates well within the Titan quota for a single session.

FastMCP runs tools as async functions. `boto3` calls are synchronous. `asyncio.to_thread` is
used to run each `bedrock.embed()` call in a thread pool without blocking the event loop.

## Decision

Section embedding within a single artifact uses `asyncio.to_thread` + `asyncio.gather` bounded
by `asyncio.Semaphore(SECTION_CONCURRENCY)`. Default is 5 concurrent embedding calls per
artifact. After all section embeddings complete, all resulting vectors are written in a single
`vectors.put_vectors_batch()` call per artifact (chunked at the S3 Vectors API limit of 500
vectors per call).

Artifact-level concurrency in `write_artifacts` and `migrate_artifacts` uses a separate
`asyncio.Semaphore(ARTIFACT_CONCURRENCY)`. Default is 3 concurrent artifacts.

The Bedrock retry in `bedrock.py` applies one retry with `random.uniform(0, 1)` seconds of
jitter on `ThrottlingException`. The duplicate retry block that previously existed in
`write.py` was removed in Phase 8 (T27) — double-retrying on throttle extended write latency
by up to 5 seconds per throttled section for no benefit.

Both `SECTION_CONCURRENCY` and `ARTIFACT_CONCURRENCY` are validated at startup — values less
than 1 cause a hard startup failure.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — `asyncio.gather` + `asyncio.Semaphore` | Idiomatic for async Python; bounded concurrency; works naturally inside FastMCP's async event loop; jitter prevents thundering herd | Requires `asyncio.to_thread` for synchronous boto3 calls; combined product `ARTIFACT_CONCURRENCY × SECTION_CONCURRENCY` must be documented as a quota guideline |
| `ThreadPoolExecutor` directly | Familiar synchronous-style concurrency | Less idiomatic inside an `async` FastMCP tool; requires explicit executor management; harder to bound with a semaphore |
| Sequential `for` loop (original) | Simplest implementation; no concurrency complexity | Does not meet the NFR-13 write latency target for artifacts with more than 3–4 sections |
| One Bedrock call per artifact (concatenated text) | Single embed call per write | Loses section-level semantic granularity; contradicts ADR-006; concatenated text may exceed token limits for long artifacts |

## Consequences

- A typical 8-section artifact completes in approximately the time of one Bedrock round-trip
  (5 concurrent calls effectively parallelise all 8 sections across two waves), meeting the
  NFR-13 target.
- All section vectors for one artifact are written in a single `put_vectors_batch` call,
  reducing S3 Vectors API calls from N (one per section) to 1 per artifact.
- The product `ARTIFACT_CONCURRENCY × SECTION_CONCURRENCY` must be kept at or below ~15 for
  single-session use and lower for multi-session deployments. Configuration documentation
  states the recommended ceiling explicitly.
- `SECTION_CONCURRENCY=0` and `ARTIFACT_CONCURRENCY=0` are rejected at startup — these values
  would silently disable all writes.
- The jitter in `bedrock.py` (`random.uniform(0, 1)` seconds before the single retry)
  distributes simultaneous retries across a 1-second window, preventing a coordinated
  thundering herd when `SECTION_CONCURRENCY` concurrent embeds all throttle at once.
- The migration skill's previous `migrate.py` script duplicated the write path with a serial
  loop and was therefore always slower than calling the server. It was deleted in Phase 9
  (Z1) and replaced by the server-side `migrate_artifacts` tool, which inherits section-level
  and artifact-level concurrency automatically.

> **Revised (2026-07-05).** Every reference above to a server-wide
> `ARTIFACT_CONCURRENCY` environment variable, and the statement that it "is validated at
> startup" with values below 1 causing "a hard startup failure," is superseded. Artifact-level
> concurrency for `write_artifacts` and `migrate_artifacts` is now a **per-call caller
> parameter** — `artifact_concurrency` on the `write_artifacts` MCP tool signature (exposed
> as a caller-supplied argument), default `3` — not a server-wide env var. The inner function
> **clamps** the supplied value to `[1, 15]` rather than rejecting it: values above 15 are
> capped to 15, values below 1 are substituted with the default 3, and an out-of-range value
> produces a `"warning"` field in the response instead of a startup failure. There is no
> startup-time validation or rejection path for this parameter at all — the old
> `ARTIFACT_CONCURRENCY=0` startup-rejection scenario described above no longer exists because
> the setting is no longer server-wide configuration. `SECTION_CONCURRENCY` is unaffected by
> this change: it remains a server-wide env var, still validated at startup exactly as
> described above. The `artifact_concurrency × SECTION_CONCURRENCY ≤ ~15` quota guideline still
> applies conceptually, but the first factor is now chosen per call rather than fixed for the
> whole server. See `src/cairn_mcp/tools/write_artifacts.py` and `SERVER-REFERENCE.md`
> ("Per-call tool parameters") for the current behaviour.

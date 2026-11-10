---
type: Spec
id: p2-t7-write-artifact
title: T7 — Write Artifact Tool
description: Feature spec for the write_artifact MCP tool that stores artifact content in S3, generates per-section Bedrock embeddings, and writes vectors to S3 Vectors with idempotent upsert semantics.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T11:30:23Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T7 — Write Artifact Tool

## TL;DR

`write_artifact` is the MCP tool that stores an artifact's content in S3, generates one Bedrock
embedding per `##` section, and writes the section vectors to S3 Vectors with idempotent upsert
semantics. It is the entry point for all value in Arkeology: without it an agent cannot persist an
artifact mid-session, and the write → search → read loop cannot exist.

## 1. Problem Statement

Writing is the entry point for all value in Arkeology. An agent that cannot persistently
store an artifact mid-session — immediately and idempotently — gets nothing from the server.
This tool stores the artifact content in S3, generates one embedding per `##` section via
Bedrock, and writes the corresponding section vectors to S3 Vectors. The write → search →
read loop cannot exist without this tool. Its four user stories — writing a new artifact and
getting back an identifier, same-day tier 2 idempotency, tier 3 re-write with orphan cleanup, and
structured credential errors — are all priority P1.

## 2. Rules — Input validation

### R1 — Invalid input is rejected before any AWS call

`write_artifact` rejects these inputs before making any AWS call (no S3 put, no Bedrock call):

| Input | Outcome |
|-------|---------|
| Description exceeding 280 characters | Validation error |
| Unknown type | Validation error listing the valid types |
| Invalid tier | Error returned |
| Invalid visibility | Error returned |
| `file_extension` not starting with `"."` | Rejected — `file_extension` must start with `"."` (validated before any AWS calls) |

## 3. Rules — Keys and identifier

### R2 — Tier 2 key includes the current date, so same-day rewrites are idempotent

When `write_artifact` is called with tier=2, the artifact key is derived from type, the current
calendar date (server-local UTC), and title — making same-day rewrites idempotent. An agent that
accidentally calls `write_artifact` twice with identical inputs on the same day ends with exactly
one artifact in S3 and one set of vectors in the index — no duplicates.

**Example**

- Given the same type, date, title, and content written twice, when both calls succeed, then S3
  contains exactly one object and the index contains exactly one vector per section.
- Given a tier 2 artifact written today and again tomorrow with identical inputs, when both calls
  succeed, then S3 contains two objects (different keys) and the index contains two independent
  sets of vectors.

### R3 — Tier 3 key ignores the date

When `write_artifact` is called with tier=3, the artifact key is derived from type and title only —
date is not a factor. The tier 3 key is identical across two writes on different dates.

### R4 — S3 content key

The S3 key for the artifact content is `{write_prefix}/{artifact_id}{file_extension}` (default
`file_extension=".md"`). `WRITE_PREFIX` is guaranteed non-empty (validated at startup), so the key
always has the form `prefix/artifact-id.ext` — no conditional branch, no risk of a leading `/`.

### R5 — Success returns the full S3 key as `artifact_id`, plus `sections_indexed`

When `write_artifact` succeeds, it returns `artifact_id` and `sections_indexed` (integer count of
vectors written). The returned `artifact_id` is the full S3 key (including prefix), not just the
hash portion: it is the globally unique identifier used for retrieval and cross-scope
deduplication, which the agent can share with teammates or pass to `read_artifact` later.

**Example**

- Given valid inputs with three `##` sections, when `write_artifact` is called, then S3 contains
  the content under the correct key, three vectors are in the index each carrying `artifact_id` in
  metadata, `sections_indexed == 3`, and the returned `artifact_id` matches the S3 key.
- Given valid inputs with no `##` sections, when `write_artifact` is called, then exactly one
  vector is in the index (document-level fallback), `sections_indexed == 1`, and the returned
  `artifact_id` is correct.

## 4. Rules — Embedding

### R6 — One labelled embedding per `##` section

When the artifact content contains one or more `##` headings, one Bedrock embedding is generated
per section. Each embedding input is `title + type + tags + section content` concatenated, as a
**labelled, structured string** so the embedding model understands the role of each field:

```
Title: {title}
Type: {type}
Tags: {tag1}, {tag2}, ...

{section_heading}
{section_body}
```

- The section heading line is included as part of the embedding (it is the strongest semantic
  signal for that section).
- If `tags` is empty, omit the `Tags:` line entirely — do not embed `"Tags: "`.
- A blank line separates the metadata block from the section content.

**Why:** labelled inputs consistently outperform plain concatenation in retrieval benchmarks,
because the label anchors the semantic meaning of each field to the query.

### R7 — Content with no `##` headings gets one document-level embedding

When the artifact content contains no `##` headings, exactly one Bedrock embedding is generated,
whose input is `title + description + type + tags` concatenated, as a labelled, structured string:

```
Title: {title}
Type: {type}
Tags: {tag1}, {tag2}, ...
Description: {description}
```

### R8 — `reconcile_index` re-embeds through the same section pipeline as `write_artifact`

The embedding-text building, together with the min-length filter / `EMBED_MAX_SECTIONS` cap /
per-section truncation steps that sit around it, is one shared section pipeline:
`reconcile_index` re-embeds artifacts using the same section pipeline as `write_artifact`.

**Why:** a reconcile that bypasses the filter/cap/truncation steps re-submits a section truncated
at write time full-length on every reconcile replay, failing Titan's input limit forever.

## 5. Rules — Vectors

### R9 — Vector keys

When embedding succeeds, one vector per section is written to S3 Vectors with key
`{artifact_id}#{section_slug}` — also stated as `{s3_key}#{section_slug}`. The `#` character is
confirmed valid in S3 Vectors keys (verified in Phase 1 integration tests). When the single
document-level fallback is used, one vector is written with key equal to `artifact_id` — the same as
the S3 key (no `#` suffix).

### R10 — Vector metadata

Vector metadata must include every filterable field from FR-09 as string-valued entries, plus `scope`
(set to `settings.write_prefix`) for cross-scope filtering, plus `artifact_id` (the full S3 key)
for the re-fetch loop `$nin` filter. Non-filterable metadata declared at index creation
(`description`, `source_artifacts`) must also be written into vector metadata on every write.

Source: FR-09

### R11 — List-valued S3 object metadata survives a round-trip

`tags` is stored in S3 object metadata as a comma-separated string; `source_artifacts` is
similarly encoded — the developer must choose and document the encoding. All list-valued metadata
fields must survive a round-trip (write then read back from S3 object metadata returns the
original list).

## 6. Rules — Write order and failures

### R12 — S3 is written before any Bedrock or S3 Vectors call

The write to S3 happens before any Bedrock or S3 Vectors calls. If embedding or indexing fails,
the S3 object is already written (partial write scenario; failure log is Phase 3).

### R13 — Vector write failure returns a structured error with the `artifact_id`

When S3 PutObject succeeds but all S3 Vectors PutVector calls fail, `write_artifact` returns a
structured error response containing the `artifact_id`. Partial vector failures (some sections
fail) are treated as total failure for Phase 2 (Phase 3 adds the failure log).

### R14 — Credential errors return a structured response

A mid-session credential expiry during the Bedrock embed call must not surface as a raw
exception: when a `CredentialError` is raised at any point, `write_artifact` returns a structured
MCP error response with a human-readable message — never a raw exception.

**Example**

- Given a Bedrock credential failure during `write_artifact`, when the tool returns, then the
  response contains a human-readable error message and no raw exception traceback (S3 already
  written).
- Given an S3 credential failure during the PutObject call, when the tool returns, then the
  response contains a structured error — not a Python exception — and no Bedrock call was made.

## 7. Rules — Tier 3 re-write

### R15 — Tier 3 re-write writes new vectors first, then deletes orphans

When an ADR or other tier 3 artifact is re-written, the index must not retain vectors for sections
that no longer exist. After writing the new vectors, `write_artifact` queries the index for all
existing vector keys whose `artifact_id` matches the artifact key and deletes any key not present
in the newly written set. Sequence for a tier 3 re-write:

1. S3 PutObject (content).
2. Embed all new sections.
3. PutVector for all new section keys (upsert — existing keys are overwritten in place).
4. `list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})` → get all current keys.
5. Delete any key in the returned set that is not in the newly written key set.

**Example**

- Given a tier 3 artifact first written with sections A, B, C, when re-written with sections A, B
  only, then the index contains vectors for A and B only — the vector for C is deleted.
- Given a tier 3 artifact first written with one section, when re-written with three sections,
  then the index contains exactly three vectors after the re-write.
- Given a tier 3 artifact re-written with identical sections, when the re-write completes, then
  the index contains the same number of vectors as before (upsert, no orphans).

**Why write first:** deleting first creates a window where the artifact has zero vectors — a
concurrent search during that window returns nothing and the artifact disappears briefly; worse,
if the new vector writes fail, the old index entries are already deleted and cannot be recovered
without re-embedding. Writing first means new vectors are live before stale ones are removed: a
concurrent search during the delete phase may briefly see both old and new section vectors for the
same artifact, but the artifact still surfaces in results with a correct score — far less harmful
than invisibility.

**Forward pointer (2026-07-06, shipped in `7a697dd`).** The sequence above has since been extended
in two ways it does not reflect — this spec predates both the `commit_refs`/`references` link fields
and this concurrency hardening:

1. **Optimistic-concurrency writes.** Step 1's `PutObject` is a conditional write guarded by an
   ETag compare-and-swap (`IfMatch`); on a detected concurrent change it performs a bounded retry
   (~3 attempts: re-read, re-merge, re-write) before returning a structured `conflict` error.
   Vector writes (steps 2–3) stay unconditional — they are the recoverable, derived copy healed by
   `reconcile_index` if needed. Rationale: ADR-011 decision 6.
2. **Reference-field value semantics.** On this same overwriting write, `commit_refs` is read
   forward and merged (accretive — union with the value supplied to the call), while `references`
   is replaced outright with exactly the value supplied to the call (a call supplying no
   `references` clears it). Rationale: ADR-011 decision 4.

## 8. Boundaries

**Always:**
- The tool function signature receives `settings`, `s3`, `vectors`, and `bedrock` as injected
  dependencies — it must not import or instantiate clients directly.

**Ask First:**
- Whether to truncate long titles/content before embedding, or pass them as-is and let Bedrock
  return a token-count error. (Default: pass as-is; Bedrock errors surface as tool errors.)

**Never:**
- Do not store artifact content inside S3 Vectors metadata — content belongs in S3 only.
- Do not call Bedrock before S3 PutObject succeeds.
- Do not allow tier 2 artifacts to be re-written with different content on the same day without
  logging it (silently overwriting is correct; it is a defined idempotency contract, not an error).
- Do not generate a UUID or random suffix for artifact keys — keys are fully deterministic.

## 9. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write.py` | Create | Written first (Red) |
| `src/arkeology/tools/__init__.py` | Create | Empty package marker |
| `src/arkeology/tools/write.py` | Create | Written after unit tests (Green). Calls `prepare_sections_for_embedding` at Step 5 instead of parsing sections and building embedding text inline |
| `tests/integration/test_tools_write.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `write_artifact` tool on `_app` |
| `src/arkeology/__main__.py` | Modify | Pass `settings`, `s3`, `vectors`, `bedrock` to tool registration |

The section pipeline of R8 lives in the shared module `tools/_section_pipeline.py`, not in
`tools/write.py`: the two embedding-text helpers `build_section_embedding_text` and
`build_document_embedding_text` (R6, R7) — first specified as the private helpers
`_build_section_embedding_text` and `_build_document_embedding_text` in `tools/write.py` — plus
`prepare_sections_for_embedding`, with the min-length filter / `EMBED_MAX_SECTIONS` cap /
per-section truncation steps that sit around them.

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_write.py` first → all tests fail → implement
`tools/write.py` → all unit tests pass.

**TDD cycle B (integration):** write `test_tools_write.py` integration tests first → fail
(ImportError) → wire the tool → integration tests pass against real AWS.

**Embedding-text helpers (R6, R7):** `build_section_embedding_text` and
`build_document_embedding_text` must both be unit-tested directly (pass strings in, assert the
formatted output) — these helpers are the most fragile part of the write pipeline. Their unit tests
live in `tests/unit/test_tools_section_pipeline.py`.

**`test_tools_write.py` — unit tests (fakes only, no AWS):**

Happy path (R5, R9):
- Three-section content → three vectors written; S3 contains the content; returned
  `sections_indexed == 3`.
- No-section content → one vector written (document fallback); `sections_indexed == 1`.
- Returned `artifact_id` is the full S3 key (prefix + hash).

Tier 2 idempotency (R2):
- Write same artifact twice on same date → S3 still has exactly one object; index has the same
  number of vectors (no duplicates). Use `FakeVectorsClient` to count stored keys.
- Write same artifact on two different dates → two distinct S3 keys, two independent vector sets.

Tier 3 re-write (R3, R15):
- First write: sections [A, B, C]. Second write: sections [A, B]. After second write, the fake
  index must contain keys for A and B only — C's key must be absent.
- First write: one section. Second write: three sections. Fake index contains three keys.
- Re-write with identical sections: vector count unchanged.
- Tier 3 key is identical across two writes with different dates.

Input validation (R1) — all must fail before any AWS call; assert no S3/Bedrock calls on fake:
- Description >280 chars → error returned, zero S3 puts.
- Invalid type → error returned, zero S3 puts.
- Invalid tier → error returned.
- Invalid visibility → error returned.

Credential failure (R14):
- S3 credential failure → structured error in response; no Bedrock call made.
- Bedrock credential failure → structured error in response (S3 already written).

**`test_tools_write.py` — integration tests (`@pytest.mark.integration`):**

- Full round-trip: write → S3 GetObject returns content; S3 Vectors GetVectors returns vectors with
  correct `artifact_id` in metadata.
- Tier 3 re-write: write with sections [A, B, C] then re-write with [A, B] → verify via
  `list_vectors_by_metadata({"artifact_id": key})` that exactly two vector keys exist.
- **Integration checkpoint:** Confirm `PutVector` on an existing key is a true upsert (no
  duplicate, no error). Record finding in `plan.md` under Learnings if not already done.
- **Integration checkpoint:** Confirm `#` separator in vector keys is valid (expected: already
  confirmed in Phase 1 — verify no regression).

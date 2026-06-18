---
type: spec
title: T7 — Write Artifact Tool
description: Feature spec for the write_artifact MCP tool that stores artifact content in S3, generates per-section Bedrock embeddings, and writes vectors to S3 Vectors with idempotent upsert semantics.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p2-t7-write-artifact
status: ready
phase: 2
task: 7
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T7 — Write Artifact Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Writing is the entry point for all value in cairn-mcp. An agent that cannot persistently
store an artifact mid-session — immediately and idempotently — gets nothing from the server.
This tool stores the artifact content in S3, generates one embedding per `##` section via
Bedrock, and writes the corresponding section vectors to S3 Vectors. The write → search →
read loop cannot exist without this tool.

## User Stories

### Story 1 — Agent writes a new artifact and gets back an identifier (P1)

A developer agent finishes a code review and calls `write_artifact`. The artifact is stored
and indexed; the agent receives an identifier it can share with teammates or pass to
`read_artifact` later.

**Acceptance criteria:**
- Given valid inputs with three `##` sections, when `write_artifact` is called, then S3
  contains the content under the correct key, three vectors are in the index each carrying
  `artifact_id` in metadata, and the returned `artifact_id` matches the S3 key.
- Given valid inputs with no `##` sections, when `write_artifact` is called, then exactly
  one vector is in the index (document-level fallback) and the returned `artifact_id` is
  correct.

### Story 2 — Same-day tier 2 write is idempotent (P1)

An agent accidentally calls `write_artifact` twice with identical inputs on the same day.
The result is exactly one artifact in S3 and one set of vectors in the index — no duplicates.

**Acceptance criteria:**
- Given the same type, date, title, and content written twice, when both calls succeed, then
  S3 contains exactly one object and the index contains exactly one vector per section.
- Given a tier 2 artifact written today and again tomorrow with identical inputs, when both
  calls succeed, then S3 contains two objects (different keys) and the index contains two
  independent sets of vectors.

### Story 3 — Tier 3 re-write updates content and cleans orphaned vectors (P1)

An ADR is updated: the new version has fewer sections than the old. The index must not
retain vectors for sections that no longer exist.

**Acceptance criteria:**
- Given a tier 3 artifact first written with sections A, B, C, when re-written with sections
  A, B only, then the index contains vectors for A and B only — the vector for C is deleted.
- Given a tier 3 artifact first written with one section, when re-written with three sections,
  then the index contains exactly three vectors after the re-write.
- Given a tier 3 artifact re-written with identical sections, when the re-write completes,
  then the index contains the same number of vectors as before (upsert, no orphans).

### Story 4 — Credential errors return structured responses (P1)

A mid-session credential expiry during the Bedrock embed call must not surface as a raw
exception.

**Acceptance criteria:**
- Given a Bedrock credential failure during `write_artifact`, when the tool returns, then
  the response contains a human-readable error message and no raw exception traceback.
- Given an S3 credential failure during the PutObject call, when the tool returns, then the
  response contains a structured error — not a Python exception.

## Requirements

- WHEN `write_artifact` is called with a description exceeding 280 characters THE SYSTEM
  SHALL reject the call with a validation error before making any AWS call.
- WHEN `write_artifact` is called with an unknown type THE SYSTEM SHALL reject the call with
  a validation error listing the valid types.
- WHEN `write_artifact` is called with tier=2 THE SYSTEM SHALL derive the artifact key from
  type, the current calendar date (server-local UTC), and title — making same-day rewrites
  idempotent.
- WHEN `write_artifact` is called with tier=3 THE SYSTEM SHALL derive the artifact key from
  type and title only — date is not a factor.
- WHEN the artifact content contains one or more `##` headings THE SYSTEM SHALL generate one
  Bedrock embedding per section; each embedding input is `title + type + tags +
  section content` concatenated.
- WHEN the artifact content contains no `##` headings THE SYSTEM SHALL generate exactly one
  Bedrock embedding whose input is `title + description + type + tags` concatenated.
- WHEN embedding succeeds THE SYSTEM SHALL write one vector per section to S3 Vectors with
  key `{artifact_id}#{section_slug}` and metadata carrying all filterable fields.
- WHEN the single document-level fallback is used THE SYSTEM SHALL write one vector with key
  equal to `artifact_id` (no `#` suffix).
- WHEN writing a tier 3 artifact THE SYSTEM SHALL after writing new vectors query the index
  for all existing vector keys with `artifact_id` matching the artifact key and delete any
  key not present in the newly written set.
- WHEN S3 PutObject succeeds but all S3 Vectors PutVector calls fail THE SYSTEM SHALL return
  a structured error response containing the `artifact_id`; partial vector failures (some
  sections fail) are treated as total failure for Phase 2 (Phase 3 adds the failure log).
- WHEN a CredentialError is raised at any point THE SYSTEM SHALL return a structured MCP
  error response with a human-readable message — never a raw exception.
- WHEN `write_artifact` succeeds THE SYSTEM SHALL return `artifact_id` and `sections_indexed`
  (integer count of vectors written).

## Boundaries

**Always:**
- S3 key for the artifact content: `{write_prefix}/{artifact_id}{file_extension}` (default `file_extension=".md"`). `WRITE_PREFIX` is
  guaranteed non-empty (validated at startup), so the key always has the form
  `prefix/artifact-id.ext` — no conditional branch, no risk of a leading `/`.
  `file_extension` must start with `"."` (validated before any AWS calls).
- Vector key for a section: `{s3_key}#{section_slug}`. The `#` character is confirmed valid
  in S3 Vectors keys (verified in Phase 1 integration tests).
- Vector key for the document-level fallback: same as the S3 key (no `#` suffix).
- The `artifact_id` returned to the caller is the full S3 key (including prefix), not just
  the hash portion. This is the globally unique identifier used for retrieval and cross-scope
  deduplication.
- Vector metadata must include every filterable field from FR-09 as string-valued entries,
  plus `scope` (set to `settings.write_prefix`) for cross-scope filtering, plus `artifact_id`
  (the full S3 key) for the re-fetch loop `$nin` filter.
- Non-filterable metadata declared at index creation (`description`, `source_artifacts`) must
  also be written into vector metadata on every write.
- The write to S3 happens before any Bedrock or S3 Vectors calls. If embedding or indexing
  fails, the S3 object is already written (partial write scenario; failure log is Phase 3).
- `tags` stored in S3 object metadata as a comma-separated string;
  `source_artifacts` similarly encoded — the developer must choose and document the encoding.
- All list-valued metadata fields must survive a round-trip (write then read back from S3
  object metadata returns the original list).
- The tool function signature receives `settings`, `s3`, `vectors`, and `bedrock` as
  injected dependencies — it must not import or instantiate clients directly.

**Ask First:**
- Whether to truncate long titles/content before embedding, or pass them as-is and let
  Bedrock return a token-count error. (Default: pass as-is; Bedrock errors surface as tool
  errors.)

**Never:**
- Do not store artifact content inside S3 Vectors metadata — content belongs in S3 only.
- Do not call Bedrock before S3 PutObject succeeds.
- Do not allow tier 2 artifacts to be re-written with different content on the same day
  without logging it (silently overwriting is correct; it is a defined idempotency contract,
  not an error).
- Do not generate a UUID or random suffix for artifact keys — keys are fully deterministic.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/__init__.py` | Create | Empty package marker |
| `src/cairn_mcp/tools/write.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_write.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `write_artifact` tool on `_app` |
| `src/cairn_mcp/__main__.py` | Modify | Pass `settings`, `s3`, `vectors`, `bedrock` to tool registration |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_write.py` first → all tests fail → implement
`tools/write.py` → all unit tests pass.

**TDD cycle B (integration):** write `test_tools_write.py` integration tests first → fail
(ImportError) → wire the tool → integration tests pass against real AWS.

---

**`test_tools_write.py` — unit tests (fakes only, no AWS):**

Happy path:
- Three-section content → three vectors written; S3 contains the content; returned
  `sections_indexed == 3`.
- No-section content → one vector written (document fallback); `sections_indexed == 1`.
- Returned `artifact_id` is the full S3 key (prefix + hash).

Tier 2 idempotency:
- Write same artifact twice on same date → S3 still has exactly one object; index has the
  same number of vectors (no duplicates). Use `FakeVectorsClient` to count stored keys.
- Write same artifact on two different dates → two distinct S3 keys, two independent vector
  sets.

Tier 3 re-write:
- First write: sections [A, B, C]. Second write: sections [A, B]. After second write, the
  fake index must contain keys for A and B only — C's key must be absent.
- First write: one section. Second write: three sections. Fake index contains three keys.
- Re-write with identical sections: vector count unchanged.
- Tier 3 key is identical across two writes with different dates.

Input validation (all must fail before any AWS call — assert no S3/Bedrock calls on fake):
- Description >280 chars → error returned, zero S3 puts.
- Invalid type → error returned, zero S3 puts.
- Invalid tier → error returned.
- Invalid visibility → error returned.

Credential failure:
- S3 credential failure → structured error in response; no Bedrock call made.
- Bedrock credential failure → structured error in response (S3 already written).

**`test_tools_write.py` — integration tests (`@pytest.mark.integration`):**

- Full round-trip: write → S3 GetObject returns content; S3 Vectors GetVectors returns
  vectors with correct `artifact_id` in metadata.
- Tier 3 re-write: write with sections [A, B, C] then re-write with [A, B] → verify via
  `list_vectors_by_metadata({"artifact_id": key})` that exactly two vector keys exist.
- **Integration checkpoint:** Confirm `PutVector` on an existing key is a true upsert
  (no duplicate, no error). Record finding in `plan.md` under Learnings if not already done.
- **Integration checkpoint:** Confirm `#` separator in vector keys is valid (expected:
  already confirmed in Phase 1 — verify no regression).

## Embedding Input Format — Decision

Use a **labelled, structured string** so the embedding model understands the role of each
field. Labelled inputs consistently outperform plain concatenation in retrieval benchmarks
because the label anchors the semantic meaning of each field to the query.

**Section vector embedding input:**
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

**Document-level fallback embedding input (no `##` sections):**
```
Title: {title}
Type: {type}
Tags: {tag1}, {tag2}, ...
Description: {description}
```

Implement a private helper `_build_section_embedding_text` and
`_build_document_embedding_text` in `tools/write.py`. Both must be unit-tested directly
(pass strings in, assert the formatted output) — these helpers are the most fragile part of
the write pipeline.

## Tier 3 Orphan Cleanup Timing — Decision

**Write new vectors first, then delete orphans.**

Rationale:
- **Delete first** creates a window where the artifact has zero vectors. A concurrent search
  during that window returns nothing — the artifact disappears briefly. Worse, if the new
  vector writes fail, you have deleted the old index entries and cannot recover without
  re-embedding.
- **Write first** means new vectors are live before stale ones are removed. A concurrent
  search during the delete phase may briefly see both old and new section vectors for the
  same artifact, but the artifact still surfaces in results with a correct score. Far less
  harmful than invisibility.

Sequence for tier 3 re-write:
1. S3 PutObject (content).
2. Embed all new sections.
3. PutVector for all new section keys (upsert — existing keys are overwritten in place).
4. `list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})` → get all current keys.
5. Delete any key in the returned set that is not in the newly written key set.

## Open Questions

*(none — all decisions resolved)*

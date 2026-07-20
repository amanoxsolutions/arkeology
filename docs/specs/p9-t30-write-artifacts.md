---
type: spec
title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
description: Spec for concurrent bulk write and migration tools plus section truncation guard, resolving migration performance problems by moving all logic server-side.
tags: []
timestamp: 2026-06-03T00:00:00Z
okf_version: "0.1"
feature: p9-t30-write-artifacts
phase: 9
task: 30
status: complete
references: []
authored:
  by: "architect"
  date: "2026-06-03"
revised:
  by: "developer"
  date: "2026-07-05"
---

# Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Three tightly coupled capabilities that together resolve the migration performance problem and
eliminate `migrate.py`: `write_artifacts` (concurrent bulk write, FR-25), `migrate_artifacts`
(concurrent bulk migration with server-side Nova Lite description generation, FR-26), and
`EMBED_MAX_SECTION_LENGTH` (section body truncation guard before embedding, P4/FR-01). All
document-level and section-level parallelism moves inside a single MCP call, making it
transport-topology-agnostic and always in sync with server-side fixes.

## Problem Statement

After Phase 8 (P1–P3 + L1+L2), per-artifact write latency improved, but migration performance
remained dominated by two structural problems. (1) `migrate.py` contained a duplicated write path
that never received P1's concurrent embedding fix — the script's `write_artifact` calls still used
the old serial for-loop, making it 2× slower per artifact than the MCP server. (2) L1 assumed
sub-agents spawned via the `task` tool get independent MCP connections — empirical evidence shows
they share the parent's stdio pipe, serialising all `write_artifact` calls and collapsing write
parallelism to zero. Both problems trace to the same root cause: bypassing MCP requires duplicating
write logic, and duplicated code does not inherit server-side fixes. Additionally, the write path
has no upper-bound guard on section body length — a section exceeding Titan Text Embeddings v2's
8,192-token / 50,000-character limit causes a runtime embed failure. This spec resolves all three
problems simultaneously by moving all logic server-side.

## User Stories

### Story 1 — Bulk write 10 artifacts concurrently (FR-25)

An agent calls `write_artifacts` with 10 descriptors. The server processes all concurrently,
bounded by `ARTIFACT_CONCURRENCY`, applying P1 section-level concurrency within each artifact.
Any individual failure is reported per-artifact without aborting the batch.

**Acceptance criteria:**
- Given 10 descriptors and `ARTIFACT_CONCURRENCY=3`, when `write_artifacts` is called, then at
  most 3 artifacts are in-flight simultaneously (verifiable by log ordering or spy).
- Given a mixed list where entry 4 has a missing required field (e.g. `content`), when
  `write_artifacts` returns, then entries 1–3 and 5–10 are written and report `written=True`;
  entry 4 carries `error="validation_error"` and a `message` naming the missing field.
- Given `ARTIFACT_CONCURRENCY=0`, when the server starts, then it exits with a clear validation
  error before accepting any tool call.

### Story 2 — Preview migration before committing (FR-26, dry_run=True)

An agent calls `migrate_artifacts(descriptors, dry_run=True)` with some entries missing a
`description`. The server generates missing descriptions via Nova Lite, clips all to 280 chars,
and returns the enriched list — no writes to S3 or the vector index.

**Acceptance criteria:**
- Given 5 descriptors (3 with descriptions, 2 without), when `migrate_artifacts(dry_run=True)` is
  called, then exactly 2 Nova Lite calls are made and the response contains 5 enriched descriptors
  with descriptions ≤ 280 chars.
- Given `dry_run=True`, when the tool returns, then `s3.put_object` and `vectors.put_vectors_batch`
  are never called.
- Given a descriptor with an agent-provided description of 300 chars, when
  `migrate_artifacts(dry_run=True)` is called, then the returned description is clipped to 280
  chars.

### Story 3 — Execute migration in one server-side operation (FR-26, dry_run=False)

An agent calls `migrate_artifacts(descriptors, dry_run=False)`. The server generates missing
descriptions concurrently, then writes all artifacts by delegating to `write_artifacts`. The
response is a per-artifact result list identical in structure to `write_artifacts`.

**Acceptance criteria:**
- Given 10 descriptors (8 with descriptions, 2 without) and `dry_run=False`, when
  `migrate_artifacts` is called, then exactly 2 Nova Lite calls are made and all 10 artifacts
  are written to S3, indexed in S3 Vectors, and returned by `list_artifacts`.
- Given 10 descriptors all of which already have descriptions and `dry_run=False`, when
  `migrate_artifacts` is called, then zero Nova Lite calls are made and all 10 artifacts are
  written to S3, indexed in S3 Vectors, and returned by `list_artifacts`.
- Re-calling `migrate_artifacts` with the same 10 descriptors produces no duplicate artifacts
  and no errors.
- Given a `BEDROCK_TEXT_MODEL` that is unreachable, when the server starts, then it exits with
  a clear error identifying the text model startup check as the failure point.

### Story 4 — Section body truncated before embedding, not in S3 (FR-01, P4)

An artifact contains a `##` section whose body exceeds `EMBED_MAX_SECTION_LENGTH`. The server
truncates the body before calling Bedrock but stores the full body in S3 unchanged.

**Acceptance criteria:**
- Given `EMBED_MAX_SECTION_LENGTH=100` and a section with a 200-char body, when `write_artifact`
  is called, then `bedrock.embed` receives a body of at most 100 chars; `read_artifact` returns
  the full 200-char body.
- Given `EMBED_MAX_SECTION_LENGTH=0`, when `write_artifact` is called with any section body
  length, then the body is passed to `bedrock.embed` unmodified.
- Given `EMBED_MAX_SECTION_LENGTH` set to a negative integer, when the server starts, then it
  exits with a clear validation error.

### Story 5 — Partial-failure recovery via CAIRN_IMPORT.yaml status tracking (FR-27)

An operator runs a > 10 file migration. During the `migrate_artifacts(dry_run=False)` call, 2 of
10 artifacts fail due to a transient Bedrock throttle. The per-artifact response identifies the
2 failures. The agent updates the CAIRN_IMPORT.yaml manifest: 8 entries become `written`, 2
become `failed` with the error detail. On re-run, the agent reads the manifest, filters to only
`pending` and `failed` entries, and calls `migrate_artifacts` again with only those 2. Both are
written successfully. The agent updates the manifest to mark all entries `written` and reports
migration complete.

**Acceptance criteria:**
- Given 10 manifest entries with `status: pending` and a fully successful
  `migrate_artifacts(dry_run=False)` response, when the agent processes the response, then all
  10 entries in CAIRN_IMPORT.yaml are updated to `status: written`.
- Given a partial failure where 2 of 10 entries fail, when the agent processes the response,
  then the 8 successful entries have `status: written` and the 2 failed entries have
  `status: failed` with the error message populated in the manifest.
- Given a manifest where 8 entries are `written` and 2 are `failed`, when the agent prepares
  the next migration call, then only the 2 `failed` entries are included in the
  `migrate_artifacts` input; the 8 `written` entries are skipped entirely.
- Given a manifest where all entries are `written`, when the migration workflow is initiated,
  then no `migrate_artifacts` call is made and the agent reports migration complete.
- Given any manifest entries with `status: failed` after a run, when the agent concludes
  the session, then it lists every failed entry by path and error message before stopping.

## Requirements

- WHEN `write_artifacts` receives a descriptor missing a required field THE SYSTEM SHALL return
  `error="validation_error"` with a message naming the missing field for that entry, without
  aborting the batch.
- WHEN `write_artifacts` is called with a list of descriptors THE SYSTEM SHALL process all
  concurrently using `asyncio.gather` bounded by `asyncio.Semaphore(settings.artifact_concurrency)`.
- WHEN any individual artifact in `write_artifacts` fails THE SYSTEM SHALL record the error in
  that artifact's response entry and continue processing all remaining entries without aborting.
- WHEN `write_artifacts` returns THE SYSTEM SHALL include one entry per input descriptor:
  successful entries carry `written=True` and `sections_indexed`; failed entries carry `error`
  and `message`.
- WHEN `migrate_artifacts` is called with `dry_run=True` THE SYSTEM SHALL generate missing
  descriptions concurrently, clip all descriptions to 280 chars, and return the enriched list
  without calling `s3.put_object` or `vectors.put_vectors_batch`.
- WHEN `migrate_artifacts` is called with `dry_run=False` THE SYSTEM SHALL generate missing
  descriptions concurrently (bounded by `asyncio.Semaphore(settings.artifact_concurrency)`) then
  delegate to `write_artifacts` for the write phase.
- WHEN `migrate_artifacts` is called with `dry_run=False` and all descriptors already carry a
  description THE SYSTEM SHALL delegate directly to `write_artifacts` without making any Nova
  Lite calls.
- WHEN Nova Lite generates a description exceeding 280 chars THE SYSTEM SHALL clip it to 280 chars
  and log the clip at DEBUG.
- WHEN an agent-provided description exceeds 280 chars THE SYSTEM SHALL clip it to 280 chars and
  log at DEBUG (applies in both `dry_run` modes).
- WHEN a section body exceeds `settings.embed_max_section_length` (and the setting is not 0) THE
  SYSTEM SHALL truncate the body to that length before calling `bedrock.embed`.
- WHEN `EMBED_MAX_SECTION_LENGTH=0` THE SYSTEM SHALL pass section bodies to `bedrock.embed`
  unmodified.
- WHEN `embed_max_section_length` is a negative integer THE SYSTEM SHALL reject it at startup with
  a clear validation error.
- WHEN `ARTIFACT_CONCURRENCY` is absent from the environment THE SYSTEM SHALL default to 3.
- WHEN `ARTIFACT_CONCURRENCY` is less than 1 THE SYSTEM SHALL reject it at startup with a clear
  validation error.
- WHEN `BEDROCK_TEXT_MODEL` is configured THE SYSTEM SHALL validate accessibility at startup via a
  live `bedrock:InvokeModel` call and fail hard if the model is unreachable.
- WHEN `BEDROCK_TEXT_MODEL` is absent from the environment THE SYSTEM SHALL skip the text model
  startup check entirely.
- WHEN `migrate_artifacts` returns a per-artifact result list THE AGENT SHALL update each
  corresponding entry in CAIRN_IMPORT.yaml: `status: written` for successful entries;
  `status: failed` with the error message populated for failed entries.
- WHEN the agent prepares a `migrate_artifacts` call THE AGENT SHALL include only entries with
  `status: pending` or `status: failed`; entries with `status: written` SHALL be skipped.
- WHEN all entries in CAIRN_IMPORT.yaml carry `status: written` THE AGENT SHALL report
  migration complete without calling `migrate_artifacts`.
- IF any entries carry `status: failed` after a run THE AGENT SHALL list every failed entry by
  path and error message before concluding the session.

## Boundaries

**Always:**
- `write_artifacts` is a bulk-write primitive for contexts where all descriptor
  fields — including `description` and `content` — are already known by the caller.
  It is appropriate for non-migration bulk writes (e.g. writing multiple code reviews
  or session summaries in a single call). It never generates missing fields.
  **Agents performing migration must always call `migrate_artifacts`**, which handles
  description generation and delegates to `write_artifacts` internally.
- `write_artifacts` requires `description` on every descriptor — it delegates to the existing
  `_write_artifact_inner` shared logic; it never generates descriptions.
- `migrate_artifacts` delegates to `write_artifacts` internally for the write phase — it never
  calls `_write_artifact_inner` directly.

> **Forward-pointer note (2026-07-06, not yet shipped).** Because every entry ultimately delegates
> to `_write_artifact_inner`, both `write_artifacts` and `migrate_artifacts` inherit, without any
> change of their own: (a) the optimistic-concurrency compare-and-swap guard on an overwriting
> write (ETag `IfMatch`, bounded retry, structured `conflict` error on exhaustion — vector writes
> stay unconditional/recoverable), and (b) the `references`-replace / `commit_refs`-accrete
> asymmetry on that same overwriting write. Neither tool needs its own logic for either — both are
> properties of the shared inner write path. Full requirements:
> `docs/specs/review-followup-2026-07-06-design-fixes.md` ("Optimistic-Concurrency Writes" and
> "Reference-Field Value Semantics" sections) and ADR-011 decisions 4 and 6.
- Section body truncation (`EMBED_MAX_SECTION_LENGTH`) applies to the embedding input only.
  Content stored in S3 is always the original, untruncated body.
- The `ARTIFACT_CONCURRENCY` semaphore governs both `write_artifacts` (document-level parallelism)
  and `migrate_artifacts` description generation — one semaphore, two uses; no separate
  `DESCRIPTION_CONCURRENCY`.
- All tools follow the existing `_<name>_inner` + top-level `try/except Exception` pattern.
- TDD: every test file must be written (Red — failing) before the implementation file it gates.
- `BEDROCK_TEXT_MODEL` defaults to `None` — operators must explicitly configure it to use
  `migrate_artifacts`. Operators in eu-central-1 must use a cross-region inference profile;
  this is documented in the configuration reference, not enforced by the server.

**Ask First:**
- Should each failed artifact in `write_artifacts` also produce a failure log entry (consistent
  with `write_artifact` behaviour), or only surface errors in the response list?
- What is the Nova Lite prompt template for description generation? Fixed constant in code, or
  read from a configuration variable?

**Never:**
- Do not call the `write_artifact` MCP tool wrapper from within `write_artifacts` — call
  `_write_artifact_inner` directly to avoid double exception wrapping.
- Do not store truncated content in S3 — full body always; truncation is embedding-input-only.
- Do not add a `DESCRIPTION_CONCURRENCY` config var — reuse `ARTIFACT_CONCURRENCY`.
- Do not call `migrate.py` or any external script — the script is deleted as part of this task;
  all logic is server-side.
- Do not change `BedrockClientInterface.embed` to async — section truncation happens at the call
  site in `write.py`; the client signature is unchanged.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_config.py` | Modify | Tests for `ARTIFACT_CONCURRENCY` (default 3, ≥ 1), `BEDROCK_TEXT_MODEL` (optional string), `EMBED_MAX_SECTION_LENGTH` (default 24000, ≥ 0) — written first (Red) |
| `tests/unit/test_tools_write.py` | Modify | Add P4 truncation tests (body clipped before embed, full body in S3); update existing embed-input assertions — written first (Red) |
| `tests/unit/test_tools_write_artifacts.py` | Create | Tests for `write_artifacts`: concurrent processing, partial failure, semaphore bound, response structure — written first (Red) |
| `tests/unit/test_tools_migrate_artifacts.py` | Create | Tests for `migrate_artifacts`: Nova Lite calls for missing descriptions, description clipping (both dry_run modes), dry_run=True writes nothing, dry_run=False delegates to write_artifacts, concurrency bound — written first (Red) |
| `tests/unit/clients/test_bedrock.py` | Modify | Add `invoke_text_model` tests: returns string, credential error → CredentialError — written first (Red) |
| `tests/unit/test_startup.py` | Modify | Tests for 6th startup check: BEDROCK_TEXT_MODEL configured + reachable → passes; unreachable → hard fail; absent → check skipped — written first (Red) |
| `src/cairn_mcp/config.py` | Modify | Add `ARTIFACT_CONCURRENCY` (int, default 3, validator ≥ 1), `BEDROCK_TEXT_MODEL` (str \| None, default `amazon.nova-lite-v1:0`), `EMBED_MAX_SECTION_LENGTH` (int, default 24000, validator ≥ 0) |
| `src/cairn_mcp/clients/interfaces.py` | Modify | Add `invoke_text_model(model_id: str, prompt: str) -> str` to `BedrockClientInterface` Protocol |
| `src/cairn_mcp/clients/bedrock.py` | Modify | Implement `invoke_text_model` using `bedrock:InvokeModel` with Nova Lite request/response shape |
| `src/cairn_mcp/clients/fakes/fake_bedrock.py` | Modify | Add `invoke_text_model` stub returning a deterministic short string (e.g. `"Fake description."`) |
| `src/cairn_mcp/startup.py` | Modify | Add 6th check: when `settings.bedrock_text_model` is set, call `bedrock.invoke_text_model` with a minimal probe prompt; fail hard on any error |
| `src/cairn_mcp/tools/write.py` | Modify | Apply P4: before calling `bedrock.embed`, truncate section body to `settings.embed_max_section_length` when non-zero; log truncation at DEBUG |
| `src/cairn_mcp/tools/write_artifacts.py` | Create | `write_artifacts` MCP tool: accept list of descriptors; `asyncio.gather` + `asyncio.Semaphore(ARTIFACT_CONCURRENCY)`; delegate to `_write_artifact_inner` per entry; return per-artifact result list |
| `src/cairn_mcp/tools/migrate_artifacts.py` | Create | `migrate_artifacts` MCP tool: generate missing descriptions via Nova Lite (bounded by `ARTIFACT_CONCURRENCY` semaphore); clip all descriptions to 280 chars; `dry_run=True` returns enriched list; `dry_run=False` delegates to `write_artifacts` |
| `src/cairn_mcp/server.py` | Modify | Register `write_artifacts` and `migrate_artifacts` tools via `register_tools()` |
| `skills/migrating-to-cairn/scripts/migrate.py` | Delete | Script eliminated — all logic now server-side |
| `skills/migrating-to-cairn/scripts/validate_manifest.py` | Create | PEP 723 standalone script; validates all required fields in `CAIRN_IMPORT.yaml` before step 3.B5; exits non-zero if any `status: pending` entry is missing a required field |
| `skills/migrating-to-cairn/schema.yaml` | Modify | Add `status` field (`pending` \| `written` \| `failed`) with optional `error` string per artifact entry; update header comment to remove `migrate.py` script reference |

## Testing Approach

**TDD cycle A — config layer:**
- `tests/unit/test_config.py` (Red) → `src/cairn_mcp/config.py` (Green)
- `ARTIFACT_CONCURRENCY` default=3, zero → ValidationError; `EMBED_MAX_SECTION_LENGTH` default=24000,
  negative → ValidationError, zero accepted; `BEDROCK_TEXT_MODEL` absent → None, set → string.

**TDD cycle B — P4 section truncation:**
- `tests/unit/test_tools_write.py` (Red) → `src/cairn_mcp/tools/write.py` (Green)
- Section body > limit → `bedrock.embed` spy receives truncated body; `read_artifact` returns full
  body; limit=0 → body unchanged; truncation logged at DEBUG.

**TDD cycle C — `write_artifacts` tool:**
- `tests/unit/test_tools_write_artifacts.py` (Red) → `src/cairn_mcp/tools/write_artifacts.py` (Green)
- 10-entry list → all written; entry with invalid field → error entry in response, others succeed;
  `ARTIFACT_CONCURRENCY=1` → sequential (spy call order); response fields (`written`, `sections_indexed`,
  `error`).

**TDD cycle D — Bedrock text model client:**
- `tests/unit/clients/test_bedrock.py` (Red) → `src/cairn_mcp/clients/bedrock.py` + `fake_bedrock.py` (Green)
- `invoke_text_model` returns a string; credential error → `CredentialError`; fake returns
  deterministic string.

**TDD cycle E — `migrate_artifacts` tool:**
- `tests/unit/test_tools_migrate_artifacts.py` (Red) → `src/cairn_mcp/tools/migrate_artifacts.py` (Green)
- `dry_run=True` → Nova Lite called for missing descriptions only, no S3/vectors writes (spy);
  description > 280 chars → clipped to 280; `dry_run=False` → `write_artifacts` called with
  enriched descriptors; existing description ≤ 280 → unchanged; `ARTIFACT_CONCURRENCY=2` → at
  most 2 concurrent Nova Lite calls (spy + semaphore).

**TDD cycle F — startup check:**
- `tests/unit/test_startup.py` (Red) → `src/cairn_mcp/startup.py` (Green)
- `BEDROCK_TEXT_MODEL` configured + `invoke_text_model` succeeds → check passes; raises → startup
  fails with actionable error; `BEDROCK_TEXT_MODEL` absent → `invoke_text_model` never called.

**Integration tests** (add to `tests/integration/`, `@pytest.mark.integration`):
- `write_artifacts`: 10-artifact round-trip → `list_artifacts` confirms all present; re-run is
  idempotent (no duplicates).
- `migrate_artifacts`: `dry_run=True` returns enriched list with descriptions ≤ 280 chars, no
  artifacts written; `dry_run=False` writes all and makes them searchable; re-run is idempotent.

**Story 5 — skill-side, no server TDD cycle:**
Story 5 (manifest status tracking) is agent/skill behaviour exercised entirely within the SKILL.md
workflow. There are no new server code paths to test. Verification is done through the
`migrate_artifacts` integration test round-trip: the per-artifact result list it returns is the
input the agent uses to update the manifest. The SKILL.md rewrite (part of T30 SKILL.md
simplification) must describe the manifest update step explicitly.

## Open Questions

All open questions resolved during implementation:

- [x] Should each failed artifact in `write_artifacts` also produce a failure log entry? **Yes** —
  consistent with `write_artifact` behaviour.
- [x] Nova Lite prompt template — hardcoded constant in `migrate_artifacts.py`; visible and
  documented, not in config.

> **Revised (2026-07-05).** Two gaps closed in `migrate_artifacts`'s Nova
> Lite description generation:
>
> 1. A failed generation previously fell through Step 3's clip logic to
>    `description: ""`, which passed validation and wrote a degraded, near-unsearchable
>    artifact. A failed-generation descriptor is now **skipped, never written** — its result
>    entry is `{"written": False, "skipped": True, "reason": "description_generation_failed",
>    "message": ...}` (mirroring the A-1 `skipped_existing` shape), and a top-level
>    `"generation_failed"` list (`index`, `title`, `message`) is included in the response in
>    both `dry_run` modes.
> 2. The generation prompt interpolated the full, untruncated artifact content. It is now
>    bounded to `_PROMPT_CONTENT_MAX_CHARS` (8000 chars) via `_truncate_prompt_content` before
>    being sent to Nova Lite.
>
> See `tests/unit/test_tools_migrate_artifacts.py` (`test_m12_*`).

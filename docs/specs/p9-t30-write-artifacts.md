---
type: Spec
id: p9-t30-write-artifacts
title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
description: Spec for concurrent bulk write and migration tools plus section truncation guard, resolving migration performance problems by moving all logic server-side.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T16:41:18Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation

## TL;DR

Three tightly coupled capabilities that together resolve the migration performance problem and
eliminate `migrate.py`: `write_artifacts` (concurrent bulk write, FR-25), `migrate_artifacts`
(concurrent bulk migration with server-side Nova Lite description generation, FR-26), and
`EMBED_MAX_SECTION_LENGTH` (section body truncation guard before embedding, P4/FR-01). All
document-level and section-level parallelism moves inside a single MCP call, making it
transport-topology-agnostic and always in sync with server-side fixes.

## 1. Problem Statement

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
problems simultaneously by moving all logic server-side. The manifest status-tracking rules
(Migration manifest status tracking) are agent/skill behaviour in the migration skill's workflow,
not server code.

## 2. Rules — `write_artifacts` bulk write

### R1 — Descriptors are processed concurrently, bounded by `ARTIFACT_CONCURRENCY`

When an agent calls `write_artifacts` with a list of descriptors, the server processes all of them
concurrently using `asyncio.gather` bounded by `asyncio.Semaphore(settings.artifact_concurrency)`,
applying P1 section-level concurrency within each artifact.

**Example**

- Given 10 descriptors and `ARTIFACT_CONCURRENCY=3`, when `write_artifacts` is called, then at
  most 3 artifacts are in-flight simultaneously (verifiable by log ordering or spy).

Source: FR-25

### R2 — One artifact's failure never aborts the batch

When any individual artifact in `write_artifacts` fails, the server records the error in that
artifact's response entry and continues processing all remaining entries without aborting. When a
descriptor is missing a required field, that entry returns `error="validation_error"` with a
message naming the missing field, without aborting the batch.

**Example**

- Given a mixed list where entry 4 has a missing required field (e.g. `content`), when
  `write_artifacts` returns, then entries 1–3 and 5–10 are written and report `written=True`;
  entry 4 carries `error="validation_error"` and a `message` naming the missing field.

Source: FR-25

### R3 — Each failed artifact also produces a failure log entry

Each failed artifact in `write_artifacts` also produces a failure log entry, besides surfacing its
error in the response list.

**Why:** consistent with `write_artifact` behaviour.

Source: none

### R4 — The response holds one entry per input descriptor

When `write_artifacts` returns, the response includes one entry per input descriptor: successful
entries carry `written=True` and `sections_indexed`; failed entries carry `error` and `message`.

Source: FR-25

### R5 — Overwriting writes inherit the shared inner write path's guards

Because every entry ultimately delegates to `_write_artifact_inner`, both `write_artifacts` and
`migrate_artifacts` inherit, without any change of their own: (a) the optimistic-concurrency
compare-and-swap guard on an overwriting write (ETag `IfMatch`, bounded retry, structured
`conflict` error on exhaustion — vector writes stay unconditional/recoverable), and (b) the
`references`-replace / `commit_refs`-accrete asymmetry on that same overwriting write. Neither
tool needs its own logic for either — both are properties of the shared inner write path. Full
mechanism: `docs/specs/p2-t7-write-artifact.md`'s equivalent forward-pointer note.

Source: ADR-011 decisions 4 and 6 (rationale); shipped in commit 7a697dd

## 3. Rules — `migrate_artifacts` bulk migration

### R6 — `dry_run=True` returns the enriched list and writes nothing

When an agent calls `migrate_artifacts(descriptors, dry_run=True)`, the server generates missing
descriptions concurrently via Nova Lite, clips all descriptions to 280 chars, and returns the
enriched list without calling `s3.put_object` or `vectors.put_vectors_batch` — no writes to S3 or
the vector index.

**Example**

- Given 5 descriptors (3 with descriptions, 2 without), when `migrate_artifacts(dry_run=True)` is
  called, then exactly 2 Nova Lite calls are made and the response contains 5 enriched descriptors
  with descriptions ≤ 280 chars.
- Given `dry_run=True`, when the tool returns, then `s3.put_object` and `vectors.put_vectors_batch`
  are never called.

Source: FR-26

### R7 — `dry_run=False` generates missing descriptions, then delegates the write phase to `write_artifacts`

When an agent calls `migrate_artifacts(descriptors, dry_run=False)`, the server generates missing
descriptions concurrently (bounded by `asyncio.Semaphore(settings.artifact_concurrency)`), then
delegates to `write_artifacts` for the write phase. When all descriptors already carry a description, it
delegates directly to `write_artifacts` without making any Nova Lite calls. The response is a
per-artifact result list identical in structure to `write_artifacts`'s.

**Example**

- Given 10 descriptors (8 with descriptions, 2 without) and `dry_run=False`, when
  `migrate_artifacts` is called, then exactly 2 Nova Lite calls are made and all 10 artifacts
  are written to S3, indexed in S3 Vectors, and returned by `list_artifacts`.
- Given 10 descriptors all of which already have descriptions and `dry_run=False`, when
  `migrate_artifacts` is called, then zero Nova Lite calls are made and all 10 artifacts are
  written to S3, indexed in S3 Vectors, and returned by `list_artifacts`.
- Re-calling `migrate_artifacts` with the same 10 descriptors produces no duplicate artifacts
  and no errors.

Source: FR-26

### R8 — Every description is clipped to 280 chars

When Nova Lite generates a description exceeding 280 chars, the server clips it to 280 chars and
logs the clip at DEBUG. When an agent-provided description exceeds 280 chars, the server clips it
to 280 chars and logs at DEBUG; this applies in both `dry_run` modes.

**Example**

- Given a descriptor with an agent-provided description of 300 chars, when
  `migrate_artifacts(dry_run=True)` is called, then the returned description is clipped to 280
  chars.

Source: FR-26

### R9 — A descriptor whose description generation fails is skipped, never written

When Nova Lite description generation fails for a descriptor, that descriptor is skipped, never
written: its result entry is `{"written": False, "skipped": True, "reason":
"description_generation_failed", "message": ...}` (mirroring the `skipped_existing` shape), and a
top-level `"generation_failed"` list (`index`, `title`, `message`) is included in the response in
both `dry_run` modes.

**Why:** a failed generation falling through the clip logic to `description: ""` passes
validation and writes a degraded, near-unsearchable artifact.

Source: none

### R10 — The generation prompt's content is bounded to 8000 chars

The artifact content the Nova Lite generation prompt interpolates is bounded to
`_PROMPT_CONTENT_MAX_CHARS` (8000 chars) via `_truncate_prompt_content` before being sent to Nova
Lite, never the full, untruncated artifact content.

Source: none

### R11 — The prompt template is a hardcoded constant

The Nova Lite prompt template for description generation is a hardcoded constant in
`migrate_artifacts.py` — visible and documented, not in config.

Source: none

## 4. Rules — Section truncation before embedding (P4)

### R12 — A section body over the limit is truncated for the embedding input only

When a section body exceeds `settings.embed_max_section_length` (and the setting is not 0), the
server truncates the body to that length before calling `bedrock.embed`, logging the truncation at
DEBUG. Truncation applies to the embedding input only: content stored in S3 is always the
original, untruncated body. When `EMBED_MAX_SECTION_LENGTH=0`, the server passes section bodies to
`bedrock.embed` unmodified.

**Example**

- Given `EMBED_MAX_SECTION_LENGTH=100` and a section with a 200-char body, when `write_artifact`
  is called, then `bedrock.embed` receives a body of at most 100 chars; `read_artifact` returns
  the full 200-char body.
- Given `EMBED_MAX_SECTION_LENGTH=0`, when `write_artifact` is called with any section body
  length, then the body is passed to `bedrock.embed` unmodified.

Source: FR-01, P4

## 5. Rules — Configuration and startup checks

### R13 — `ARTIFACT_CONCURRENCY` defaults to 3 and is rejected below 1

When `ARTIFACT_CONCURRENCY` is absent from the environment, it defaults to 3. When it is less than
1, the server rejects it at startup with a clear validation error.

**Example**

- Given `ARTIFACT_CONCURRENCY=0`, when the server starts, then it exits with a clear validation
  error before accepting any tool call.

Source: FR-25

### R14 — `EMBED_MAX_SECTION_LENGTH` defaults to 24000 and is rejected when negative

`EMBED_MAX_SECTION_LENGTH` defaults to 24000, and zero is accepted. When `embed_max_section_length`
is a negative integer, the server rejects it at startup with a clear validation error.

**Example**

- Given `EMBED_MAX_SECTION_LENGTH` set to a negative integer, when the server starts, then it
  exits with a clear validation error.

Source: FR-01, P4

### R15 — `BEDROCK_TEXT_MODEL` is optional, and checked live at startup when configured

`BEDROCK_TEXT_MODEL` defaults to `None` — operators must explicitly configure it to use
`migrate_artifacts`. When `BEDROCK_TEXT_MODEL` is configured, the server validates its
accessibility at startup via a live `bedrock:InvokeModel` call and fails hard if the model is
unreachable. When `BEDROCK_TEXT_MODEL` is absent from the environment, the server skips the text
model startup check entirely. Operators in eu-central-1 must use a cross-region inference
profile; this is documented in the configuration reference, not enforced by the server.

**Example**

- Given a `BEDROCK_TEXT_MODEL` that is unreachable, when the server starts, then it exits with
  a clear error identifying the text model startup check as the failure point.

Source: FR-26

## 6. Rules — Migration manifest status tracking

### R16 — The agent records every result in ARKEOLOGY_IMPORT.yaml

When `migrate_artifacts` returns a per-artifact result list, the agent updates each corresponding
entry in ARKEOLOGY_IMPORT.yaml: `status: written` for successful entries; `status: failed` with
the error message populated for failed entries.

**Example**

- Given 10 manifest entries with `status: pending` and a fully successful
  `migrate_artifacts(dry_run=False)` response, when the agent processes the response, then all
  10 entries in ARKEOLOGY_IMPORT.yaml are updated to `status: written`.
- Given a partial failure where 2 of 10 entries fail, when the agent processes the response,
  then the 8 successful entries have `status: written` and the 2 failed entries have
  `status: failed` with the error message populated in the manifest.

Source: FR-27

### R17 — The agent sends only pending and failed entries, and stops when all are written

When the agent prepares a `migrate_artifacts` call, it includes only entries with
`status: pending` or `status: failed`; entries with `status: written` are skipped. When all
entries in ARKEOLOGY_IMPORT.yaml carry `status: written`, the agent reports migration complete
without calling `migrate_artifacts`.

**Example**

- An operator runs a > 10 file migration. During the `migrate_artifacts(dry_run=False)` call, 2
  of 10 artifacts fail due to a transient Bedrock throttle, and the per-artifact response
  identifies the 2 failures. The agent marks 8 entries `written` and 2 `failed` with the error
  detail. On re-run, the agent reads the manifest, filters to only `pending` and `failed` entries,
  and calls `migrate_artifacts` again with only those 2. Both are written successfully; the agent
  marks all entries `written` and reports migration complete.
- Given a manifest where 8 entries are `written` and 2 are `failed`, when the agent prepares
  the next migration call, then only the 2 `failed` entries are included in the
  `migrate_artifacts` input; the 8 `written` entries are skipped entirely.
- Given a manifest where all entries are `written`, when the migration workflow is initiated,
  then no `migrate_artifacts` call is made and the agent reports migration complete.

Source: FR-27

### R18 — The agent lists every failed entry before concluding

If any entries carry `status: failed` after a run, the agent lists every failed entry by path and
error message before concluding the session.

**Example**

- Given any manifest entries with `status: failed` after a run, when the agent concludes the
  session, then it lists every failed entry by path and error message before stopping.

Source: FR-27

### R19 — The manifest carries a per-entry status and is validated before step 3.B5

The manifest schema (`schema.yaml`) has a `status` field (`pending` | `written` | `failed`) with
an optional `error` string per artifact entry. `validate_manifest.py`, a PEP 723 standalone
script, validates all required fields in `ARKEOLOGY_IMPORT.yaml` before step 3.B5 and exits
non-zero if any `status: pending` entry is missing a required field.

Source: none

## 7. Boundaries

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
- The `ARTIFACT_CONCURRENCY` semaphore governs both `write_artifacts` (document-level parallelism)
  and `migrate_artifacts` description generation — one semaphore, two uses; no separate
  `DESCRIPTION_CONCURRENCY`.
- All tools follow the existing `_<name>_inner` + top-level `try/except Exception` pattern.
- TDD: every test file must be written (Red — failing) before the implementation file it gates.

**Ask First:**
- None.

**Never:**
- Do not call the `write_artifact` MCP tool wrapper from within `write_artifacts` — call
  `_write_artifact_inner` directly to avoid double exception wrapping.
- Do not store truncated content in S3 — full body always; truncation is embedding-input-only.
- Do not add a `DESCRIPTION_CONCURRENCY` config var — reuse `ARTIFACT_CONCURRENCY`.
- Do not call `migrate.py` or any external script — the script is deleted as part of this task;
  all logic is server-side.
- Do not change `BedrockClientInterface.embed` to async — section truncation happens at the call
  site in `write.py`; the client signature is unchanged.

## 8. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_config.py` | Modify | Tests for `ARTIFACT_CONCURRENCY` (default 3, ≥ 1), `BEDROCK_TEXT_MODEL` (optional string), `EMBED_MAX_SECTION_LENGTH` (default 24000, ≥ 0) — written first (Red) |
| `tests/unit/test_tools_write.py` | Modify | Add P4 truncation tests (body clipped before embed, full body in S3); update existing embed-input assertions — written first (Red) |
| `tests/unit/test_tools_write_artifacts.py` | Create | Tests for `write_artifacts`: concurrent processing, partial failure, semaphore bound, response structure — written first (Red) |
| `tests/unit/test_tools_migrate_artifacts.py` | Create | Tests for `migrate_artifacts`: Nova Lite calls for missing descriptions, description clipping (both dry_run modes), dry_run=True writes nothing, dry_run=False delegates to write_artifacts, concurrency bound — written first (Red) |
| `tests/unit/clients/test_bedrock.py` | Modify | Add `invoke_text_model` tests: returns string, credential error → CredentialError — written first (Red) |
| `tests/unit/test_startup.py` | Modify | Tests for 6th startup check: BEDROCK_TEXT_MODEL configured + reachable → passes; unreachable → hard fail; absent → check skipped — written first (Red) |
| `src/arkeology/config.py` | Modify | Add `ARTIFACT_CONCURRENCY` (int, default 3, validator ≥ 1), `BEDROCK_TEXT_MODEL` (str \| None, default `amazon.nova-lite-v1:0`), `EMBED_MAX_SECTION_LENGTH` (int, default 24000, validator ≥ 0) |
| `src/arkeology/clients/interfaces.py` | Modify | Add `invoke_text_model(model_id: str, prompt: str) -> str` to `BedrockClientInterface` Protocol |
| `src/arkeology/clients/bedrock.py` | Modify | Implement `invoke_text_model` using `bedrock:InvokeModel` with Nova Lite request/response shape |
| `src/arkeology/clients/fakes/fake_bedrock.py` | Modify | Add `invoke_text_model` stub returning a deterministic short string (e.g. `"Fake description."`) |
| `src/arkeology/startup.py` | Modify | Add 6th check: when `settings.bedrock_text_model` is set, call `bedrock.invoke_text_model` with a minimal probe prompt; fail hard on any error |
| `src/arkeology/tools/write.py` | Modify | Apply P4: before calling `bedrock.embed`, truncate section body to `settings.embed_max_section_length` when non-zero; log truncation at DEBUG |
| `src/arkeology/tools/write_artifacts.py` | Create | `write_artifacts` MCP tool: accept list of descriptors; `asyncio.gather` + `asyncio.Semaphore(ARTIFACT_CONCURRENCY)`; delegate to `_write_artifact_inner` per entry; return per-artifact result list |
| `src/arkeology/tools/migrate_artifacts.py` | Create | `migrate_artifacts` MCP tool: generate missing descriptions via Nova Lite (bounded by `ARTIFACT_CONCURRENCY` semaphore); clip all descriptions to 280 chars; `dry_run=True` returns enriched list; `dry_run=False` delegates to `write_artifacts` |
| `src/arkeology/server.py` | Modify | Register `write_artifacts` and `migrate_artifacts` tools via `register_tools()` |
| `skills/migrating-to-arkeology/scripts/migrate.py` | Delete | Script eliminated — all logic now server-side |
| `skills/migrating-to-arkeology/scripts/validate_manifest.py` | Create | PEP 723 standalone script; validates all required fields in `ARKEOLOGY_IMPORT.yaml` before step 3.B5; exits non-zero if any `status: pending` entry is missing a required field |
| `skills/migrating-to-arkeology/schema.yaml` | Modify | Add `status` field (`pending` \| `written` \| `failed`) with optional `error` string per artifact entry; update header comment to remove `migrate.py` script reference |

### Contracts

None.

### Testing Approach

**TDD cycle A — config layer:**
- `tests/unit/test_config.py` (Red) → `src/arkeology/config.py` (Green)
- `ARTIFACT_CONCURRENCY` default=3, zero → ValidationError; `EMBED_MAX_SECTION_LENGTH` default=24000,
  negative → ValidationError, zero accepted; `BEDROCK_TEXT_MODEL` absent → None, set → string.

**TDD cycle B — P4 section truncation:**
- `tests/unit/test_tools_write.py` (Red) → `src/arkeology/tools/write.py` (Green)
- Section body > limit → `bedrock.embed` spy receives truncated body; `read_artifact` returns full
  body; limit=0 → body unchanged; truncation logged at DEBUG.

**TDD cycle C — `write_artifacts` tool:**
- `tests/unit/test_tools_write_artifacts.py` (Red) → `src/arkeology/tools/write_artifacts.py` (Green)
- 10-entry list → all written; entry with invalid field → error entry in response, others succeed;
  `ARTIFACT_CONCURRENCY=1` → sequential (spy call order); response fields (`written`, `sections_indexed`,
  `error`).

**TDD cycle D — Bedrock text model client:**
- `tests/unit/clients/test_bedrock.py` (Red) → `src/arkeology/clients/bedrock.py` + `fake_bedrock.py` (Green)
- `invoke_text_model` returns a string; credential error → `CredentialError`; fake returns
  deterministic string.

**TDD cycle E — `migrate_artifacts` tool:**
- `tests/unit/test_tools_migrate_artifacts.py` (Red) → `src/arkeology/tools/migrate_artifacts.py` (Green)
- `dry_run=True` → Nova Lite called for missing descriptions only, no S3/vectors writes (spy);
  description > 280 chars → clipped to 280; `dry_run=False` → `write_artifacts` called with
  enriched descriptors; existing description ≤ 280 → unchanged; `ARTIFACT_CONCURRENCY=2` → at
  most 2 concurrent Nova Lite calls (spy + semaphore).
- The failed-generation skip and the prompt-content bound are covered by
  `tests/unit/test_tools_migrate_artifacts.py` (`test_m12_*`).

**TDD cycle F — startup check:**
- `tests/unit/test_startup.py` (Red) → `src/arkeology/startup.py` (Green)
- `BEDROCK_TEXT_MODEL` configured + `invoke_text_model` succeeds → check passes; raises → startup
  fails with actionable error; `BEDROCK_TEXT_MODEL` absent → `invoke_text_model` never called.

**Integration tests** (add to `tests/integration/`, `@pytest.mark.integration`):
- `write_artifacts`: 10-artifact round-trip → `list_artifacts` confirms all present; re-run is
  idempotent (no duplicates).
- `migrate_artifacts`: `dry_run=True` returns enriched list with descriptions ≤ 280 chars, no
  artifacts written; `dry_run=False` writes all and makes them searchable; re-run is idempotent.

**Manifest status tracking — skill-side, no server TDD cycle:**
The manifest status tracking is agent/skill behaviour exercised entirely within the SKILL.md
workflow. There are no new server code paths to test. Verification is done through the
`migrate_artifacts` integration test round-trip: the per-artifact result list it returns is the
input the agent uses to update the manifest. The SKILL.md rewrite (part of T30 SKILL.md
simplification) must describe the manifest update step explicitly.

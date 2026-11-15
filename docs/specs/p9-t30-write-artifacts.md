---
type: Spec
id: p9-t30-write-artifacts
title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
description: Spec for concurrent bulk write and migration tools plus section truncation guard, resolving migration performance problems by moving all logic server-side.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/specs/p10-t39-caller-controlled-artifact-concurrency.md
    title: T39 — Caller-Controlled artifact_concurrency on write_artifacts and migrate_artifacts
  - resource: docs/specs/p12-t56-deterministic-content-reference-rewrite.md
    title: T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)
  - resource: docs/specs/p12-t61-migration-self-heal.md
    title: T61 — Migration Self-Heal — skipped_unindexed Classification
  - resource: docs/specs/p12-t62-bounded-reconcile-retry.md
    title: T62 — Bounded reconcile_index Failure-Log Retry + Fetch-and-Reindex Dedup
  - resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
  - resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
generated:
  by: "axians-architect/unknown"
  at: 2026-06-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
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
8,192-token / 50,000-character limit causes a runtime embed failure. This spec addresses the first
two by moving all logic server-side, and the third with a character-length guard sized for prose
(R12, R14). The manifest status-tracking rules (Migration manifest status tracking) are agent/skill
behaviour in the migration skill's workflow, not server code. The per-call `artifact_concurrency`
both tools take is `p10-t39-caller-controlled-artifact-concurrency`'s, and the classification of an
artifact that is stored but not indexed is `p12-t61-migration-self-heal`'s.

## 2. Rules — `write_artifacts` bulk write

### R1 — Descriptors are processed concurrently, bounded by the call's `artifact_concurrency`

When an agent calls `write_artifacts` with a list of descriptors, the server processes them
concurrently, with at most the call's effective `artifact_concurrency` artifacts in flight at once,
applying P1 section-level concurrency within each artifact. The parameter's range, default and
clamping are `p10-t39-caller-controlled-artifact-concurrency`'s.

**Example**

- Given 10 descriptors and `artifact_concurrency=3`, when `write_artifacts` is called, then at
  most 3 artifacts are in flight at any moment (verifiable by counting writes in flight).

Source: FR-25; p10-t39-caller-controlled-artifact-concurrency R1

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

### R3 — A failed entry has a failure-log entry exactly when the single write would record one

A failed entry in `write_artifacts` has a failure-log entry exactly when `write_artifact` records
one for the same descriptor — once that entry's object write has landed, in which case its result
carries `failure_logged` — and never for an entry rejected before anything was stored, such as one
missing a required field or failing validation.

**Why:** the failure log lists writes `reconcile_index` must complete; an entry for a rejection
names nothing to repair. The bulk tool inherits the single write's failure logging and adds none
of its own.

**Example**

- Given a batch where entry 4 lacks `content` and entry 7's embedding fails after its object was
  stored, when `write_artifacts` returns, then entry 4 carries `validation_error` and no
  failure-log entry exists for it, and entry 7 carries `partial_write` with
  `failure_logged: true` and has exactly one failure-log entry.

Source: FR-25; arkeology.tools.write

### R4 — The response holds one entry per input descriptor

When `write_artifacts` returns, the response includes one entry per input descriptor: successful
entries carry `written=True`, `artifact_id` and `sections_indexed`; failed entries carry `error`
and `message`.

Source: FR-25

### R5 — Overwriting writes inherit the single write path's guards

Because every entry delegates to the single `write_artifact` implementation, an overwriting entry
of `write_artifacts` inherits, without any change of its own: (a) the optimistic-concurrency
compare-and-swap guard on an overwriting write (ETag `IfMatch`, bounded retry, structured
`conflict` error on exhaustion — vector writes stay unconditional/recoverable), and (b) the
`references`-replace / `commit_refs`-accrete asymmetry on that same overwriting write. The tool
needs its own logic for neither — both are properties of the shared write path. `migrate_artifacts`
never overwrites (an existing key is skipped), so neither guard applies to it. Full mechanism:
`docs/specs/p2-t7-write-artifact.md`'s equivalent forward-pointer note.

Source: adr-2026-07-03-annotation-backed-link-storage D4; adr-2026-07-03-annotation-backed-link-storage D6

### R20 — An entry whose key already exists is rejected unless overwriting applies to it

`write_artifacts` applies `write_artifact`'s collision rule to each entry: an entry whose generated
key already exists is rejected with `validation_error` and nothing is written for it, while the rest
of the batch continues — unless overwriting applies to that entry. The call's `overwrite` flag, off
by default, is the batch default; a descriptor may carry its own `overwrite`, which applies to that
entry alone. An overwriting entry replaces the artifact under the guards R5 names.

**Example**

- Given 10 artifacts written by an earlier `write_artifacts` call, when the same call is made
  again without `overwrite`, then every entry returns `validation_error`, and the 10 artifacts
  are neither duplicated nor changed.
- Given the same 10 artifacts, when the same call is made with `overwrite=True`, then all 10
  entries return `written=True` and `list_artifacts` still returns exactly 10 artifacts.

Source: FR-01; FR-25; arkeology.tools.write_artifacts

## 3. Rules — `migrate_artifacts` bulk migration

### R6 — `dry_run=True` returns each descriptor's description, not the document, and writes nothing

⚠️ Hard to reverse: the migration skill and any direct caller are written against this response
shape, and widening it again would bring back the echo of every document.

When an agent calls `migrate_artifacts(descriptors, dry_run=True)`, the server generates missing
descriptions concurrently via Nova Lite, clips all descriptions to 280 chars, and writes nothing —
no write to S3 or the vector index. The response returns, per input descriptor and in input order,
only what the review step uses: the descriptor's `index` and its clipped `description`. It never
echoes a descriptor's `content` or any other field the caller submitted, with one exception: a
descriptor that carried a non-empty `resolved_references_map` also returns its rewritten `content`,
so that the reference rewrite can be previewed. An entry whose description generation failed
carries no `description`.

**Why:** the caller already holds every document it sent; returning each one in full makes the
agent read the whole corpus back to obtain a field of at most 280 characters per document.

**Example**

- Given 5 descriptors (3 with descriptions, 2 without), when `migrate_artifacts(dry_run=True)` is
  called, then exactly 2 Nova Lite calls are made and the response holds 5 entries, each with its
  `index` (0 to 4) and a `description` of at most 280 chars, and no entry carries `content`.
- Given a descriptor that carries a non-empty `resolved_references_map`, when
  `migrate_artifacts(dry_run=True)` returns, then its entry also carries `content`, already
  rewritten, and no `resolved_references_map`.
- Given `dry_run=True`, when the tool returns, then `s3.put_object` and `vectors.put_vectors_batch`
  are never called.

Source: FR-26; arkeology.tools.migrate_artifacts

### R7 — `dry_run=False` generates missing descriptions, then delegates the write phase to `write_artifacts`

When an agent calls `migrate_artifacts(descriptors, dry_run=False)`, the server generates missing
descriptions concurrently (at most the call's effective `artifact_concurrency` at a time), then
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
- Re-calling `migrate_artifacts` with the same 10 descriptors returns every entry skipped as
  already imported: no duplicate artifacts and no errors.

Source: FR-26; p10-t39-caller-controlled-artifact-concurrency R3

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

Generation fails for a descriptor when its text-model call raises — a credential error, a Bedrock
error still raised after the client's single retry of a transient error, or a response that does
not hold the expected text — and when the answer the model returns is empty or holds only
whitespace. Such a descriptor is skipped, never written: its result entry is
`{"written": False, "skipped": True, "reason": "description_generation_failed", "message": ...}`
(mirroring the `skipped_existing` shape), and a top-level `"generation_failed"` list (`index`,
`title`, `message`) is included in the response in both `dry_run` modes. One failure never stops
generation for the other descriptors. Any other answer is a generated description, clipped (R8) and
used.

**Why:** a failed generation falling through the clip logic to `description: ""` passes
validation and writes a degraded, near-unsearchable artifact; an empty answer stored as the
description writes that same artifact.

**Example**

- Given 3 descriptors without descriptions whose second model call raises a throttling error
  twice, when `migrate_artifacts(dry_run=False)` is called, then descriptors 1 and 3 are written,
  descriptor 2's entry carries `reason: "description_generation_failed"`, and `generation_failed`
  lists index 1.
- Given a descriptor without a description whose model answer is three spaces, when
  `migrate_artifacts(dry_run=True)` is called, then its entry carries no `description` and
  `generation_failed` lists its index.

Source: FR-26; arkeology.tools.migrate_artifacts

### R10 — The generation prompt's content is bounded to 8000 chars

The artifact content the Nova Lite generation prompt interpolates is bounded to its first 8,000
characters, followed by a marker saying the content was truncated, before being sent to Nova
Lite — never the full, untruncated artifact content.

Source: none

### R11 — The prompt asks for one plain-text sentence under 280 characters, and the request caps the answer

The Nova Lite prompt for description generation is a hardcoded constant in the server — visible
and documented, not in config. It gives the model the descriptor's title and its content bounded
per R10, and asks for a single-sentence description that summarises what the artifact is about,
under 280 characters, in plain text with no markdown. Each request caps the model's answer at 300
output tokens. An answer that is not empty or whitespace only (R9) is used as returned and then
clipped per R8: an answer longer than 280 characters is cut at character 280, wherever that falls.

**Example**

- Given a descriptor without a description whose model answer is 400 characters long, when
  `migrate_artifacts(dry_run=True)` is called, then its returned description is the answer's first
  280 characters.

Source: FR-26

## 4. Rules — Section truncation before embedding (P4)

### R12 — A section body over the limit is truncated for the embedding input only

When a section body is longer than `settings.embed_max_section_length` characters (and the setting
is not 0), the server truncates the body to that many characters before building the section's
embedding input, logging the truncation at DEBUG. The limit counts characters of the body alone:
the embedding input also carries the section's header lines (title, type, tags, section heading),
so it runs slightly longer than the setting. Truncation applies to the embedding input only:
content stored in S3 is always the original, untruncated body. When `EMBED_MAX_SECTION_LENGTH=0`,
the server passes section bodies to `bedrock.embed` unmodified.

When the embedding model still refuses a section after the cut (R14), the write returns
`partial_write`: the object is stored, and its failure-log entry names the embedding step as the
one that failed. A retry does not fix it: every `reconcile_index` replay rebuilds the same cut,
fails the same way and uses up one of the entry's bounded retries
(`p12-t62-bounded-reconcile-retry` R2), so the repair is to lower `EMBED_MAX_SECTION_LENGTH` and
restart the server — before those retries run out, or after, followed by an overwriting write of
the artifact, which resolves the stuck entry (`p12-t62-bounded-reconcile-retry` R2).

**Example**

- Given `EMBED_MAX_SECTION_LENGTH=100` and a section with a 200-char body, when `write_artifact`
  is called, then `bedrock.embed` receives a body of at most 100 chars; `read_artifact` returns
  the full 200-char body.
- Given `EMBED_MAX_SECTION_LENGTH=0`, when `write_artifact` is called with any section body
  length, then the body is passed to `bedrock.embed` unmodified.
- Given the default setting and one section whose body is a 20,000-character table of
  configuration keys that tokenises to more than 8,192 tokens, when `write_artifact` is called,
  then the body passes the cut untouched, the embedding call is refused, and the write returns
  `partial_write` with `failure_logged: true`.

Source: FR-01, P4

## 5. Rules — Configuration and startup checks

### R14 — `EMBED_MAX_SECTION_LENGTH` defaults to 24000 and is rejected when negative

`EMBED_MAX_SECTION_LENGTH` defaults to 24000, and zero is accepted. When `embed_max_section_length`
is a negative integer, the server rejects it at startup with a clear validation error. The setting
is a character stand-in for a token limit: the embedding model refuses an input over 8,192 tokens
or over 50,000 characters, and 24,000 characters stay within 8,192 tokens only while the text
averages about 2.9 characters per token or more. The default is sized for prose; a deployment whose
documents hold single sections of long code, wide tables, identifiers or hashes, or non-Latin text
lowers it.

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
profile; this is documented in the configuration reference, not enforced by the server. With an
inference profile, Bedrock may serve each description request — which carries the descriptor's
title and up to 8,000 characters of its content (R10) — in any region of the profile's geography,
not only the deployment's region: the document text is processed there, though nothing is stored
there, and the server's role needs `bedrock:InvokeModel` on the model in each of those regions as
well as on the profile. Enabling description generation through a profile is therefore a choice
about where document text is processed.

**Example**

- Given a `BEDROCK_TEXT_MODEL` that is unreachable, when the server starts, then it exits with
  a clear error identifying the text model startup check as the failure point.

Source: FR-26

## 6. Rules — Migration manifest status tracking

### R16 — The agent maps every result to a manifest status and records the artifact's identifier

When `migrate_artifacts(dry_run=False)` returns a per-artifact result list, the agent updates each
corresponding entry in ARKEOLOGY_IMPORT.yaml from its result, by this mapping:

| Result entry | Manifest entry |
|---|---|
| `written: true` | `status: written`; the result's `artifact_id` recorded |
| `skipped: true` with no `reason` — already migrated and indexed | `status: written`; the result's `artifact_id` recorded |
| `skipped: true`, `reason: "unindexed"` — stored but not indexed | `status: failed` with the message; repaired and re-sent per R21 |
| `skipped: true`, `reason: "existence_check_failed"` | `status: failed` with the message |
| `skipped: true`, `reason: "description_generation_failed"` | `status: failed` with the message |
| `error` | `status: failed` with the error message |

The agent tells the kinds of result apart by each `results` entry's own keys and nothing else: an
entry with `error` failed; otherwise `skipped: true` with no `reason` is the already-imported kind,
and any other skip is told by its `reason`. It never reads the top-level `skipped_existing`,
`skipped_unindexed`, `check_failed` or `generation_failed` lists, which repeat the same skips by
`index`.

**Why:** a skip with no `reason` is an artifact the server already holds in full; leaving its entry
`failed` would re-send it on every run, and the migration could never complete. The recorded
`artifact_id` lets a later step, or a later session, name every migrated artifact without the
responses that wrote them.

**Example**

- Given 10 manifest entries with `status: pending` and a fully successful
  `migrate_artifacts(dry_run=False)` response, when the agent processes the response, then all
  10 entries in ARKEOLOGY_IMPORT.yaml are updated to `status: written`, each with its
  `artifact_id`.
- Given a partial failure where 2 of 10 entries fail, when the agent processes the response,
  then the 8 successful entries have `status: written` and their `artifact_id`, and the 2 failed
  entries have `status: failed` with the error message populated in the manifest.
- Given an entry whose artifact an earlier session wrote and indexed but did not record, when it
  is re-sent and its result is skipped with no `reason`, then the entry becomes `status: written`
  with the result's `artifact_id`.

Source: FR-27; arkeology.tools.migrate_artifacts

### R17 — The agent sends only pending and failed entries, and stops when all are written

When the agent prepares a `migrate_artifacts` call, it includes only entries with
`status: pending` or `status: failed`; entries with `status: written` are skipped. When all
entries in ARKEOLOGY_IMPORT.yaml carry `status: written`, the agent reports migration complete
without calling `migrate_artifacts`.

**Example**

- An operator runs a > 10 file migration. During the `migrate_artifacts(dry_run=False)` call,
  description generation fails for 2 of 10 artifacts during a Bedrock throttling spell, and the
  per-artifact response identifies the 2 failures. The agent marks 8 entries `written` and 2
  `failed` with the error detail. On re-run, the agent reads the manifest, filters to only
  `pending` and `failed` entries, and calls `migrate_artifacts` again with only those 2. Both are
  written successfully; the agent marks all entries `written` and reports migration complete.
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

### R19 — The manifest carries a per-entry status, and the live call checks its descriptors

The manifest schema (`schema.yaml`) has a `status` field (`pending` | `written` | `failed`) with
an optional `error` string and an optional `artifact_id` string per artifact entry. The skill bundles
no validator of the manifest's descriptor fields: an entry missing a required field is sent like
any other, comes back from the live `migrate_artifacts(dry_run=False)` call as that entry's
`validation_error` naming the missing field (R2), and becomes `status: failed` with that message
(R16).

**Why:** the server already checks every descriptor and names the missing field; a copy of its
required-field list in the skill would drift from the server's.

**Example**

- Given a pending manifest entry with no `title`, when the agent sends it in a write batch, then
  its result carries `error="validation_error"` and a message naming `title`, the rest of the batch
  is written, and the entry becomes `status: failed` with that message.

Source: FR-23; FR-27

### R21 — Unindexed results are repaired by one `reconcile_index` call, then re-sent once

When, and only when, any result of the migration's write phase is skipped with
`reason: "unindexed"`, the agent calls `reconcile_index` once after the last write batch — the
repair that result's message names — then re-sends those entries once, in one more
`migrate_artifacts(dry_run=False)` call, and maps the new results by R16. An entry still unindexed
after that keeps `status: failed` and is listed per R18.

**Example**

- Given an earlier run in which two artifacts were stored and their embedding failed, so their
  entries are `failed`, when the agent re-runs and both results come back skipped with
  `reason: "unindexed"`, then after the last batch it calls `reconcile_index` once, re-sends the
  two, receives both skipped with no `reason`, and marks both `status: written` with their
  `artifact_id`.

Source: FR-27; p12-t61-migration-self-heal R4

## 7. Boundaries

**Always:**
- `write_artifacts` is a bulk-write primitive for contexts where all descriptor
  fields — including `description` and `content` — are already known by the caller.
  It is appropriate for non-migration bulk writes (e.g. writing multiple code reviews
  or session summaries in a single call). It never generates missing fields.
  **Agents performing migration must always call `migrate_artifacts`**, which handles
  description generation and delegates to `write_artifacts` internally.
- `write_artifacts` requires `description` on every descriptor — it delegates to the single
  `write_artifact` implementation; it never generates descriptions.
- `migrate_artifacts` delegates to `write_artifacts` internally for the write phase — it never
  calls the single-write implementation directly.
- One per-call `artifact_concurrency` bounds both `write_artifacts` (document-level parallelism)
  and `migrate_artifacts` description generation — one bound, two uses; no separate description
  concurrency.
- All tools follow the existing `_<name>_inner` + top-level `try/except Exception` pattern.
- TDD: every test file must be written (Red — failing) before the implementation file it gates.

**Ask First:**
- None.

**Never:**
- Do not call the `write_artifact` MCP tool wrapper from within `write_artifacts` — call
  `write_artifact_inner` directly to avoid double exception wrapping.
- Do not store truncated content in S3 — full body always; truncation is embedding-input-only.
- Do not add a separate description-concurrency setting or parameter — the call's
  `artifact_concurrency` bounds both phases.
- Do not call `migrate.py` or any external script — the script is deleted as part of this task;
  all logic is server-side.
- Do not change `BedrockClientInterface.embed` to async — section truncation happens at the call
  site in `write.py`; the client signature is unchanged.
- Do not check the manifest's descriptor fields in the skill (R19) — revisit if a malformed entry
  could ever be written rather than returned as its own `validation_error`.

## 8. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_config.py` | Modify | Tests for `BEDROCK_TEXT_MODEL` (optional string, default `None`), `EMBED_MAX_SECTION_LENGTH` (default 24000, ≥ 0) — written first (Red) |
| `tests/unit/test_tools_write.py` | Modify | Add P4 truncation tests (body clipped before embed, full body in S3); update existing embed-input assertions — written first (Red) |
| `tests/unit/test_tools_write_artifacts.py` | Create | Tests for `write_artifacts`: concurrent processing, partial failure, in-flight bound, response structure, failure-log entry only after a landed object write, existing-key rejection and `overwrite` (batch default and per-descriptor) — written first (Red) |
| `tests/unit/test_tools_migrate_artifacts.py` | Create | Tests for `migrate_artifacts`: Nova Lite calls for missing descriptions, description clipping (both dry_run modes), an empty or whitespace-only model answer → the generation-failure skip (R9), dry_run=True writes nothing and returns only `index` + `description` per entry (`content` only for a non-empty `resolved_references_map`), dry_run=False delegates to write_artifacts, concurrency bound — written first (Red) |
| `tests/unit/clients/test_bedrock.py` | Modify | Add `invoke_text_model` tests: returns string, request caps the answer at 300 output tokens, credential error → CredentialError — written first (Red) |
| `tests/unit/test_startup.py` | Modify | Tests for 6th startup check: BEDROCK_TEXT_MODEL configured + reachable → passes; unreachable → hard fail; absent → check skipped — written first (Red) |
| `src/arkeology/config.py` | Modify | Add `BEDROCK_TEXT_MODEL` (str \| None, default `None`), `EMBED_MAX_SECTION_LENGTH` (int, default 24000, validator ≥ 0) |
| `src/arkeology/clients/interfaces.py` | Modify | Add `invoke_text_model(model_id: str, prompt: str) -> str` to `BedrockClientInterface` Protocol |
| `src/arkeology/clients/bedrock.py` | Modify | Implement `invoke_text_model` using `bedrock:InvokeModel` with Nova Lite request/response shape, `inferenceConfig.maxTokens` 300 |
| `src/arkeology/clients/fakes/fake_bedrock.py` | Modify | Add `invoke_text_model` stub returning a deterministic short string (e.g. `"Fake description."`) |
| `src/arkeology/startup.py` | Modify | Add 6th check: when `settings.bedrock_text_model` is set, call `bedrock.invoke_text_model` with a minimal probe prompt; fail hard on any error |
| `src/arkeology/tools/write.py` | Modify | Apply P4: before calling `bedrock.embed`, truncate section body to `settings.embed_max_section_length` when non-zero; log truncation at DEBUG (the cut lives in `_section_pipeline.py`, shared with `reconcile_index`) |
| `src/arkeology/tools/write_artifacts.py` | Create | `write_artifacts` MCP tool: accept list of descriptors; `asyncio.gather` bounded by an `asyncio.Semaphore` of the effective `artifact_concurrency` (clamp helper in `tools/_concurrency.py`); delegate to `write_artifact_inner` per entry, forwarding the batch or per-descriptor `overwrite`; return per-artifact result list |
| `src/arkeology/tools/migrate_artifacts.py` | Create | `migrate_artifacts` MCP tool: generate missing descriptions via Nova Lite (bounded by the effective `artifact_concurrency`); prompt constant `_DESCRIPTION_PROMPT`, content bound `_PROMPT_CONTENT_MAX_CHARS` via `_truncate_prompt_content`; an empty or whitespace-only answer takes the generation-failure path (R9); clip all descriptions to 280 chars; `dry_run=True` returns `{index, description}` per descriptor (plus rewritten `content` for a non-empty `resolved_references_map`); `dry_run=False` delegates to `write_artifacts` |
| `src/arkeology/server.py` | Modify | Register `write_artifacts` and `migrate_artifacts` tools via `register_tools()` |
| `plugins/arkeology/skills/migrating-to-arkeology/scripts/migrate.py` | Delete | Script eliminated — all logic now server-side |
| `plugins/arkeology/skills/migrating-to-arkeology/scripts/validate_manifest.py` | Delete | The skill bundles no manifest validator; the live call returns a malformed entry as its own `validation_error` (R19) |
| `plugins/arkeology/skills/migrating-to-arkeology/schema.yaml` | Modify | `status` field (`pending` \| `written` \| `failed`) with optional `error` and `artifact_id` strings per artifact entry; header comment names no `migrate.py` or `validate_manifest.py` script |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | 3.B3 reads `index` + `description` from each dry-run entry; 3.B5 applies R16's result-to-status mapping from each `results` entry's own keys, records `artifact_id`, and runs R21's single `reconcile_index` + re-send; no manifest-validation step before 3.B5 (R19) |

### Contracts

- `docs/contracts/modules/arkeology.tools.write_artifacts.md` § write_artifacts — the bulk write's descriptors, the batch `overwrite` default, the `artifact_concurrency` bound and the positionally aligned `results` (R1–R5, R20).
- `docs/contracts/modules/arkeology.tools.migrate_artifacts.md` § migrate_artifacts — description generation, the dry-run `descriptors` and live `results` shapes, and the skipped entries the manifest mapping reads (R6–R11, R16–R21).
- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the single write every entry delegates to: its collision rule, overwrite guards, failure-log entry and per-section truncation (R3, R5, R12, R20).
- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the repair call the migration skill makes for unindexed results (R21).

### Testing Approach

**TDD cycle A — config layer:**
- `tests/unit/test_config.py` (Red) → `src/arkeology/config.py` (Green)
- `EMBED_MAX_SECTION_LENGTH` default=24000, negative → ValidationError, zero accepted;
  `BEDROCK_TEXT_MODEL` absent → None, set → string.

**TDD cycle B — P4 section truncation:**
- `tests/unit/test_tools_write.py` (Red) → `src/arkeology/tools/write.py` (Green)
- Section body > limit → `bedrock.embed` spy receives truncated body; `read_artifact` returns full
  body; limit=0 → body unchanged; truncation logged at DEBUG; an embed call raising a non-transient
  error → `partial_write` with `failure_logged: true`.

**TDD cycle C — `write_artifacts` tool:**
- `tests/unit/test_tools_write_artifacts.py` (Red) → `src/arkeology/tools/write_artifacts.py` (Green)
- 10-entry list → all written; entry with invalid field → error entry in response, others succeed,
  no failure-log entry for it; `artifact_concurrency=1` → never more than one write in flight
  (count concurrent calls in the patched write, not a spy on the semaphore); response fields
  (`written`, `artifact_id`, `sections_indexed`, `error`); existing key without `overwrite` →
  `validation_error`, with `overwrite=True` (batch or per-descriptor) → replaced.

**TDD cycle D — Bedrock text model client:**
- `tests/unit/clients/test_bedrock.py` (Red) → `src/arkeology/clients/bedrock.py` + `fake_bedrock.py` (Green)
- `invoke_text_model` returns a string; its request carries `maxTokens` 300; credential error →
  `CredentialError`; fake returns deterministic string.

**TDD cycle E — `migrate_artifacts` tool:**
- `tests/unit/test_tools_migrate_artifacts.py` (Red) → `src/arkeology/tools/migrate_artifacts.py` (Green)
- `dry_run=True` → Nova Lite called for missing descriptions only, no S3/vectors writes (spy);
  each entry holds `index` and `description` and no `content`, except a descriptor with a non-empty
  `resolved_references_map`, whose entry carries the rewritten `content`; description > 280 chars →
  clipped to 280; `dry_run=False` → `write_artifacts` called with enriched descriptors; existing
  description ≤ 280 → unchanged; `artifact_concurrency=2` → never more than 2 Nova Lite calls in
  flight (count concurrent calls in the fake).
- The failed-generation skip and the prompt-content bound are covered by
  `tests/unit/test_tools_migrate_artifacts.py` (`test_m12_*`); the fake's answer is set to `""` and
  to whitespace only, and each takes the skip with no `description` in the entry (R9).

**TDD cycle F — startup check:**
- `tests/unit/test_startup.py` (Red) → `src/arkeology/startup.py` (Green)
- `BEDROCK_TEXT_MODEL` configured + `invoke_text_model` succeeds → check passes; raises → startup
  fails with actionable error; `BEDROCK_TEXT_MODEL` absent → `invoke_text_model` never called.

**Integration tests** (add to `tests/integration/`, `@pytest.mark.integration`):
- `write_artifacts`: 10-artifact round-trip → `list_artifacts` confirms all present; a second
  identical call returns `validation_error` for every entry and leaves the 10 artifacts unchanged
  (no duplicates); the same call with `overwrite=True` replaces all 10.
- `migrate_artifacts`: `dry_run=True` returns one entry per descriptor with its `index` and a
  description ≤ 280 chars and no `content`, no artifacts written; `dry_run=False` writes all and
  makes them searchable; a re-run skips every entry as already imported, with no duplicates and no
  errors.

**Manifest status tracking — skill-side, no server TDD cycle:**
The manifest status tracking is agent/skill behaviour exercised entirely within the SKILL.md
workflow. There are no new server code paths to test. Verification is done through the
`migrate_artifacts` integration test round-trip: the per-artifact result list it returns is the
input the agent uses to update the manifest. The SKILL.md must describe the manifest update step
explicitly — R16's mapping from each `results` entry's own keys, the recorded `artifact_id`, and
R21's single `reconcile_index` call and re-send — and holds no manifest-validation step (R19).

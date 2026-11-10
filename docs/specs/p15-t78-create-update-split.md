---
type: Spec
id: p15-t78-create-update-split
title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
description: Replaces write_artifact and write_artifacts, and their overwrite flag, with create_artifact / create_artifacts (succeed only when the key is new, atomically) and update_artifact / update_artifacts (succeed only when it exists, address it by id, never move the key, guard against a concurrent delete with If-Match, and offer an opt-in if_match on last_edited_ulid). Removed names are rejected with a validation_error naming the replacement.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr
    resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-09-29T00:00:00Z
  - id: brainstorming
    resource: docs/brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md
    title: OKF v0.2 Adoption for Arkeology
    last_modified: 2026-09-24T00:00:00Z
  - id: requirements
    resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-09-24T00:00:00Z
  - id: plan
    resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-migrate
    resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
    last_modified: 2026-09-15T00:00:00Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-s3-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: aws-conditional-writes
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html
    title: How to prevent object overwrites with conditional writes
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T13:02:46Z
phase: 15
task: 78
---

# T78 — Split Writing into `create_artifact` / `update_artifact`; Drop `overwrite`

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

`write_artifact` and `write_artifacts` and their `overwrite` flag are replaced by four tools, each
named for what the caller means. `create_artifact` / `create_artifacts` succeed only when the key is
new. `update_artifact` / `update_artifacts` succeed only when the artifact exists, address it by id
so the key never moves, and use S3 conditional writes so an update cannot recreate an artifact that
was deleted while it ran. This removes the two silent failures of the flag: a mistyped id that
creates an artifact, and an overwrite of something the caller did not mean to replace (D51).

## Problem Statement

`overwrite` does not say what the caller intends. `overwrite=true` on a mistyped id creates a new
artifact, and on a correct id replaces whatever is stored whether the caller meant to or not. The key
is also re-derived from the title on every write, so retitling a tier-3 document produces a new id
and leaves the old artifact orphaned. The producer `amanox-ai-agents` plugin now mints ids (D28),
so the server has to check what the caller says it is doing rather than trust the id: a create
must not replace anything, and an update must not create anything (ADR-017 `## Decision`, "Identity" and "Tool surface"; FR-75, C-05).

## User Stories

### Story 1 — Create never replaces (P1)
- Given a tier 2 artifact already stored, when the same type, date and title are created again,
  then the call returns `validation_error` naming `update_artifact`, and one S3 object and the
  original vectors remain unchanged (AC-04).
- Given a tier 3 artifact already stored, when the same type and title are created again, on the
  same day or a different one, then the call returns `validation_error` and nothing changes (AC-05).
- Given two concurrent creates of the same key, when both run, then exactly one succeeds and the
  other returns `validation_error` (C-05).

### Story 2 — Update replaces in place, by id (P1)
- Given a stored tier 2 or tier 3 artifact, when `update_artifact` is called with its `artifact_id`
  and new content, then the content is replaced in place, exactly one stored artifact remains, and
  stale section vectors are removed (AC-04, AC-05).
- Given a tier 3 artifact with a generated id, when it is updated with a new title, then its id is
  unchanged, reading it returns the new title, and no second artifact exists (AC-83).
- Given no artifact with id X, when X is updated, then the call returns `not_found` and nothing is
  created (AC-82). The same holds when X differs from a stored id only in letter case.

### Story 3 — Update cannot move an artifact across type, tier, team or project (P1)
- Given a stored artifact, when an update supplies a different `tier`, `team`, `project` or `type`,
  then it returns `validation_error` and the stored artifact is unchanged (AC-84).

### Story 4 — Opt-in optimistic concurrency (P1)
- Given a caller that read X at revision R, and another writer that has since updated X, when the
  caller updates X with `if_match=R`, then it returns `conflict` and X keeps the other writer's
  content. When the same update omits `if_match`, it succeeds and replaces X (AC-86).

### Story 5 — Bulk update (P1)
- Given three update descriptors, one naming an id that does not exist, when `update_artifacts`
  runs, then the two existing artifacts are updated, the third entry reports `not_found`, and the
  batch is not aborted (AC-85).

### Story 6 — Removed names are rejected, not aliased (P1)
- Given a caller using `write_artifact`, `write_artifacts` or `overwrite`, when it calls the
  server, then the call returns `validation_error` naming the replacement (AC-80; D42).

## Requirements

**Create** (FR-01, FR-08, FR-13, FR-15, FR-25, C-05; D51)

- WHEN `create_artifact` is called THE SYSTEM SHALL derive the key exactly as `write_artifact` does
  today and write the object with a conditional create (`IfNoneMatch: "*"`), with no existence read
  beforehand. The conditional write is the existence check.
- WHEN the key already exists, including when a concurrent create lands first, THE SYSTEM SHALL
  return `validation_error` carrying `artifact_id` with a message naming `update_artifact`, and SHALL
  write nothing to S3, annotations, vectors or the failure log.
- WHEN `create_artifact` succeeds THE SYSTEM SHALL return what `write_artifact` returns today. All
  other behaviour (validation, metadata budgets, section pipeline, annotation write, failure log) is
  unchanged.

**Update: addressing and existence** (FR-75, AC-82, AC-83; D51)

- WHEN `update_artifact` receives an `artifact_id` that does not start with `write_prefix + "/"`
  THE SYSTEM SHALL return `access_denied` before any read, as `archive_artifact` and
  `delete_artifact` do.
- WHEN no object exists at `artifact_id` (exact, case-sensitive match) THE SYSTEM SHALL return
  `not_found` and create nothing.
- THE SYSTEM SHALL write to the supplied `artifact_id` and never derive a key from the title, date
  or type, so the id never changes, including on a retitle.
- THE SYSTEM SHALL make every object write of an update conditional (`If-Match`) on the ETag read
  in the same attempt. WHEN S3 reports the object gone, whether on a re-read or as a 404 from the
  conditional write, THE SYSTEM SHALL return `not_found` and never recreate the object.

**Update: what is replaced, checked and carried forward** (FR-55, FR-69, FR-75, AC-84, C-07; D50)

- THE SYSTEM SHALL replace content, `title`, `description`, `visibility`, `tags`, `author_role`,
  `source_artifacts` and `references` with exactly what the call supplies. An omitted optional
  field takes its create default. There is no partial patch.
- WHEN the call supplies `type`, `team`, `project` or `tier` and the value differs from the one
  stored THE SYSTEM SHALL return `validation_error` naming the field and change nothing. An
  omitted value, or one equal to the stored value, is accepted. Either way the stored value is the
  one written. The comparison runs on every attempt's re-read.
- THE SYSTEM SHALL carry `date` and the archive marker forward from stored object metadata into
  both object and vector metadata. The archive marker is `status` until T76 lands and `archived`
  after it. Neither is an update parameter. Once T81 lands, the OKF lifecycle `status` is also
  carried forward when an update omits it; only an explicit `status: null` clears it (T81,
  operator decision 2026-10-13).
- WHEN the stored `tier` cannot be read THE SYSTEM SHALL return `corrupt_metadata` and write
  nothing (D50: a write never proceeds over a value it cannot read).
- THE SYSTEM SHALL keep today's overwrite link-field semantics unchanged. `commit_refs` is read
  forward from its annotation and union-merged with the supplied value. `references` is set to
  exactly the supplied list.
- THE SYSTEM SHALL regenerate `last_edited_ulid`, clean up orphaned section vectors, and return
  `artifact_id`, `sections_indexed` and `last_edited_ulid`.

**Update: concurrency** (C-05, FR-75, AC-86; D51)

- WHEN the ETag changes between read and write THE SYSTEM SHALL retry the whole cycle (read,
  merge, conditional write, conditional annotation write) up to `CAS_MAX_ATTEMPTS` times,
  re-merging the caller's original values each time. On exhaustion it returns `conflict` if
  nothing landed and `partial_write` if the final attempt's object write landed. This is today's
  overwrite cycle. Without `if_match`, racing updates are last-writer-wins.
- WHEN `if_match` is supplied and the stored `last_edited_ulid` read in the same attempt differs
  from it, or is absent, THE SYSTEM SHALL return `conflict` and change nothing. The check runs on
  every attempt until this call's own object write lands. After that the condition is proven,
  because that write was conditional on the ETag read together with the matching ulid, so later
  retries in the same call do not repeat the check.

**Bulk** (FR-25, FR-76, AC-85; D51)

- `create_artifacts` SHALL be today's `write_artifacts` with `overwrite` removed from both the batch
  and the descriptors. Each entry runs the create logic.
- `update_artifacts` SHALL accept a list of update descriptors, each with the fields of
  `update_artifact` including an optional per-entry `if_match`, plus `artifact_concurrency` with the
  same clamp and `concurrency_warning`. Its results SHALL be positionally aligned and in the same
  shape as `create_artifacts`. A failure in one entry never aborts the others.
- WHEN two descriptors in one `update_artifacts` call name the same `artifact_id` THE SYSTEM SHALL
  fail every later one with `validation_error` naming the first index, mirroring the duplicate
  pre-flight in `create_artifacts`.
- `migrate_artifacts` SHALL delegate to `create_artifacts`. Its skip-existing behaviour is unchanged
  and it never updates.

**Removed names** (AC-80; D42)

- WHEN a tool call names `write_artifact` or `write_artifacts` THE SYSTEM SHALL return
  `{"error": "validation_error", "message": …}` naming `create_artifact` / `update_artifact`
  (respectively `create_artifacts` / `update_artifacts`) without dispatching. Neither name appears
  in the tool list.
- WHEN a call to `create_artifact`, `create_artifacts`, `update_artifact` or `update_artifacts`
  passes an `overwrite` argument THE SYSTEM SHALL return `validation_error` naming `update_artifact`
  (`update_artifacts` for the bulk tools). WHEN a bulk descriptor carries an `overwrite` key THE
  SYSTEM SHALL fail that entry the same way.
- THE SYSTEM SHALL add no case-insensitive id check. Ids that differ only in case are distinct keys
  (D51; FR-08).

### Decisions taken in this spec

**Which fields an update takes.** FR-75 makes `tier`, `team`, `project` and `type` immutable but
AC-84 expects an update that *supplies* a different value to fail with `validation_error`. They are
therefore optional parameters that must match what is stored, not absent parameters. As absent
parameters, an MCP call would get FastMCP's generic unknown-argument error, and a bulk descriptor
would drop them silently. Optional-must-match also lets a caller send back the full descriptor it
created with, and a mismatch tells the caller it has the wrong id, which is D51's principle that
the server checks the caller's stated intent. `date` and the archive marker are carried forward
and are not parameters. `date` is the first-authorship day that anchors tier-2 ids (FR-08), and
first-authorship provenance survives every update (FR-69). T79 replaces it with `generated`,
carried forward the same way, so this is the end-state behaviour. The archive marker belongs to
`archive_artifact` (ADR-017 `## Decision`, "Lifecycle"), and an update that silently un-archived would be a lifecycle
change made through a content write (FR-14).

**When `if_match` is checked.** If the check ran on every attempt, it would wrongly fail an update
whose own write had already landed: a retry re-reads this call's *own* new ulid. Returning
`conflict` at that point would leave this call's content durable while reporting that nothing
changed. Checking until the object write lands, together with the `If-Match` on the ETag read in
the same `head_object` as the ulid, makes the check atomic with the write.

**How removed names are rejected.** With the pinned FastMCP 3.4.6, an unregistered tool returns
`Unknown tool: '<name>'` and an unknown argument returns a pydantic unexpected-argument error,
verified 2026-10-13. Neither is a structured `validation_error` and neither names a replacement.
`server.py` therefore gets one table mapping removed tool names, and removed (tool, parameter)
pairs, to their replacements, and one FastMCP `Middleware` whose `on_call_tool` consults it before
dispatch and argument validation. It returns a `ToolResult` whose structured content is the usual
error dict. The table is per tool because T81 reintroduces `status` with a new meaning, so a
global parameter table would break it. Alternatives rejected:
- Stub tools that always error would stay in the tool list, cost context tokens in every session,
  and read as the aliases D42 forbids.
- A kept `overwrite` parameter that errors would stay in the schema and invite its own use.

Later rename tasks (T76, T79, T84) add rows to the same table. Bulk descriptor keys are inside a
`list[dict]` the middleware cannot see, so each bulk tool checks those itself.

**Module layout.** `create_artifact` and `update_artifact` both live in `tools/write.py`, and
`create_artifacts` and `update_artifacts` in `tools/write_artifacts.py`. The pairs share all of
the section, vector, orphan and failure-log pipeline, which is why `write_artifacts` already
delegates to `write_artifact_inner`. Separate modules would need a third shared module for no
behavioural gain, and the contract ids `arkeology.tools.write` and
`arkeology.tools.write_artifacts` stay valid.

**Create issues no existence read.** The `head_object` before the write existed only to choose
between the overwrite and create branches. Without `overwrite` it saves nothing. The conditional
put is already the authoritative check, and removing the read saves one round trip on every
successful create.

## Boundaries

**Always:**
- Use `is_own_scope` (`startswith(scope + "/")`) for the update scope check.
- Follow the `public / _inner` pattern wrapped in `try/except Exception`, and log to stderr only.
- Keep update's object write and annotation write inside one bounded CAS cycle, with the same
  durability-keyed choice between `conflict` and `partial_write`, and the same failure-log entries
  and `failure_step` stamps the overwrite path has today.
- Store first, then annotations, then vectors.

**Ask First:**
- Adding fields to bulk results, for example a per-entry `last_edited_ulid` so a caller can chain
  `if_match`.
- Changing `CAS_MAX_ATTEMPTS`.

**Never:**
- Add stub tools, aliases or a kept `overwrite` parameter for removed names.
- Check existence for an update with a read-then-write. It must be a condition on the write itself.
- Derive or change a key on update, or apply a partial patch.
- Add a case-insensitive uniqueness lookup.
- Touch the archive marker's rename (T76), the type list (T77), provenance (T79) or link-field
  storage (T84).
- Edit the plugins' skills or agent snippets (T88, T91), README, SERVER-REFERENCE, CHANGELOG or
  AGENTS.md (T91).
- Change `migrate_artifacts`' skip-existing semantics.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_s3.py` | Modify | First. `put_object(..., if_match=…)` on a missing key raises `KeyError` |
| `src/arkeology/clients/s3.py` | Modify | `S3ClientImpl.put_object`: map `NoSuchKey`/`404` under `if_match` to `KeyError(key)` (real S3 returns 404 when a delete beats a conditional write) |
| `src/arkeology/clients/interfaces.py` | Modify | `put_object` docstring: `Raises: KeyError` when `if_match` is set and the object is gone |
| `tests/unit/test_tools_write.py` | Modify | Rename to `create_artifact`; convert every `overwrite=True` test to `update_artifact`; add the update tests below |
| `src/arkeology/tools/write.py` | Modify | `write_artifact` becomes `create_artifact`; new `update_artifact`. Split `write_artifact_inner` into a create path (no `head_object`, conditional create) and an update path (the existing CAS branch, keyed on `artifact_id`, with not-found, immutables, `if_match` and carry-forward added). Reuse `coerce_tier` and `is_own_scope` from `_scope.py` |
| `tests/unit/test_tools_write_artifacts.py` | Modify | Rename to `create_artifacts`; drop `overwrite` cases; add `update_artifacts` tests |
| `src/arkeology/tools/write_artifacts.py` | Modify | `write_artifacts` becomes `create_artifacts`; new `update_artifacts` (own required fields, duplicate-id pre-flight, per-entry `if_match`, same `clamp_concurrency`); reject a descriptor `overwrite` key in both |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Delegation target is `create_artifacts`; no `overwrite` forwarded |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Import and call `create_artifacts`; drop `overwrite=False`; update comments |
| `tests/unit/test_server.py` | Modify | Delete the `overwrite` forwarding tests; add registration and forwarding tests for the four tools; add the AC-80 tests through a real `fastmcp.Client(_app)` (`tool.fn` bypasses middleware) |
| `src/arkeology/server.py` | Modify | Register the four tools; remove `write_artifact` / `write_artifacts`; add the removed-name table and middleware. Add the middleware once at module level, next to `_app`, not inside `register_tools()`, because tests call that repeatedly |
| `tests/unit/test_resources.py` | Modify | Tier and synthesis guidance text names `create_artifact` / `update_artifact`, never `write_artifact` / `overwrite` |
| `src/arkeology/resources.py` | Modify | `tiers_schema_content` and the synthesis and commit-link guidance: replace `write_artifact` / `overwrite=true` with `create_artifact` / `update_artifact` |
| `tests/unit/test_data_resources.py`, `tests/unit/test_tools_section_pipeline.py` | Modify | Import rename only |
| `src/arkeology/errors.py`, `annotations.py`, `failure_log.py`, `tools/archive.py`, `tools/reconcile.py`, `tools/link_metadata.py`, `tools/freshness.py` | Modify | Docstring and comment wording only (`write_artifact` / `overwrite` become `create_artifact` / `update_artifact`). *Uncertain:* sweep with `grep -rn "write_artifact\|overwrite" src/` and leave S3-semantics uses of "overwrite" alone |
| `tests/integration/*` | Modify | See Testing Approach |

## Contract Amendments

Amend these before the tests (plan.md `## Phase 15`, TDD rule):

- **`docs/contracts/modules/arkeology.tools.write.md`**:
  - Rename `### write_artifact` to `### create_artifact` and remove `overwrite`. The collision
    `validation_error` names `update_artifact`, and the existence pre-read is dropped from the
    invariants.
  - Add `### update_artifact`, with errors `access_denied`, `not_found` (missing at start, or gone
    mid-cycle), `validation_error` (immutables), `conflict` (`if_match` mismatch, or CAS exhausted
    while nothing landed) and `corrupt_metadata` (unreadable stored `tier`), plus the existing
    `partial_write`, `annotation_unavailable`, `credential_error` and `internal_error`. Add these
    invariants: the key never changes; immutables match; `date` and the archive marker are carried
    forward; the `if_match` check window; `commit_refs` read forward and `references` replaced.
  - Update the frontmatter `description`.
- **`docs/contracts/modules/arkeology.tools.write_artifacts.md`**:
  - Rename `### write_artifacts` to `### create_artifacts` and drop `overwrite`, both batch and per
    descriptor (a descriptor key is rejected).
  - Add `### update_artifacts`: delegation to `update_artifact`, per-entry `if_match`, duplicate-id
    pre-flight, positional results, no abort.
- **`docs/contracts/modules/arkeology.tools.migrate_artifacts.md`**: the delegation target becomes
  `create_artifacts`. Remove the sentence about the `write_artifacts` `overwrite` split; the
  skip-never-overwrite invariant stays.
- **`docs/contracts/data/s3.artifact.md`**, `## Compatibility Guarantees`:
  - The collision bullet says the artifact is replaced only through `update_artifact`, not an
    `overwrite` flag.
  - The annotation-wipe bullet reads "every update or archive re-PUT".
  - Under `## Storage Shape`, the `last_edited_ulid` row names `create_artifact` / `update_artifact`
    and is noted as the `if_match` token.
- **`docs/contracts/data/s3-annotations.artifact.md`**: the read-forward is keyed on the update
  path rather than on `overwrite`, and `write_artifact` mentions are renamed.
- **`docs/contracts/modules/arkeology.tools.reconcile.md`, `arkeology.tools.link_metadata.md`,
  `arkeology.tools.freshness.md`**: wording only, renaming `write_artifact` / `write_artifacts` /
  "overwriting write" to the new tools and "update".

## Testing Approach

**TDD order** (each test file red before the implementation file it gates):
1. `tests/unit/clients/test_s3.py`, then `clients/s3.py`.
2. `tests/unit/test_tools_write.py`, then `tools/write.py`.
3. `tests/unit/test_tools_write_artifacts.py`, then `tools/write_artifacts.py`.
4. `tests/unit/test_tools_migrate_artifacts.py`, then `tools/migrate_artifacts.py`.
5. `tests/unit/test_server.py` and `tests/unit/test_resources.py`, then `server.py` and
   `resources.py`.
6. Integration updates.

**Moto.** The pinned moto 5.2.2 (`moto[s3]~=5.2`) supports both conditional headers on
`put_object`, so no conftest extension is needed. Verified 2026-10-13 against `moto/s3/responses.py`
and a boto3 probe:
- `IfNoneMatch: "*"` on an existing key returns 412 `PreconditionFailed`.
- `If-Match` with a stale ETag returns 412.
- `If-Match` on a missing or deleted key returns 404 `NoSuchKey`, matching real S3.

The existing self-mock in `tests/unit/conftest.py` clears annotations on `S3Backend.put_object`,
which runs after the conditional check, so it composes unchanged.

**Unit tests to add (with the AC each proves):**
- Create:
  - Second create of the same tier-2 key returns `validation_error` naming `update_artifact`, one
    object, vectors unchanged (AC-04).
  - The same for tier-3 on a different `date` (AC-05).
  - Create makes no `head_object` call (spy), and `put_object` is called with `if_none_match=True`.
- Update, existence and key:
  - An update by id replaces content and cleans orphans, leaving one object (AC-04, AC-05).
  - Updating a missing id returns `not_found`, no object, no vectors (AC-82).
  - A case-variant id returns `not_found`.
  - A foreign-scope id returns `access_denied`, and the `head_object` spy is not called.
  - A retitle keeps the id, a read returns the new title, and one object exists (AC-83).
  - A delete between `head_object` and `put_object` (inject via `side_effect` that deletes first)
    returns `not_found` and no object exists afterwards.
- Update, fields:
  - Each of `type`, `tier`, `team` and `project` differing returns `validation_error` with the
    object unchanged (AC-84).
  - Equal and omitted values succeed.
  - A stored archive marker of inactive stays inactive after the update.
  - The stored `date` is carried forward when it differs from today's date.
  - An unreadable stored `tier` returns `corrupt_metadata` and writes nothing.
  - `commit_refs` is read forward and `references` replaced. Keep the existing overwrite tests,
    retargeted.
- Update, `if_match`:
  - Another update since R gives `conflict` with the other writer's content kept, while the same
    update without `if_match` succeeds (AC-86).
  - A matching `if_match` succeeds.
  - An absent stored ulid gives `conflict`.
  - Our object write lands, the annotation write conflicts once, and the retry succeeds without
    `conflict` (the check-window decision).
- Bulk:
  - `update_artifacts` with three entries, one missing, gives two updated and one `not_found`
    (AC-85).
  - Per-entry `if_match` conflict fails only that entry.
  - A duplicate `artifact_id` in the batch fails the later entry.
  - `concurrency_warning` is emitted when out of range.
- AC-80, via `fastmcp.Client(_app)`:
  - Calling `write_artifact` or `write_artifacts` gives `validation_error` naming the replacements,
    and neither appears in `list_tools`.
  - `overwrite` passed to each of the four tools gives `validation_error`.
  - A descriptor `overwrite` key in `create_artifacts` or `update_artifacts` fails that entry.
- Client: `put_object(if_match=…)` on a missing key raises `KeyError`.

**Integration tests this change breaks** (update in this task, per plan.md):
- Rewrite `tests/integration/test_tools_write.py`:
  - Use `create_artifact` throughout.
  - Its three `overwrite=True` tests become `update_artifact` by `artifact_id`.
  - Add AC-82 (update of a missing id is `not_found` against real S3) and AC-83 (retitle keeps
    the id).
- `tests/integration/test_tools_write_artifacts.py`: rename to `create_artifacts`, and add one
  `update_artifacts` round trip (AC-85).
- `tests/integration/clients/test_s3_client.py`: add a test that `put_object(if_match=…)` on a
  missing key raises `KeyError` against real S3, the one behaviour moto can only approximate.
- Import and call rename `write_artifact` → `create_artifact`, fixtures only:
  `test_calibration_per_artifact_vector_lookup.py`, `test_tools_archive.py`,
  `test_tools_delete.py`, `test_tools_freshness.py`, `test_tools_link_metadata.py`,
  `test_tools_list.py`, `test_tools_propose_commit_links.py`, `test_tools_purge.py`,
  `test_tools_read.py`, `test_tools_reconcile.py`, `test_tools_search.py`,
  `test_tools_studio.py`, `test_tools_synthesise.py`.
- Not broken, and only docstrings mention the old names: `test_tools_migrate_artifacts.py`,
  `test_calibration_vector_metadata_budget.py`, `clients/test_s3_annotations.py`.

## Open Questions

None. No contradiction was found between ADR-017, requirements.md and plan.md for this task. One
open dependency: T76 and T79 add their removed-name rows to the table in `server.py` that this
spec defines, and whichever of T76 and T78 lands first creates it. The T76 spec has confirmed this
shape. It adds per-tool `status` rows, including `update_artifact` and bulk descriptors, and it
removes the archive-marker parameter from `create_artifact`. Until T76 lands, `create_artifact`
keeps today's `status` parameter.

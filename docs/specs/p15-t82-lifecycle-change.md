---
type: Spec
id: p15-t82-lifecycle-change
title: T82 — Change Lifecycle status Without Re-Embedding
description: Adds set_artifact_status, a small own-scope tool that sets, changes or clears an artifact's OKF lifecycle status by reusing archive_artifact's in-place re-PUT cycle, now moved into one shared module. The tool carries content, every other metadata key, every stored annotation and every embedding forward unchanged, so it makes no embedding call and never moves revised, last_edited_ulid or the revision history. The shared cycle carries the whole annotation set annotations.py defines, so T83's verified annotation survives archive and lifecycle changes without either tool changing.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr
    resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-10-13T12:05:48Z
  - id: brainstorming
    resource: docs/brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md
    title: OKF v0.2 Adoption for Arkeology
    last_modified: 2026-10-13T11:37:59Z
  - id: requirements
    resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-10-13T16:47:09Z
  - id: plan
    resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-13T16:23:40Z
  - id: adr-annotations
    resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-10-13T12:05:23Z
  - id: spec-t76
    resource: docs/specs/p15-t76-archived-boolean.md
    title: T76 — Archive Marker status → archived (bool)
    last_modified: 2026-10-13T16:02:34Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T15:56:53Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:22:08Z
  - id: spec-t80
    resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:47:21Z
  - id: spec-t81
    resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: T81 — OKF Lifecycle status and the In-Force Default View
    last_modified: 2026-10-13T16:41:56Z
  - id: spec-t84
    resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:27:20Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-s3vectors
    resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-s3-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: t15
    resource: docs/specs/p3-t15-partial-write-failure-log.md
    title: T15 — Partial Write Failure Log
    last_modified: 2026-11-10T16:24:49Z
  - id: review-2026-11-10
    resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: Architecture review — Arkeology (whole design record)
    last_modified: 2026-11-10T11:21:17Z
  - id: review-2026-11-15
    resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-07-03-annotation-backed-link-storage
    type: constrained_by
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
  - to: p15-t80-revision-history
    type: builds_on
  - to: p15-t81-lifecycle-status-in-force
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T17:40:25Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-16T10:34:57Z
---

# T82 — Change Lifecycle `status` Without Re-Embedding

## TL;DR

A new own-scope tool, `set_artifact_status`, sets, changes or clears an artifact's OKF lifecycle
`status` without a content write. It reuses `archive_artifact`'s in-place re-PUT cycle, which this
task moves into one shared module, so it makes no embedding call and leaves content, `revised`,
`last_edited_ulid`, the link fields and the revision history untouched (FR-68, AC-71). The cycle
carries every annotation in the set `annotations.py` defines, so T83's `verified` survives without
any change to either tool.

## 1. Problem Statement

After T81, the only way to change `status` is `update_artifact`, which is a content write. It
re-embeds every section, appends a revision-history entry and moves `revised`. Because a citing
synthesis treats a moved `revised` as a source change
(brainstorming-2026-09-17-okf-v02-adoption D19), deprecating a document through an update makes
every synthesis that cites it look stale. FR-68 needs a path that only touches the lifecycle key.
ADR-017 `### 2. Lifecycle` names that path: an in-place object re-PUT that carries metadata and
annotations forward, then a vector-metadata update, as `archive_artifact` already does.
`add_artifact_links` (renamed from `link_metadata` by T84) cannot do it, because it writes
annotations only.

All five of this spec's user stories are P1: deprecate without re-embedding (R7, R8), provenance is
not moved (R8), change back or clear (R1, R6, R7), foreign scope and bad input are refused (R2, R3),
and every annotation survives, including ones added later (R10).

## 2. Rules — The tool and its input

### R1 — `set_artifact_status` is its own tool, and sets, changes or clears the lifecycle status

THE SYSTEM SHALL provide `set_artifact_status`, its own tool, not a generalised `archive_artifact`.
It takes `artifact_id`, the full own-scope key, and `status`. Both are required. `status` is
`draft`, `stable`, `deprecated`, or null, where null removes the lifecycle status. Clearing is
allowed, as an explicit null on the required parameter.

**Why:** ADR-017 leaves the choice to the spec. ADR-017 `### 2` separates the archive marker from
the lifecycle `status` and gives them different owners. One tool taking both would rejoin the two
meanings that brainstorming-2026-09-17-okf-v02-adoption D21 split apart. The two operations also
differ in shape: archiving is one-way, warns about referrers and reports `already_archived`; a
lifecycle change goes in any direction and can clear the status. A merged signature would accept
combinations that no requirement defines, such as un-archiving. The tool name states the caller's
intent, as brainstorming-2026-09-17-okf-v02-adoption D51 argues for `create_artifact` /
`update_artifact`. The name follows the existing pattern: `archive_artifact`, `add_artifact_links`,
`add_artifact_verification`. Both tools call one shared cycle, so the path is reused, not copied.
The cost is one more entry in the tool list.

**Why:** T81 makes "no status" a real in-force state, distinct from `stable`. If this tool could not
reach it, the only way back would be an update, which re-embeds, appends history and moves
`revised`. FR-68 exists to avoid exactly that. A sentinel string was rejected because it would look
like a fourth lifecycle value.

Source: FR-14, FR-68; ADR-017 `### 2. Lifecycle`, `### 8. Tool surface`; brainstorming-2026-09-17-okf-v02-adoption D21, D51; T81

*Dated probe, not a rule — probed on FastMCP 3.4.6 (2026-10-13):* `str | None` with no default is
advertised as required. Omitting the argument is rejected before dispatch, and an explicit `null`
reaches the tool as `None`.

### R2 — A foreign-scope `artifact_id` is refused with `access_denied` before any storage call

WHEN `artifact_id` is not in the own scope THE SYSTEM SHALL return `access_denied` before any
storage call. The check is `is_own_scope`, that is `startswith(write_prefix + "/")`.

**Example**

- Given a foreign-scope artifact, when the caller sets its status, then `access_denied` is returned
  before any read (FR-68).

Source: FR-14, FR-68; ADR-017 `### 2. Lifecycle`, `### 8. Tool surface`

### R3 — A `status` string other than the three values is refused with `validation_error` before any storage call

WHEN `status` is a string other than the three values (including `active`, `inactive`, `""`,
`"all"` and other letter cases) THE SYSTEM SHALL return `validation_error` before any storage call,
naming the three values and `archive_artifact`. It SHALL reuse T81's create/update check. `status`
is a plain nullable string on the wire, so the value reaches this check through MCP.

**Example**

- Given `status` of `inactive`, `Stable` or `all`, when the caller calls the tool, then
  `validation_error` names `draft`, `stable`, `deprecated` and `archive_artifact`, and nothing is
  read.

Source: FR-14, FR-68; ADR-017 `### 2. Lifecycle`, `### 8. Tool surface`; T81

### R4 — A missing object, or one deleted during a retry, returns `not_found`

WHEN the object does not exist, or a concurrent delete removes it during a retry, THE SYSTEM SHALL
return `not_found`, as `archive_artifact` does.

Source: FR-14, FR-68; ADR-017 `### 2. Lifecycle`, `### 8. Tool surface`

### R5 — A stored S3 `status` that is present but not one of the three values refuses the change with `corrupt_metadata`

WHEN the stored S3 `status` is present but not one of the three values THE SYSTEM SHALL return
`corrupt_metadata` naming `status` and write nothing (brainstorming-2026-09-17-okf-v02-adoption D50,
case 1). A legacy `active` / `inactive` marker on an object that has not been migrated falls under
this rule. T90 still needs that marker.

**Why:** Overwriting it would destroy the only copy of an unmigrated object's archive marker. A
corrupt value is still fixed by `update_artifact`, and a legacy one by T90.

Source: FR-14, FR-68; ADR-017 `### 2. Lifecycle`, `### 8. Tool surface`; brainstorming-2026-09-17-okf-v02-adoption D50, case 1; T90

## 3. Rules — No-op and completion

### R6 — A state already in S3 and every vector writes nothing; a state in S3 alone is completed

WHEN the S3 `status` already equals the requested value, or both are absent for null, AND every
vector of the artifact agrees THE SYSTEM SHALL write nothing and return `already_set: true`.

WHEN S3 agrees but any vector does not THE SYSTEM SHALL run the full change, which completes an
interrupted one. This is the same rule as `archive_artifact`'s idempotency check.

**Example**

- Given an artifact already in the requested state in S3 and in every vector, when the caller sets
  it again, then nothing is written and the response says `already_set: true`.

Source: FR-68

## 4. Rules — The change

### R7 — The change sets or removes `status` in the object metadata and in every vector through the shared re-PUT cycle

Otherwise — when the call is not a no-op — THE SYSTEM SHALL run the shared re-PUT cycle with one
edit. The shared cycle is `archive_artifact`'s in-place object re-PUT that carries metadata and
annotations forward, then a vector-metadata update, moved into one shared module that
`archive_artifact` and `set_artifact_status` both call. In the re-PUT object metadata `status` is
set to the value, or the key is removed for null. Each vector of the artifact is re-put with its
stored embedding and stored metadata, with `status` set or removed the same way.

**Example**

- Given an own-scope artifact with link fields and a two-entry revision history, when a caller sets
  its `status` to `deprecated`, then no embedding call is made. Its content bytes, `generated`,
  `revised`, `last_edited_ulid`, `archived`, link fields, revision history and every vector's
  embedding are unchanged, and S3 and every vector report `status: deprecated` (AC-71).
- Given that artifact, when the caller searches or lists with default parameters, then it is not
  returned, and reading it by id still works (FR-67).
- Given an artifact in `draft`, when the caller sets `stable`, then both stores say `stable`.
- Given an artifact in `stable`, when the caller sets `status` to null, then neither store holds a
  `status` key, and reads, lists and searches return `status: null` (T81).

Source: FR-67, FR-68, FR-69, FR-72, AC-71; brainstorming-2026-09-17-okf-v02-adoption D19, D30; T81

### R8 — The change makes no Bedrock call, re-PUTs the content and every other object-metadata key but the `ETag` sentinel as read, and appends no revision

THE SYSTEM SHALL make no Bedrock call.

THE SYSTEM SHALL re-PUT the content bytes it read, unchanged. It SHALL write every other
object-metadata key back exactly as read, including `archived`, `generated`, `revised`,
`last_edited_ulid`, `type`, `tier`, `title` and `tags`. The only exception is the reserved `ETag`
sentinel, which is never written.

THE SYSTEM SHALL NOT append to the revision history.

**Example**

- Given an artifact first written by X and updated by Y, when its lifecycle status is changed, then
  first authorship still names X and the latest revision still names Y at Y's time (FR-69, the
  lifecycle leg of AC-72).

Source: FR-68, FR-69, FR-72, AC-71, AC-72; brainstorming-2026-09-17-okf-v02-adoption D19, D30; T80, "Everything else carries it unchanged"

### R9 — A lifecycle change preserves `last_edited_ulid`, as archive preserves it

`last_edited_ulid` is preserved, as archive preserves it. Two consequences follow, and neither
reopens an earlier decision:

- `update_artifact`'s `if_match` does not detect a lifecycle change. FR-75 compares the revision the
  caller read, and a lifecycle change is not a revision (FR-69). `archive_artifact` and
  `add_artifact_links` behave the same way.
- An update that omits `status` keeps it; only an explicit `status: null` on update, or this tool,
  clears it (T81, operator decision 2026-10-13).

**Why:** This ULID is the supersession token that `reconcile_index` uses to decide whether a
failure-log entry's link value still holds. If a lifecycle change moved it, a pending entry could
lose its only copy of the links.

Source: FR-69, FR-75; T81, operator decision 2026-10-13

## 5. Rules — Every annotation is carried

### R10 — The shared cycle carries every annotation in the fixed set `annotations.py` defines, and names none individually

The shared cycle SHALL do four things to every annotation in the carried set that `annotations.py`
defines: read it before the re-PUT, carry it across compare-and-swap attempts, restore it after the
re-PUT under `if_match` on the new ETag, and record it in failure-log entries. Today the set is
`commit_refs`, the link annotation (`links`, renamed from `references` by T84) and
`revision_history`. `verified` joins it with T83.

Each annotation keeps its own carry rule, as T80 and T84 define them:

- `commit_refs` and logs accumulate as an ordered union;
- the link annotation accumulates while `last_edited_ulid` is unchanged, and resets to the fresh
  read when it moves.

An annotation that was absent before the change SHALL stay absent.

The cycle, `archive_artifact` and `set_artifact_status` SHALL NOT name any annotation individually.
Adding an annotation to the set changes none of them. The carried set is fixed by name in
`annotations.py` and never discovered.

**Example**

- Given an artifact carrying every annotation in the carried set, when its status is changed or it
  is archived, then every annotation reads back unchanged. A stand-in annotation added to the set in
  a test survives both operations with no change to either tool (ADR-017 `## Consequences`, "Every
  re-PUT must carry three annotations forward").

**Why:** Each annotation needs its own decoder and its own carry rule across attempts. An
annotation the server does not own has neither, and `update_artifact` drops it anyway. A fixed list
also avoids an extra call per attempt.

Source: FR-54, C-06, C-07; ADR-017 `## Consequences`; T80, T84

### R11 — An unreadable carried annotation returns `corrupt_metadata` and writes nothing, unless this call's own re-PUT has already landed

WHEN a carried annotation is unreadable THE SYSTEM SHALL return `corrupt_metadata` naming it and
write nothing. If this call's own re-PUT has already landed, the failure path for a failure after
the re-PUT applies instead: a failure-log entry, then `partial_write`, or `credential_error` /
`annotation_unavailable` when that is the cause.

Source: FR-54, C-06, C-07; ADR-017 `## Consequences`; T80, T84; brainstorming-2026-09-17-okf-v02-adoption D50 case 1

### R12 — The re-PUT is guarded by an ETag compare-and-swap retried up to `CAS_MAX_ATTEMPTS` times

THE SYSTEM SHALL guard the re-PUT with an ETag compare-and-swap and retry it up to
`CAS_MAX_ATTEMPTS` times. When the retries run out it SHALL return `conflict` if nothing landed,
and `partial_write` if the final attempt's re-PUT landed.

The accepted residuals of C-06 and C-07 apply unchanged. That includes the case where a process
dies between the re-PUT and the restore, which loses the artifact's whole annotation set.

Source: FR-54, C-06, C-07; ADR-017 `## Consequences`

## 6. Rules — Failure and repair

### R13 — A failure after this call's re-PUT has landed appends a failure-log entry, then returns `partial_write` or the causing `credential_error` / `annotation_unavailable`

WHEN any step fails after this call's re-PUT has landed THE SYSTEM SHALL append a failure-log
entry. The entry carries each carried annotation's value under the annotation's name (omitted when
empty) and the preserved `last_edited_ulid`. Its `failure_step` is one of `lifecycle_cas_reread`,
`annotation_read`, `lifecycle_content_fetch`, `lifecycle_reput`, `annotation_write` or
`lifecycle_vector_update`. THE SYSTEM SHALL then return `partial_write`, or `credential_error` /
`annotation_unavailable` when that is the cause. Archive's step names are unchanged. Every such
response carries `failure_logged` (T15 R11): `true` when the entry was appended, `false` when the
append itself failed.

Source: FR-17; C-07; T15 R11

### R14 — `reconcile_index` repairs a lifecycle failure-log entry exactly as it repairs a partial archive

`reconcile_index` SHALL repair a failure-log entry that a lifecycle change appended exactly as it
repairs a partial archive. It restores the annotations and rebuilds the vectors from S3 metadata,
and T81's rebuild rule then copies the new `status`.

Source: FR-17; C-07; T81

## 7. Rules — Response and wiring

### R15 — Success returns the id and the status, plus `already_set: true` on a no-op; an escaping exception returns `internal_error`

On success THE SYSTEM SHALL return `{"artifact_id": …, "status": <value or null>}`, plus
`already_set: true` on a no-op. The public function delegates to `_inner` inside
`try/except Exception`, and an escaping exception returns `internal_error`.

Source: none

### R16 — `server.py` registers `set_artifact_status`; `archive_artifact` does not change and no name is removed

`server.py` SHALL register `set_artifact_status` in `register_tools()`. `archive_artifact`'s
signature, response and observable behaviour do not change. No name is removed, so this task adds
no removed-name row (AC-80 does not apply).

Source: none

## 8. Boundaries

**Always:**
- Keep one re-PUT cycle, shared by `archive_artifact` and `set_artifact_status`, and fix it there.
- Check scope with `is_own_scope` before any storage call.
- Log only through `logging`.

**Ask First:**
- A bulk form, an `if_match` parameter, a referrer or synthesis warning on deprecation, or a Studio
  control.
- Moving `revised` or `last_edited_ulid` on a lifecycle change.

**Never:**
- Call Bedrock, alter content bytes, or append to the revision history.
- Read or write `archived` in `set_artifact_status`, or give `archive_artifact` a `status` input.
- Translate a legacy `active` / `inactive` value (T90).
- Name an individual annotation in the cycle or the two tools, or carry an annotation that is outside
  the set.
- Add a fallback for unavailable annotations.
- Edit the schema resource (T89), or README, CHANGELOG, SERVER-REFERENCE or AGENTS.md (T91).

## 9. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/tools/_reput.py` | Create | The cycle moved out of `archive.py`: the compare-and-swap loop of `_archive_artifact_inner` (read-forward, content fetch, conditional re-PUT, restore, vector re-put) and `_record_partial_archive_failure`, generalised. It takes the object-metadata edit, the vector-metadata edit and the step-name prefix (`archive` / `lifecycle`) |
| `src/arkeology/tools/archive.py` | Modify | Keeps the scope check, idempotency check, referrer check and response, and calls the cycle. Docstrings point to `_reput.py` |
| `src/arkeology/tools/lifecycle.py` | Create | `set_artifact_status` and `_set_artifact_status_inner` |
| `src/arkeology/annotations.py` | Modify | The carried set and three operations over it: read all, merge across attempts by each annotation's rule, restore all. *Uncertain:* T80 and T84 may already have gathered these. If so, only make the cycle use them |
| `src/arkeology/failure_log.py` | Modify | *Uncertain:* if `build_failure_entry` still takes one keyword per annotation, let it take the carried set keyed by annotation name |
| `src/arkeology/server.py` | Modify | Register `set_artifact_status`. The docstring lists the three values and states that null clears |
| `src/arkeology/tools/reconcile.py` | None expected | T81's rebuild already copies `status` from S3. A test pins this |
| `src/arkeology/artifact.py` / `constants.py` | None | Reuse T81's lifecycle value check |

### Contracts

Amend these before writing tests (plan.md `## Phase 15`, the TDD rule):

- **`modules/arkeology.tools.lifecycle.md`** — New (`writing-contracts`). `set_artifact_status`:
  signature, the error list (`access_denied`, `validation_error`, `not_found`, `corrupt_metadata`,
  `conflict`, `partial_write`, `credential_error`, `annotation_unavailable`, `internal_error`),
  `failure_logged` on every response after the re-PUT landed (T15 R11), and the invariants and
  postconditions from the rules above.
- **`modules/arkeology.tools.archive.md`** — State the carry invariant over the carried set, not
  per field, and note that the cycle is shared with `set_artifact_status`. Archive's step names and
  behaviour are unchanged.
- **`data/s3-annotations.artifact.md`** — `## Compatibility Guarantees`: name the carried set as
  normative and say that every re-PUT (update, archive, lifecycle change) carries all of it. A new
  annotation joins the set or is lost on the next re-PUT.
- **`data/s3.artifact.md`** — `status` is also changed in place by `set_artifact_status`. The
  `last_edited_ulid` row adds the lifecycle change to the operations that never add or move it. The
  wipe bullet names the lifecycle change.
- **`data/s3vectors.artifact.md`** — `status` can be rewritten in place, keeping the embedding.
- **`modules/arkeology.tools.reconcile.md`** — The supersession-token invariant adds the lifecycle
  change to the operations that leave the ULID untouched. Its failure entries replay as archive's do.
- **`modules/arkeology.tools.write.md`** — `update_artifact`'s `if_match`: a lifecycle change, like
  an archive or a link backfill, does not move the token.

### Testing Approach

**TDD order.** Each test file below is written red before the implementation file it gates.

1. `tests/unit/test_annotations.py`, then `annotations.py`. Cases:
   - the carried-set read returns every annotation in the set;
   - absent reads as empty, a failed read raises, and an unreadable payload raises naming the
     annotation;
   - restore writes each non-empty annotation under `if_match`, and absent stays absent;
   - the across-attempt merge follows each annotation's rule, including a reset of the link field
     when `last_edited_ulid` moves.
2. `tests/unit/test_tools__reput.py` (new), then `_reput.py` and `archive.py` delegating to it.
   These tests drive the cycle directly with a `status` edit and cover R10 and C-06:
   - content bytes and every other metadata key are identical, and the vectors keep their data;
   - a `mocker.spy` on `bedrock.embed` is not called;
   - every carried annotation, plus a stand-in added to the set with `monkeypatch`, is restored;
   - one injected `ArtifactConflictError` triggers a retry, which accumulates across the attempts;
   - when retries run out, the result is `conflict` before the re-PUT and `partial_write` after it;
   - post-PUT failures write entries with the step names and the annotation copies, and return
     `failure_logged: true`; with the append made to fail, they return `failure_logged: false`.

   The existing `tests/unit/test_tools_archive.py` must pass unchanged, which proves the extraction
   kept archive's behaviour. Add one test to it: the stand-in annotation survives an archive.
3. `tests/unit/test_tools_lifecycle.py` (new), then `lifecycle.py`:
   - **AC-71**: an artifact with `commit_refs`, link fields, two history entries and `revised` is
     set to `deprecated`. No embed call is made. Content, `generated`, `revised`,
     `last_edited_ulid`, `archived`, link fields, history and embeddings are unchanged. S3 and every
     vector say `deprecated`.
   - Every transition between the three values, and a clear to null that removes the key from both
     stores (R7's examples).
   - Foreign scope gives `access_denied` with a `head_object` spy not called, including the prefix
     collision of scope `team-a` against `team-abc/…` (FR-68).
   - These values give `validation_error` naming `archive_artifact`, with nothing read: `active`,
     `inactive`, `""`, `Stable`, `all`.
   - `not_found`.
   - A stored `status: "inactive"`, or any other invalid value, gives `corrupt_metadata`, with the
     `put_object` spy not called.
   - No-op: S3 and the vectors already agree, so `already_set` is returned and nothing is put. When
     S3 agrees and one vector does not, that vector is updated.
   - An archived artifact changes, and `archived` stays true.
   - An unreadable `revision_history` gives `corrupt_metadata` and nothing is written.
   - A credential error before the re-PUT gives no entry. After the re-PUT it gives an entry.
   - The catch-all returns `internal_error`.
4. `tests/unit/test_tools_reconcile.py`: replaying a `lifecycle_vector_update` entry leaves every
   vector with S3's new `status` and every annotation restored. No `reconcile.py` change is expected.
5. `tests/unit/test_tools_write.py`:
   - extend T79's AC-72 composite with a `set_artifact_status` step, after which `generated` and
     `revised` equal the post-update values (FR-69);
   - an `update_artifact` with an `if_match` read before a lifecycle change still succeeds (pins the
     ULID decision, R9).
6. `tests/unit/test_server.py`, then `server.py`:
   - the registered-tool set gains `set_artifact_status`;
   - through `fastmcp.Client(_app)`: `status: null` reaches the inner function as `None`, an omitted
     `status` is rejected before dispatch, and `"inactive"` returns the tool's `validation_error`.
7. **Integration** — new `tests/integration/test_tools_lifecycle.py` against real AWS:
   - create with `commit_refs` and a link field, then set `deprecated`;
   - default `list_artifacts` excludes the artifact, and full lineage includes it;
   - `get_vectors` embeddings are equal before and after;
   - the annotations and `revised` are unchanged;
   - clearing to null returns it to the default list.

   No existing integration test breaks: no signature or behaviour changes. `test_tools_archive.py`
   must still pass unchanged.
8. **Mutation** — `annotations.py` is in `only_mutate`. After landing, run `uv run mutmut run` on
   its own and triage survivors as AGENTS.md describes. `_reput.py` holds no gate and is not added.

**AC-80:** this task removes no name, so it needs no rejection test.

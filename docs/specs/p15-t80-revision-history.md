---
type: Spec
id: p15-t80-revision-history
title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
description: Every content write appends one {by, at} entry to the artifact's own revision_history annotation. The history is uncapped, carried across updates and archives, restorable by reconcile_index, returned by read_artifact, and returned by list_artifacts only on request. The task also builds the object-ETag compare-and-swap append helper that T83 reuses for verified, and states which races and crash windows that compare-and-swap leaves open.
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
  - id: adr-annotations
    resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: spec-t76
    resource: docs/specs/p15-t76-archived-boolean.md
    title: T76 — Archive Marker status → archived (bool)
    last_modified: 2026-10-13T15:57:36Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T13:02:46Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: contract-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-list
    resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-07-03-annotation-backed-link-storage
    type: constrained_by
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t78-create-update-split
    type: builds_on
  - to: p15-t76-archived-boolean
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T16:40:30Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T21:49:10Z
---

# T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper

## TL;DR

Every create and every update adds one `{by, at}` entry to an artifact's `revision_history`
annotation; nothing else adds to it, and every re-PUT carries it forward. `read_artifact` returns
the history, and `list_artifacts` returns it only when the caller asks. The task also builds the
annotation-append helper that T83 reuses for `verified`, and states plainly which races the
object-ETag compare-and-swap underneath does not close (FR-72; D26, D30, D31, D34).

## Open Questions

2. **Non-blocking — hand-off to T90.** Artifacts written before Phase 15 have no history, so after
   migration their first entry is their first update, not `generated`. ADR-017 states that the
   first entry coincides with `generated`. Recommendation: T90 seeds `[generated]`, plus a `revised`
   entry where it writes one, so that statement holds for every artifact. T80 reads an absent
   history as `[]` either way.

## 1. Problem Statement

After T79, `revised` holds only the latest revision, so a reader cannot see how often a living
document changed or who changed it. FR-72 asks for the full history, uncapped, surviving every
update. Object metadata is capped at 2 KB, and vector metadata has a per-section filterable budget,
so neither can hold it (D26). The link annotation is replaced whole whenever links change, so it
cannot hold it either (D31). A separate annotation brings its own hazard: S3 wipes every annotation
when the object is re-PUT, and an annotation write does not change the object's ETag. The history
survives only because every re-PUT reads it first and restores it afterwards. The compare-and-swap
that guards those cycles guards the object, not the annotation (ADR-017 `### 3. Provenance`;
annotation-backed link storage ADR, decision 6). This spec says what that protects and what it does
not.

All six user stories are P1: history records every content write; only content writes add entries;
listings omit history unless asked; unreadable history fails loudly and is never written over; a
failed restore is repairable; and the shared append helper, which T83 consumes.

## 2. Rules — Storage

### R1 — The history is kept in its own `revision_history` annotation, as a JSON array of `{by, at}` objects, oldest first

The system must keep the revision history in its own S3 object annotation, `revision_history`,
apart from the link and `commit_refs` annotations. Its payload must be a JSON array of
`{"by": …, "at": …}` objects, oldest first, with non-ASCII characters escaped. `by` and `at` must be
copied byte-for-byte from the resolved provenance block, whose `at` is T79's canonical
`YYYY-MM-DDTHH:MM:SSZ`. The annotation and the response key are both `revision_history`.

**Why:** Names and encoding: ADR-017 `## Deferred to the Specs` leaves these to the data contract,
and this spec sets them. The payload is JSON because entries are structured and an actor string may
contain commas. The ceiling of about 14,500 entries was measured with this JSON shape
(brainstorming, `## Measurement`). Escaping non-ASCII characters keeps an actor such as
`human:Zürich` byte-stable.

Source: FR-54, FR-72, C-07, C-08; D26, D30, D31, D34

### R2 — The append path never caps, truncates, compacts or deduplicates the history; an entry that would take the payload past the annotation payload limit is refused before anything is written

The system must never cap, truncate, compact or deduplicate the history on the append path (D34).
When an appended entry would take the payload past the annotation payload limit (1,048,576 bytes,
measured 2026-09-23), the system must return `validation_error` before writing anything.

**Why:** The limit refuses the write; it does not cap the history. If an update silently stopped
appending, the history would no longer hold one entry per content write. If the size failure
surfaced only at the restore, the PUT would already have wiped the history. Refusing before the PUT
is the only order that loses nothing.

Source: FR-54, FR-72, C-07, C-08; D26, D30, D31, D34

### R3 — Decoding accepts only a well-formed `{by, at}` array; an absent annotation is an empty history, and every other read failure raises

When decoding, the system must accept only a JSON array in which every element is an object with
exactly two keys: `by`, a non-empty string, and `at`, a string that T79's parser reads as an
offset-aware timestamp. Anything else is unreadable. An absent annotation is an empty history.
Every other read failure raises, as `read_link_annotations` does (`s3-annotations.artifact`
`## Not-Found Semantics`).

Source: FR-54, FR-72, C-07, C-08; D26, D30, D31, D34

## 3. Rules — Content writes append

### R4 — A successful `create_artifact` writes `revision_history` as `[generated]` in the post-PUT annotation step

When `create_artifact` succeeds, the system must write `revision_history` as `[generated]`, in the
same post-PUT annotation step as the link fields and unconditionally like them (T78). Where no link
field is supplied, the link-field call stays skipped. Every create now writes an annotation, so if
annotation permissions drift after setup, a create fails after its object write, with today's
failure-log entry and `annotation_unavailable` (C-08).

**Example**

- Given a newly created artifact, when it is read, then `revision_history` holds exactly one entry,
  equal to `generated`.

Source: FR-55, FR-69, FR-72; D30, D35

### R5 — In every compare-and-swap attempt, `update_artifact` reads the history, appends the resolved `revised` block, and restores the result after the object write

When `update_artifact` runs, in every compare-and-swap attempt, the system must:

- read the history together with the link fields, before the conditional object write;
- append the resolved `revised` block, which is the same entry on every retry because T79 resolves
  the block once per call;
- after the object write, restore the result with the link fields, under `if_match` on the new
  ETag.

**Example**

- Given an artifact created by X, then updated by Y, then by Z, when it is read, then
  `revision_history` holds three `{by, at}` entries in write order: X, Y, Z. The first entry equals
  `generated` and the last equals `revised`, field for field (AC-75; D30, D35).
- Given an artifact with history H, when it is updated, then its history is H plus one entry (FR-55;
  the history clause of AC-60).

Source: FR-55, FR-69, FR-72; D30, D35

### R6 — The history is carried from one compare-and-swap attempt to the next the way `commit_refs` is

The system must carry the history from one attempt to the next the way `commit_refs` is carried
today. The base list is the first attempt's read plus, from each later read, any entries not already
in it. The new entry is then appended.

**Why:** If another writer restores only what it read while this call's annotations were wiped, a
retry that discarded the first read would lose all earlier history.

Source: FR-55, FR-69, FR-72; D30, D35

### R7 — `create_artifacts`, `update_artifacts` and `migrate_artifacts` get the same behaviour through delegation

`create_artifacts`, `update_artifacts` and `migrate_artifacts` get the same behaviour through
delegation.

Source: FR-55, FR-69, FR-72; D30, D35

## 4. Rules — Everything else carries it unchanged

### R8 — `archive_artifact`, and the T82 lifecycle change on the same path, carry the history across attempts and restore it unchanged; neither appends

`archive_artifact`, and the T82 lifecycle change built on the same path, must read the history,
carry it across attempts as `update_artifact` does, and restore it unchanged after the re-PUT.
Neither appends.

**Example**

- Given an artifact with history H, when it is archived, has links backfilled, or is re-indexed by
  `reconcile_index`, then its history is still exactly H (FR-17, FR-54, FR-72; D30).

Source: FR-17, FR-54, FR-72; D30

### R9 — `link_metadata` neither reads nor writes the history

`link_metadata` (renamed `add_artifact_links` by T84) never re-PUTs the object. It must neither read
nor write the history.

Source: FR-17, FR-54, FR-72; D30

### R10 — `reconcile_index` never adds an entry, and writes the history only to restore a failure-log copy

`reconcile_index` must never add an entry. It writes the history only to restore a copy that a
failure-log entry recorded.

Source: FR-17, FR-54, FR-72; D30

### R11 — An update or archive whose read finds the history unreadable returns `corrupt_metadata` and writes nothing; once its own object write has landed, the durable-failure path applies instead

When an update's or archive's read finds the history unreadable, the system must return
`corrupt_metadata` naming `revision_history` and write nothing. Once this call's own object write
has landed, the existing durable-failure path applies instead: a failure-log entry and a structured
error (D50, case 1).

**Example**

- Given a stored history payload that does not decode, then an update or archive of the artifact
  returns `corrupt_metadata` and writes nothing (D50, case 1).

Source: FR-17, FR-54, FR-72; D30; D50 (case 1)

## 5. Rules — Failure log and repair

### R12 — A failure-log entry carrying link-field copies also records the full history being written

When a create, update or archive records a failure-log entry carrying link-field copies, the system
must also record the full history it was writing. An absent field means there is nothing to
restore.

Source: FR-17, FR-54; annotation-backed link storage ADR `## Revision — 2026-09-05`

### R13 — `reconcile_index` restores a recorded history unconditionally: the entries' copies in log order, then any current entries not already present

When `reconcile_index` replays a group of entries that carry a history, the system must restore it
unconditionally, as it restores `commit_refs`. The restored list is the entries' copies in log
order, followed by any entries in the current annotation that are not already present.

**Example**

- Given an update whose object write lands and whose annotation restore then raises, when
  `reconcile_index` replays the failure-log entry, then the history is restored, including that
  update's entry (FR-17, FR-54).

**Why:** The history is append-only, so entries from a later write belong after the failed write's
entries, never in place of them.

Source: FR-17, FR-54; annotation-backed link storage ADR `## Revision — 2026-09-05`

## 6. Rules — Reading

### R14 — A successful `read_artifact` returns `revision_history` (`[]` when the annotation is absent), read after the cross-scope gate

When `read_artifact` succeeds, the system must return `revision_history` as a list of `{by, at}`, or
`[]` when the annotation is absent. The history is read after the cross-scope gate, so a denied
artifact's history is never fetched.

Source: FR-72; D34, D50

### R15 — An unreadable payload makes `read_artifact` return `corrupt_metadata` naming `revision_history` and the reason, never echoing the payload

When the payload is unreadable, `read_artifact` must return `corrupt_metadata` naming
`revision_history` and the reason. It must never echo the payload, to any reader.

**Example**

- Given a stored history payload that does not decode, when the artifact is read, then
  `read_artifact` returns `corrupt_metadata` naming `revision_history`.

**Why:** `corrupt_metadata` never carries the payload. A history can be a megabyte. D50 case 5
forbids echoing a raw value to a foreign-scope reader. Naming the annotation and the reason serves
every reader.

Source: FR-72; D34, D50

### R16 — `list_artifacts` returns the history only when `include_revision_history` is true; search, synthesis and the `arkeology://artifacts` resource never return it

`list_artifacts` must accept `include_revision_history`, default false:

- False: no entry has the key, and no history annotation is read.
- True: every entry carries `revision_history`, read next to the link fields under the same
  concurrency bound.
- An unreadable payload skips the entry and counts it under `skipped_malformed_count`.
- Any other read failure fails the listing, as a failed link-field read does today.

`search_artifacts`, `synthesise_artifacts` and the `arkeology://artifacts` resource must not return
the history.

**Example**

- Given a page of artifacts, when `list_artifacts` is called without `include_revision_history`,
  then no entry carries `revision_history` and no history annotation is read. When the option is
  true, every entry carries it (AC-75; D34).
- Given a stored history payload that does not decode, then a listing that asked for history skips
  the artifact and counts it under `skipped_malformed_count`.

**Why:** The option is on `list_artifacts` only. FR-72 and AC-75 name listings. No consumer needs
the history in search results, and adding it there later would not break anything. The cost it
avoids is one annotation GET per artifact per page (D34).

Source: FR-72; D34, D50

## 7. Rules — Shared append helper

### R17 — `annotations.py` gains one annotation-only, object-ETag compare-and-swap append operation for any `{by, at}` log annotation

`annotations.py` must gain one annotation-only append operation for any `{by, at}` log annotation.
It reads the object's ETag, reads the log (absent means `[]`, and an unreadable payload raises),
appends the entry, checks the size limit, and writes with `if_match` on that ETag. On a failed
precondition it starts again from the ETag read, for at most `CAS_MAX_ATTEMPTS` (3) attempts.
Outcomes:

- success: it returns the list it wrote;
- retries exhausted: `ArtifactConflictError`, which the caller maps to `conflict`, with nothing
  written;
- object gone (`ObjectNotFoundError` or `KeyError`): the caller maps it to `not_found`;
- unreadable payload: the caller maps it to `corrupt_metadata`, with nothing written;
- payload over the limit (`MetadataTooLargeError`): the caller maps it to `validation_error`;
- `CredentialError` and `AnnotationUnavailableError` propagate unchanged.

The helper never re-PUTs the object, so it never moves `revised` or `last_edited_ulid`.

**Example**

- Given an object carrying a `{by, at}` log annotation, when the helper appends an entry, then the
  annotation holds the earlier entries followed by the new one.
- Given an object re-PUT that lands between the helper's ETag read and its write, when the helper
  runs, then it retries and appends to the list that re-PUT restored.
- Given an unreadable payload, when the helper runs, then nothing is written (D46, D50).

Source: D46; ADR-017 `### 8. Tool surface`

### R18 — Every path that touches the history uses the helper's decode, encode and size check

The history's read and write go through the same decode, encode and size check that the helper
uses, in every path that touches it. T83 then adds `verified` by naming a second annotation, not by
writing a second implementation.

Source: D46; ADR-017 `### 8. Tool surface`

## 8. Rules — What the object-ETag compare-and-swap guarantees, and what it does not

No S3 annotation operation accepts an annotation-level precondition. `PutObjectAnnotation` accepts
only `ObjectIfMatch`, which is the object's ETag (verified 2026-09-06). An annotation write never
changes that ETag.

### R19 — Guarded: a writer that read before another writer's object re-PUT fails its own conditional write and retries from a fresh read

A writer that read before another writer's object re-PUT fails its own conditional write and
retries from a fresh read. For an update or archive, that conditional write is the object PUT; for
the helper, it is the annotation write. Two updates whose reads both come before either PUT
therefore serialise, and the history ends as H, a, b.

Source: none attached — stated in this spec

### R20 — Not guarded: residuals 1–3 are left open, unmitigated, and the spec claims no protection beyond what this section states

These are the residuals this design leaves open:

1. **A read inside another writer's wipe window.** Between a re-PUT's object write and its
   annotation restore, the annotations are genuinely absent: S3 answers `NoSuchAnnotation`, not an
   error. A second re-PUT, or a helper append, whose read lands in that window sees an empty
   history. The first writer's restore does not move the ETag, so the second writer's conditional
   write still matches, and it replaces the history with its own entry alone. The same happens when
   an update lands between a create's object write and the create's annotation write.
2. **An annotation-only write just before a re-PUT.** A helper append that lands between a re-PUT's
   read and its object write is overwritten when that re-PUT restores the list it read. Nothing
   writes the history without a re-PUT, so this affects T83's `verified` rather than the history,
   but the helper inherits it.
3. **A process death between the object write and the restore.** Every annotation on the artifact
   is lost: history, links and `commit_refs`. There is no failure-log entry, and the artifact still
   has vectors, so `reconcile_index` never visits it. The failure-log repair above covers a raised
   exception, not a crash. The window covers only the annotation calls, because embedding runs
   after them.

Each residual needs two writers on one artifact within a few hundred milliseconds, or a process
death inside that window. Decision 6 of the annotation-backed link storage ADR accepted the first
kind for link fields, given the server's low-concurrency profile. The requirements are narrower.
All three residuals above can drop an entire history. C-06 and C-07 were amended on 2026-10-13 to
accept exactly these residuals unmitigated (Open Question 1, resolved). This spec claims no
protection beyond what this section states.

No new concurrency mechanism is built: the residuals above are stated, not engineered away. The
options that would narrow them are under Open Questions item 1 below, and ADR-017 decided none of
them.

1. **Open Questions item 1 — resolved 2026-10-13 — the operator accepted these residuals; C-06 and C-07 now name them.**
   *Original question:* the residuals this design leaves open are wider than C-06 and C-07 accept.

   In plain terms, three races can wipe an artifact's whole revision history, along with its
   `commit_refs` trail and links:
   - another write reads during the brief window when a re-PUT has wiped the annotations but not
     yet restored them;
   - an annotation-only append lands just before a re-PUT;
   - the process dies between a re-PUT and its restore.

   C-06 accepts only two `add_artifact_links` calls racing on one field. C-07 accepts only the loss
   of one write's *incremental* `commit_refs`. FR-72 says the history "survives updates" without
   exception. C-07's wording dates from before the 2026-09-05 revision of the annotation-backed
   link storage ADR. At that time a crash lost only one write's additions, because a union with the
   vector copy still kept the older `commit_refs`. That union is gone, so the same crash now loses
   the whole annotation.

   Options:
   - **(a) Recommended: accept and restate.** The PM amends C-06 and C-07, through
     `writing-requirements`, to name residuals 1–3, and FR-72 is read subject to them. This spec
     needs no change. The rationale is decision 6 of the annotation-backed link storage ADR:
     against a low-concurrency profile, a heavier mechanism is not justified.
   - **(b) Mitigate.** Two partial measures:
     - Write a failure-log entry ahead of every re-PUT and clear it on success. This closes
       residual 3 while the host-local log survives, at the cost of a locked file append and
       rewrite on every update and archive.
     - Treat an absent history on an artifact that has been created as a restore still in progress,
       and retry. This closes residual 1 for those artifacts, but it needs T90 to seed histories,
       and an artifact wiped by a crash would then refuse every write.

     Neither measure closes residual 2. Each is a mechanism ADR-017 did not decide.

Source: C-06, C-07; annotation-backed link storage ADR decision 6; Open Questions item 1 (resolved 2026-10-13)

## 9. Boundaries

**Always:**
- Read the history before every re-PUT and restore it after, alongside the link fields, in the same
  compare-and-swap cycle.
- Raise on every failed history read. Only an absent annotation is empty.
- Keep each entry byte-identical to the resolved block (D30).
- Keep the public / `_inner` pattern with `try/except Exception`, and log to stderr only.
- After changing `annotations.py`, which is in `only_mutate`, run mutmut alone and triage survivors
  as AGENTS.md describes.

**Ask First:**
- Any mechanism that closes residual 1, 2 or 3 (Open Question 1).
- Returning the history from search, synthesis, Studio or a resource.
- Changing `CAS_MAX_ATTEMPTS`.

**Never:**
- Derive `generated` or `revised` from the history, or rebuild a missing history from them (D35).
  An absent history is returned as `[]`.
- Keep any copy of the history in object or vector metadata, or read it from anywhere but its
  annotation (D26).
- Append on archive, lifecycle change, link backfill, verification or reconciliation (D30: one
  entry per content write).
- Build the `verified` annotation or `add_artifact_verification` (T83). Restructure the link
  annotation (T84). Seed history in the store migration (T90). Rewrite the schema resource (T89).
  Edit README, SERVER-REFERENCE, CHANGELOG or AGENTS.md (T91).

## 10. For the developer agent

### Files to Touch

T80 lands after T76, T78 and T79, so it edits their result.

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/errors.py` | Modify | Add `CorruptAnnotationError(key, annotation_name, reason)` |
| `src/arkeology/annotations.py` | Modify | Add `REVISION_HISTORY_ANNOTATION`, `ANNOTATION_PAYLOAD_MAX_BYTES`, and the log read, write and append operations. Decode here, inside the mutation scope (ADR-017 `## Consequences`). The suggested shape is `read_entry_log(s3, key, name)`, `write_entry_log(s3, key, name, entries, *, if_match)` and `append_entry_log(s3, key, name, entry)`; the contract fixes the final one. Update the module docstring |
| `src/arkeology/tools/_errors.py` | Modify | Add a `corrupt_metadata` response for `CorruptAnnotationError`, next to the other two mappings. *Uncertain:* inline it if only `read.py` ends up needing it |
| `src/arkeology/failure_log.py` | Modify | `build_failure_entry` gains optional `revision_history`, omitted when empty |
| `src/arkeology/tools/write.py` | Modify | Create: write `[generated]`. Update: read forward, carry across attempts, check size before the PUT, append, restore. Record the history in every durable-failure entry |
| `src/arkeology/tools/archive.py` | Modify | Read forward, carry, restore unchanged. Record the history in failure entries |
| `src/arkeology/tools/reconcile.py` | Modify | `_restore_group_link_fields`, or a sibling helper, restores the history by union |
| `src/arkeology/tools/read.py` | Modify | Read after the gate. Return `revision_history`. Map a corrupt payload to `corrupt_metadata` |
| `src/arkeology/tools/list.py` | Modify | Add `include_revision_history`. Fetch inside `_fetch_link_fields`'s semaphore only when the option is true. Count a malformed payload as a skip |
| `src/arkeology/server.py` | Modify | Forward `include_revision_history` and document it in the `list_artifacts` docstring |
| Tests | Modify / Create | See Testing Approach |

### Contracts

Amend these before the tests (plan.md `## Phase 15`, TDD rule):

- **`data/s3-annotations.artifact.md`**
  - `## Scope`: the store also holds the revision history.
  - New symbols for the log read, write and append, with the errors and outcomes above.
  - The CAS boundary invariant states residuals 1 and 2 by name.
  - `## Storage Shape` gains a `revision_history` row (JSON, oldest first, never empty after a
    create completes, 1 MiB limit refuses).
  - `## Compatibility Guarantees`: every re-PUT carries the history forward; failure-log entries
    carry a copy; residual 3 joins the wipe bullet.
- **`data/s3.artifact.md`** — The `## Compatibility Guarantees` wipe bullet names the history among
  the annotations each re-PUT restores.
- **`modules/arkeology.tools.write.md`**
  - `create_artifact` writes `[generated]`.
  - `update_artifact` appends one entry, carries history across attempts, and returns
    `validation_error` over the limit and `corrupt_metadata` on an unreadable history, writing
    nothing in either case.
  - Failure entries carry the history.
- **`modules/arkeology.tools.archive.md`** — The history is carried unchanged and recorded in
  failure entries. Add `corrupt_metadata`.
- **`modules/arkeology.tools.reconcile.md`** — A failure-log entry may carry `revision_history`,
  which is restored by ordered union. Reconcile never adds an entry.
- **`modules/arkeology.tools.read.md`** — The postcondition adds `revision_history`.
  `corrupt_metadata` now also covers the history, and its message never carries the payload.
- **`modules/arkeology.tools.list.md`** — Add `include_revision_history`. The default reads nothing.
  A malformed history is a skip. A failed read fails the listing.

### Testing Approach

**TDD order** (each test file is red before the implementation file it gates). T80 removes no name,
so no AC-80 test applies.

1. `tests/unit/test_annotations.py`, then `annotations.py` and `errors.py`:
   - Log read: absent gives `[]`. Each malformed payload raises `CorruptAnnotationError`: not JSON,
     not an array, a missing `at`, an extra key, a naive `at`, an empty `by`. `ObjectNotFoundError`,
     a bare `KeyError` and `CredentialError` propagate (mirror the `read_link_annotations` tests).
   - Write: `if_match` is passed through, and a stale ETag raises `ArtifactConflictError`. Over the
     limit raises `MetadataTooLargeError` with no put call (spy; patch the constant small). A
     `human:Zürich` actor round-trips.
   - Append: it appends to an existing log and creates `[entry]` on an absent one. A re-PUT plus
     restore injected between the head and the write (`side_effect`) triggers a retry that appends
     to the restored list. Exhaustion raises after `CAS_MAX_ATTEMPTS` writes. A corrupt payload
     means no put call. A deleted object raises. The object ETag is unchanged afterwards.
2. `tests/unit/test_failure_log.py`, then `failure_log.py`: the entry carries the history when given
   and omits it when empty.
3. `tests/unit/test_tools_write.py`, then `write.py`:
   - **AC-75:** create by X, update by Y, update by Z; the read returns three entries in order, the
     first equal to `generated` and the last to `revised`.
   - The history is carried across an update (AC-60, history clause). The existing test that a
     create with no link fields issues no annotation delete still passes.
   - Carry across attempts: after this call's PUT, inject a competing re-PUT that restores only
     `[b]`. The final history is H, b, e, and `e` keeps the same `at` on every attempt.
   - Over the limit returns `validation_error` and the object is unchanged. A corrupt stored history
     returns `corrupt_metadata` with no PUT (spy).
   - An annotation restore that raises after the PUT records the full history in the failure-log
     entry.
4. `tests/unit/test_tools_archive.py`, then `archive.py`: archiving leaves the history
   byte-identical. A failed restore records it. A corrupt history returns `corrupt_metadata` with
   no PUT.
5. `tests/unit/test_tools_reconcile.py`, then `reconcile.py`:
   - An entry copy `[g, e1]` with a current `[e2]` restores `[g, e1, e2]`.
   - With no history in the entries, the history annotation receives no put call (spy).
   - Re-indexing an artifact leaves its history byte-identical.
6. `tests/unit/test_tools_read.py`, then `read.py`:
   - The history is returned, and an absent history gives `[]`.
   - A corrupt history returns `corrupt_metadata` naming `revision_history`, and the message does
     not contain the payload.
   - A gate-denied foreign artifact issues no history GET (spy).
7. `tests/unit/test_tools_list.py`, then `list.py`:
   - **AC-75:** the default response omits the key and issues no history GET (spy); the option
     returns the history.
   - A corrupt history increments `skipped_malformed_count`.
   - A failed read fails the listing.
8. `tests/unit/test_server.py`, then `server.py`: `include_revision_history` is forwarded.

**Moto.** The self-mock in `tests/unit/conftest.py` already supports everything these tests need:
put, get and delete of a named annotation with arbitrary bytes, `NoSuchAnnotation` for an absent
one, a 412 for `x-amz-object-if-match` against a stale ETag, and wiping on `S3Backend.put_object`.
Checked against the extension on 2026-10-13. The mock does not enforce the 1 MiB limit, which is
why the size guard is tested before any call is made. No conftest change is needed.

**Mutation.** `annotations.py` is in `only_mutate`. After the unit suite is green, run
`uv run mutmut run` alone, then clear `__pycache__`. Triage every survivor in the new functions
against the equivalent-mutant classes, as AGENTS.md describes.

**Integration tests.** None break. T80 adds a response key and an optional parameter, and no
`tests/integration/` test pins an exact response key set or the set of annotations on an object.
Checked against `test_tools_read.py`, `test_tools_list.py`, `test_tools_write.py`,
`test_tools_archive.py` and `test_tools_reconcile.py`. Add:
- `tests/integration/test_tools_read.py`: AC-75 against real AWS. Create, then update twice, once
  with a non-ASCII `human:` actor. The read returns the three entries. `list_artifacts` omits them
  by default and returns them with the option.
- `tests/integration/clients/test_s3_annotations.py`: `put_object_annotation` with `if_match` set to
  the ETag from before a re-PUT raises `ArtifactConflictError` against real S3. Every guarded case
  above rests on this behaviour, and moto only self-mocks it.

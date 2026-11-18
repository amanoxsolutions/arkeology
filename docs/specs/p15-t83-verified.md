---
type: Spec
id: p15-t83-verified
title: "T83 — verified Annotation, add_artifact_verification, and the \"Unverified Since Revised\" Flag"
description: Records verification events as {by, at} entries in the artifact's own verified annotation through a new own-scope tool, add_artifact_verification, built on T80's compare-and-swap append helper — no re-PUT, no re-embedding, no move of revised, revision_history or last_edited_ulid. Every re-PUT carries verified forward. read_artifact returns the list and an advisory unverified_since_revised boolean that never changes the tier. Listings and search stay out of scope (backlog B-14).
tags: []
status: stable
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
  - id: backlog
    resource: docs/planning-artifacts/backlog.md
    title: Backlog
    last_modified: 2026-06-13T18:25:19Z
  - id: adr-annotations
    resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T13:02:46Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: spec-t80
    resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:40:30Z
  - id: spec-t82
    resource: docs/specs/p15-t82-lifecycle-change.md
    title: T82 — Change Lifecycle status Without Re-Embedding
    last_modified: 2026-10-13T17:40:25Z
  - id: contract-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
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
  - to: p15-t80-revision-history
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t82-lifecycle-change
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T17:50:06Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-16T10:12:15Z
verified:
  - by: "human:mlnrt"
    at: 2026-11-18T16:29:34Z
---

# T83 — `verified` Annotation, `add_artifact_verification`, and the "Unverified Since Revised" Flag

## TL;DR

A new own-scope tool, `add_artifact_verification`, records that someone verified an artifact's
content by appending one `{by, at}` entry to the artifact's own `verified` annotation through T80's
append helper. It never re-PUTs the object, re-embeds, or moves `revised`, the revision history or
`last_edited_ulid`. `read_artifact` returns the list plus an advisory `unverified_since_revised`
boolean, true only when the newest verification predates the latest revision; the tier never changes
(FR-70, FR-71; brainstorming-2026-09-17-okf-v02-adoption D41, D44, D45, D46).

## 1. Problem Statement

After T79 an artifact carries first authorship and its latest revision, but nothing records that
anyone confirmed the content still holds. OKF v0.2 carries that as a `verified` list
(brainstorming-2026-09-17-okf-v02-adoption D6). It cannot live in object or vector metadata: it
grows with every review and would eventually trip the 2 KB budgets and block ordinary content writes
(brainstorming-2026-09-17-okf-v02-adoption D44). It cannot share the link or history annotation,
because reviewers append on their own schedule (brainstorming-2026-09-17-okf-v02-adoption D31, D44).
Recording one must not touch content or `revised`, or every synthesis citing the artifact would look
stale (brainstorming-2026-09-17-okf-v02-adoption D19). Once a document has been revised after its
last verification, a reader should be told so — as a warning, not a demotion
(brainstorming-2026-09-17-okf-v02-adoption D41).

All four of this spec's user stories are P1: record a verification without disturbing the artifact
(R11), the advisory flag on read (R15), verifications survive every re-PUT (R3), and refusals (R4,
R8, R19).

## 2. Rules — Storage

### R1 — Verifications live in their own `verified` S3 object annotation, encoded as T80's `revision_history`, with no copy in object or vector metadata and never read from content

THE SYSTEM SHALL keep verifications in their own S3 object annotation, `verified`, encoded exactly
as T80's `revision_history`: a JSON array of `{"by", "at"}` objects in the order recorded,
non-ASCII escaped, decoded and size-checked by T80's log functions. An absent annotation is `[]`.
No copy is kept in object or vector metadata, and nothing filters on it.

The content's own frontmatter is not read. A producer document may carry a `verified:` block in its
stored content. The annotation is the store's record; content is never parsed for it.

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44; T80

### R2 — `create_artifact` writes no `verified` annotation

`create_artifact` SHALL write no `verified` annotation.

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44

### R3 — `verified` joins the carried set, so every re-PUT path carries it forward and none appends to it

`verified` SHALL join the carried set in `annotations.py` (T82), so `update_artifact`,
`archive_artifact` and `set_artifact_status` each read it before their re-PUT, carry it across
compare-and-swap attempts by the log rule (ordered union), restore it unchanged after the re-PUT,
and record it in any failure-log entry they write. None of them appends to it.

**Example**

- Given a verified artifact, when it is updated, archived or has its lifecycle status changed, then
  its `verified` list reads back unchanged (ADR-017 `## Consequences`, "Every re-PUT must carry three
  annotations forward").

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44; T82; ADR-017 `## Consequences`

### R4 — An unreadable `verified` payload on a re-PUT path returns `corrupt_metadata` and writes nothing, until that call's own re-PUT has landed

WHEN any of those paths — `update_artifact`, `archive_artifact` and `set_artifact_status` — reads an
unreadable `verified` payload THE SYSTEM SHALL return `corrupt_metadata` naming `verified` and write
nothing; once that call's own re-PUT has landed, the existing failure-log path applies instead
(brainstorming-2026-09-17-okf-v02-adoption D50, case 1; T80, T82).

**Example**

- Given a `verified` payload that does not decode, when the artifact is read, verified, updated,
  archived or has its status changed, then `corrupt_metadata` names `verified` and nothing is written
  (brainstorming-2026-09-17-okf-v02-adoption D50, case 1).

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44; brainstorming-2026-09-17-okf-v02-adoption D50, case 1; T80, T82

### R5 — `reconcile_index` restores a failure-log entry's `verified` by ordered union and never adds a verification

WHEN `reconcile_index` replays failure-log entries carrying `verified` THE SYSTEM SHALL restore it
by T80's ordered-union rule. Reconcile never adds a verification.

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44; T80

### R6 — The C-06 and C-07 residuals apply unchanged

The C-06 and C-07 residuals apply unchanged. In particular, a verification appended between a
re-PUT's read and its object write is lost when that re-PUT restores what it read.

Source: FR-54, FR-70, C-06, C-07, C-08; brainstorming-2026-09-17-okf-v02-adoption D44

## 3. Rules — `add_artifact_verification`

### R7 — `add_artifact_verification` takes one artifact and one `{by, at}` block named `verification`

THE SYSTEM SHALL provide `add_artifact_verification`, taking `artifact_id` (the full own-scope key)
and `verification`, a `{by, at}` block with `by` required and `at` optional. One call records one
entry on one artifact: there is no list of entries and no `artifact_ids` batch.

**Why:** AC-73 and brainstorming-2026-09-17-okf-v02-adoption D46 treat a verification as one event
on one artifact, so there is no list of entries and no `artifact_ids` batch (unlike
`add_artifact_links`, which merges sets). The block reuses T79's resolver unchanged, so actor and
timestamp rules cannot drift between `generated`, `revised` and verifications. It is named
`verification`, not `verified`, because OKF's `verified` is the list and a single object under that
name would misstate the shape. The response echoes the resolved block so a caller that omitted `at`
learns the stamped time; the full list is `read_artifact`'s job.

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`; T79

### R8 — A foreign-scope `artifact_id` is refused with `access_denied` before any storage call

WHEN `artifact_id` fails `is_own_scope` against the write prefix THE SYSTEM SHALL return
`access_denied` before any storage call. Verification is own scope only.

**Example**

- Given a foreign-scope artifact, when a verification is requested, then `access_denied` is returned
  before any storage call.

**Why:** Every write path is own-scope (archive, T82, `add_artifact_links`). A foreign verification
would let one team move another team's advisory signal and add `human:` verifiers that an OKF §5.3
consumer derives a trust tier from, and it would need annotation write access to another team's
prefix. `access_denied` rather than a silent skip matches T82's single-artifact tool; cross-team
review is recorded by the owning team.

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`; T82

### R9 — `verification` is validated and resolved by T79's provenance-block resolver before any storage call; `at` is optional and unordered

THE SYSTEM SHALL validate and resolve `verification` with T79's provenance-block resolver before
any storage call: OKF §7 actor forms for `by`, ISO 8601 with an explicit offset for `at` (an
offset-naive value or a bare date is rejected, never assumed UTC), any other key rejected — each a
`validation_error` naming the field. An accepted `at` is stored in T79's canonical UTC form
(`YYYY-MM-DDTHH:MM:SSZ`, truncated to seconds); an omitted `at` is the server clock in that form,
resolved once per call so every retry appends the same entry.

`at` is optional and unordered, as T79 decided for `revised`. No check runs against `generated.at`,
`revised.at` or the clock.

**Why:** Importing a producer document's existing `verified` list needs past times. The owner records
its own statement under the same write authority that could withhold it. A future-dated entry
therefore suppresses the flag until a later revision — accepted, as the flag is advisory.

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`; T79

### R10 — The entry is appended with T80's append helper, and each outcome maps to one response

THE SYSTEM SHALL append the resolved entry with T80's append helper and map its outcomes:

| Outcome | Response |
|---------|----------|
| object gone | `not_found` |
| unreadable payload | `corrupt_metadata` naming `verified`, nothing written |
| payload past the annotation limit | `validation_error` |
| retries exhausted | `conflict` |
| `CredentialError` | `credential_error` |
| `AnnotationUnavailableError` | `annotation_unavailable` |

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`; T80

### R11 — Recording a verification makes no Bedrock call, object PUT or vector write, and leaves the object and every other annotation as they were

THE SYSTEM SHALL make no Bedrock call, no object PUT and no vector write. The object's ETag,
metadata (`generated`, `revised`, `last_edited_ulid`, `archived`, `status`) and every other
annotation stay as they were (FR-69, FR-72). No failure-log entry is ever written: the only write
is the annotation, which either lands or does not.

**Example**

- Given an own-scope artifact, when a verification is recorded and then a second one, then no
  embedding call is made, content, `revised`, `revision_history` and `last_edited_ulid` are
  unchanged, and reading it returns both verifications in the order recorded (AC-73).
- Given an artifact created by X and updated by Y, when a verification is recorded, then
  `generated` still names X and `revised` still names Y at Y's time (the verification leg of AC-72).

Source: FR-14, FR-69, FR-70, FR-72, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`

### R12 — Archived, deprecated and draft artifacts may be verified

Archived, deprecated and draft artifacts MAY be verified; no archive or lifecycle check runs.

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`

### R13 — Success returns the artifact id and the resolved block; an escaping exception returns `internal_error`

On success THE SYSTEM SHALL return `{"artifact_id": …, "verification": {"by": …, "at": …}}` with
the resolved values. The public function delegates to `_inner` inside `try/except Exception`; an
escaping exception returns `internal_error`.

Source: FR-14, FR-70, AC-72, AC-73; brainstorming-2026-09-17-okf-v02-adoption D46; ADR-017 `### 8. Tool surface`

## 4. Rules — Reading and the flag

### R14 — A successful `read_artifact` always returns `verified` and `unverified_since_revised`, read after the cross-scope gate

WHEN `read_artifact` succeeds THE SYSTEM SHALL return `verified` as the stored list (or `[]`) and
`unverified_since_revised` as a boolean, both always present, next to `tier`. Both are read and
computed after the cross-scope gate, so a denied artifact's `verified` is never fetched; a reader
the gate admits receives both.

**Why:** Absent signal is `false`, never an omitted key, matching T79's house rule that response keys
are always present (`revised: null`). The name states the condition in FR-71's own words.

Source: FR-70, FR-71, AC-73, AC-74; brainstorming-2026-09-17-okf-v02-adoption D19, D41, D45; ADR-017 `### 10`; T79

### R15 — `unverified_since_revised` is true only when the latest `verified.at` is strictly earlier than `revised.at`

THE SYSTEM SHALL set `unverified_since_revised` to true only WHEN `verified` is non-empty AND
`revised` is present AND the latest `verified.at` — the maximum over all entries, not the last
entry — is strictly earlier than `revised.at`, both compared as parsed, offset-aware datetimes
(brainstorming-2026-09-17-okf-v02-adoption D19). Otherwise it is false. `generated.at` is never used
as a fallback.

**Example**

- Given an artifact verified by X and then updated by Y, when it is read, then
  `unverified_since_revised` is true and `tier` is unchanged. After a new verification is
  recorded, it reads false (AC-74).
- Given an artifact never verified, or verified after its latest revision, or never revised, when it
  is read, then `unverified_since_revised` is false (AC-74; FR-71).

**Why:** Because entries can arrive out of time order, the flag uses the maximum `at`, not the last
entry. No `revised` means no flag: FR-71 asks whether content was revised after the most recent
verification; an artifact never revised was not, whatever its `generated.at`. FR-71 and AC-74 say
"never revised" is false outright. Falling back to `generated.at` would flag a verification
backdated before first authorship, which is a data-entry oddity, not a revision.

Source: FR-70, FR-71, AC-73, AC-74; brainstorming-2026-09-17-okf-v02-adoption D19, D41, D45; ADR-017 `### 10`

### R16 — An unreadable `verified` payload fails the read with `corrupt_metadata`, never echoing the payload

WHEN the `verified` payload is unreadable `read_artifact` SHALL return `corrupt_metadata` naming
`verified` and never echo the payload, to any reader (brainstorming-2026-09-17-okf-v02-adoption D50,
case 5). An unreadable `revised` already returns `corrupt_metadata` (T79), so the flag is never
computed from an unreadable timestamp. Unreadable timestamps fail the read, not just the flag.

**Why:** ADR-017 `### 10`'s "marks only its own source" rule is about freshness sources. A
`verified` entry's `at` is validated when decoded, so an unreadable one makes the whole annotation
payload uninterpretable, which the same section makes `corrupt_metadata` on a single read. Returning
the artifact with the flag silently false would be the degraded path AGENTS.md forbids, and would
under-warn.

Source: FR-70, FR-71, AC-73, AC-74; brainstorming-2026-09-17-okf-v02-adoption D19, D41, D45; ADR-017 `### 10`; brainstorming-2026-09-17-okf-v02-adoption D50, case 5; T79

### R17 — Computing the flag writes nothing and alters no returned field

Computing the flag SHALL write nothing and SHALL NOT alter `tier`, `visibility` or any other
returned field (brainstorming-2026-09-17-okf-v02-adoption D41).

Source: FR-70, FR-71, AC-73, AC-74; brainstorming-2026-09-17-okf-v02-adoption D19, D41, D45; ADR-017 `### 10`

### R18 — Listings, search, synthesis, Studio and the `arkeology://` resources do not return `verified` or the flag

`list_artifacts`, `search_artifacts`, `synthesise_artifacts`, Studio and the `arkeology://`
resources SHALL NOT return `verified` or the flag (brainstorming-2026-09-17-okf-v02-adoption D45;
backlog B-14).

Source: FR-70, FR-71, AC-73, AC-74; brainstorming-2026-09-17-okf-v02-adoption D19, D41, D45; ADR-017 `### 10`; B-14

## 5. Rules — Redirect for a write-time `verified`

### R19 — A write-time `verified` is redirected to `add_artifact_verification` with `validation_error`

THE SYSTEM SHALL add rows to T78's per-tool removed-name table: `create_artifact` and
`update_artifact`, name `verified`, replacement `add_artifact_verification`. WHEN a
`create_artifacts` or `update_artifacts` descriptor carries a `verified` key THE SYSTEM SHALL fail
that entry with the same `validation_error`; `migrate_artifacts` inherits this through delegation.

Write-time verification is a second call: calling `add_artifact_verification` right after the
create or update.

**Example**

- Given a caller passing `verified` to `create_artifact` or `update_artifact`, or as a key in a
  `create_artifacts` / `update_artifacts` descriptor, then the call (or entry) fails with
  `validation_error` naming `add_artifact_verification`.

**Why:** FR-70 allows recording "at write time or at any later point". Calling
`add_artifact_verification` right after the create or update satisfies it with one code path, and
keeps create/update signatures as T78 and T79 froze them. Today a bulk descriptor's unknown key is
silently ignored, so a migration passing frontmatter `verified` would drop verifications without
error; the redirect rows turn that into a `validation_error` naming the tool. `verified` was never a
parameter, so this is not an AC-80 removed name; the row reuses T78's mechanism as T79 did for
`timestamp`.

Source: FR-70; brainstorming-2026-09-17-okf-v02-adoption D42; T78, T79

## 6. Boundaries

**Always:**
- Check `is_own_scope` and validate the block before any storage call.
- Go through T80's helper and log functions; raise on every failed read, treat only an absent
  annotation as empty.
- Compare timestamps as parsed datetimes through T79's parser.
- Keep the public / `_inner` pattern and log to stderr only. After changing `annotations.py`
  (in `only_mutate`), run mutmut alone and triage survivors as AGENTS.md describes.

**Ask First:**
- A bulk or multi-entry form, a foreign-scope verification, or removing or editing a verification.
- Surfacing `verified` or the flag on any surface other than `read_artifact` (B-14).
- Accepting `verified` on create or update instead of redirecting it.

**Never:**
- Re-PUT the object, call Bedrock, write vectors, or move `revised`, `revision_history` or
  `last_edited_ulid` when recording a verification.
- Change `tier` or any trust classification from the flag
  (brainstorming-2026-09-17-okf-v02-adoption D41).
- Store any copy of `verified` in object or vector metadata, or read it from content.
- Let the flag affect freshness, the in-force view or any filter.
- Build a second append implementation, or add a fallback when the annotation is unavailable.
- Rewrite the schema resource (T89), migrate stored verifications (T88, T90), or edit README,
  SERVER-REFERENCE, CHANGELOG or AGENTS.md (T91).

## 7. For the developer agent

### Files to Touch

The plan blocks T83 on T80 only. Where T82 has not landed yet, the carried set does not exist; the
uncertain rows below say what changes in that case.

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/annotations.py` | Modify | `VERIFIED_ANNOTATION = "verified"`; add it to the carried set (log carry rule). *Uncertain:* if T82 has not landed, no set exists — add the name next to `REVISION_HISTORY_ANNOTATION` and carry it explicitly in the files below |
| `src/arkeology/tools/verification.py` | Create | `add_artifact_verification` and `_add_artifact_verification_inner`: scope check, T79 block resolver, T80's append helper (final name per the `s3-annotations.artifact` contract), outcome mapping |
| `src/arkeology/tools/read.py` | Modify | Read `verified` after the gate with the history; decode error → `corrupt_metadata`; compute the flag with T79's parser |
| `src/arkeology/tools/write.py` | Modify | *Uncertain:* none if update already iterates the carried set; otherwise read, carry, restore and failure-log `verified` exactly as T80 does `revision_history` |
| `src/arkeology/tools/archive.py`, `tools/_reput.py` | None expected | *Uncertain:* none once T82's shared cycle iterates the set; otherwise carry `verified` in `archive.py` as T80 carries the history |
| `src/arkeology/failure_log.py`, `tools/reconcile.py` | Modify | *Uncertain:* none if T82 keyed entries and restore by carried-set name; otherwise add a `verified` field and restore it by ordered union beside `revision_history` |
| `src/arkeology/tools/write_artifacts.py` | Modify | Fail a create or update descriptor carrying `verified`, naming `add_artifact_verification` |
| `src/arkeology/server.py` | Modify | Register `add_artifact_verification` in `register_tools()` with a docstring (block shape, `at` optional, own scope, no re-embed); add the two redirect rows |
| `src/arkeology/tools/_errors.py` | None expected | Reuse T80's `CorruptAnnotationError` → `corrupt_metadata` mapping |
| Tests | Modify / Create | See Testing Approach |

### Contracts

Amend these before writing tests (plan.md `## Phase 15`, TDD rule):

- **`modules/arkeology.tools.verification.md`** — New (`writing-contracts`). `add_artifact_verification`:
  signature; errors (`access_denied`, `validation_error`, `not_found`, `corrupt_metadata`,
  `conflict`, `credential_error`, `annotation_unavailable`, `internal_error`); invariants (no re-PUT,
  no Bedrock call, no vector write, ETag and object metadata unchanged, no failure-log entry, the
  C-06 residuals); postcondition (resolved block returned).
- **`data/s3-annotations.artifact.md`** — `## Storage Shape`: a `verified` row (T80's log encoding,
  record order, absent is `[]`, 1 MiB limit refuses). `## Compatibility Guarantees`: `verified` is in
  the carried set; failure-log entries may carry it; residual 2 names it.
- **`data/s3.artifact.md`** — The wipe bullet names `verified` among the annotations each re-PUT
  restores.
- **`modules/arkeology.tools.read.md`** — Postconditions add `verified` and `unverified_since_revised`
  with the condition above; the read writes nothing; `corrupt_metadata` covers `verified` without
  echoing the payload; neither key is fetched for a denied artifact.
- **`modules/arkeology.tools.write.md`** — `update_artifact` carries `verified` unchanged and returns
  `corrupt_metadata` on an unreadable one; `create_artifact` writes none; a `verified` argument is
  rejected naming `add_artifact_verification`.
- **`modules/arkeology.tools.write_artifacts.md`**, **`.migrate_artifacts.md`** — A `verified`
  descriptor key fails the entry.
- **`modules/arkeology.tools.reconcile.md`** — A failure-log entry may carry `verified`, restored by
  ordered union; reconcile never adds one.

### Testing Approach

**TDD order** (each test file is red before the implementation file it gates). T83 removes no name,
so no AC-80 test applies; the redirect rows are tested in step 6 through the same middleware.

1. `tests/unit/test_annotations.py`, then `annotations.py`: `verified` is in the carried set; T80's
   log read, write and append round-trip under the name `verified` (one parametrised case, not a
   copy of T80's suite).
2. `tests/unit/test_tools_verification.py`, then `tools/verification.py`:
   - **AC-73:** two verifications; Bedrock and vector puts never called (spy); content, `revised`,
     `revision_history`, `last_edited_ulid` and the object ETag identical before and after; the read
     returns both in order.
   - **AC-72 verification leg:** extend T79's composite (create by X, update by Y, …) with a
     verification; provenance in both stores equals the post-update values.
   - Foreign scope → `access_denied` with no S3 call (spy). Missing `by`, a role name as `by`, a
     naive `at`, a bare date, an extra key → `validation_error`, no S3 call.
   - Omitted `at` stores the canonical server time; an offset `at` is stored as its UTC instant; a
     forced retry appends the same entry once.
   - Missing object → `not_found`; corrupt payload → `corrupt_metadata`, no put (spy); over the limit
     (constant patched small) → `validation_error`; exhaustion → `conflict`; `CredentialError` and
     `AnnotationUnavailableError` map to their codes; an escaping exception → `internal_error`.
   - An archived artifact can be verified.
3. `tests/unit/test_tools_read.py`, then `read.py`:
   - **AC-74:** verified by X, updated by Y → true, `tier` unchanged; verified again → false; never
     verified → false; verified after the latest revision → false.
   - Never revised with a verification backdated before `generated.at` → false; `verified.at` equal to
     `revised.at` → false; a newer entry followed by an older backdated one → the maximum decides; a
     stored `+02:00` entry compared against a `Z` `revised.at` as instants
     (brainstorming-2026-09-17-okf-v02-adoption D19).
   - Absent annotation → `verified: []`, flag false; corrupt payload → `corrupt_metadata` naming
     `verified`, message without the payload; a gate-denied foreign artifact issues no `verified` GET
     (spy); an admitted foreign reader receives both keys; the read issues no put (spy).
4. `tests/unit/test_tools_write.py`, then `write.py` (if changed): an update carries `verified`
   byte-identical; a competing re-PUT injected between attempts keeps the ordered union; a corrupt
   payload → `corrupt_metadata` with no PUT; a failed restore records `verified` in the failure entry.
5. `tests/unit/test_tools_archive.py`, `test_tools_lifecycle.py` and `test_tools_reconcile.py`, then
   the files they gate if changed: `verified` byte-identical after archive and `set_artifact_status`
   (replacing T82's stand-in with the real name); a failure entry's copy restored by ordered union;
   reconcile adds no entry.
6. `tests/unit/test_tools_write_artifacts.py` and `test_server.py`, then `write_artifacts.py` and
   `server.py`: a `verified` descriptor key fails only its entry naming the tool; through
   `fastmcp.Client(_app)`, `verified` on `create_artifact` / `update_artifact` returns
   `validation_error` naming `add_artifact_verification` without awaiting the inner function; the new
   tool is registered and forwards its arguments.

**Moto.** T80's annotation self-mock in `tests/unit/conftest.py` covers every call here (named put
and get, `NoSuchAnnotation`, 412 on a stale object ETag, wipe on re-PUT). No conftest change.

**Mutation.** `annotations.py` is in `only_mutate`. Run `uv run mutmut run` alone after the unit
suite is green, clear `__pycache__`, and triage survivors against the known equivalent classes.

**Integration tests.** None break: `tests/integration/test_tools_read.py` checks field membership,
not an exact key set, and no integration test pins the set of annotations on an object. Add
`tests/integration/test_tools_verification.py`: against real AWS, create, verify, update (a real
re-PUT wipes and restores `verified`), read → the list is intact and the flag true; verify again →
false; the object ETag is unchanged across each verification.

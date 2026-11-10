---
type: Spec
id: p15-t79-provenance
title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
description: Replaces the date and author_role fields with OKF provenance. generated {by, at} is required on create, written once and carried forward by every update; revised {by, at} is absent until the first update and moves only on a content write. Both are stored as flat keys in S3 object metadata and vector metadata and returned as nested blocks. A generated tier-2 id anchors on the UTC day of generated.at. Timestamps are offset-aware ISO 8601, normalised to UTC with a Z suffix and compared as parsed datetimes. date, author_role and timestamp are rejected with a validation_error naming the replacement.
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
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: spec-t76
    resource: docs/specs/p15-t76-archived-boolean.md
    title: T76 — Archive Marker status → archived (bool)
    last_modified: 2026-10-13T15:57:36Z
  - id: spec-t77
    resource: docs/specs/p15-t77-open-type-list.md
    title: T77 — Open Type List
    last_modified: 2026-10-13T13:04:34Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T13:02:46Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-s3vectors
    resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
    last_modified: 2026-09-04T00:00:00Z
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
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-list
    resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-search
    resource: docs/contracts/modules/arkeology.tools.search.md
    title: arkeology.tools.search
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-synthesise
    resource: docs/contracts/modules/arkeology.tools.synthesise.md
    title: arkeology.tools.synthesise
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-link-metadata
    resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-freshness
    resource: docs/contracts/modules/arkeology.tools.freshness.md
    title: arkeology.tools.freshness
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-studio
    resource: docs/contracts/modules/arkeology.tools.studio.md
    title: arkeology.tools.studio
    last_modified: 2026-09-06T00:00:00Z
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format — Specification
  - id: producer-okf-frontmatter
    resource: https://github.com/amanoxsolutions/amanox-ai-agents/blob/main/plugins/amanox/skills/authoring-skills/references/okf-frontmatter.md
    title: OKF frontmatter reference of the producer amanox-ai-agents plugin
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
  - to: p15-t78-create-update-split
    type: builds_on
  - to: p15-t76-archived-boolean
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T16:20:20Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T21:24:53Z
---

# T79 — Provenance: `generated` / `revised`; Drop `date`, `author_role`, `timestamp`

## TL;DR

Every artifact records who first wrote it and when (`generated`) and, once it has been updated, who
last revised it and when (`revised`): both are OKF `{by, at}` blocks supplied by the writer and kept
in both stores. `generated` is written once at create and carried forward by every update, and
`revised` moves only on an update, never on a link backfill, archive or reconciliation. `date` and
`author_role` are removed and rejected, and a generated tier-2 id now anchors on the UTC day of
`generated.at` (D9, D19, D32, D35).

## Open Questions

1. **Non-blocking — no task owns the `commit_refs` cap re-calibration.** ADR-017 `## Consequences`
   requires re-running it when the filterable key mix changes. T76 shrank the mix, T79 adds about
   160 bytes, and T81 adds lifecycle `status`, which completes the mix. *Recommended:* the plan's
   T81 entry gains "re-run the calibration against the final key mix". The margin is 20 entries
   against a measured 36, about 4 entries for T79's keys, so the cap is expected to hold.
2. **Non-blocking — import fidelity of `revised`.** Following the plan, create writes no `revised`.
   A producer document already revised in Git therefore imports with only `generated`, and its
   frontmatter `revised` stays in the content. One false negative follows. Suppose a citing
   document captured the source between the source's first authorship and its Git revision. At
   import, the source's effective time is its `generated.at`, so the citing document reads as
   fresh until the source's next update. *Recommended:* keep T79 as planned, and let T88, which
   owns import fidelity, decide whether `create_artifact` should accept an optional `revised` for
   migration.
3. **Non-blocking — stale rationale in plan.md's T90 entry.** "so a later overwrite of a tier-2
   artifact regenerates the key already stored" predates T78. An update re-derives nothing
   (ADR-017 §9). The rule itself still holds, for AC-04's create collision. *Recommended:* reword
   that clause when T90 is specced.

## 1. Problem Statement

Arkeology's `date` mixes two meanings. On a tier-2 artifact it is the authorship day, and on an
overwritten tier-3 artifact it is in practice the day of the last update. `author_role` holds a
role name, or an actor string that every write overwrites. Neither says who first wrote the
artifact, or when it last changed. OKF v0.2 documents now carry exactly that as `generated` and
`revised`, and T86's per-source freshness needs a revision time that only content writes move
(ADR-017 `## Decision`, "3. Provenance"; FR-69). The house fields go, with no aliases (D42).

All six user stories are P1: create records first authorship; a tier-2 id anchors on the UTC day of
`generated.at`; update records the latest revision and keeps first authorship; nothing else moves
provenance; readers see provenance, and corrupt values are reported; removed names are rejected, not
aliased.

## 2. Rules — Input

### R1 — `create_artifact` requires a `generated` block and `update_artifact` a `revised` block, each with a required `by` and an optional `at`

When `create_artifact` is called, the system must require a `generated` block with a required `by`
and an optional `at`, and must reject any other key in the block. When `update_artifact` is called,
the system must require a `revised` block of the same shape. Bulk descriptors carry the same block
under the same key.

**Why:** Each block is set by the writer (D35). FR-01 requires the writer's identity, so `by` is
required.

Source: FR-01, FR-75; D9, D35

### R2 — `by` is accepted only as an OKF §7 actor, stored verbatim

The system must accept `by` only as an OKF §7 actor, stored verbatim and never split or normalised.
The accepted forms are `human:<id>` or `process:<id>` with a non-empty id, or
`<producer>/<version>` with a non-empty producer containing no `/` and a non-empty version. When
`by` has none of these forms, has leading or trailing whitespace, or contains a control character,
the system must return `validation_error` naming the field.

**Example**

- Given a create whose `by` is `"developer"`, then it is rejected with `validation_error` naming the
  field, and nothing is written.

**Why:** The actor-form check exists to reject role names left over from `author_role`, and because
OKF §5.3 trust classification keys on the `human:` prefix.

Source: FR-01, FR-75; D9, D35

### R3 — A supplied `at` must parse as ISO 8601 with a UTC offset, and gets no ordering or future-time check

When `at` is supplied, the system must parse it as ISO 8601. When it does not parse, or parses
without a UTC offset (a bare date included), the system must return `validation_error` naming the
field. It must never assume UTC for such a value. No ordering check runs against the stored
`generated.at` or the previous `revised.at`, and future times are not rejected.

**Example**

- Given a create whose `generated.at` has no UTC offset, then it is rejected with `validation_error`
  naming the field, and nothing is written.

**Why:** Offset-naive input is rejected, not assumed UTC. OKF §5 requires an explicit offset, and
ADR-017 `### 10` treats a naive value as unreadable on the freshness side. Accepting a naive value at
write time would store exactly what the reader must refuse. Assuming UTC would silently shift the
instant, and could move the tier-2 anchor day.

**Why:** `generated` can never be rewritten, so an ordering rule would leave an artifact with a
mistyped `generated.at` unable to accept any update. A backdated `revised.at` is the owner's own
statement about its own document, under the write authority that could equally withhold the update.

Source: FR-01, FR-75; D9, D35

### R4 — An accepted `at` is stored converted to UTC and truncated to whole seconds; an omitted `at` takes the system's own clock

The system must store an accepted `at` converted to UTC, truncated to whole seconds, as
`YYYY-MM-DDTHH:MM:SSZ`. When `at` is omitted, the system must use its own clock in the same form.

**Example**

- Given a create with `generated: {by: "axians-developer/claude-opus-5.5"}` and no `at`, when it
  succeeds and is read, then `generated.by` is that string, `generated.at` is the server's UTC
  write time in the form `YYYY-MM-DDTHH:MM:SSZ`, and `revised` is `null` (FR-09, FR-69).
- Given a create with `generated.at: "2026-03-01T14:30:00+02:00"`, when it is read, then
  `generated.at` is `"2026-03-01T12:30:00Z"`.

**Why:** `at` is optional. A caller may supply it because migration must record a first-authorship
time from the past (T88, T90). It also matters because the producer `amanox-ai-agents` plugin
captures `sources[].last_modified` from its own `revised.at`. If the server stamped its own later
time on an update, every document citing the source would report stale permanently. Without `at`,
the server stamps its clock, so AC-72's "Y's write time" holds.

**Why:** Seconds precision, truncated. The producer writes `date -u +%Y-%m-%dT%H:%M:%SZ`, so a
producer-supplied value is stored byte-identical to the document's own frontmatter. Truncation
never moves a time forward. Two updates of a source within one second are indistinguishable to
freshness. This is accepted.

Source: FR-01, FR-75; D9, D35

### R5 — Each artifact write resolves its block once

Each artifact write resolves its block once. The same value is used for the key, both stores and
every compare-and-swap retry.

Source: FR-01, FR-75; D9, D35

### R6 — The block, actor and `at` checks all run before any storage call; the metadata budget check covers the new keys

The block, actor and `at` checks must all be made before any storage call. The metadata budget check
(FR-59) covers the new keys, because it measures the assembled dicts.

Source: FR-01, FR-75; D9, D35; FR-59

## 3. Rules — Storage

### R7 — Both stores hold provenance as four flat string keys named alike, all filterable vector metadata

S3 object metadata and every vector's metadata use four flat string keys named alike:
`generated_by`, `generated_at`, `revised_by` and `revised_at`. Responses nest them as OKF blocks.
All four keys must be filterable vector metadata. `author_role` must stay in
`NON_FILTERABLE_METADATA_KEYS`, unwritten, because the index slot stays declared (C-01).

**Why:** Persisted encoding: ADR-017 `## Deferred to the Specs` leaves this to the data contracts,
and it is set here. Flat scalars match every other metadata key and stay individually filterable. A
JSON string per block was rejected: it would need a parse on every read, and it would be
percent-encoded a second time as an S3 header.

Source: FR-09, C-01; D35

### R8 — Create writes `generated_by` and `generated_at` to both stores, and no `revised_*`, `date` or `author_role` key

When an artifact is created, the system must write `generated_by` and `generated_at` to S3 object
metadata and to every vector's metadata as strings, and must write no `revised_*`, `date` or
`author_role` key.

**Why:** Create writes no `revised`. The plan entry is explicit: absent until the first update. See
Open Questions, item 2, for the import consequence.

Source: FR-09, C-01; D35

### R9 — Update writes `revised_by` and `revised_at`, and copies `generated_by` and `generated_at` byte-for-byte from the same compare-and-swap attempt

When an artifact is updated, the system must write `revised_by` and `revised_at` from the resolved
block. It must copy `generated_by` and `generated_at` byte-for-byte from the object metadata read in
the same compare-and-swap attempt. This replaces T78's `date` carry-forward and removes
`author_role` from T78's list of replaced fields.

**Example**

- Given an artifact created by X, when Y updates it with `revised: {by: Y}`, then `generated` still
  names X at the original time, and `revised` names Y at Y's write time (FR-69).
- Given a second update by Z, then `revised` names Z only. It is a single block, not a list.

Source: FR-09, C-01; D35

### R10 — An update whose stored `generated` is missing or unreadable returns `corrupt_metadata`; an unreadable stored `revised` does not block it

When the compare-and-swap attempt's stored `generated` is missing or unreadable, the system must
return `corrupt_metadata` and write nothing (D50, case 1). A stored `revised` that cannot be read
does not block an update, because the update replaces it.

Source: FR-09, C-01; D35; D50 (case 1)

## 4. Rules — Identity

### R11 — A generated tier-2 id anchors on the UTC calendar day of the resolved `generated.at`

When a tier-2 id is generated, the system must use the UTC calendar day of the resolved
`generated.at` where it used `date`. The formula, the hash suffix and tier-3 ids are unchanged. The
create path, the `create_artifacts` duplicate pre-flight and the `migrate_artifacts` existence probe
must each use the same resolved value they then write.

**Example**

- Given a tier-2 artifact created with `generated.at` `2026-10-12T23:59:59Z`, when the same type and
  title are created again with `2026-10-13T00:30:00+02:00`, the same UTC day, then the second
  create is rejected with `validation_error` and exactly one artifact remains (AC-04).
- Given the same type and title created with `2026-10-13T00:30:00Z`, a different UTC day, then a
  second artifact is created.
- Given two titles of the same type and first-authorship day that differ only in punctuation,
  beyond the length cutoff, or in non-Latin script, then both get distinct ids (AC-64).

**Why:** The tier-2 anchor is the UTC day; this confirms the ADR default. The same instant always
yields the same key, whoever wrote it and in whatever time zone (D32 as amended). Anchoring on the
producer's local day would give two keys for one instant, and the UTC normalisation of an accepted
`at` already discards the offset.

Source: FR-08, AC-04, AC-64; D32

### R12 — Provenance never moves an id

An update never re-derives a key (T78), so provenance never moves an id.

Source: FR-08, AC-04, AC-64; D32

## 5. Rules — Never moved by non-content operations

### R13 — `archive_artifact` and `link_metadata` carry all four keys forward unchanged in both stores

`archive_artifact` and `link_metadata` must carry all four keys forward unchanged in both stores.
They already copy metadata whole, and T79 proves this with tests.

**Example**

- Given an artifact updated by Y, when a link backfill, an archive and a reconciliation then touch
  it, then `generated` and `revised` are byte-identical in S3 and in every vector (AC-72).

Source: FR-17, FR-69, AC-72; D19

### R14 — A `reconcile_index` rebuild copies the four keys verbatim from S3 without reading a clock, and fails an artifact whose stored provenance is unreadable

When `reconcile_index` rebuilds vectors, on either the orphan path or the failure-log path, the
system must copy the four keys verbatim from S3 object metadata and must not read a clock. When the
S3 `generated` is unreadable, or `revised` is present but unreadable, the system must write no
vectors for that artifact and report it under `failed` with a reason naming the field. This is the
same treatment T76 gives `archived`.

Source: FR-17, FR-69, AC-72; D19

### R15 — `last_edited_ulid` is unchanged, and neither it nor `revised.at` is derived from the other

`last_edited_ulid` stays the internal token for archive's compare-and-swap, reconcile's ordering,
the failure-log supersession check and `if_match`. `revised.at` is never derived from it, nor it
from `revised.at`, so the two may differ when a caller supplies `at`. Search's ULID-derived
`last_edited_at` stays as it is.

Source: D19

## 6. Rules — Read surfaces

### R16 — `read_artifact`, `list_artifacts`, `search_artifacts` and `synthesise_artifacts` return `generated` and `revised` (`null` when absent), and no `date` or `author_role`

When `read_artifact`, `list_artifacts`, `search_artifacts` or `synthesise_artifacts` returns an
artifact, the system must include `generated: {by, at}` and `revised: {by, at}`, or
`revised: null` when it is absent, using the stored strings. It must include no `date` or
`author_role`.

**Example**

- Given any artifact, when it is read, listed, searched or synthesised, then each entry carries
  `generated` and `revised`, and carries no `date` or `author_role`.

**Why:** Absent `revised` is returned as `null` rather than omitted, matching the house rule that
summary keys are always present (`author_role` was `null` when unset).

Source: FR-09, FR-69; D50

### R17 — When stored provenance is absent or unreadable

`generated` is unreadable when either key is missing or empty, or when `at` does not parse to an
offset-aware datetime. `revised` is absent when both keys are missing, and unreadable when only
one is present or its `at` does not parse.

Source: FR-09, FR-69; D50

### R18 — An unreadable value makes `read_artifact` return `corrupt_metadata` and listings skip and count the artifact, after the cross-scope gate

When a value is unreadable, `read_artifact` must return `corrupt_metadata` naming the field,
echoing the raw value only to an own-scope reader (D50, case 5). Listings must skip the artifact
and count it under `skipped_malformed_count`. The cross-scope gate still runs first.

**Example**

- Given a stored `generated` that is missing or unparseable, then `read_artifact` returns
  `corrupt_metadata` naming `generated`, and a listing skips the artifact and counts it under
  `skipped_malformed_count` (ADR-017 `### 10. Malformed values in the new fields`).

Source: FR-09, FR-69; D50 (case 5)

## 7. Rules — Freshness and Studio

### R19 — `check_synthesis_freshness` stops reading `date`, and a source is not reported stale when either side lacks a `last_edited_ulid`

`check_synthesis_freshness` must stop reading `date`. When either side of a staleness comparison
lacks a `last_edited_ulid`, the source must not be reported stale. T86 replaces the comparison.

Source: FR-20, FR-48; D19

### R20 — Studio and the `arkeology_studio` text fallback order artifacts by parsed effective revision time, newest first

Studio and the `arkeology_studio` text fallback must order artifacts by their effective revision
time, which is `revised.at` and otherwise `generated.at`, compared as parsed instants, newest
first. An unparseable value sorts last. A list row shows the UTC day of the effective time. The
detail view shows a `generated` day pill, and a `revised` day pill when one exists.

Source: FR-20, FR-48; D19

## 8. Rules — Removed names

### R21 — Removed names are rejected with `validation_error` naming the replacement, not aliased

T79 must add these rows to T78's per-tool removed-name table in `server.py` ("How removed names
are rejected"):

| Tool | Name | Replacement named |
|---|---|---|
| `create_artifact` | `date`, `timestamp` | `generated.at` |
| `create_artifact` | `author_role` | `generated.by` |
| `update_artifact` | `date`, `timestamp` | `revised.at` |
| `update_artifact` | `author_role` | `revised.by` |
| `update_artifact` | `generated` | `revised` (`generated` is written once at create and carried forward) |

When a `create_artifacts` or `update_artifacts` descriptor carries one of those keys for its kind,
the system must fail that entry with the same `validation_error`. `migrate_artifacts` inherits this
through its delegation to `create_artifacts`, as it does for T76's `status`.

**Example**

- Given a caller passing `date`, `author_role` or `timestamp` to a write tool, or `generated` to an
  update tool, as an argument or a bulk-descriptor key, then the call or entry returns
  `validation_error` naming the replacement (AC-80; D42).

**Why:** `timestamp` gets rows although it was never a parameter. AC-80 names it. The write tools
are where a caller still holding OKF v0.1 frontmatter would send it, and a row costs nothing.

Source: AC-80; D42

## 9. Rules — Hooks for later tasks

### R22 — T79 makes the resolved block available at both revision-history points and writes no history

T80 appends the resolved block to the revision history: `generated` at create's annotation write,
and `revised` inside update's compare-and-swap cycle after the object write lands. T79 makes the
resolved block available at both points and writes no history. T84's D40 fill-in and T86's
freshness read `revised.at`, falling back to `generated.at`, through T79's parser.

Source: none attached — decided in this spec

## 10. Boundaries

**Always:**
- Compare timestamps as parsed, offset-aware datetimes, never as strings (D19).
- Use one parser, one formatter and one actor check, all in `artifact.py`, from every write path,
  read path, reconcile and the Studio fallback.
- Keep provenance byte-identical across archive, link backfill and reconcile.
- Keep the `public` / `_inner` pattern with `try/except Exception`, and log to stderr only.

**Ask First:**
- Returning `generated` or `revised` in create or update responses.
- Changing the stored precision or format.

**Never:**
- Read `date` or `author_role` as a fallback for missing provenance, or translate them anywhere,
  including reconcile (D42; T90 migrates).
- Write `revised` on create, or move it on any path other than an update.
- Remove `author_role` from `NON_FILTERABLE_METADATA_KEYS`, or change the index.
- Remove the failure-log entry's own `timestamp` key. It is the entry's time, not the artifact field.
- Build the revision-history annotation or append helper (T80), `verified` (T83), lifecycle change
  (T82), per-source freshness (T86) or supplied ids (T87).
- Re-run the `commit_refs` cap calibration (Open Questions, item 1).
- Rewrite the schema resource beyond the provenance rows (T89), or edit README, SERVER-REFERENCE,
  CHANGELOG or AGENTS.md (T91).

## 11. For the developer agent

### Files to Touch

T79 lands after T76 and T78 (plan: blocked by 76 and 78), so it edits their result.

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/artifact.py` | Modify | Add the strict timestamp parser (offset-aware or `None`), the canonical UTC formatter, the actor check, the block resolver and the stored-provenance reader. `Artifact` loses `date` and `author_role`. `generate_artifact_id` keeps its `date` parameter, which now means the anchor day. Its docstring says "UTC day of `generated.at`". `references.py` still passes a day (T88) |
| `src/arkeology/failure_log.py` | Modify | `build_failure_entry` drops `date`. Its own `timestamp` key stays. Nothing reads the field |
| `src/arkeology/tools/write.py` | Modify | Create: resolve `generated`, anchor the key, write two keys. Update: resolve `revised` once before the CAS loop, carry `generated` from each attempt's re-read, return `corrupt_metadata` on an unreadable value. Drop `date` and `author_role` everywhere, including failure-entry calls |
| `src/arkeology/tools/write_artifacts.py` | Modify | `_REQUIRED_FIELDS`: `generated` replaces `date` for create, and `revised` is required for update. Resolve once per descriptor before the duplicate pre-flight. Reject the removed descriptor keys |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Resolve `generated` once per descriptor, then probe the candidate key and delegate with the same resolved block |
| `src/arkeology/tools/read.py` | Modify | Response provenance, `corrupt_metadata` |
| `src/arkeology/tools/_search_helper.py` | Modify | `build_artifact_summary` returns provenance and returns `None` when it is unreadable. This covers list, search and synthesise |
| `src/arkeology/tools/reconcile.py` | Modify | Copy the four keys in the rebuild and fail the artifact when they are unreadable. Drop `date` and `author_role` from the rebuild and from failure entries |
| `src/arkeology/tools/archive.py`, `link_metadata.py` | Modify | Remove only the `date` argument to `build_failure_entry` |
| `src/arkeology/tools/freshness.py` | Modify | Delete the `date` fallback in Step 7 and update its comment |
| `src/arkeology/tools/studio.py` | Modify | Sort the fallback by parsed effective revision time |
| `src/arkeology/static/arkeology-studio.html` | Modify | `buildRow`, `renderList` sort, `selectArtifact` pills |
| `src/arkeology/resources.py` | Modify | Schema rows: `generated` and `revised` replace `date` and `author_role`. Tiers text: tier-2 key `{date}` is the UTC day of `generated.at` |
| `src/arkeology/server.py` | Modify | `create_artifact` / `update_artifact` signatures and docstrings (blocks replace `date` and `author_role`), plus the removed-name rows |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | *Uncertain location:* descriptors sent to `migrate_artifacts` carry `generated: {by: "process:migrating-to-arkeology", at: "<date>T00:00:00Z"}` instead of `date`. The manifest keeps `date`. Interim until T88 prefers the frontmatter `generated`. The day is unchanged, so ids are unchanged |
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Modify | Step 3: compute a listed entry's bare id from the UTC day of its `generated.at` rather than `date`. T76 and T77 also edit this file |
| Tests | Modify / Create | See Testing Approach |

### Contracts

Amend these before writing tests (plan.md `## Phase 15`, TDD rule):

- **`data/s3.artifact.md`** — `## Storage Shape`: delete the `date` and `author_role` rows. Add
  `generated_by` and `generated_at` (required) and `revised_by` and `revised_at` (both present or
  both absent; absent until the first update). `at` values are in the canonical form. Remove
  "falling back to the subject `date`" from the `last_edited_ulid` row. `### generate_artifact_id`:
  `date` is the UTC calendar day of `generated.at`. `## Compatibility Guarantees`: `generated` is
  never rewritten; `revised` moves only on an update; timestamps are compared parsed, never as text.
- **`data/s3vectors.artifact.md`** — The same rows, as filterable `str` values. `author_role` stays
  a declared, unwritten non-filterable slot. Note that the filterable key mix changed.
- **`modules/arkeology.tools.write.md`** — `### create_artifact`: the `generated` block replaces
  `date` and `author_role`, with `validation_error` causes for the block, the actor, a naive or
  unparseable `at`, and removed names. `### update_artifact`: the `revised` block is required.
  `generated` is carried forward in place of `date`. `corrupt_metadata` now also covers an
  unreadable `generated`. `generated` passed as an argument is rejected.
- **`arkeology.tools.write_artifacts.md`**, **`arkeology.tools.migrate_artifacts.md`** — The
  descriptor fields change as above. There is one resolution per descriptor, reused for the key and
  the write. Removed keys fail the entry.
- **`arkeology.tools.read.md`**, **`.list.md`**, **`.search.md`**, **`.synthesise.md`** — Entries
  carry `generated` and `revised` (or `null`). Unreadable provenance joins the `corrupt_metadata`
  and malformed-skip causes.
- **`arkeology.tools.archive.md`**, **`.link_metadata.md`** — New invariant: provenance is carried
  unchanged, and `revised` never moves.
- **`arkeology.tools.reconcile.md`** — The rebuild copies provenance verbatim and never stamps it.
  Unreadable provenance fails the artifact (FR-17).
- **`arkeology.tools.freshness.md`** — Replace the `date` fallback invariant with "not stale when
  either side lacks a `last_edited_ulid`".
- **`arkeology.tools.studio.md`** — The fallback order is effective revision time (parsed)
  descending, then `artifact_id` ascending.
- **`design/arkeology-studio-tokens.html`** — Wording only: "date" becomes the effective revision
  day, in the list meta and the sort-order notes.

### Testing Approach

**TDD order** (each test file is red before the implementation file it gates). No file in the
mutation `only_mutate` scope is touched, so no mutation run is required.

1. `tests/unit/test_artifact.py`, then `artifact.py`:
   - The parser accepts `Z`, `+02:00` and fractional seconds, and normalises
     `2026-10-13T12:00:00.9+02:00` to `2026-10-13T10:00:00Z`. It rejects naive values, bare dates
     and garbage.
   - The actor check accepts `axians-pm/unknown`, `human:Matthieu Lienart`, `human:Zürich` and
     `process:x`. It rejects `developer`, `human:`, `/v1`, `p/`, ` human:x` and a control
     character.
   - The anchor: `2026-10-13T00:30:00+02:00` gives `2026-10-12`.
   - The AC-64 cases are re-parameterised on the anchor day.
2. `tests/unit/test_failure_log.py`, then `failure_log.py`: the entry has no `date` and still has
   `timestamp`.
3. `tests/unit/test_tools_write.py`, then `write.py`:
   - Create writes two keys to both stores and no `revised_*`, `date` or `author_role` (R2–R4, R8).
   - An omitted `at` is canonical and inside the test's time window.
   - An invalid block, actor or `at` gives `validation_error` with no `put_object` (spy).
   - The AC-04 same-UTC-day and different-day pairs (R11).
   - An update writes `revised` and keeps `generated` byte-identical. A second update replaces
     `revised` (R9).
   - A stored `generated` with a naive `at` gives `corrupt_metadata` and nothing written. A stored
     `revised` with a half-present value is replaced.
   - An oversized `by` gives `validation_error` (FR-59).
   - `revised.at` is identical across a forced CAS retry.
   - **AC-72 composite:** create by X, update by Y, `link_metadata`, `archive_artifact`,
     `reconcile_index`. Then the S3 and vector provenance equal the post-update values.
4. `tests/unit/test_tools_write_artifacts.py`, then `write_artifacts.py`: removed descriptor keys
   fail only their entry, naming the replacement. Two descriptors with the same title and no `at`
   are caught as duplicates.
5. `tests/unit/test_tools_migrate_artifacts.py`, then `migrate_artifacts.py`: the probed key equals
   the written key when `at` is omitted (spy). A `date` descriptor is rejected.
6. `tests/unit/test_tools_read.py`, then `read.py`: the shape, `revised: null`, and
   `corrupt_metadata` for missing, naive and half-present values. A foreign-scope message carries
   no raw value.
7. `tests/unit/test_tools__search_helper.py`, `test_tools_list.py`, `test_tools_search.py` and
   `test_tools_synthesise.py`, then `_search_helper.py`: summaries carry provenance, and unreadable
   provenance is skipped and counted.
8. `tests/unit/test_tools_archive.py` and `test_tools_link_metadata.py`, then `archive.py` and
   `link_metadata.py`: provenance is unchanged in both stores (AC-72 legs).
9. `tests/unit/test_tools_reconcile.py`, then `reconcile.py`:
   - The orphan path and the failure-log path copy all four keys verbatim.
   - Unreadable provenance gives an entry in `failed` and no vectors.
   - A legacy `date` is never read.
10. `tests/unit/test_tools_freshness.py`, then `freshness.py`: a later `date` with no ULID is not
    reported stale.
11. `tests/unit/test_tools_studio.py`, then `studio.py`: `revised` outranks `generated`; a `+02:00`
    value orders by its instant; an unparseable value sorts last.
12. `tests/static/studio-provenance.test.js` (new, using the `extractBlock` approach), then
    `arkeology-studio.html`: the sort comparator and the day label.
13. `tests/unit/test_resources.py` and `test_server.py`, then `resources.py` and `server.py`: the
    schema rows, and every AC-80 row through `fastmcp.Client(_app)` with the inner function not
    awaited.
14. `test_skill_artifact_id_drift.py` is unchanged: the formula is unchanged. Integration updates
    follow.

**Integration tests this change breaks** (update in this task, per plan.md):
- Replace the `date` / `author_role` kwargs and descriptor keys with `generated` in:
  `test_tools_write.py`, `test_tools_write_artifacts.py`, `test_tools_migrate_artifacts.py`,
  `test_tools_read.py`, `test_tools_list.py`, `test_tools_search.py`, `test_tools_synthesise.py`,
  `test_tools_archive.py`, `test_tools_purge.py`, `test_tools_delete.py`, `test_tools_freshness.py`,
  `test_tools_link_metadata.py`, `test_tools_reconcile.py`, `test_tools_propose_commit_links.py`,
  `test_tools_studio.py` and `test_calibration_per_artifact_vector_lookup.py`.
- `test_tools_read.py`: in the expected-field list, `date` and `author_role` become `generated` and
  `revised`.
- `test_calibration_vector_metadata_budget.py`: the modelled filterable dict replaces `date` with
  the four provenance keys. Do not re-run the calibration.
- `test_tools_reconcile.py`: drop `date` from the hand-built failure entry and keep `timestamp`.
- `test_tools_freshness.py`: its date-based staleness case still fails until T86.
- **Add** to `test_tools_write.py` a real-AWS round trip of a non-ASCII `human:` actor and an
  offset-bearing `at` through S3 header encoding and vector metadata. Then update and archive, and
  check that the read provenance is unchanged.

### Hand-offs

- **AC-72 hand-offs:** the verification leg of AC-72 belongs to T83, and the lifecycle-change leg of
  FR-69 to T82. Each plan entry already requires "no `revised` change". Each extends the AC-72
  composite test in TDD order item 3 above.

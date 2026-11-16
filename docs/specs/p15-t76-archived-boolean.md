---
type: Spec
id: p15-t76-archived-boolean
title: T76 — Archive Marker status → archived (bool)
description: Renames Arkeology's archive marker from status (active/inactive) to archived (bool) in S3 object metadata, vector metadata, every tool parameter, response field and filter expression, Studio's facet and the data resources; deletes ArtifactStatus; makes reconcile_index detect and repair vectors whose archived is missing or not a boolean; and rejects the old status parameter, so the status key is free when OKF lifecycle status lands in T81.
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
  - id: adr-sentinel
    resource: docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md
    title: The status="all" Sentinel as a Cross-Tool Convention for Query-Shaped Tools
    last_modified: 2026-09-25T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
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
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-purge
    resource: docs/contracts/modules/arkeology.tools.purge.md
    title: arkeology.tools.purge
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-delete
    resource: docs/contracts/modules/arkeology.tools.delete.md
    title: arkeology.tools.delete
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-freshness
    resource: docs/contracts/modules/arkeology.tools.freshness.md
    title: arkeology.tools.freshness
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-resources
    resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-link-metadata
    resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
    last_modified: 2026-09-06T00:00:00Z
  - id: aws-s3vectors-filtering
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html
    title: S3 Vectors — Metadata filtering
  - id: spec-t92
    resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T14:38:17Z
  - id: spec-t90
    resource: docs/specs/p15-t90-store-migration.md
    title: T90 — Store Migration Skill and Command
    last_modified: 2026-11-12T14:38:17Z
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-08-12-status-all-sentinel-convention
    type: constrained_by
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T15:57:36Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-16T10:34:57Z
verified:
  - by: "human:mlnrt"
    at: 2026-11-15T11:12:39Z
---

# T76 — Archive Marker `status` → `archived` (bool)

## TL;DR

Arkeology's archive marker moves from `status` (`active` / `inactive`) to `archived` (a boolean)
in both stores and in every tool parameter, response field, filter expression, the Studio facet
and the data resources. `ArtifactStatus` is deleted, and `reconcile_index` repairs any vector whose
`archived` is missing or not a boolean (brainstorming-2026-09-17-okf-v02-adoption D50). T76 lands
before T81, so once it ships no code path writes, filters on or returns a `status` key, and the key
is free for the OKF lifecycle (brainstorming-2026-09-17-okf-v02-adoption D21).

## 1. Problem Statement

Today one key, `status`, records whether Arkeology has archived an artifact. OKF v0.2 documents
carry their own `status` (`draft | stable | deprecated`), which T81 ingests. If both existed, a
`read_artifact` payload would hold `status: active` in the metadata and `status: stable` in the
content. Code could tell them apart, but an agent reading the payload could not (ADR-017
`## Context` > `### Forces`). The archive marker is a yes/no fact, so it becomes a boolean named for
what it records. It must ship alone and first, so that `status` never means two things in one
release (plan.md `## Phase 15`, Ordering).

Six user stories frame this spec, all P1: archiving is a boolean, filtered with three
states; no `status` key in data the server writes or returns; purge, delete and freshness key on
`archived`; humans see the same default view; vectors with a missing or non-boolean `archived`
are repaired; the old parameter is rejected, not aliased.

## 2. Rules — Storage

### R1 — `archived` is stored as an exact string in S3 and a native boolean in vectors, never as `status`

When any path writes an artifact's metadata, it stores `archived` as follows and writes no
`status` key:

| Store | `archived` |
|-------|------------|
| S3 object metadata | exactly the string `"true"` or `"false"` (the exact lowercase strings) |
| Vector metadata | a native boolean, in filterable metadata |

No index change is needed: keys are filterable by default (ADR-017 `## Consequences`,
"No re-index").

**Why:** ADR-017 `## Deferred to the Specs` leaves the persisted encodings to the data contracts,
and they are set here. S3 object metadata holds strings because S3 user metadata is string-only.
Vector metadata holds a native boolean, which S3 Vectors supports and filters with `$eq` (AWS S3
Vectors metadata filtering documentation).

Source: FR-09, brainstorming-2026-09-17-okf-v02-adoption D21, D50, aws-s3vectors-filtering

### R2 — Creating an artifact writes `archived` false and takes no archive marker

When an artifact is created (`create_artifact`, including through the bulk and migrate tools),
`archived` is written false in both stores. Create takes no archive
marker: the `status` parameter is removed from create rather than renamed, and its AC-80 row
names `archive_artifact`.

**Why:** ADR-017 §2 names `archive_artifact` as the owner of `archived`, and FR-14 lists archiving
as a post-write operation. T78's update already carries the marker forward instead of accepting
it. If create also accepted it, there would be a second writer of the marker outside archive's
partial-failure and idempotency machinery. No caller needs to create an artifact that is already
archived; the one test that does so writes and then archives.

Source: FR-09, brainstorming-2026-09-17-okf-v02-adoption D21, D50, FR-14, ADR-017 §2, AC-80

### R3 — `archived` is read back strictly, and any other value is uninterpretable

When reading `archived` back, only `"true"` / `"false"` (case-sensitive) are accepted from S3
object metadata, and only a native boolean from vector metadata. Any other value, including
absence, is uninterpretable. It is never defaulted, and it is never derived from a legacy
`status` key.

**Why:** a tolerant parser (`"True"`, `"1"`) would be a second encoding that nothing writes.

Source: FR-09, brainstorming-2026-09-17-okf-v02-adoption D21, D50

### R4 — No `status` key in artifact data after T76

After T76, no code path writes, filters on or returns a `status` key for artifact data. A store
written or migrated after T76 therefore holds none. `health_check`'s per-component `status` is a
different field and is unchanged.

**Example**

- Given any artifact written after T76, when it is read, listed, searched or synthesised, then
  each entry carries `archived` as a JSON boolean and carries no `status` key. Its S3 object
  metadata and vector metadata hold `archived` and no `status`.

Source: None

### R23 — No server runs on an own scope still in the earlier shape; another team's not-yet-migrated artifacts are malformed foreign data

This release reads `archived` and never falls back to a legacy `status` (R4). WHEN the server's own
write prefix still holds an artifact written before T76 THE SYSTEM SHALL refuse to start, naming the
store migration to run. T90's store-shape startup check does this (T90 R34–R36) and ships in the
same release; T76 adds no check of its own. Another team's area, read through `READ_PREFIXES`, is
not checked. Until that team migrates, its artifacts carry no `archived` and follow the
malformed-data policy for foreign data: list, search, synthesis and Studio's default view leave
them out, because their filter asks for `archived` false; with `archived="all"` each is skipped and
counted under `skipped_malformed_count` (R8); and `read_artifact` returns `corrupt_metadata` naming
`archived` (R9).

**Example**

- Given an own scope holding an artifact that still carries `status: active` and no `archived`,
  when the server starts, then it exits before serving any request, with a message naming
  `arkeology-migrate-store` (T90 R35).
- Given a migrated own scope and a foreign read prefix still in the earlier shape, when an agent
  lists with `archived="all"`, then the foreign artifacts are absent and counted under
  `skipped_malformed_count`.

**Why:** a store this release cannot read is reported once, at startup, where the operator sees it.
Served anyway, every default view would come back empty, `read_artifact` would fail on every
artifact, `reconcile_index` would list every artifact under `failed`, and
`check_synthesis_freshness` would report `all_fresh: true` while checking nothing, which looks like
health. Another team's area is not checked because teams sharing a store may migrate at different
times (T90 "Shared stores"), and one team's lag must not stop another team's server.

Source: FR-07; brainstorming-2026-09-17-okf-v02-adoption D42, D50; refusing to start on a store not yet migrated (Operator, 2026-10-13; confirmed 2026-11-15)

## 3. Rules — Query

### R5 — `list_artifacts` and `search_artifacts` filter on a three-state `archived`, default `false`

`list_artifacts` and `search_artifacts` accept `archived: bool | Literal["all"] = False` with
three states, and AND the result with the scope filter exactly as the `status` clause is ANDed
today:

| `archived` | Clause added |
|------------|--------------|
| `false`, the default | `archived $eq false` |
| `true` | `archived $eq true` |
| `"all"` | no archived clause |

The schema advertises `anyOf: [boolean, {const: "all"}]`. JSON `null` is rejected as the "all"
spelling.

**Example**

- Given an artifact X that has been archived, when the caller lists or searches with default
  parameters, then X is not returned (AC-08).
- Given the same store, when the caller passes `archived=true`, then only archived artifacts are
  returned. When the caller passes `archived="all"`, archived and non-archived artifacts are both
  returned.

**Why:** the sentinel ADR's revision leaves the shape of "all" to the spec. This shape keeps the
one accepted literal `"all"`, checked before validation, so Studio's existing `"all"` default
carries over unchanged. JSON `null` was rejected because many MCP clients send `null` for an
optional they mean to leave unset, and that would silently widen to "all".

Source: FR-04, FR-05, FR-14, brainstorming-2026-09-17-okf-v02-adoption D21, adr-2026-08-12-status-all-sentinel-convention `## Revision — 2026-09-25`, AC-08

### R6 — An `archived` value that is neither a boolean nor `"all"` is rejected

The value is compared against `"all"` before it is validated. When the value is neither a
boolean nor `"all"`, the call returns `validation_error` naming the value. Through MCP, the
tool's input schema already rejects such a value before dispatch, with FastMCP's argument error.
That error is not the structured `validation_error` that `status="activ"` returns today; this is
accepted. Callers that bypass MCP — `resources.py`, Studio's fallback and unit tests — get the
structured `validation_error` from the inner check.

**Why:** a FastMCP argument error is how a `tier` type mismatch already behaves, and the value is
still rejected.

Note (probed 2026-10-13, with the pinned FastMCP 3.4.6): `"all"`, `true` and `false` pass, the
string `"true"` is coerced to `true`, and `null`, `"All"` and `"inactive"` are rejected with
FastMCP's argument error before dispatch.

Source: FR-04, FR-05, FR-14, brainstorming-2026-09-17-okf-v02-adoption D21, adr-2026-08-12-status-all-sentinel-convention `## Revision — 2026-09-25`

### R7 — `synthesise_artifacts` always applies `archived $eq false`

`synthesise_artifacts` keeps exposing no archive parameter and always applies
`archived $eq false`.

Source: FR-04, FR-05, FR-14, brainstorming-2026-09-17-okf-v02-adoption D21, adr-2026-08-12-status-all-sentinel-convention `## Revision — 2026-09-25`

### R8 — Listed, searched and synthesised entries carry `archived`; a non-boolean vector value is skipped and counted

When `list_artifacts`, `search_artifacts` or `synthesise_artifacts` returns an entry, the entry
includes `archived` as a boolean. When a candidate's vector `archived` is not a boolean, the
candidate is skipped and counted under `skipped_malformed_count`, as for an unreadable `tier`.

Source: FR-04, FR-05, FR-14, brainstorming-2026-09-17-okf-v02-adoption D21, adr-2026-08-12-status-all-sentinel-convention `## Revision — 2026-09-25`, adr-2026-09-14-malformed-persisted-data-policy D2, D3 and its revision

### R9 — `read_artifact` returns `archived` from S3 object metadata, or `corrupt_metadata` naming `archived`

When `read_artifact` succeeds, it returns `archived` parsed from S3 object metadata. When that
value is uninterpretable, it returns `corrupt_metadata` naming `archived`. The raw value appears
in the message only for an own-scope reader. The gate still runs first, so a denied foreign
artifact returns `access_denied`.

Source: FR-04, FR-05, FR-14, brainstorming-2026-09-17-okf-v02-adoption D21, adr-2026-08-12-status-all-sentinel-convention `## Revision — 2026-09-25`, brainstorming-2026-09-17-okf-v02-adoption D50 (case 5)

## 4. Rules — Archive, purge, delete, freshness

### R10 — `archive_artifact` sets `archived` true in both stores

When `archive_artifact` succeeds, it sets S3 `archived` to `"true"` through the existing
compare-and-swap re-PUT, sets every vector's `archived` to `true`, and returns
`{"artifact_id": …, "archived": true}` plus today's optional keys (`already_archived`,
`referrers`, `warning_message`).

**Example**

- Given `archive_artifact` succeeds on X, then its response is
  `{"artifact_id": …, "archived": true}`, and X's S3 object metadata and every one of its vectors
  record it as archived.

Source: FR-05, FR-14, FR-22

### R11 — `archive_artifact` short-circuits only when both stores already hold archived `true`

When S3 `archived` parses as true and every vector's `archived` is the boolean `true`,
`archive_artifact` short-circuits with `already_archived: true`. Any other vector value falls
through and completes the flip.

Source: FR-05, FR-14, FR-22

### R12 — `purge_archived` selects on `archived`

`purge_archived` selects its purge set as own-scope vectors with `archived $eq true`, and its
cascade candidates as own-scope syntheses with `archived $eq false`.

**Example**

- Given archived artifacts A and B and a non-archived synthesis S whose every source is A or B,
  when `purge_archived(confirm=True)` runs, then A, B and S are deleted from S3 and the index, and
  S is named in the response (AC-20).

Source: FR-05, FR-14, FR-22, AC-20

### R13 — The referrer lookup considers only non-archived own-scope referrers

The referrer lookup used by `delete_artifact` and `archive_artifact` (`find_referrers`) considers
only own-scope referrers with `archived $eq false`.

Source: FR-05, FR-14, FR-22

### R14 — `check_synthesis_freshness` audits non-archived syntheses and reports archived sources by the boolean

`check_synthesis_freshness` audits own-scope syntheses with `archived $eq false`, and reports a
source as archived when its vector `archived` is the boolean `true`.

**Example**

- Given a non-archived synthesis citing an archived source, when the freshness audit runs, then
  the source is listed under `archived_sources`.

Source: FR-05, FR-14, FR-22

## 5. Rules — Resources and Studio

### R15 — `arkeology://artifacts` uses `list_artifacts`' default `archived`

`arkeology://artifacts` delegates to `list_artifacts` with the default `archived`.

**Example**

- Given archived and non-archived own-scope artifacts, when a host reads `arkeology://artifacts`,
  then only the non-archived ones are listed (AC-52).

Source: FR-46, FR-48, AC-52

### R16 — The schema resource describes `archived` and no longer mentions `status`

The schema resource describes `archived` as a required boolean, set only by `archive_artifact`,
and no longer mentions `status`, `active` or `inactive`. T89 rewrites the rest of the resource.

Source: FR-46, FR-48

### R17 — Studio's archived facet sends the same `archived` value to list and search

Studio's archived facet offers All (the default), Not archived and Archived. These send
`archived: "all"`, `false` and `true` respectively, and the same value is sent to both
`list_artifacts` and `search_artifacts`. The detail view shows an "archived" pill when
`archived` is true and no pill otherwise. This rule covers the archived-state part of AC-54; the
lifecycle-status facet half of AC-54 / FR-48 is T81's.

**Example**

- Given Studio is open, when the operator picks a value in the archived facet, then
  `list_artifacts` and `search_artifacts` are called with the matching `archived` argument.

**Why:** resolved 2026-10-13 — T81 owns the lifecycle-status half: plan.md's T81 entry now
includes "Studio gains a lifecycle-status facet" and AC-54, and T76 proves only the
archived-state half. AC-54 requires Studio facets for archived state *and* lifecycle status, and
lifecycle status does not exist until T81. AC-08 and AC-52 do not have this problem: before T81
no artifact carries a lifecycle status, so "not archived" and "in force" select the same set.

Source: FR-46, FR-48, AC-54

## 6. Rules — Reconcile

### R18 — The `reconcile_index` rebuild takes `archived` strictly from S3 and fails an artifact whose value is uninterpretable

When `reconcile_index` rebuilds an artifact's vectors, it takes `archived` from its S3 object
metadata. When that value is uninterpretable, it writes no vectors for that artifact and reports
it under `failed` with a reason naming `archived`. This replaces today's default to `active`.

Source: FR-17, brainstorming-2026-09-17-okf-v02-adoption D42, D50

### R19 — `reconcile_index` repairs vectors whose `archived` is absent or not a boolean when the S3 value is interpretable

When `reconcile_index` runs, after its existing three phases it examines every own-scope vector
whose `archived` is absent or not a boolean, using a strict type test (`0` and `1` are not
booleans). For each affected artifact still in S3 and not reported as dangling:

| The affected vectors' keys | The artifact's S3 `archived` | Outcome |
|----------------------------|------------------------------|---------|
| All numbered, `{artifact_id}#{n}` with `n` from 0 to 99 | Interpretable | Each affected vector is rewritten with that value, keeping its embedding and every other metadata key, with no embedding call. The artifact is reported in `reconciled` with `source: "archived_repair"` and the count of vectors rewritten. |
| All numbered | Uninterpretable | Nothing is written. The artifact is reported under `failed` with a reason naming `archived`. |
| Any at another key — a heading slug or the bare `artifact_id`, written by an earlier release | Either | Nothing is written for the artifact, and every such vector is left as it is. The artifact is reported under `failed` with a reason naming `arkeology-migrate-store`. |

The report reuses the existing fields: a repair is a `reconciled` entry with a fifth `source`
value, `archived_repair`, and an unrepairable artifact goes in `failed`; no new top-level key is
added. To detect bad values, the own-scope vector listing that reconcile already takes is
fetched together with its metadata (`fetch_vectors_by_metadata`), which adds one `get_vectors`
pass. A filter of `archived $nin [true, false]` is not used.

**Example**

- Given a vector whose `archived` is absent, or is a string or a number, and whose S3 object
  metadata says `archived: "true"`, when `reconcile_index` runs, then the vector is rewritten
  with `archived: true` and keeps its embedding, the artifact is reported, and no embedding call
  is made (brainstorming-2026-09-17-okf-v02-adoption D50).
- Given an own-scope vector at a heading-slug key with no `archived`, written by a server of the
  earlier release after the store migration, when `reconcile_index` runs, then that vector is
  unchanged, the artifact is reported under `failed` naming `arkeology-migrate-store`, and the next
  server start still refuses at the store-shape check.

**Why:** consumers already filter `reconciled` on `source`. The extra `get_vectors` pass is
accepted because reconcile is an operator-triggered repair tool. The `$nin` filter was rejected
because the in-process evaluator compares with Python `==`, where `1 == True`, so it would miss
exactly the non-boolean values it exists to catch.

**Why (A vector at an earlier key is the store migration's to fix):** a vector this release reads by
key sits at a numbered key (T92 R1). One at an earlier key was written by a server of the earlier
release, and the store migration re-keys it while writing `archived` on the copy (T90 R22, R44).
Stamping `archived` on it in place would stop the store-shape check from refusing to start (T90
R34), the signal that sends the operator back to the migration, while leaving a vector no by-key
path reads — an archive or a delete would never reach it.

Source: FR-17, brainstorming-2026-09-17-okf-v02-adoption D42, D50; p15-t92-numbered-vector-keys R1; p15-t90-store-migration R22, R34, R44

### R20 — `reconcile_index` never translates a legacy `status` into `archived`

`reconcile_index` translates a legacy `status` value into `archived` nowhere. Store migration is
T90's (brainstorming-2026-09-17-okf-v02-adoption D42).

Source: FR-17, brainstorming-2026-09-17-okf-v02-adoption D42, D50

## 7. Rules — Removed name

### R21 — `status` is a removed name on the list, search and write tools

T76 adds rows to the per-tool removed-name table and middleware in `server.py` that T78's spec
defines (`### Decisions taken in this spec`, "How removed names are rejected"). Whichever of T76
and T78 lands first creates the table. The rows are:

- (`list_artifacts`, `status`) → `archived`;
- (`search_artifacts`, `status`) → `archived`;
- (`create_artifact`, `status`) and (`update_artifact`, `status`) → `archive_artifact`.

**Example**

- Given a caller passing `status` to `list_artifacts` or `search_artifacts`, when it calls
  through MCP, then the call returns `validation_error` naming `archived` and is not dispatched
  (AC-80; brainstorming-2026-09-17-okf-v02-adoption D42).

Source: AC-80, brainstorming-2026-09-17-okf-v02-adoption D42

### R22 — A bulk descriptor carrying `status` fails only that entry

When a bulk descriptor in `create_artifacts` or `update_artifacts` carries a `status` key, that entry fails with `validation_error` naming `archive_artifact`.
`migrate_artifacts` inherits this through its delegation.

Source: AC-80, brainstorming-2026-09-17-okf-v02-adoption D42

## 8. Boundaries

**Always:**
- The archived clause is ANDed beside the scope filter. It never replaces or loosens the
  cross-scope gate, and `"all"` removes only the archived constraint.
- `list_artifacts` and `search_artifacts` map `archived` to a clause through one helper in
  `_search_helper.py`, next to `build_user_filters`, so the two tools cannot drift apart. That
  drift is the failure the sentinel ADR records.
- Check values with `isinstance(value, bool)` / `is True`, never `== True` or truthiness.
- Public functions keep delegating to `_inner` inside `try/except Exception`. Logging goes through
  `logging`, never stdout.
- Every re-PUT and vector rewrite carries the other metadata keys and the annotations forward, as
  today.

**Ask First:**
- None. Every outcome is decided above or handed off (under Hand-offs).

**Never:**
- Read a legacy `status` key as a fallback for a missing `archived`, in any tool. This is the
  no-fallback-paths rule.
- Translate, strip or rewrite a legacy `status` key in `archive_artifact`, `reconcile_index` or
  `add_artifact_links` (renamed from `link_metadata` by T84) (brainstorming-2026-09-17-okf-v02-adoption D42). Whole-dict copy paths carry such
  a key forward untouched until T90 removes it.
- Add OKF lifecycle `status`, the in-force view, or a full-lineage option to `synthesise_artifacts`
  (T81).
- Add a startup check of T76's own for a store not yet migrated: T90's store-shape check is the
  one (R23).
- Change `health_check`'s `status` field, or the `status: pending | written | failed` field in the
  migration skill's local manifest.
- Rewrite the schema resource beyond the `archived` row and the enum summary line (T89), or edit
  README, SERVER-REFERENCE or CHANGELOG (T91).
- Re-run the `commit_refs` cap calibration. `archived: false` is smaller than `status: "active"`,
  so the filterable budget only gains headroom. Calibrating against the final Phase 15 key mix is
  outside T76.

## 9. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/constants.py` | Modify | Delete `ArtifactStatus` and its mention in the module docstring |
| `src/arkeology/artifact.py` | Modify | Remove `Artifact.status` and `validate_status`. Add one strict parser for the S3 string (`"true"` → `True`, `"false"` → `False`, else `None`), used by read, archive and reconcile |
| `src/arkeology/tools/write.py` | Modify | Remove the `status` parameter. Both metadata dicts write `archived` (`"false"` / `False`) instead of `status`. T78 may have renamed the function to `create_artifact`; edit whichever exists |
| `src/arkeology/tools/write_artifacts.py` | Modify | Drop `descriptor.get("status", …)`. Fail an entry carrying a `status` key with `validation_error` naming `archive_artifact` |
| `src/arkeology/tools/_search_helper.py` | Modify | Add the `archived` clause helper next to `build_user_filters`. `build_artifact_summary` returns `archived` (a bool) instead of `status`, and returns `None` when it is not a bool. `find_referrers` uses `archived $eq false`. `run_search_loop` changes in wording only (its `status_filter` becomes the archived clause) |
| `src/arkeology/tools/list.py`, `search.py` | Modify | `archived: bool \| Literal["all"] = False` replaces `status`, through the helper |
| `src/arkeology/tools/synthesise.py` | Modify | `archived $eq false` |
| `src/arkeology/tools/read.py` | Modify | Return `archived` from the S3 parser. `corrupt_metadata` when it is uninterpretable, echoing the raw value only for an own-scope reader |
| `src/arkeology/tools/archive.py` | Modify | Set S3 `"true"` and vector `True`. Idempotency test and response use `archived`. Step constant value `archive_status_reput` becomes `archive_reput` (the step set is open, nothing branches on it, and T82 reuses this path). Docstrings and comments: "status flip" becomes "archive flip" |
| `src/arkeology/tools/purge.py`, `freshness.py` | Modify | Clauses and the archived-source test as in R12 and R14 |
| `src/arkeology/tools/reconcile.py` | Modify | The rebuild takes `archived` strictly from S3 and fails the artifact when it is unreadable. Fetch the Phase 2 own-scope listing with metadata. Add the post-Phase-3 archived-repair pass |
| `src/arkeology/resources.py` | Modify | Schema row and enum line. `_artifacts_listing_content` relies on the default (drop `status=`) |
| `src/arkeology/server.py` | Modify | `list_artifacts` and `search_artifacts` signatures and docstrings. The write tool loses `status`. Add the removed-name rows (create the table and middleware per T78 if T78 has not landed) |
| `src/arkeology/static/arkeology-studio.html` | Modify | `sel-status` becomes `sel-archived` (All / Not archived / Archived), `filterStatus` becomes `filterArchived`, `filterArgs` sends `archived` as `"all"` or a boolean, detail pill on `meta.archived === true`. Update the sentinel comments |
| `src/arkeology/errors.py`, `annotations.py`, `tools/link_metadata.py` | Modify | Wording only ("status re-PUT" becomes "archive re-PUT"; the `status="actve"` example becomes an `archived` one). *Uncertain:* sweep `grep -rn "status\|inactive" src/` and leave `health.py` alone |
| Tests | Modify / Create | See Testing Approach |

### Contracts

Amend these before writing tests (plan.md `## Phase 15`, TDD rule):

- **`data/s3.artifact.md`** — `## Storage Shape`: the `status` row becomes `archived`, a scalar,
  exactly `"true"` / `"false"`, required. Anything else, including absence, is uninterpretable and
  never defaulted. `## Compatibility Guarantees`: no path writes `status`; a legacy `status` on an
  unmigrated object is carried forward by whole-dict copies and removed only by the store
  migration. The "status re-PUT" wording becomes "archive re-PUT".
- **`data/s3vectors.artifact.md`** — The `status` row becomes `archived`, a native `bool`,
  filterable. A missing or non-boolean value is malformed: the filters exclude it and
  `reconcile_index` repairs it from S3 (brainstorming-2026-09-17-okf-v02-adoption D50). Note that
  the filterable key mix changed (shrank).
- **`modules/arkeology.tools.list.md`, `arkeology.tools.search.md`** — Change the signature to
  `archived: bool | Literal["all"] = False`. Add the three-state invariant (`"all"` checked first,
  clause omitted). Entries carry `archived`. A non-boolean `archived` joins the malformed-skip
  causes. In list's preconditions, `status` becomes `archived`.
- **`arkeology.tools.synthesise.md`** — Fixed `archived $eq false`. Entries carry `archived`.
- **`arkeology.tools.read.md`** — The response carries `archived` (from S3). `corrupt_metadata`
  now also covers an uninterpretable `archived`, and the raw value is echoed only to own-scope
  readers.
- **`arkeology.tools.archive.md`** — Rewrite the description and invariants in terms of
  `archived`. Response `{"artifact_id", "archived": true}`. Step name `archive_reput`.
- **`arkeology.tools.purge.md`, `arkeology.tools.delete.md`, `arkeology.tools.freshness.md`** —
  "inactive / active status" becomes `archived` true / false. The rules themselves are unchanged.
- **`arkeology.tools.reconcile.md`** — The rebuild reads `archived` strictly, and an unreadable
  value fails the artifact (it no longer defaults to active). New invariant: archived detection
  and repair, with no migration of `status`. In Postconditions, add the fifth `source` value
  `archived_repair` (with `vectors_repaired`); "two of the four sources" becomes "of the five".
- **`arkeology.resources.md`** — `arkeology://artifacts` uses `list_artifacts`' default `archived`.
- **`arkeology.tools.write.md`, `arkeology.tools.write_artifacts.md`** — Remove the `status`
  parameter. Create writes `archived` false. A `status` argument or descriptor key is rejected,
  naming `archive_artifact`. Coordinate with T78's amendments to the same files.
- **`arkeology.tools.link_metadata.md`** — Wording ("archive re-PUT").
- **`design/arkeology-studio-tokens.html`** — The illustrative facet sample `status: active ▾`
  becomes `archived: all ▾`.

### Testing Approach

**TDD order** (each test file is red before the implementation file it gates):
1. `tests/unit/test_artifact.py`, then `artifact.py` and `constants.py`.
2. `tests/unit/test_tools_write.py` and `test_tools_write_artifacts.py`, then `write.py` and
   `write_artifacts.py`.
3. `tests/unit/test_tools__search_helper.py`, then `_search_helper.py`.
4. `tests/unit/test_tools_list.py`, `test_tools_search.py` and `test_tools_synthesise.py`, then
   the three tools.
5. `tests/unit/test_tools_read.py`, then `read.py`.
6. `tests/unit/test_tools_archive.py`, `test_tools_purge.py`, `test_tools_delete.py` and
   `test_tools_freshness.py`, then those tools.
7. `tests/unit/test_tools_reconcile.py`, then `reconcile.py`.
8. `tests/unit/test_resources.py`, `test_data_resources.py` and `test_server.py`, then
   `resources.py` and `server.py`.
9. `tests/static/studio-archived-facet.test.js`, then `arkeology-studio.html`.
10. Integration updates.

**Moto.** No conftest change is needed. Probed 2026-10-13: moto stores a native boolean vector
metadata value, and `matches_filter` gives `archived $eq false` matching the boolean `false` but
not the string `"false"` or a missing key.

**Unit tests to add or change (with the AC each proves):**
- Storage: a create writes S3 `archived == "false"` and every vector `archived is False`, with no
  `status` key in either store or in the response (R4). The S3 parser maps only the two exact
  strings; `"True"`, `""` and absent all give `None`.
- Query, parameterised over list and search:
  - The default excludes an archived artifact (AC-08).
  - `true` returns only archived artifacts. `"all"` returns both, and the filter passed to the
    vector client has no `archived` key (a spy).
  - `"activ"` and `None` passed to the inner function return `validation_error`.
  - Entries carry `archived` as a bool and no `status`.
  - A vector with `archived: "false"` under `"all"` is skipped and counted.
- Synthesise excludes an archived artifact (AC-08), and its entries carry `archived`.
- Read: an S3 `archived` of `"yes"` or absent returns `corrupt_metadata` naming `archived`. The
  own-scope message contains `"yes"`; the message for an admitted foreign-scope artifact does not.
- Archive: `{"archived": true}`; S3 and all vectors flipped (AC-08 together with list). An
  idempotent second call returns `already_archived`. A vector left as `"true"` (a string) is
  re-flipped and does not short-circuit.
- Purge: archived A and B plus a non-archived synthesis whose sources are only A and B are all
  deleted, and the synthesis is reported (AC-20). A non-archived artifact is untouched.
- Delete and archive referrers: an archived referrer is not reported, and a non-archived one is.
- Freshness: a source whose vector has `archived: true` is in `archived_sources`, and an archived
  synthesis is not audited.
- Reconcile (brainstorming-2026-09-17-okf-v02-adoption D50):
  - Vectors with `archived` missing, `"false"` and `1`, under an S3 `"true"`, are rewritten as
    `True` with their embedding unchanged. The `bedrock.embed` spy is not called, and the result
    has one `reconciled` entry with `source: "archived_repair"`.
  - An S3 `archived` that is absent gives an entry in `failed` naming `archived`, and the vectors
    are unchanged.
  - A vector with no `archived` at a heading-slug key, under an S3 `"true"`, is left unchanged, and
    the artifact is in `failed` naming `arkeology-migrate-store`; one at `{id}#0` beside it is not
    rewritten either. Apart from this case, unit fixtures for this rule seed numbered keys.
  - An orphan re-index with an unreadable S3 `archived` writes no vectors and lands in `failed`.
  - A legacy S3 `status: "inactive"` with no `archived` is never translated.
- Resources: `arkeology://artifacts` omits an archived artifact (AC-52). The schema text contains
  `archived` and none of `status`, `active` or `inactive`.
- AC-80, through `fastmcp.Client(_app)` (`tool.fn` bypasses middleware):
  - `list_artifacts(status="inactive")` and `search_artifacts(status="all")` return
    `validation_error` whose message names `archived`, and the inner functions are not awaited.
  - The write tool given `status` returns `validation_error` naming `archive_artifact`.
  - A bulk descriptor with `status` fails only that entry.
  - Through the client, `archived="All"` and `archived=null` are rejected.
- Studio (AC-54, archived half): `tests/static/studio-archived-facet.test.js` slices `filterArgs`
  out of the shipped HTML using the existing `extractBlock` approach, and asserts that the facet
  values `"all"`, `"true"` and `"false"` produce `archived` as `"all"`, `true` and `false`, and
  that no `status` key is ever produced.

**Integration tests this change breaks** (update in this task, per plan.md):
- Remove the `status` kwarg or descriptor key from every write fixture:
  `test_tools_write.py`, `test_tools_read.py`, `test_tools_search.py`, `test_tools_list.py`,
  `test_tools_archive.py`, `test_tools_purge.py`, `test_tools_delete.py`,
  `test_tools_synthesise.py`, `test_tools_reconcile.py`, `test_tools_link_metadata.py`,
  `test_tools_write_artifacts.py`, `test_tools_migrate_artifacts.py`,
  `test_tools_propose_commit_links.py`, `test_tools_studio.py`,
  `test_calibration_per_artifact_vector_lookup.py`.
- `test_tools_list.py`, `test_tools_archive.py` and `test_tools_purge.py`: `status="inactive"`
  becomes `archived=True`, and `archive_result["status"] == "inactive"` becomes
  `archive_result["archived"] is True`.
- `test_tools_read.py`: the expected-field list replaces `"status"` with `"archived"`.
- `test_tools_freshness.py`: the archived source is written and then archived through
  `archive_artifact`, instead of being written with `"status": "inactive"`. The file's
  date-staleness case still fails until T86.
- `test_calibration_vector_metadata_budget.py`: the modelled filterable dict replaces
  `"status": "active"` with `"archived": False`. Do not re-run the calibration (see Boundaries).
- `clients/test_vectors_filter_semantics.py`: **add** a real-AWS test that `archived $eq false`
  matches a boolean `false` vector and matches neither a string `"false"` vector nor one missing
  the key. This is the server-side type strictness that moto and `matches_filter` only
  approximate. The existing plain-equality probe uses `status` only as arbitrary metadata and stays.
- Not broken: `test_tools_health.py` (its `status` is the health field).
- T78 splits the write tools in the same files. If T76 lands first, the rules here that name
  `create_artifact`, `update_artifact`, `create_artifacts` and `update_artifacts` apply to the
  earlier write tools those four replace. Whichever task lands second rebases the other's fixture
  edits.

### Hand-offs

- **Hand-off to T81 (not blocking) — delete the `status` rows if the name is reused.** The
  (`list_artifacts`, `status`) and (`search_artifacts`, `status`) rows, and the write-tool rows,
  exist only until T81. If T81 reintroduces `status` as the OKF lifecycle filter or as a write
  parameter (brainstorming-2026-09-17-okf-v02-adoption D22), it must delete the matching rows. After
  that, an old caller sending `status: "active"` or `"inactive"` must still get `validation_error`
  as an unrecognised lifecycle value, and the message must name `archived` (or `archive_artifact` on
  a write tool). T81's spec must include that test. Per ADR-017 §2, the `"all"` convention also
  binds any lifecycle `status` filter T81 adds.

---
type: Spec
id: p15-t76-archived-boolean
title: T76 — Archive Marker status → archived (bool)
description: Renames Arkeology's archive marker from status (active/inactive) to archived (bool) in S3 object metadata, vector metadata, every tool parameter, response field and filter expression, Studio's facet and the data resources; deletes ArtifactStatus; makes reconcile_index detect and repair vectors whose archived is missing or not a boolean; and rejects the old status parameter, so the status key is free when OKF lifecycle status lands in T81.
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
phase: 15
task: 76
---

# T76 — Archive Marker `status` → `archived` (bool)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Arkeology's archive marker moves from `status` (`active` / `inactive`) to `archived` (a boolean)
in both stores and in every tool parameter, response field, filter expression, the Studio facet
and the data resources. `ArtifactStatus` is deleted, and `reconcile_index` repairs any vector whose
`archived` is missing or not a boolean (D50). T76 lands before T81, so once it ships no code path
writes, filters on or returns a `status` key, and the key is free for the OKF lifecycle (D21).

## Problem Statement

Today one key, `status`, records whether Arkeology has archived an artifact. OKF v0.2 documents
carry their own `status` (`draft | stable | deprecated`), which T81 ingests. If both existed, a
`read_artifact` payload would hold `status: active` in the metadata and `status: stable` in the
content. Code could tell them apart, but an agent reading the payload could not (ADR-017
`## Context` > `### Forces`). The archive marker is a yes/no fact, so it becomes a boolean named for
what it records. It must ship alone and first, so that `status` never means two things in one
release (plan.md `## Phase 15`, Ordering).

## User Stories

### Story 1 — Archiving is a boolean, filtered with three states (P1)

- Given an artifact X that has been archived, when the caller lists or searches with default
  parameters, then X is not returned (AC-08).
- Given the same store, when the caller passes `archived=true`, then only archived artifacts are
  returned. When the caller passes `archived="all"`, archived and non-archived artifacts are both
  returned.
- Given `archive_artifact` succeeds, then its response is `{"artifact_id": …, "archived": true}`,
  and X's S3 object metadata and every one of its vectors record it as archived.

### Story 2 — No `status` key in data the server writes or returns (P1)

- Given any artifact written after T76, when it is read, listed, searched or synthesised, then
  each entry carries `archived` as a JSON boolean and carries no `status` key. Its S3 object
  metadata and vector metadata hold `archived` and no `status`.

### Story 3 — Purge, delete and freshness key on `archived` (P1)

- Given archived artifacts A and B and a non-archived synthesis S whose every source is A or B,
  when `purge_archived(confirm=True)` runs, then A, B and S are deleted from S3 and the index, and S
  is named in the response (AC-20).
- Given a non-archived synthesis citing an archived source, when the freshness audit runs, then
  the source is listed under `archived_sources`.

### Story 4 — Humans see the same default view (P1)

- Given archived and non-archived own-scope artifacts, when a host reads `arkeology://artifacts`,
  then only the non-archived ones are listed (AC-52).
- Given Studio is open, when the operator picks a value in the archived facet, then
  `list_artifacts` and `search_artifacts` are called with the matching `archived` argument (the
  archived-state part of AC-54; see Open Questions).

### Story 5 — Vectors with a missing or non-boolean `archived` are repaired (P1)

- Given a vector whose `archived` is absent, or is a string or a number, and whose S3 object
  metadata says `archived: "true"`, when `reconcile_index` runs, then the vector is rewritten with
  `archived: true` and keeps its embedding, the artifact is reported, and no embedding call is made
  (D50).

### Story 6 — The old parameter is rejected, not aliased (P1)

- Given a caller passing `status` to `list_artifacts` or `search_artifacts`, when it calls through
  MCP, then the call returns `validation_error` naming `archived` and is not dispatched (AC-80;
  D42).

## Requirements

**Storage** (FR-09; D21, D50)

- WHEN any path writes an artifact's S3 object metadata THE SYSTEM SHALL store `archived` as
  exactly the string `"true"` or `"false"`, and SHALL NOT write a `status` key.
- WHEN any path writes an artifact's vector metadata THE SYSTEM SHALL store `archived` as a native
  boolean in filterable metadata, and SHALL NOT write a `status` key. No index change is needed:
  keys are filterable by default (ADR-017 `## Consequences`, "No re-index").
- WHEN an artifact is created (`write_artifact`, or `create_artifact` after T78, including through
  the bulk and migrate tools) THE SYSTEM SHALL write `archived` false in both stores.
- WHEN reading `archived` back THE SYSTEM SHALL accept only `"true"` / `"false"` from S3 object
  metadata (case-sensitive) and only a native boolean from vector metadata. Any other value,
  including absence, is uninterpretable. It is never defaulted, and it is never derived from a
  legacy `status` key.

**Query** (FR-04, FR-05, FR-14; D21; status-all sentinel ADR, `## Revision — 2026-09-25`)

- WHEN `list_artifacts` or `search_artifacts` is called THE SYSTEM SHALL accept `archived` with
  three states and AND the result with the scope filter exactly as the `status` clause is ANDed
  today:
  - `false`, the default, adds the clause `archived $eq false`;
  - `true` adds `archived $eq true`;
  - `"all"` adds no archived clause.
- THE SYSTEM SHALL compare against `"all"` before validating. WHEN the value is neither a boolean
  nor `"all"` THE SYSTEM SHALL return `validation_error` naming the value. Through MCP, the tool's
  input schema already rejects such a value before dispatch (see the decisions below).
- `synthesise_artifacts` SHALL keep exposing no archive parameter and SHALL always apply
  `archived $eq false`.
- WHEN `list_artifacts`, `search_artifacts` or `synthesise_artifacts` returns an entry THE SYSTEM
  SHALL include `archived` as a boolean in it. WHEN a candidate's vector `archived` is not a
  boolean THE SYSTEM SHALL skip it and count it under `skipped_malformed_count`, as for an
  unreadable `tier` (malformed-data ADR D2/D3 and its revision).
- WHEN `read_artifact` succeeds THE SYSTEM SHALL return `archived` parsed from S3 object metadata.
  WHEN that value is uninterpretable THE SYSTEM SHALL return `corrupt_metadata` naming `archived`.
  The raw value appears in the message only for an own-scope reader (D50, case 5). The gate still
  runs first, so a denied foreign artifact returns `access_denied`.

**Archive, purge, delete, freshness** (FR-05, FR-14, FR-22)

- WHEN `archive_artifact` succeeds THE SYSTEM SHALL set S3 `archived` to `"true"` through the
  existing compare-and-swap re-PUT, set every vector's `archived` to `true`, and return
  `{"artifact_id": …, "archived": true}` plus today's optional keys (`already_archived`,
  `referrers`, `warning_message`).
- WHEN S3 `archived` parses as true AND every vector's `archived` is the boolean `true` THE SYSTEM
  SHALL short-circuit with `already_archived: true`. Any other vector value falls through and
  completes the flip.
- `purge_archived` SHALL select its purge set as own-scope vectors with `archived $eq true`, and
  its cascade candidates as own-scope syntheses with `archived $eq false`.
- The referrer lookup used by `delete_artifact` and `archive_artifact` (`find_referrers`) SHALL
  consider only own-scope referrers with `archived $eq false`.
- `check_synthesis_freshness` SHALL audit own-scope syntheses with `archived $eq false`, and SHALL
  report a source as archived when its vector `archived` is the boolean `true`.

**Resources and Studio** (FR-46, FR-48)

- `arkeology://artifacts` SHALL delegate to `list_artifacts` with the default `archived`.
- The schema resource SHALL describe `archived` as a required boolean, set only by
  `archive_artifact`, and SHALL no longer mention `status`, `active` or `inactive`. T89 rewrites
  the rest of the resource.
- Studio's archived facet SHALL offer All (the default), Not archived and Archived. These send
  `archived: "all"`, `false` and `true` respectively, and the same value is sent to both
  `list_artifacts` and `search_artifacts`. The detail view SHALL show an "archived" pill when
  `archived` is true and no pill otherwise.

**Reconcile** (FR-17; D42, D50)

- WHEN `reconcile_index` rebuilds an artifact's vectors THE SYSTEM SHALL take `archived` from its
  S3 object metadata. WHEN that value is uninterpretable THE SYSTEM SHALL write no vectors for that
  artifact and SHALL report it under `failed` with a reason naming `archived`. This replaces
  today's default to `active`.
- WHEN `reconcile_index` runs THE SYSTEM SHALL, after its existing three phases, examine every
  own-scope vector whose `archived` is absent or not a boolean, using a strict type test (`0` and
  `1` are not booleans). For each affected artifact still in S3 and not reported as dangling:
  - WHEN its S3 `archived` is interpretable THE SYSTEM SHALL rewrite each affected vector with that
    value, keeping its embedding and every other metadata key, making no embedding call, and SHALL
    report the artifact in `reconciled` with `source: "archived_repair"` and the count of vectors
    rewritten.
  - WHEN its S3 `archived` is uninterpretable THE SYSTEM SHALL write nothing and report it under
    `failed` with a reason naming `archived`.
- THE SYSTEM SHALL NOT translate a legacy `status` value into `archived` anywhere in
  `reconcile_index`. Store migration is T90's (D42).

**Removed name** (AC-80; D42)

- T76 SHALL add rows to the per-tool removed-name table and middleware in `server.py` that T78's
  spec defines (`### Decisions taken in this spec`, "How removed names are rejected"). Whichever of
  T76 and T78 lands first creates the table. The rows are:
  - (`list_artifacts`, `status`) → `archived`;
  - (`search_artifacts`, `status`) → `archived`;
  - (`write_artifact`, `status`) → `archive_artifact`. After T78 lands, the same row exists for
    `create_artifact` and `update_artifact` instead.
- WHEN a bulk descriptor in `write_artifacts` (`create_artifacts` / `update_artifacts` after T78)
  carries a `status` key THE SYSTEM SHALL fail that entry with `validation_error` naming
  `archive_artifact`. `migrate_artifacts` inherits this through its delegation.

**Invariant** — After T76, no code path writes, filters on or returns a `status` key for artifact
data. A store written or migrated after T76 therefore holds none. `health_check`'s per-component
`status` is a different field and is unchanged.

### Decisions taken in this spec

**The shape of "all": `archived: bool | Literal["all"] = False`.** The sentinel ADR's revision
leaves this shape to the spec. It keeps the one accepted literal `"all"`, checked before
validation, so Studio's existing `"all"` default carries over unchanged. JSON `null` was rejected
as the "all" spelling, because many MCP clients send `null` for an optional they mean to leave
unset, and that would silently widen to "all". The schema advertises
`anyOf: [boolean, {const: "all"}]`. With the pinned FastMCP 3.4.6 (probed 2026-10-13): `"all"`,
`true` and `false` pass, the string `"true"` is coerced to `true`, and `null`, `"All"` and
`"inactive"` are rejected with FastMCP's argument error before dispatch. That error is not the
structured `validation_error` that `status="activ"` returns today. This is accepted: it is how a
`tier` type mismatch already behaves, and the value is still rejected. Callers that bypass MCP —
`resources.py`, Studio's fallback and unit tests — get the structured `validation_error` from the
inner check.

**Create takes no archive marker.** ADR-017 §2 names `archive_artifact` as the owner of
`archived`, and FR-14 lists archiving as a post-write operation. T78's update already carries the
marker forward instead of accepting it. If create also accepted it, there would be a second writer
of the marker outside archive's partial-failure and idempotency machinery. No caller needs to
create an artifact that is already archived; the one test that does so writes and then archives.
The `status` parameter is therefore removed from create rather than renamed, and its AC-80 row
names `archive_artifact`.

**Persisted encodings.** ADR-017 `## Deferred to the Specs` leaves these to the data contracts,
and they are set here. S3 object metadata holds the exact lowercase strings `"true"` / `"false"`,
because S3 user metadata is string-only. Vector metadata holds a native boolean, which S3 Vectors
supports and filters with `$eq` (AWS S3 Vectors metadata filtering documentation). Parsing is
strict: a tolerant parser (`"True"`, `"1"`) would be a second encoding that nothing writes.

**The reconcile report reuses existing fields.** A repair is reported as a `reconciled` entry with
a fifth `source` value, `archived_repair`, and an unrepairable artifact goes in `failed`. This adds
no new top-level key, and consumers already filter `reconciled` on `source`. To detect bad values,
the own-scope vector listing that reconcile already takes is fetched together with its metadata
(`fetch_vectors_by_metadata`). That adds one `get_vectors` pass, which is accepted because
reconcile is an operator-triggered repair tool. A filter of `archived $nin [true, false]` was
rejected: the in-process evaluator compares with Python `==`, where `1 == True`, so it would miss
exactly the non-boolean values it exists to catch.

## Boundaries

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
- None. Every outcome is decided above or handed off under Open Questions.

**Never:**
- Read a legacy `status` key as a fallback for a missing `archived`, in any tool. This is the
  no-fallback-paths rule.
- Translate, strip or rewrite a legacy `status` key in `archive_artifact`, `reconcile_index` or
  `link_metadata` (D42). Whole-dict copy paths carry such a key forward untouched until T90
  removes it.
- Add OKF lifecycle `status`, the in-force view, or a full-lineage option to `synthesise_artifacts`
  (T81).
- Add a startup check for an unmigrated store (T90; see Open Questions).
- Change `health_check`'s `status` field, or the `status: pending | written | failed` field in the
  migration skill's local manifest.
- Rewrite the schema resource beyond the `archived` row and the enum summary line (T89), or edit
  README, SERVER-REFERENCE or CHANGELOG (T91).
- Re-run the `commit_refs` cap calibration. `archived: false` is smaller than `status: "active"`,
  so the filterable budget only gains headroom. Calibrating against the final Phase 15 key mix is
  outside T76.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

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
| `src/arkeology/tools/purge.py`, `freshness.py` | Modify | Clauses and the archived-source test as in Requirements |
| `src/arkeology/tools/reconcile.py` | Modify | The rebuild takes `archived` strictly from S3 and fails the artifact when it is unreadable. Fetch the Phase 2 own-scope listing with metadata. Add the post-Phase-3 archived-repair pass |
| `src/arkeology/resources.py` | Modify | Schema row and enum line. `_artifacts_listing_content` relies on the default (drop `status=`) |
| `src/arkeology/server.py` | Modify | `list_artifacts` and `search_artifacts` signatures and docstrings. The write tool loses `status`. Add the removed-name rows (create the table and middleware per T78 if T78 has not landed) |
| `src/arkeology/static/arkeology-studio.html` | Modify | `sel-status` becomes `sel-archived` (All / Not archived / Archived), `filterStatus` becomes `filterArchived`, `filterArgs` sends `archived` as `"all"` or a boolean, detail pill on `meta.archived === true`. Update the sentinel comments |
| `src/arkeology/errors.py`, `annotations.py`, `tools/link_metadata.py` | Modify | Wording only ("status re-PUT" becomes "archive re-PUT"; the `status="actve"` example becomes an `archived` one). *Uncertain:* sweep `grep -rn "status\|inactive" src/` and leave `health.py` alone |
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Modify | Drop `status="active"` from both `list_artifacts` calls (the default is now non-archived). Otherwise the skill fails AC-80 until T88 rewrites it |
| Tests | Modify / Create | See Testing Approach |

## Contract Amendments

Amend these before writing tests (plan.md `## Phase 15`, TDD rule):

- **`data/s3.artifact.md`** — `## Storage Shape`: the `status` row becomes `archived`, a scalar,
  exactly `"true"` / `"false"`, required. Anything else, including absence, is uninterpretable and
  never defaulted. `## Compatibility Guarantees`: no path writes `status`; a legacy `status` on an
  unmigrated object is carried forward by whole-dict copies and removed only by the store
  migration. The "status re-PUT" wording becomes "archive re-PUT".
- **`data/s3vectors.artifact.md`** — The `status` row becomes `archived`, a native `bool`,
  filterable. A missing or non-boolean value is malformed: the filters exclude it and
  `reconcile_index` repairs it from S3 (D50). Note that the filterable key mix changed (shrank).
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

## Testing Approach

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
  `status` key in either store or in the response (Story 2). The S3 parser maps only the two exact
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
- Reconcile (D50):
  - Vectors with `archived` missing, `"false"` and `1`, under an S3 `"true"`, are rewritten as
    `True` with their embedding unchanged. The `bedrock.embed` spy is not called, and the result
    has one `reconciled` entry with `source: "archived_repair"`.
  - An S3 `archived` that is absent gives an entry in `failed` naming `archived`, and the vectors
    are unchanged.
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
- T78 renames `write_artifact` in the same files. Whichever task lands second rebases the other's
  fixture edits.

## Open Questions

1. **Resolved 2026-10-13 — T81 owns it.** plan.md's T81 entry now includes "Studio gains a
   lifecycle-status facet" and AC-54; T76 proves only the archived-state half. *Original
   question:* who owns the lifecycle-status half of AC-54 / FR-48? plan.md's T76 entry lists
   AC-54 under Done, but AC-54 requires Studio facets for archived state *and* lifecycle status.
   Lifecycle status does not exist until T81, and T81's plan entry names neither Studio nor AC-54,
   so no task builds that facet. *Recommended answer:* T76 proves the archived-state half (Story 4,
   the static test above), and the plan's T81 entry gains "Studio lifecycle-status facet; AC-54
   passes". AC-08 and AC-52 do not have this problem: before T81 no artifact carries a lifecycle
   status, so "not archived" and "in force" select the same set.

2. **Hand-off to T81 (not blocking) — delete the `status` rows if the name is reused.** The
   (`list_artifacts`, `status`) and (`search_artifacts`, `status`) rows, and the write-tool rows,
   exist only until T81. If T81 reintroduces `status` as the OKF lifecycle filter or as a write
   parameter (D22), it must delete the matching rows. After that, an old caller sending
   `status: "active"` or `"inactive"` must still get `validation_error` as an unrecognised
   lifecycle value, and the message must name `archived` (or `archive_artifact` on a write tool).
   T81's spec must include that test. Per ADR-017 §2, the `"all"` convention also binds any
   lifecycle `status` filter T81 adds.

3. **Behaviour on a store not yet migrated (not blocking).** On a store written before T76, no
   object or vector carries `archived`. T76's code does not fall back to `status`, so, in a loud
   rather than silent way:
   - `list_artifacts`, `search_artifacts` (`zero_results: true`), `synthesise_artifacts`,
     `arkeology://artifacts` and Studio's Not archived view return nothing.
   - `archived="all"` and Studio's default All view return no entries and a
     `skipped_malformed_count` equal to the number of candidates.
   - `read_artifact` returns `corrupt_metadata` naming `archived`.
   - `purge_archived` finds nothing.
   - The delete and archive referrer warnings find no referrers.
   - `check_synthesis_freshness` checks nothing and reports `all_fresh: true`. This is the one
     misleading signal, and it is bounded by `total_checked: 0`.
   - `archive_artifact` still works and adds `archived` while carrying the legacy `status` forward.
   - `reconcile_index` lists every own-scope artifact under `failed`, with S3 `archived`
     unreadable, and writes nothing. That is the operator's clearest indication that the store
     needs migrating.

   The remedy is T90's store-migration skill (ADR-017 §9: run the migration before or with the
   upgrade). The coordinator has asked the operator whether a startup check should refuse to start
   on an unmigrated store. If the answer is yes, it belongs to T90's scope, not T76's.

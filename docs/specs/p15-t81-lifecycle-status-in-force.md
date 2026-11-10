---
type: Spec
id: p15-t81-lifecycle-status-in-force
title: T81 — OKF Lifecycle status and the In-Force Default View
description: Ingests OKF document status (draft | stable | deprecated) on create and update into S3 object metadata and filterable vector metadata, and makes search, listing and synthesis preparation default to the in-force view — not deprecated and not archived, where an artifact with no status is in force — with a status filter, an exclude_drafts option and full lineage via archived="all" plus status="all". A supersedes edge never excludes anything. Studio gains a lifecycle facet, T76's temporary status rejection rows give way to value validation that still names archived, and the commit_refs vector cap is re-calibrated against real AWS with the final Phase 15 filterable key set.
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
    last_modified: 2026-10-13T11:56:32Z
  - id: plan
    resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-13T16:01:28Z
  - id: adr-sentinel
    resource: docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md
    title: The status="all" Sentinel as a Cross-Tool Convention for Query-Shaped Tools
    last_modified: 2026-09-25T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-budget
    resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
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
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: learnings
    resource: docs/learnings.md
    title: Learnings
    last_modified: 2026-06-10T11:51:16Z
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
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-resources
    resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
    last_modified: 2026-09-04T00:00:00Z
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
  - to: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal
    type: constrained_by
  - to: p15-t76-archived-boolean
    type: builds_on
  - to: p15-t78-create-update-split
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T16:19:13Z
phase: 15
task: 81
---

# T81 — OKF Lifecycle `status` and the In-Force Default View

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Arkeology stores the OKF document `status` (`draft | stable | deprecated`) that a writer supplies on
create or update, in S3 object metadata and filterable vector metadata (D22). Search, listing and
synthesis preparation then default to the in-force view: not `deprecated` and not archived, where an
artifact with no status is in force (D23). Callers can ask for full lineage, exclude drafts, or filter
on an exact status. The decision keys only on the artifact's own `status` and `archived`, never on a
`supersedes` edge (D24, D25).

## Problem Statement

Producer documents now carry an OKF lifecycle `status`, and Arkeology discards it. A deprecated spec
therefore ranks beside its replacement in every search, and an agent cannot ask what is currently in
force (FR-67). T76 freed the `status` key for this. The in-force decision must key on the retired
artifact's own `status`. A `supersedes` edge is cheap, can be generated by a machine, and is written on
a *different* document, so letting it exclude anything is the threat described in OKF GitHub issue #22.
`status: deprecated` on A is a write to A under A's own write authority (ADR-017 `## Decision`,
"2. Lifecycle").

## User Stories

### Story 1 — In force by default (P1)
- Given own-scope artifacts A (`deprecated`), B (`draft`), C (archived) and D (no lifecycle status
  key), when the caller searches or lists with default parameters, then B and D are returned, and A
  and C are excluded (AC-69). Synthesis preparation returns the same set.

### Story 2 — Lineage and stricter readings on request (P1)
- Given the same store, when the caller passes `archived="all"` and `status="all"`, then A, B, C and
  D are returned (full lineage). When the caller passes `exclude_drafts=true`, then only D is
  returned. A and C remain retrievable by id (AC-69).
- Given the same store, when the caller passes `status="deprecated"`, then only A is returned (FR-04).

### Story 3 — A supersedes claim never retires anything (P1)
- Given B declares it supersedes A, and A is `stable` and not archived, when the caller searches or
  lists with default parameters, then A is returned (AC-70).

### Story 4 — The writer sets its document's status (P1)
- Given `create_artifact` with `status="draft"`, then both stores hold `draft`. Given a create with no
  `status`, then neither store holds a `status` key, and the artifact is in force (D22).
- Given a stored `deprecated` artifact, when it is updated with `status="stable"`, then both stores
  hold `stable`. When it is updated without `status`, then both stores still hold `deprecated`;
  when it is updated with `status=null`, then neither store holds a `status` key (operator decision
  2026-10-13).

### Story 5 — Humans see the same view (P1)
- Given a deprecated own-scope artifact, when a host reads `arkeology://artifacts`, then it is not
  listed, and draft and status-less artifacts are listed (AC-52, FR-46).
- Given Studio is open, when the operator picks a lifecycle facet value, then `list_artifacts` and
  `search_artifacts` are called with the matching `status` argument (AC-54, lifecycle half).

### Story 6 — Old archive values are rejected and name the replacement (P1)
- Given a caller still sending `status="active"` or `"inactive"`, when it calls a query tool, then
  the result is `validation_error` naming `archived`. On a create or update tool, the error names
  `archive_artifact` (AC-80; D42).

## Requirements

**Storage** (FR-01, FR-09, FR-75; D22)

- WHEN a create or update receives `status` equal to exactly `draft`, `stable` or `deprecated` THE
  SYSTEM SHALL store that string under `status` in S3 object metadata and in the filterable metadata
  of every vector of the artifact.
- WHEN a create receives no `status` THE SYSTEM SHALL write no `status` key to either store. It
  never writes an empty string or a default. "No lifecycle status" is a real state, and it is in
  force.
- WHEN an update omits `status` THE SYSTEM SHALL carry the stored `status` (or its absence) forward
  unchanged, exactly as it carries `archived` forward. WHEN an update receives `status: null` THE
  SYSTEM SHALL remove the key from both stores. *Rationale (operator decision 2026-10-13):* an
  update that merely omits the field must never silently return a deprecated artifact to the
  in-force view; clearing is always explicit — `status: null` here, or `set_artifact_status` (T82).
  On `update_artifact`, `status` is therefore optional and nullable; omitted and `null` differ.
- WHEN `status` is any other value, including `active`, `inactive`, `""` or a different letter case,
  THE SYSTEM SHALL return `validation_error` naming the three accepted values and `archive_artifact`,
  and SHALL write nothing. In `create_artifacts` / `update_artifacts` only that entry fails.
  `migrate_artifacts` inherits this through its delegation.
- WHEN `update_artifact` runs THE SYSTEM SHALL replace `status` with exactly what the call supplies.
  An omitted `status` removes the key from both stores. It is not carried forward the way the archive
  marker is (see the decisions below).
- `archive_artifact` and the link-backfill tool (`link_metadata`, renamed `add_artifact_links` by
  T84) SHALL carry `status` forward unchanged in both stores. Their whole-dict copies already do this.
- THE SYSTEM SHALL NOT derive `status` from the content's frontmatter. The parameter is the only
  input (FR-01).

**The view** (FR-04, FR-67; D23–D25; status-all sentinel ADR, `## Revision — 2026-09-25`)

- `list_artifacts`, `search_artifacts` and `synthesise_artifacts` SHALL accept three view inputs.
  Each one controls exactly one clause:
  - `archived` — T76's input, unchanged (`false` by default, `true`, or `"all"`).
    `synthesise_artifacts` gains it.
  - `status` — the lifecycle filter. When it is omitted or null, the in-force lifecycle clause is
    added. `"all"` adds no lifecycle clause. `draft`, `stable` or `deprecated` adds an exact match.
  - `exclude_drafts` — `false` by default. When `true`, `draft` is added to the excluded values.
- THE SYSTEM SHALL compare `status` against `"all"` before validating it. WHEN the value is anything
  else that is not one of the three THE SYSTEM SHALL return `validation_error` naming the accepted
  values and `archived`.
- WHEN `exclude_drafts` is true and `status` is `"draft"` THE SYSTEM SHALL return `validation_error`.
  That combination could only match nothing, and the sentinel ADR forbids a silently empty result.
  When `status` is `stable` or `deprecated`, `exclude_drafts` adds no clause.
- The lifecycle clause SHALL be exactly:

  | `status` | `exclude_drafts` | Lifecycle clause |
  |---|---|---|
  | omitted / null | false | `{"$or": [{"status": {"$exists": false}}, {"status": {"$nin": ["deprecated"]}}]}` |
  | omitted / null | true | the same, with `$nin: ["deprecated", "draft"]` |
  | `"all"` | false | none |
  | `"all"` | true | the same, with `$nin: ["draft"]` |
  | `draft` / `stable` / `deprecated` | false (or true, except `draft`) | `{"status": {"$eq": <value>}}` |

- The default (in force) is `archived $eq false` AND the first row. Full lineage is
  `archived="all"` with `status="all"`, which adds neither clause.
- **Composition.** The final filter is
  `{"$and": [user filters…, commit_refs clauses (list only), archived clause?, lifecycle clause?, build_scope_filter(…), artifact_id $nin? (search loop only)]}`,
  and it is unwrapped when only one clause remains, as today. Each view clause is its own conjunct.
  The scope filter is passed through unmodified and is never wrapped, merged or replaced, and `"all"`
  removes only its own clause. `is_cross_scope_readable` still runs on every candidate. No view input
  ever widens what the gate admits.
- The view SHALL depend only on the candidate's own `status` and `archived` (D25). Building or
  applying it SHALL NOT read link annotations, `relationships`, `references`, or any other artifact.
- `read_artifact` and `arkeology://artifact/{id}` apply no view, so every artifact stays retrievable
  by id (FR-67). `find_referrers`, `purge_archived`, `check_synthesis_freshness`, `reconcile_index`
  and `propose_commit_links` gain no lifecycle clause.

**Responses** (FR-09; malformed-data ADR D2–D4 and `## Revision — 2026-09-25`)

- Every entry from list, search and synthesise SHALL carry `status`: the stored string, or `null`
  when there is none.
- WHEN a candidate's vector `status` is present but is not exactly one of the three strings THE
  SYSTEM SHALL skip it and count it under `skipped_malformed_count`, under every view.
- `read_artifact` SHALL return `status` from S3 object metadata (`null` when absent). WHEN it is
  present but invalid THE SYSTEM SHALL return `corrupt_metadata` naming `status`. The raw value is
  echoed only to an own-scope reader. The gate still runs first.

**Reconcile** (FR-17; D50)

- WHEN `reconcile_index` rebuilds an artifact's vectors THE SYSTEM SHALL copy a valid S3 `status`
  into each one, and SHALL write no `status` key when the S3 key is absent. WHEN the S3 `status` is
  invalid THE SYSTEM SHALL write no vectors for that artifact and SHALL report it under `failed`,
  with a reason naming `status`. There is no lifecycle repair pass: a missing `status` is legitimate,
  and D50's repair applies only to `archived`.

**Resources and Studio** (FR-18, FR-46, FR-48)

- `arkeology://artifacts` SHALL keep delegating to `list_artifacts`' defaults, which is the in-force
  view.
- The schema resource SHALL gain a `status` row (optional; `draft`, `stable` or `deprecated`; absent
  means no lifecycle status) and one line stating the in-force default and how to ask for full
  lineage. T89 rewrites the rest.
- Studio SHALL add a lifecycle facet next to T76's archived facet, with these options: All (the
  default, sending `status: "all"`), Not deprecated (sending no `status`), Draft, Stable and
  Deprecated. The same value goes to both `list_artifacts` and `search_artifacts`. The detail view
  SHALL show a pill with the lifecycle status when there is one.

**Removed names** (AC-80; D42; T76 `## Open Questions` item 2)

- T81 SHALL delete T76's temporary rows from the removed-name table in `server.py`:
  - (`list_artifacts`, `status`) and (`search_artifacts`, `status`);
  - (`create_artifact`, `status`) and (`update_artifact`, `status`), or (`write_artifact`, `status`)
    if T78 has not landed;
  - T76's rejection of a `status` key in bulk descriptors.

  The value checks above replace them.
- `status` SHALL reach each tool's own validation through MCP. Its input schema therefore accepts any
  string, and the accepted values are listed in the parameter description, so FastMCP does not
  pre-empt the check.

**Filterable budget** (ADR-017 `## Consequences`; budget ADR D2 and `## Revision — 2026-09-25`)

- After T81, the filterable vector key set is final for Phase 15. The changes since 2026-08-13 are:
  - out: `date` and the archive `status`;
  - in: `archived` (T76), the four provenance keys `generated_by`, `generated_at`, `revised_by` and
    `revised_at` (T79), and lifecycle `status` (T81).
- THE SYSTEM's 20-entry `commit_refs` vector cap SHALL be confirmed by re-running the 2026-08-13
  calibration method against real AWS with this key set:
  - binary-search the `commit_refs` length at which `PutVectors` rejects;
  - `put_vector` is called directly, bypassing the local guard;
  - the payload is realistic but worst-plausible (see Testing Approach).
- T81 is not done until AWS accepts at least 20 entries for that payload.

**Invariant**: from T81 on, `status` in any store, parameter or response means the OKF lifecycle and
nothing else.

### Decisions taken in this spec

**Query surface: `status` + `exclude_drafts`, with full lineage as two `"all"`s.** ADR-017
`## Deferred to the Specs` leaves the parameter shapes to the spec. Each clause has exactly one
controlling input, so no precedence rules are needed. A separate `full_lineage` switch was rejected
because it would overlap both `archived` and `status`: `full_lineage=true, archived=false` has no
obvious meaning. The recipe (`archived="all"`, `status="all"`) goes in the parameter descriptions and
the schema resource. Exclude-drafts cannot be an exact `status` value, because AC-69 requires it to
keep D, which has no status. The name `status` is reused for the filter because ADR-017 §2 binds the
`"all"` convention to it.

**`status` is a plain string on the wire.** A `Literal` enum would let FastMCP reject `"inactive"`
before dispatch, with a generic argument error that does not name `archived`, and that fails AC-80.
T76 could accept FastMCP's generic error for a bad `archived` value because its middleware row met
AC-80 for the old name. T81 deletes that row, so the tool's own check is what names the replacement. One check serves MCP and
non-MCP callers (resources, Studio fallback, tests) alike.

**The filter expression states the missing-key case explicitly.** The AWS S3 Vectors metadata
filtering page defines `$ne` ("Not equal comparison"), `$nin` ("Match none of the values in array")
and `$exists` ("Check if field exists"). It does not say whether a vector *without* the key matches
`$ne` or `$nin`. So the clause does not depend on that answer: `$exists: false` admits the
status-less artifact under either semantics, which leaves `$nin` to decide only for vectors that
carry the key.
This matters in production, not only in tests. `list_artifacts` filters client-side with
`matches_filter` (`VectorsClientImpl.list_vectors_by_metadata`), while search and synthesise filter
server-side in AWS, so if the two disagreed, list and search would disagree on the same view.

`$nin` is used for both exclusion sets rather than `$ne`, because `matches_filter` already supports
it. `$ne` stays unsupported and keeps raising `FilterEvaluationError`.

A denylist was chosen over an allowlist (`$in: [draft, stable]`), as ADR-017's literal
`status != deprecated` requires. It also means a malformed value reaches code and is counted, rather
than being dropped inside the index uncounted (the failure D50 case 3 describes for `archived`).

The cost is at most 3 filter constraints (an `ENHANCED` index counts each value, with a cap of 100
per query) and about 90 bytes of filter JSON. That fits inside the headroom
`_NIN_EXCLUSION_BYTE_BUDGET` reserves, which is unchanged.

**Update replaces `status`; it does not carry it forward.** T78 rules out partial patches: an omitted
optional field takes its create default, and for `status` that default is "none". ADR-017 §2 names
the document's writer as the owner of `status`, and the archive marker's owner as `archive_artifact`.
That is why `archived` is carried forward and `status` is not. A status change without a content
write is T82's job.

**`synthesise_artifacts` gains all three inputs.** FR-67 requires synthesis preparation to offer full
lineage, and full lineage needs the `archived` clause widened too. T76 handed this to T81 (its
Boundaries, "Never"). The same helper serves all three tools, so they cannot drift apart — the
failure the sentinel ADR records.

**Malformed values follow the malformed-data policy by the shape of the call.** A present but invalid
`status` is read successfully but cannot be interpreted. A single read therefore returns
`corrupt_metadata`, and a listing skips and counts. Reconcile writes nothing over it (D50 case 1).

**Studio's lifecycle facet defaults to All**, matching T76's archived facet, so Studio still opens on
the whole store. "Not deprecated" sends no `status`. `exclude_drafts` gets no Studio control:
AC-54 needs the facet, not the option.

## Boundaries

**Always:**
- Build both view clauses in one helper in `_search_helper.py`, by extending T76's archived-clause
  helper, and call it from list, search and synthesise.
- AND each view clause beside `build_scope_filter`'s output. Leave `_scope.py` untouched; the mutation
  Scope is unchanged.
- Compare `status` with `"all"` first. Validate with exact string membership, never case-folding.
- Keep public functions delegating to `_inner` inside `try/except Exception`, and log only through
  `logging`.

**Ask First:**
- Adding a `full_lineage` switch, a Studio `exclude_drafts` control, or a lifecycle clause to any tool
  not named above.
- Any change to `COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES`. The cap is an operator-approved decision
  (budget ADR D2). If the re-calibration shows that AWS rejects 20 entries, stop and report the
  measured boundary rather than lowering the cap.

**Never:**
- Read a `supersedes` edge, `relationships`, `references` or any annotation to decide what is in force
  (D25).
- Default a missing `status` to `stable` or any other value, in any store or response.
- Use `$ne`, or rely on what `$nin` does for a missing key, in any filter.
- Change lifecycle status without a content write (T82), or touch provenance (T79), link storage
  (T84) or the schema resource beyond its `status` row and the in-force line (T89).
- Add a lifecycle repair pass to `reconcile_index`, or migrate any stored value (T90).
- Edit README, SERVER-REFERENCE, CHANGELOG, AGENTS.md or the plugins' skills (T88, T91).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/clients/filter.py` | Modify | Add `$exists`: the operand must be a bool, and the result is `(field in metadata) == operand`. A non-bool operand raises `FilterEvaluationError`. Update the docstring: AWS does not document missing-key behaviour for `$nin`/`$ne`, nothing relies on it, and `$ne` stays unsupported |
| `src/arkeology/constants.py` | Modify | Add the three lifecycle values (a `StrEnum` in the style of the deleted `ArtifactStatus`), and update the module docstring |
| `src/arkeology/artifact.py` | Modify | `Artifact` gains an optional lifecycle `status`, validated against the three values |
| `src/arkeology/tools/write.py` | Modify | Add `status` to create and update. Both metadata dicts get the key only when it is set. Update builds them without the stored `status`. If T78 has not landed, add it to `write_artifact`, whose `overwrite` path replaces it |
| `src/arkeology/tools/write_artifacts.py` | Modify | Forward the descriptor's `status`. Remove T76's descriptor rejection |
| `src/arkeology/tools/_search_helper.py` | Modify | Add the view-clause helper (raising `InvalidFilterValueError`, which every caller already maps to `validation_error`). `build_artifact_summary` adds `status` and returns `None` for a malformed one. `run_search_loop` takes a list of view clauses in place of its single status/archived clause argument |
| `src/arkeology/tools/list.py`, `search.py`, `synthesise.py` | Modify | Add `status` and `exclude_drafts`; synthesise also gains `archived`. All go through the helper |
| `src/arkeology/tools/read.py` | Modify | Return `status`. Return `corrupt_metadata` when it is invalid, echoing the raw value only to an own-scope reader |
| `src/arkeology/tools/reconcile.py` | Modify | `_reindex_artifact` carries `status` strictly from S3 |
| `src/arkeology/resources.py` | Modify | Schema row, enum-summary line and the in-force line |
| `src/arkeology/server.py` | Modify | Signatures and docstrings for the five tools. Delete T76's `status` rows |
| `src/arkeology/static/arkeology-studio.html` | Modify | Add `sel-lifecycle`, `filterLifecycle` (default `"all"`; `""` sends no `status`), the `filterArgs` change and the lifecycle detail pill |
| `src/arkeology/tools/archive.py`, `tools/link_metadata.py` | None expected | Their whole-dict copies already carry `status`; tests pin this. *Uncertain:* confirm that T84's rename keeps the copy |
| `tests/integration/test_calibration_vector_metadata_budget.py` | Modify | Model the final key set, and assert that the cap holds (see Testing Approach) |
| `docs/learnings.md` | Modify | Add the re-measured boundary, with its date and key set, beside the 2026-08-13 calibration result. The budget ADR's D2 points there for results |
| Tests | Modify / Create | See Testing Approach |

## Contract Amendments

Amend these before writing tests (plan.md `## Phase 15`, the TDD rule):

- **`data/s3.artifact.md`** — In `## Storage Shape`, add an optional scalar `status` that is exactly
  `draft`, `stable` or `deprecated`. Absence means no lifecycle status; any other value is
  uninterpretable and is never defaulted. In `## Compatibility Guarantees`: the archive and link
  re-PUTs carry it forward, and an update replaces it.
- **`data/s3vectors.artifact.md`** — Add `status` (`str`, filterable) to the present-only-when-set
  table, with the same values. Absence means in force; an invalid value is malformed and is skipped
  and counted. Note that the filterable key mix grew by at most 22 bytes (local approximation), and
  that the `commit_refs` cap was re-confirmed against the final Phase 15 key set on the date of the
  T81 run.
- **`modules/arkeology.tools.list.md`, `arkeology.tools.search.md`** — Add `status: str | None = None`
  and `exclude_drafts: bool = False`. Invariants: the in-force default, the exact lifecycle clauses,
  `"all"` checked first, the missing key admitted through `$exists`, composition beside the scope
  filter, and no consultation of `supersedes`. Errors: `validation_error` for an unrecognised value
  (naming `archived`) and for `draft` combined with `exclude_drafts`. Entries carry `status`, and an
  invalid `status` joins the malformed-skip causes.
- **`arkeology.tools.synthesise.md`** — The same three inputs, including `archived`, replacing T76's
  fixed clause. Entries carry `status`.
- **`arkeology.tools.read.md`** — The response carries `status`, and `corrupt_metadata` now also
  covers an invalid `status`. The read applies no view.
- **`arkeology.tools.write.md`, `arkeology.tools.write_artifacts.md`** — Add optional `status` to
  create, update and the descriptors, with its validation. Update replaces it (omitted means removed).
  Delete T76's `status` rejection.
- **`arkeology.tools.migrate_artifacts.md`** — A descriptor's `status` passes through to create.
- **`arkeology.tools.reconcile.md`** — The rebuild carries `status` from S3, and an invalid value
  fails the artifact. There is no lifecycle repair.
- **`arkeology.tools.archive.md`** — Invariant: lifecycle `status` is carried unchanged in both
  stores.
- **`arkeology.resources.md`** — `arkeology://artifacts` is the in-force view (`list_artifacts`'
  defaults).

## Testing Approach

**TDD order** (each test file is red before the implementation file it gates):
1. `tests/unit/clients/test_filter.py`, then `clients/filter.py`.
2. `tests/unit/test_artifact.py`, then `artifact.py` and `constants.py`.
3. `tests/unit/test_tools_write.py`, `test_tools_write_artifacts.py`,
   `test_tools_migrate_artifacts.py`, `test_tools_archive.py` and `test_tools_link_metadata.py`
   (the carry-forward tests are red because create cannot yet take `status`), then `write.py` and
   `write_artifacts.py`.
4. `tests/unit/test_tools__search_helper.py`, then `_search_helper.py`.
5. `tests/unit/test_tools_list.py`, `test_tools_search.py` and `test_tools_synthesise.py`, then the
   three tools.
6. `tests/unit/test_tools_read.py`, then `read.py`.
7. `tests/unit/test_tools_reconcile.py`, then `reconcile.py`.
8. `tests/unit/test_resources.py`, `test_data_resources.py` and `test_server.py`, then `resources.py`
   and `server.py`.
9. `tests/static/studio-lifecycle-facet.test.js`, then `arkeology-studio.html`.
10. Integration updates.

**Moto.** No conftest change is needed. Both unit-test filter paths — the `query_vectors` extension
and `list_vectors_by_metadata`'s client-side filter — run `matches_filter`, so `$exists` reaches
them once step 1 lands.

**Unit tests (with the AC each proves):**
- Filter:
  - `$exists: false` matches metadata without the key and not metadata with it; `true` is the
    converse; a list-valued key counts as existing; a non-bool operand raises.
  - The default lifecycle clause admits `{}`, `draft` and `stable` and rejects `deprecated`. The
    exclude-drafts clause admits only `{}` and `stable`.
  - `$ne` still raises.
- Artifact: the three exact values and `None` are accepted. `Stable`, `""`, `active` and `inactive`
  are rejected.
- Write (D22, FR-75):
  - A create with `deprecated` stores it in S3 and in every vector.
  - A create without `status` leaves no key in either store.
  - An update of a `deprecated` artifact with `stable` replaces it. An update without `status`
    keeps `deprecated` in both stores. An update with `status: null` removes the key from both
    stores. The same three cases hold for each `update_artifacts` entry.
  - A create or update with `inactive` returns `validation_error` naming `archive_artifact` and
    writes nothing (AC-80).
  - In the bulk tools, a descriptor with `active` fails only that entry. A migrate descriptor's
    `status` reaches S3.
- Carry-forward: after `archive_artifact`, and after the link-backfill tool, the S3 and vector
  `status` are unchanged.
- Helper: the full truth table of (`archived`, `status`, `exclude_drafts`) maps to the exact clauses
  above. `"all"` is checked first. `"inactive"` raises with a message naming `archived`, and so does
  `draft` combined with `exclude_drafts`. `build_artifact_summary` returns `status` (or `None` when
  absent), and returns `None` for the whole entry on `"Deprecated"` or `5`.
- List, search and synthesise (parameterised):
  - With A (`deprecated`), B (`draft`), C (`stable` then archived) and D (no status): the default
    returns {B, D}; `archived="all"` with `status="all"` returns {A, B, C, D}; `exclude_drafts=True`
    returns {D}; `read_artifact` on A and C succeeds (AC-69).
  - `status="deprecated"` returns {A} (FR-04).
  - `status="all"` alone returns {A, B, D} (the clauses are independent).
  - AC-70: B carries a supersedes edge to A — in its content frontmatter, and through whichever link
    field exists when T81 lands. A is `stable`. The default view returns A. A spy shows the filter
    holds no link-field key, and no annotation read happens before filtering.
  - A spy shows the default filter is an `$and` holding the archived clause, the exact lifecycle
    clause, and `build_scope_filter`'s output verbatim.
  - A foreign tier-3 shared `deprecated` artifact is excluded by default and returned under
    `status="all"`. A foreign tier-2 artifact is never returned under any view.
  - A vector with `status: "Deprecated"` is skipped and counted, by default and under `"all"`.
  - Entries carry `status` (a string or `null`).
  - `"active"` returns `validation_error` naming `archived`, and no vector or embed call is made.
- Read: `status` is returned, and is `null` when absent. `"Deprecated"` returns `corrupt_metadata`
  naming `status`, and the raw value appears only in the own-scope message.
- Reconcile: a valid S3 `status` is rebuilt into the vectors. An absent one leaves no key. An
  invalid one lands in `failed` naming `status`, and no vectors are written.
- Resources: `arkeology://artifacts` omits a deprecated artifact and lists draft and status-less ones
  (AC-52). The schema text names `draft`, `stable` and `deprecated` and the in-force default.
- AC-80, through `fastmcp.Client(_app)`, rewriting T76's `status` tests rather than deleting them:
  - `list_artifacts(status="inactive")`, `search_artifacts(status="active")` and
    `synthesise_artifacts(status="inactive")` return `validation_error` naming `archived`.
  - `create_artifact` and `update_artifact` with `status="inactive"` name `archive_artifact`, as
    does a bulk descriptor.
  - The removed-name table holds no `status` row.
- Studio (AC-54, lifecycle half): `tests/static/studio-lifecycle-facet.test.js` slices `filterArgs`
  out of the shipped HTML with the existing `extractBlock` approach. It asserts that the facet values
  `"all"`, `"draft"`, `"stable"` and `"deprecated"` are sent as `status` verbatim, that `""` sends no
  `status` key, and that `archived` is still sent.

**Integration tests:**
- **Add** to `clients/test_vectors_filter_semantics.py` a real-AWS agreement test:
  - Write four vectors tagged with a per-run marker: `status` `draft`, `stable` and `deprecated`, and
    one with no `status`.
  - Query each of these clauses, ANDed with the marker: the default lifecycle clause, the
    exclude-drafts clause, `$exists: false`, a bare `$nin: ["deprecated"]`, and `$eq: "stable"`.
  - For each clause, assert that the set of keys AWS returns equals the set `matches_filter` admits.
  - This pins that the evaluator agrees with AWS on what T81 relies on. If only the bare `$nin`
    clause disagrees, change the evaluator's missing-key branch to match AWS and update its unit test.
    The in-force results do not change, because they never depend on that branch.
- `test_tools_read.py`: add `"status"` to the expected-field list (next to T76's `"archived"`).
- `test_tools_synthesise.py`: its `required` list keeps `"status"`, which passes again now that every
  entry carries the key. Add `"archived"` if T76 has not.
- **Re-calibrate the `commit_refs` cap** in `test_calibration_vector_metadata_budget.py` (the
  filterable-budget requirement above). This is the last integration step.
  - The calibration calls `put_vector` directly on a hand-built dict, so it does not wait for T79's
    code; it uses T79's spec'd key names.
  - Rewrite `_base_vector_metadata` to the final filterable set, keeping the original method's
    realistic tier-2 payload and 2 tags:
    - drop `date` and the archive `status`;
    - add `archived: False` and `status: "deprecated"` (the longest lifecycle value);
    - add all four provenance keys, including `revised_*` (an updated artifact). Use agent-actor
      strings shaped like `axians-developer/claude-opus-5-5` and `at` values shaped like
      `2026-10-13T16:19:13Z`;
    - set `type` to a 60-character value whose slug is the id's 60-character type slug, so the worst
      case stays consistent with itself (T77);
    - set `artifact_id` to the run's write prefix plus a 141-character generated tier-2 id with its
      `.md` extension. The id is a 60-character type slug, a 10-character date, a 60-character title
      slug, an 8-character hash and 3 dashes. Per T87's spec ("No new length exposure"), that is the
      longest id once T77's open type list lands; a supplied id is capped at 128.
  - Add one assertion, `max_passing >= COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES`. The existing
    convergence assertions stay. This makes "the cap of 20 clears" pass/fail rather than only
    logged. Report the margin (`max_passing` − 20) alongside the boundary.
  - Run it alone:
    `uv run pytest tests/integration/test_calibration_vector_metadata_budget.py -s --log-cli-level=INFO`.
  - Record the passing and failing counts and their local byte figures in `docs/learnings.md`. The
    2026-08-13 baseline was 36 / 37.
    - T79 estimates that its keys consume about 4 entries.
    - The id adds about 105 bytes over the old 39-character probe key. That is roughly 2–3 entries,
      at about 44 bytes for each JSON-encoded SHA.
    - The 60-character `type` adds about 49 bytes over `code_review`, roughly 1 entry.
    - A boundary near 28–29 is therefore expected.
  - If the assertion fails, follow Boundaries, "Ask First".
- Not broken: every other file. `status` is optional, and T76 has already removed the old kwargs.

## Open Questions

None blocking. ADR-017, requirements.md and plan.md agree for this task. Hand-offs:

1. **`commit_refs` cap re-calibration** — T81 owns it, per plan.md's T81 entry (Testing Approach, last integration step).
2. **`status="all"` from a pre-Phase-15 caller is accepted with a new meaning.** It used to mean
   "every archive state". It now means "every lifecycle state, not archived". It cannot be rejected
   without breaking the lifecycle `"all"` that ADR-017 §2 requires. T91's **Breaking** CHANGELOG entry
   should say so.
3. **AC-70 once T84 lands.** T84's spec should keep the AC-70 test, with B carrying a structured
   `relationships` `supersedes` edge.
4. **Ordering with T78.** T81 is blocked only by T76. If T81 lands first, T78's `update_artifact`
   must take `status` with the carry-forward semantics above (omitted keeps, `null` clears).

---
type: spec
title: T50 — Unified Own-Scope referenced_by Warning on Delete + Archive
description: Before deleting or archiving an artifact, reverse-lookup other own-scope artifacts referencing it across both source_artifacts and references, branching by field filterability — a server-side $eq list-membership filter for filterable reference fields (references) and a filterable prefilter (type=synthesis) plus in-process membership check for the non-filterable source_artifacts. Warn-but-don't-block — delete stronger (permanent), archive informational (reversible). Strictly own-scope; never reveal foreign-scope identifiers.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t50-referenced-by-warning
status: ready
phase: 12
task: 50
references:
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "architect"
  date: "2026-07-03"
---

# T50 — Unified Own-Scope `referenced_by` Warning on Delete + Archive

> **Superseded 2026-08-17 (architect, `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`
> D2, narrowed in T60).** This spec's central design is a two-way branch: `references` is resolved
> with a server-side `$eq` list-membership filter (the "filterable" branch), while `source_artifacts`
> is resolved with a `type = synthesis` prefilter plus in-process membership check (the
> "non-filterable" branch), and the two are unioned. Once T58 removes `references` from vector
> metadata entirely, the filterable branch's `$eq` clause can no longer match anything — the
> `references`-half of this warning silently stops finding referrers rather than erroring, which is
> the same class of drift T59 closes for `list_artifacts`'s `references=` filter. T60 closes it here
> by narrowing `REFERENCE_FIELDS` to `("source_artifacts",)` — `find_referrers`'s mechanism (own-scope
> gate, warn-but-don't-block, delete/archive phrasing, `REFERENCE_FIELDS` as single source of truth)
> is otherwise unaffected, but the filterable branch described throughout Story 4, the two branching
> Requirements bullets, and the corresponding Boundaries bullets no longer has a live member to act
> on. See `docs/specs/p12-t58-commit-refs-cap-references-removal.md` and
> `docs/specs/p12-t60-narrow-reverse-lookup-warning.md` for the current, authoritative contract.

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Generalize `delete_artifact`'s synthesis-only reference check into a single unified own-scope
`referenced_by` check covering **both** `source_artifacts` (synthesis provenance) and the new
`references` field. The lookup **branches by field filterability** (T55's
`NON_FILTERABLE_METADATA_KEYS`): a **filterable** reference field (`references`) is resolved with a
server-side `$eq` list-membership filter, while the **non-filterable** `source_artifacts` — which
S3 Vectors cannot `$eq`-filter — is resolved with a filterable prefilter (`type = synthesis`,
own-scope, active) plus an in-process membership check, exactly as `delete_artifact` does today.
Referrers from both mechanisms are unioned and deduplicated. Apply it to both `delete_artifact`
(permanent → stronger warning) and `archive_artifact` (reversible → informational). It is
warn-but-don't-block and strictly own-scope: a foreign-scope referrer is never revealed. The
reverse-lookup fields are centralised in one `REFERENCE_FIELDS` constant, and the filterable/
non-filterable split is driven by `NON_FILTERABLE_METADATA_KEYS`, so a future *filterable*
reference field is covered by a single addition. (FR-56, AC-61; generalizes FR-21.)

## Problem Statement

`delete_artifact` today only warns when the target is a `source_artifact` of an active synthesis;
`archive_artifact` warns not at all. With `references` now a first-class field (T46), an artifact
can be pointed at by any type of artifact, and archiving/deleting it can leave dangling references.
Operators need to know before they act — but the check must never leak foreign-scope identifiers
(the standing non-negotiable rule) and must not fetch-all-then-filter. A subtlety forces a two-way
branch: `source_artifacts` is a **non-filterable** metadata key (T55's `NON_FILTERABLE_METADATA_KEYS`
— it can hold up to ~100 ids, over the 2 KB filterable budget, and appears only on `synthesis`), so
S3 Vectors **rejects a server-side `$eq` on it with `ValidationException`**. A single blanket
server-side `$eq` over both fields (as an earlier draft assumed) therefore fails. `references` is
filterable and resolves server-side; `source_artifacts` must use the same filterable-prefilter +
in-process membership check `delete_artifact` already performs.

## User Stories

### Story 1 — Delete warns on any own-scope referrer (P1)

**Acceptance criteria:**
- Given an own-scope artifact `T` that is listed in another own-scope artifact's `references`, when
  `delete_artifact(T, confirm=True)` is called then `T` is deleted AND the response includes a
  warning listing the referring identifier(s). (AC-61)
- Given `T` is a `source_artifact` of an active own-scope synthesis, when deleted then the synthesis
  identifier appears in the same unified warning (existing behaviour preserved).
- Given `T` is referenced via both `source_artifacts` and `references` by different own-scope
  artifacts, then all referrers appear in the warning (deduplicated).
- Given the delete warning, then it is phrased as a **stronger** (permanent-action) warning.

### Story 2 — Archive warns informationally (P1)

**Acceptance criteria:**
- Given an own-scope artifact `T` referenced by another own-scope artifact, when
  `archive_artifact(T)` is called then `T` is archived AND the response includes an
  **informational** warning listing the referrers. (AC-61)
- Given no referrers, when archive/delete runs then no warning field is added.

### Story 3 — Strictly own-scope (P1)

**Acceptance criteria:**
- Given a foreign-scope artifact that references `T`, when `T` is deleted or archived then that
  foreign-scope referrer is NEVER listed in the warning. (AC-61)

### Story 4 — Filterability-aware reverse-lookup (P1)

> **Superseded 2026-08-17 (T60).** This story's acceptance criteria describe the pre-T60 two-branch
> contract, where `references` was `REFERENCE_FIELDS`'s one filterable member. As of T60,
> `REFERENCE_FIELDS = ("source_artifacts",)` — there is no filterable member left, so only the
> `source_artifacts` bullet below still applies; the `references` server-side `$eq` bullet describes
> retired behaviour. See `docs/specs/p12-t60-narrow-reverse-lookup-warning.md`.

**Acceptance criteria (pre-T60, superseded — retained for decision history):**
- Given a **filterable** reference field (`references` — a `REFERENCE_FIELDS` member NOT in
  `NON_FILTERABLE_METADATA_KEYS`), when the reverse-lookup runs then it is resolved with a
  server-side `$eq` list-membership filter (`{"references": {"$eq": T}}`) ANDed with the own-scope +
  active-status filter — a single query with an `$or` over the filterable reference fields — not a
  fetch-all-then-filter scan.
- Given the **non-filterable** reference field `source_artifacts` (a `REFERENCE_FIELDS` member that
  IS in `NON_FILTERABLE_METADATA_KEYS`, which S3 Vectors cannot `$eq`-filter), when the
  reverse-lookup runs then it is resolved by a field-appropriate filterable prefilter
  (`type = synthesis`, own-scope, active) fetched server-side followed by an in-process
  `source_artifacts` membership check — exactly as `delete_artifact` does today — and **no
  server-side `$eq` is ever issued on `source_artifacts`** (which would raise `ValidationException`).
- Given both mechanisms return referrers, then they are unioned and deduplicated into the single
  warning.

## Requirements

- WHEN `delete_artifact` or `archive_artifact` is about to act on an existing own-scope `artifact_id`
  THE SYSTEM SHALL classify each field of the single `REFERENCE_FIELDS` constant — the authoritative
  list of reverse-lookup-bearing metadata fields, `("source_artifacts", "references")` — by its
  membership in T55's `NON_FILTERABLE_METADATA_KEYS`, resolve referrers by the branch matching each
  field's filterability (below), then union and deduplicate the results into one warning.
- WHEN a reference field is **filterable** (a `REFERENCE_FIELDS` member NOT in
  `NON_FILTERABLE_METADATA_KEYS` — currently `references`) THE SYSTEM SHALL resolve its referrers with
  a single `list_vectors_by_metadata` query ANDing the own-scope filter
  (`{"scope": {"$eq": settings.write_prefix}}`), the active-status filter, and an `$or` of one
  `{field: {"$eq": artifact_id}}` clause per filterable reference field. Adding a future *filterable*
  reference field is a one-line addition to `REFERENCE_FIELDS`, never a query change in each tool.
- WHEN a reference field is **non-filterable** (a `REFERENCE_FIELDS` member that IS in
  `NON_FILTERABLE_METADATA_KEYS` — currently `source_artifacts`) THE SYSTEM SHALL resolve its
  referrers with a field-appropriate **filterable prefilter fetched server-side** (for
  `source_artifacts`: `{"type": {"$eq": "synthesis"}}` ANDed with own-scope and active status)
  followed by an **in-process membership check** of `artifact_id` in each candidate's field value,
  and SHALL NOT issue a server-side `$eq` on the non-filterable field. Adding a future *non-filterable*
  reference field requires declaring its own field-appropriate prefilter (there is no generic one).
- WHEN referrers are found THE SYSTEM SHALL collect their distinct `artifact_id`s (excluding the
  target itself) and include them in a `warnings` (delete) / `warning` (archive) field in the
  response, deduplicated.
- WHEN no referrers are found THE SYSTEM SHALL omit the warning field entirely.
- WHEN a referrer is outside the own scope THE SYSTEM SHALL never include it (guaranteed by the
  own-scope filter clause).
- WHEN the reverse-lookup encounters a `CredentialError` THE SYSTEM SHALL return a structured
  credential error (as the existing synthesis check does).
- WHEN the operation proceeds THE SYSTEM SHALL still perform the delete / archive — the warning never
  blocks (warn-but-don't-block).
- WHEN `delete_artifact` builds the warning THE SYSTEM SHALL phrase it as a stronger permanent-action
  warning; `archive_artifact` SHALL phrase it as informational (reversible).

## Boundaries

**Always:**
- The reverse-lookup is **strictly own-scope** (non-negotiable rule — never reveal foreign-scope
  identifiers).

> **Forward-pointer note (2026-07-06, shipped in `2aa1633`).** This own-scope-only reverse-lookup is
> a distinct concern from a separate decision that filters the `references` *field itself* when it
> is returned to a foreign-scope reader over `read_artifact` / `list_artifacts` (dropping entries
> the reader could not independently read). That decision does not change this task's mechanism —
> this reverse-lookup never returns a foreign-scope referrer regardless — but both narrow the same
> general leakage surface (what a `references` value can reveal to a reader) from different angles.
> See `docs/specs/p12-t46-references-field.md`'s forward-pointer note and ADR-012's "Cross-scope
> reference visibility" section.
- **Filterable** reference fields (`references`) use a **server-side `$eq`** list-membership filter —
  never fetch-all-then-filter (ADR-012 D13).
- The **non-filterable** `source_artifacts` cannot be `$eq`-filtered by S3 Vectors, so it is resolved
  by a **bounded** filterable prefilter fetched server-side (`type = synthesis`, own-scope, active — a
  small set, since `source_artifacts` only ever appears on `synthesis`) followed by an in-process
  membership check, exactly as `delete_artifact` does today. This is **NOT** an unbounded
  fetch-all-then-filter: the prefilter is server-side and narrow.
- `delete_artifact` keeps its existing vectors-first-then-S3 ordering and confirm gate; this task
  only replaces/broadens the reference-check step.
- Deduplicate referrers across both mechanisms and across sections of the same referrer.
- The reverse-lookup field set is defined once in a `REFERENCE_FIELDS` constant (single source of
  truth, mirroring how `ARTIFACT_TYPES` centralises artifact types) and consumed by both tools; the
  **filterable/non-filterable branch is driven by** T55's `NON_FILTERABLE_METADATA_KEYS` — the check
  is classification-driven, not hardcoded per tool. `source_artifacts` staying in user-defined
  metadata while `references`/`commit_refs` use annotations (ADR-011) does not affect this — the
  reverse-lookup reads **vector metadata**, where all reference-like fields are `list[str]`.

**Ask First:**
- Nothing — behaviour fixed by ADR-012 D13.

**Never:**
- Do not block the operation on a warning.
- Do not include the target artifact itself as its own referrer.
- Do not extend the check across scopes (re-opens the closed cross-scope leakage concern).
- Do not issue a server-side `$eq` on a non-filterable metadata key (`source_artifacts`) — S3 Vectors
  rejects it with `ValidationException`; use the `type = synthesis` prefilter + in-process check.
- Do not fetch-all-then-filter without a filterable prefilter — for `source_artifacts` the prefilter
  (`type = synthesis`, own-scope, active) is mandatory and bounds the fetched set server-side.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_delete.py` | Modify | Broaden warning tests: `references` referrer, unified dedup, own-scope-only, stronger phrasing — Red first |
| `src/arkeology/tools/delete.py` | Modify | Replace Step-4 synthesis-only check with a call to the shared `find_referrers` helper (which internally still performs the `type = synthesis` prefilter + in-process `source_artifacts` check for the non-filterable branch, plus the new server-side `$eq` on `references`) |
| `tests/unit/test_tools_archive.py` | Modify | Add referenced_by informational-warning + own-scope-only tests — Red first |
| `src/arkeology/tools/archive.py` | Modify | Add the same `find_referrers` reverse-lookup before archiving; add `warning` to the response when referrers exist |
| `src/arkeology/artifact.py` | Modify | Add the `REFERENCE_FIELDS` constant — single source of truth for reverse-lookup-bearing fields, next to `ARTIFACT_TYPES`; value `("source_artifacts", "references")`. **`NON_FILTERABLE_METADATA_KEYS` is added by T55 (dependency)** — do not duplicate it here; import/consume it |
| `src/arkeology/tools/_search_helper.py` | Modify | Extract a shared `find_referrers(vectors, settings, artifact_id)` helper that **branches by filterability**: partition `REFERENCE_FIELDS` on membership in `NON_FILTERABLE_METADATA_KEYS`; for filterable members build one server-side query (own-scope + active + `$or` of `{field: {"$eq": artifact_id}}`); for `source_artifacts` (non-filterable) run the `type = synthesis` filterable prefilter then the in-process membership check; union + dedup. Reused by both `delete.py` and `archive.py`. Reuse `coerce_list_field` for the in-process membership check |

## Testing Approach

**TDD cycle — test file before implementation file in each pair:**

1. **`test_tools_delete.py` → `delete.py`**
   - Referrer via `references` (filterable) → deleted + warning lists the referrer; assert the
     server-side `$eq` on `references` (own-scope + active + `$or`) was passed to
     `list_vectors_by_metadata` via `mocker.spy`.
   - Referrer via `source_artifacts` (non-filterable) → found via the `type = synthesis` filterable
     prefilter + in-process membership check; existing behaviour preserved.
   - **No server-side `$eq` on `source_artifacts`** → assert (via `mocker.spy` on
     `list_vectors_by_metadata`) that no filter argument contains a `{"source_artifacts": {"$eq": …}}`
     clause; the `source_artifacts` prefilter is `{"type": {"$eq": "synthesis"}}`.
   - Both kinds of referrer → unified, deduplicated warning (union of both branches).
   - Foreign-scope referrer → never listed (seed a foreign-scope vector referencing `T`; the
     own-scope filter clause on both branches excludes it).
   - No referrers → no warning field; delete still succeeds.
   - Delete warning phrased stronger than archive.

2. **`test_tools_archive.py` → `archive.py`**
   - Referenced artifact archived + informational warning; own-scope-only; no-referrer no-warning;
     `CredentialError` → structured error.

Use `aws_mock`, `s3_client`, `vectors_client_2` fixtures; pre-seed referrer vectors via
`put_vectors_batch`.

## Dependencies

- **T46** — `references` must be in vector metadata as `list[str]` for the filterable `$eq` branch.
- **T55** — provides `NON_FILTERABLE_METADATA_KEYS` (the authoritative non-filterable-key set), the
  single source of truth that drives the filterable/non-filterable branch. T50 consumes this
  constant by reference (it must not redefine, duplicate, or hard-code its value). Sequence T55
  before (or with) T50.

## Open Questions

- **Should `commit_refs` join `REFERENCE_FIELDS`?** The metadata-filterability decision names
  `commit_refs` as a *filterable* field alongside `references`, which would place it in the
  server-side `$eq` branch automatically if added to `REFERENCE_FIELDS`. This spec deliberately keeps
  `REFERENCE_FIELDS = ("source_artifacts", "references")` because (a) PRD FR-56 and ADR-012 D13 scope
  the `referenced_by` check to `source_artifacts` + `references` only, and (b) `commit_refs` holds git
  commit SHAs, not `artifact_id`s, so a `{"commit_refs": {"$eq": T}}` clause could never match an
  artifact-id target — including it would be inert noise. `commit_refs` therefore stands as the
  canonical *future filterable reference field* the branch would cover automatically, not a current
  member. Confirm with the operator whether `commit_refs` should nonetheless be added; if so it is a
  one-line addition and no code-path change (it lands in the filterable branch).

  > **Closed 2026-08-17 (T60).** Moot: T60 narrows `REFERENCE_FIELDS` to `("source_artifacts",)` and
  > removes the filterable branch entirely — its one filterable member, `references`, no longer
  > resolves anything once T58 removes `references` from vector metadata. There is no longer a
  > filterable branch for `commit_refs` to join by addition. See
  > `docs/specs/p12-t60-narrow-reverse-lookup-warning.md`.

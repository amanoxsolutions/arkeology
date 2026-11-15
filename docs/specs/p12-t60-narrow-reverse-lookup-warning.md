---
type: Spec
id: p12-t60-narrow-reverse-lookup-warning
title: T60 — Narrow the Delete/Archive Reverse-Lookup Warning to source_artifacts Only
description: Once T58 removes references from S3 Vectors metadata, find_referrers' references-half server-side $eq scan can no longer match anything. The delete/archive reverse lookup checks source_artifacts alone, by one bounded type=synthesis query and an in-process membership check, with no field-list constant and no filterable branch, and the accepted references gap is documented in the tool docstrings rather than filled by an unbounded full-corpus annotation scan.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/brainstorming/brainstorming-2026-08-13-artifact-metadata-budget-overflow.md
    title: Artifact Metadata Budget Overflow — Guard Coverage, Calibration, and Migration Self-Heal
    last_modified: 2026-08-13T00:00:00Z
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t50-referenced-by-warning.md
    title: T50 — Unified Own-Scope referenced_by Warning on Delete + Archive
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/contracts/modules/arkeology.tools.delete.md
    title: arkeology.tools.delete
  - resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
relationships:
  - to: p12-t50-referenced-by-warning
    type: supersedes
generated:
  by: "axians-architect/claude-sonnet-5"
  at: 2026-08-17T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T60 — Narrow the Delete/Archive Reverse-Lookup Warning to `source_artifacts` Only

## TL;DR

The `referenced_by` warning on delete and archive rests on `find_referrers`, a reverse lookup of the own-scope artifacts that reference the target. Once T58 removes `references` from vector metadata, no server-side query on `references` can match, so the warning's `references`-half would silently find nothing — the same class of problem T59 closes for `list_artifacts`. This spec makes the lookup what it can serve: one field, `source_artifacts`, found by one bounded `type=synthesis` query and an in-process membership check — the synthesis-source check that existed before T50 — with no constant listing reference fields and no branch on field filterability. The gap is documented explicitly in the tool docstrings, not silently absorbed. (brainstorming-2026-08-13-artifact-metadata-budget-overflow D6 / OQ6.)

## 1. Problem Statement

`delete_artifact` and `archive_artifact` warn about own-scope artifacts that reference the target, covering both `source_artifacts` (synthesis provenance) and `references` (T50). The `references`-half of that warning depends entirely on `references` being a filterable vector-metadata field so `find_referrers` can resolve it with a single bounded server-side query. Once T58 ships, there is no vector-side representation of `references` left to query — the only remaining complete copy is the S3 annotation, and scanning annotations across the whole own-scope corpus to find who references a given target would be an unbounded full-corpus scan, which the project's own design principles (and brainstorming-2026-08-13-artifact-metadata-budget-overflow D6) explicitly reject as a substitute. The correct fix is to stop attempting the `references`-half of the reverse-lookup and say so plainly, rather than letting it silently return nothing while implying completeness.

This spec replaces T50 (`p12-t50-referenced-by-warning`), whose two-branch reverse-lookup it retires. The warning's behaviour that does not depend on the lookup is stated in `arkeology.tools.delete` § delete_artifact and `arkeology.tools.archive` § archive_artifact: the `referenced_by` check warns but never blocks the operation, with permanent-action phrasing on delete and reversible-action phrasing on archive; it names own-scope, active referrers only, and never a foreign-scope one; a successful response carries the referring artifact ids in `referrers` and the human-readable warning in `warning_message`, both present only when such a referrer was found; and a `CredentialError` during the check returns `credential_error`.

All three user stories are P1: the `source_artifacts`-based warning is unaffected (R5), the `references`-based warning is no longer attempted (R3, R6), and the gap is documented, not silently absorbed (R7).

## 2. Rules — The narrowed reverse-lookup

### R1 — The reverse lookup checks `source_artifacts` alone, named directly

`find_referrers` checks one field, `source_artifacts`, and names it directly: no constant lists the fields the reverse lookup covers, and `artifact.py` defines no `REFERENCE_FIELDS`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2; brainstorming-2026-08-13-artifact-metadata-budget-overflow D6, OQ6

### R2 — `find_referrers`'s docstring records why `references` is not checked

`find_referrers`'s docstring records why `references` is not checked (T58 removed it from vector metadata; a full-corpus annotation scan was rejected as a substitute — brainstorming-2026-08-13-artifact-metadata-budget-overflow D6), so a future reader is not tempted to add it back without re-deriving the same trade-off.

Source: brainstorming-2026-08-13-artifact-metadata-budget-overflow D6 (the rejected-scan part)

### R3 — `find_referrers` issues no `references` `$eq` clause

When an own-scope artifact `T` is listed in another own-scope artifact's `references` (and is **not** also a `source_artifact` of any synthesis) and `find_referrers` runs, it issues no server-side `$eq` query clause referencing `references` at all — confirmed via `mocker.spy` on `list_vectors_by_metadata`, asserting the built filter never contains a `{"references": {"$eq": ...}}` clause.

Source: None

### R4 — `find_referrers` makes one lookup

When `find_referrers` runs, it makes one query — own scope, active status and `type=synthesis` — and keeps each returned synthesis whose `source_artifacts` contains the target, excluding the target itself; it builds no `$or` of per-field clauses and partitions no field list by filterability.

**Example**

- Given an active own-scope synthesis whose `source_artifacts` lists `T`, when `find_referrers` runs for `T`, then its one `list_vectors_by_metadata` filter is the own-scope, active, `type=synthesis` conjunction, and the synthesis is returned.

Source: None

## 3. Rules — The `referenced_by` warning on delete and archive

### R5 — The `source_artifacts`-based warning is unaffected

When an own-scope artifact `T` is a `source_artifact` of an active own-scope synthesis and `delete_artifact(T, confirm=True)` or `archive_artifact(T)` is called, the response's `referrers` still includes the referring synthesis identifier, and `warning_message` is present — identical to today's behaviour, with no functional regression. Every existing `source_artifacts` assertion in the existing `source_artifacts`-based warning test suite (T50) continues to pass unmodified.

Source: p12-t50-referenced-by-warning (the existing test suite)

### R6 — `references`-based referrers are no longer reported

When an own-scope artifact `T` is listed in another own-scope artifact's `references` (and is **not** also a `source_artifact` of any synthesis) and `T` is deleted or archived, the response does **not** include that referrer in `referrers` — the `references`-half of the check is no longer performed, and this is expected, not a bug.

Source: None

## 4. Rules — Documenting the gap

### R7 — `delete_artifact`'s and `archive_artifact`'s docstrings state the gap explicitly

`delete_artifact`'s and `archive_artifact`'s docstrings state the `references` reverse-lookup gap explicitly: a developer or agent reading either docstring is told that the `referenced_by` reverse-lookup covers `source_artifacts` only, that `references`-based referrers are not detected, and briefly why (an unbounded full-corpus annotation scan was evaluated and rejected — see the ADR).

Source: None

### R8 — No new response field signals the gap

When a response is returned from `delete_artifact` or `archive_artifact`, no new response field is added to signal the gap — the limitation is static and universal (true of every call, not conditional on any particular artifact), so it belongs in the docstring the caller reads once, not repeated in every response payload.

**Why:** Response field vs. docstring-only documentation of the gap — resolved by this spec, flagged to the PM as a judgment call in case `plan.md`'s "response" wording was meant literally. Plan.md's task description says the gap should be "documented in the tool's response/docstring." This spec chose **docstring-only**: the limitation is static and true of every call (not conditional on the specific artifact or its referrers), so repeating it in every response would be noise inconsistent with how the codebase documents other static, universal limitations (e.g. requirements.md's own Constraints table, not a per-response field). The alternative — a static `"reference_scan_note"`-style field on every delete/archive response — was considered and rejected as adding permanent payload noise for a fact that does not vary per call.

Source: None

## 5. Boundaries

**Always:**
- `find_referrers`'s dedup and own-scope/active-status filtering are unchanged; its lookup is the single bounded `type=synthesis` query with the in-process `source_artifacts` membership check (R4).
- This narrowing is an accepted, documented capability loss (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2; brainstorming-2026-08-13-artifact-metadata-budget-overflow D6, OQ6), not a defect to be silently worked around with a fallback scan.

**Ask First:**
- Nothing — the decision to narrow rather than substitute an unbounded scan is locked (brainstorming-2026-08-13-artifact-metadata-budget-overflow D6, explicitly rejects the unbounded full-corpus annotation scan as a substitute).

**Never:**
- Do not add an unbounded, fetch-all-then-filter annotation scan across the own-scope corpus as a `references`-half substitute — this is the specific alternative the ADR rejects.
- Do not silently drop the `references`-half of the warning without updating the docstrings — the gap must be documented, per Story 3 (R7).
- Do not keep a field-list constant or a filterable/non-filterable branch in the reverse lookup — revisit when a second field that holds artifact identifiers must reach the delete/archive warning (`commit_refs` never can: it holds commit SHAs).

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_delete.py` | Modify | Update/remove the `references`-referrer-found test (T50) to assert it is **no longer** found; add a `mocker.spy`-based assertion that no `{"references": {"$eq": ...}}` clause is ever built; keep the `source_artifacts`-referrer test passing unchanged — Red first |
| `tests/unit/test_tools_archive.py` | Modify | Same narrowing assertions as `test_tools_delete.py`, mirrored for archive's informational warning — Red first |
| `src/arkeology/artifact.py` | Modify | Remove `REFERENCE_FIELDS` and its comment; the rationale moves to `find_referrers`'s docstring (R2) |
| `src/arkeology/tools/delete.py` | Modify | Update docstring to state the `references` reverse-lookup gap explicitly; no logic change (delegates to `find_referrers`, unchanged) |
| `src/arkeology/tools/archive.py` | Modify | Same docstring update as `delete.py`; no logic change |
| `src/arkeology/tools/_search_helper.py` | Modify | `find_referrers` makes R4's one lookup: drop the `REFERENCE_FIELDS` / `NON_FILTERABLE_METADATA_KEYS` imports it used for the partition, the per-field `$or` and the filterable branch; its docstring states R2's rationale |

### Contracts

- `docs/contracts/modules/arkeology.tools.delete.md` § delete_artifact — the `source_artifacts`-only referrer check over active own-scope syntheses, and the `referrers` and `warning_message` keys (R1, R4–R6, R8).
- `docs/contracts/modules/arkeology.tools.archive.md` § archive_artifact — the same check and keys on archive (R1, R4–R6, R8).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — `references` absent from vector metadata, so no `$eq` clause on it can match (R3).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_delete.py` / `test_tools_archive.py` → `_search_helper.py`, `artifact.py`** — seed an own-scope artifact whose only referrer relationship is via `references` (not `source_artifacts`); call delete/archive; assert the referrer is **not** listed in `referrers` (and that neither `referrers` nor `warning_message` is present, if that was the only referrer); assert (via `mocker.spy` on `list_vectors_by_metadata`) the built filter expression never contains a `references` clause. Seed a second artifact referenced via `source_artifacts` (an active synthesis) in the same test run and assert its warning is unaffected — proving the `source_artifacts` lookup is unaffected. Assert the one filter expression `list_vectors_by_metadata` receives is the own-scope, active, `type=synthesis` conjunction with no `$or` (R4).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; reuse T50's existing fixture-seeding pattern.

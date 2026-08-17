---
type: spec
title: T60 — Narrow the Delete/Archive Reverse-Lookup Warning to source_artifacts Only
description: Once T58 removes references from S3 Vectors metadata, find_referrers references-half server-side $eq scan can no longer match anything. Narrow REFERENCE_FIELDS to source_artifacts only, preserving find_referrers unchanged and documenting the accepted references gap in the tool docstrings rather than adding an unbounded full-corpus annotation scan as a substitute.
tags: []
timestamp: 2026-08-17T00:00:00Z
okf_version: "0.1"
feature: p12-t60-narrow-reverse-lookup-warning
status: ready
phase: 12
task: 60
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
  - docs/specs/p12-t50-referenced-by-warning.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
authored:
  by: "architect"
  date: "2026-08-17"
---

# T60 — Narrow the Delete/Archive Reverse-Lookup Warning to `source_artifacts` Only

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

T50's `find_referrers` helper resolves `REFERENCE_FIELDS` (`("source_artifacts", "references")`) into a single combined query: a server-side `$eq` clause per *filterable* field (today, `references`) OR'd with a bounded `type=synthesis` prefilter for the one *non-filterable* field (`source_artifacts`). Once T58 removes `references` from vector metadata, its `$eq` clause can never match, so the `references`-half of the `referenced_by` warning silently stops finding anything — the same class of problem T59 closes for `list_artifacts`. This task narrows `REFERENCE_FIELDS` to `("source_artifacts",)`, which — because `find_referrers` already branches generically on field filterability — requires no change to `find_referrers`'s logic at all; it naturally degrades to exactly its pre-T50 `source_artifacts`-only behaviour. The gap is documented explicitly in the tool docstrings, not silently absorbed. (ADR D6 / brainstorming OQ6.)

## Problem Statement

`delete_artifact` and `archive_artifact` warn about own-scope artifacts that reference the target, covering both `source_artifacts` (synthesis provenance) and `references` (T50). The `references`-half of that warning depends entirely on `references` being a filterable vector-metadata field so `find_referrers` can resolve it with a single bounded server-side query. Once T58 ships, there is no vector-side representation of `references` left to query — the only remaining complete copy is the S3 annotation, and scanning annotations across the whole own-scope corpus to find who references a given target would be an unbounded full-corpus scan, which the project's own design principles (and this ADR's own D6) explicitly reject as a substitute. The correct fix is to stop attempting the `references`-half of the reverse-lookup and say so plainly, rather than letting it silently return nothing while implying completeness.

## User Stories

### Story 1 — `source_artifacts`-based warning is unaffected (P1)

**Acceptance criteria:**
- Given an own-scope artifact `T` is a `source_artifact` of an active own-scope synthesis, when `delete_artifact(T, confirm=True)` or `archive_artifact(T)` is called then the response still includes the referring synthesis identifier in the warning — identical to today's behaviour, with no functional regression.
- Given the existing `source_artifacts`-based warning test suite (T50), when this task lands then every existing `source_artifacts` assertion continues to pass unmodified.

### Story 2 — `references`-based warning no longer attempted (P1)

**Acceptance criteria:**
- Given an own-scope artifact `T` is listed in another own-scope artifact's `references` (and is **not** also a `source_artifact` of any synthesis), when `T` is deleted or archived, then the response does **not** include that referrer in the warning — the `references`-half of the check is no longer performed, and this is expected, not a bug.
- Given the same scenario, when `find_referrers` runs, then it issues no server-side `$eq` query clause referencing `references` at all — confirmed via `mocker.spy` on `list_vectors_by_metadata`, asserting the built filter never contains a `{"references": {"$eq": ...}}` clause.

### Story 3 — Gap documented, not silently absorbed (P1)

**Acceptance criteria:**
- Given a developer or agent reads `delete_artifact`'s or `archive_artifact`'s docstring, then it states explicitly that the `referenced_by` reverse-lookup covers `source_artifacts` only as of this task, that `references`-based referrers are not detected, and briefly why (an unbounded full-corpus annotation scan was evaluated and rejected — see the ADR).

## Requirements

- WHEN `REFERENCE_FIELDS` is defined in `artifact.py` THE SYSTEM SHALL contain only `"source_artifacts"` — remove `"references"` from the tuple.
- WHEN `REFERENCE_FIELDS`'s docstring/comment is updated THE SYSTEM SHALL record why `"references"` was removed (T58 removed it from vector metadata; a full-corpus annotation scan was rejected as a substitute — ADR D6) rather than leaving a bare change with no rationale, so a future reader is not tempted to silently re-add it without re-deriving the same trade-off.
- WHEN `find_referrers` runs with the narrowed `REFERENCE_FIELDS` THE SYSTEM SHALL require **no code change** — its existing filterable/non-filterable partition (`[f for f in REFERENCE_FIELDS if f not in NON_FILTERABLE_METADATA_KEYS]` / `if f in NON_FILTERABLE_METADATA_KEYS`) naturally yields an empty `filterable_fields` list and an unchanged `non_filterable_fields = ["source_artifacts"]`, producing the same `type=synthesis`-prefilter-only query it built before T50 added `references`.
- WHEN `delete_artifact`'s and `archive_artifact`'s docstrings are updated THE SYSTEM SHALL state the `references` reverse-lookup gap explicitly (Story 3).
- WHEN a response is returned from `delete_artifact` or `archive_artifact` THE SYSTEM SHALL NOT add any new response field to signal the gap — the limitation is static and universal (true of every call, not conditional on any particular artifact), so it belongs in the docstring the caller reads once, not repeated in every response payload (see Open Questions for the alternative considered and why it was not chosen).

## Boundaries

**Always:**
- `find_referrers`'s query-building logic, dedup, and own-scope/active-status filtering are unchanged by this task — only the `REFERENCE_FIELDS` constant it consumes changes.
- The `source_artifacts` reverse-lookup mechanism (bounded `type=synthesis` prefilter + in-process membership check) is completely unaffected.
- This narrowing is an accepted, documented capability loss (ADR D2/D6, brainstorming OQ6), not a defect to be silently worked around with a fallback scan.

**Ask First:**
- Nothing — the decision to narrow rather than substitute an unbounded scan is locked (ADR D6, explicitly rejects the unbounded full-corpus annotation scan as a substitute).

**Never:**
- Do not add an unbounded, fetch-all-then-filter annotation scan across the own-scope corpus as a `references`-half substitute — this is the specific alternative the ADR rejects.
- Do not silently drop the `references`-half of the warning without updating the docstrings — the gap must be documented, per Story 3.
- Do not remove `REFERENCE_FIELDS` as a constant or inline its single remaining value — keep it as a named, single-source-of-truth tuple (mirroring `ARTIFACT_TYPES`), since T50's own Open Questions already flag `commit_refs` as a plausible future filterable addition to this same constant.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_delete.py` | Modify | Update/remove the `references`-referrer-found test (T50) to assert it is **no longer** found; add a `mocker.spy`-based assertion that no `{"references": {"$eq": ...}}` clause is ever built; keep the `source_artifacts`-referrer test passing unchanged — Red first |
| `tests/unit/test_tools_archive.py` | Modify | Same narrowing assertions as `test_tools_delete.py`, mirrored for archive's informational warning — Red first |
| `src/arkeology/artifact.py` | Modify | Change `REFERENCE_FIELDS: tuple[str, ...] = ("source_artifacts", "references")` to `("source_artifacts",)`; update its docstring/comment with the rationale |
| `src/arkeology/tools/delete.py` | Modify | Update docstring to state the `references` reverse-lookup gap explicitly; no logic change (delegates to `find_referrers`, unchanged) |
| `src/arkeology/tools/archive.py` | Modify | Same docstring update as `delete.py`; no logic change |
| `src/arkeology/tools/_search_helper.py` | Not touched | `find_referrers` needs no code change — confirm via the new tests that the narrowed constant alone produces the correct degraded query |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_delete.py` / `test_tools_archive.py` → `artifact.py`** — seed an own-scope artifact whose only referrer relationship is via `references` (not `source_artifacts`); call delete/archive; assert the referrer is **not** listed in the warning (or no warning field at all, if that was the only referrer); assert (via `mocker.spy` on `list_vectors_by_metadata`) the built filter expression never contains a `references` clause. Seed a second artifact referenced via `source_artifacts` (an active synthesis) in the same test run and assert its warning is unaffected — proving the two mechanisms are independent and only one was narrowed.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; reuse T50's existing fixture-seeding pattern.

## Open Questions

- **Response field vs. docstring-only documentation of the gap (resolved, documented here for the PM).** Plan.md's task description says the gap should be "documented in the tool's response/docstring." This spec chose **docstring-only**: the limitation is static and true of every call (not conditional on the specific artifact or its referrers), so repeating it in every response would be noise inconsistent with how the codebase documents other static, universal limitations (e.g. the PRD's own "Known Limitations" section, not a per-response field). The alternative — a static `"reference_scan_note"`-style field on every delete/archive response — was considered and rejected as adding permanent payload noise for a fact that does not vary per call. Flagged to the PM as a judgment call in case the "response" wording was meant literally.

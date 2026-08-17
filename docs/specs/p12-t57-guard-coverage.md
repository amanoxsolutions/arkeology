---
type: spec
title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix (I-4)
description: Call the existing check_metadata_budgets guard from the two vector-metadata-writing paths that currently skip it entirely — link_metadata.py (before its annotation write, inside the CAS retry loop) and reconcile.py (before its put_vector call) — so an oversize commit_refs/references payload is rejected before either path durably writes anything, closing review findings B-1 and B-2. Also folds in review finding I-4 — link_metadata.py's `_validate_supplied_link_values` never checks for control characters, unlike Artifact.validate_commit_refs/validate_references — by having it delegate to those classmethods directly instead of maintaining a hand-rolled parallel implementation that can drift.
tags: []
timestamp: 2026-08-17T00:00:00Z
okf_version: "0.1"
feature: p12-t57-guard-coverage
status: ready
phase: 12
task: 57
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/specs/p12-t49-link-metadata.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/reviews/review-2026-08-13-full-codebase-max.md
authored:
  by: "architect"
  date: "2026-08-17"
---

# T57 — Guard Coverage in `link_metadata.py` and `reconcile.py` + Control-Character Validation Fix (I-4)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

`check_metadata_budgets` (T55) is called in exactly two places today, both inside `write.py`. `link_metadata.py` and `reconcile.py` each independently assemble and write vector metadata (`put_vectors_batch` / `put_vector`) with **zero** budget check, so either path can durably write metadata that a fresh `write_artifact` call would reject outright — this is review findings B-1 and B-2, and the root cause of the incident's permanent partial write. This task adds one `check_metadata_budgets(s3_metadata={}, vector_metadata=...)` call to each path, at the point that most closely mirrors `write.py`'s own placement, so a rejection happens before either path durably writes anything. (ADR D1.)

Folded into the same spec (review finding I-4): `link_metadata.py`'s hand-rolled `_validate_supplied_link_values` claims to enforce "the same per-element constraints `Artifact.validate_commit_refs`/`validate_references` enforce on write," but only checks for empty/whitespace-only values and commas — it never checks for control characters, the one constraint `_require_no_control_chars` actually enforces on every other write path. A control character in a supplied `commit_refs`/`references` element therefore bypasses the `Artifact` model's invariant entirely via `link_metadata`, because `link_metadata.py` never constructs an `Artifact` instance for the merged result. This task is already reopening `link_metadata.py`'s per-attempt validation dispatch for the guard-coverage fix above, so the fix lands here rather than as a separate task.

## Problem Statement

`link_metadata.py` writes durable S3 annotations **first**, then vector metadata — durable-first ordering exists precisely so a vector-write failure leaves the annotation side already correct for `reconcile_index` to heal later (T49). But because no budget check runs anywhere in this path, an oversize merged `commit_refs`/`references` value can pass straight through: the annotation write succeeds (durably, unrecoverably in the un-budgeted sense — the annotation store itself has generous headroom, see ADR "Verified real constraints"), and the subsequent vector write then fails against AWS's real `PutVectors` accounting, which the local approximation under-measures (ADR D2, calibration). The artifact is now permanently desynced: annotation-side link fields say one thing, the vector index has none, and every later attempt to fix it (a further `link_metadata` call, or `reconcile_index`) re-derives the identical oversize payload and fails identically, forever — this is finding B-1.

`reconcile.py`'s `_reindex_artifact` is meant to be the self-heal path for exactly this kind of stuck artifact (via failure-log replay or orphan scan). But it has the same missing guard (finding B-2): it re-derives `vector_metadata` from `read_current_link_fields` (the union of both durable stores) and calls `put_vector` directly, with no size check. An artifact stuck by the B-1 mechanism is therefore **not self-healed** by reconcile — it fails identically, silently, every run, which is precisely the "self-perpetuating failure-log replay" outcome `p12-t55`'s own TL;DR states must never happen.

Both gaps must close together: fixing only `link_metadata.py` leaves `reconcile_index` unable to repair anything that manages to get durably written by some other path; fixing only `reconcile.py` leaves `link_metadata.py` free to keep creating new instances of the same stuck state.

## User Stories

### Story 1 — `link_metadata` rejects an oversize merge before writing anything (P1)

**Acceptance criteria:**
- Given a `link_metadata` call whose merged (existing ∪ supplied) `commit_refs`/`references` would breach any of the three budgets measured by `check_metadata_budgets`, when the call runs then it returns a structured `validation_error` and makes **no** `put_object_annotation` call and **no** `put_vectors_batch` call for that `artifact_id` — the annotation side is never touched, so nothing durable is left half-written.
- Given the same oversize condition is only reached *after* the read-forward merge (the supplied values alone would have passed), when the call runs then it is still rejected — the check measures the merged, about-to-be-written state, not the caller's raw input.
- Given a CAS retry attempt (a concurrent content-changing write raced the annotation write, `ArtifactConflictError` on the first attempt), when the cycle re-reads and re-merges the caller's original supplied values into fresh state, then the budget check re-runs against the freshly merged state on every attempt — not only the first.
- Given a `link_metadata` call over multiple `artifact_ids` where an earlier `artifact_id` was already linked successfully before a later one hits the oversize rejection, then the response's `linked`/`skipped` counts reflect the earlier successes (existing partial-progress convention, unchanged) and the oversize `artifact_id` is not counted in either.
- Given a `commit_refs`/`references` merge that stays within all three budgets, when the call runs then it succeeds exactly as today — this task changes no passing-case behaviour.

### Story 2 — `reconcile_index` rejects an oversize rebuild before writing anything (P1)

**Acceptance criteria:**
- Given an artifact whose rebuilt `vector_metadata` (assembled in `_reindex_artifact`, including `commit_refs`/`references` from `read_current_link_fields`) would breach any of the three budgets, when `reconcile_index` attempts to re-index it — via failure-log replay (Phase 1) or orphan scan (Phase 2) — then no `put_vector` call is made for that artifact, and the failure is reported in the existing `failed` list (not a crash, not a silent skip).
- Given the same artifact is re-indexed via either replay path, then both paths reject it identically (they share `_reindex_artifact`).
- Given an artifact whose rebuilt `vector_metadata` stays within all three budgets, when reconcile runs then re-indexing succeeds exactly as today.

### Story 3 — `link_metadata` rejects a control character in a supplied `commit_refs`/`references` element (P1, I-4)

**Acceptance criteria:**
- Given a `link_metadata` call whose supplied `commit_refs` or `references` list contains an element with a Unicode `Cc` control character (e.g. `"abc\x01def"`), when the call runs then it returns a structured `validation_error` and makes **no** `put_object_annotation` call and **no** `put_vectors_batch` call for that `artifact_id` — matching the `Artifact` model's existing behaviour on every other write path (`write_artifact`, `write_artifacts`, the read-forward component of an overwrite).
- Given a `link_metadata` call whose supplied values contain no control characters, no commas, and no empty/whitespace-only elements, when the call runs then validation behaves exactly as today — this story changes no passing-case behaviour.
- Given a `link_metadata` call over multiple `artifact_ids` (the supplied `commit_refs`/`references` lists are call-level parameters applied identically to every `artifact_id`), when a control character is present, then the whole call is rejected before any `artifact_id` is touched — the existing up-front validation loop (which runs once per call, before the per-`artifact_id` loop starts) already has this property for the empty/whitespace/comma checks, and the control-character check joins it at the same place, unchanged in position.

## Requirements

- WHEN `link_metadata`'s per-artifact CAS loop (`_apply_link_metadata_with_cas`) has computed the merged `commit_refs`/`references` for the current attempt THE SYSTEM SHALL assemble a candidate vector-metadata dict (the existing indexed vector metadata for one representative vector of the artifact, with `commit_refs`/`references` set to the merged values, or removed when empty — mirroring the existing set/pop pattern already used before `put_vectors_batch`) and call `check_metadata_budgets(s3_metadata={}, vector_metadata=candidate)` **before** the `apply_link_annotations` call for that attempt.
- WHEN that check raises `MetadataTooLargeError` THE SYSTEM SHALL propagate it out of `_apply_link_metadata_with_cas`, and `_link_metadata_inner` SHALL catch it and return `{"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}` — following the same partial-progress convention already used for `AnnotationUnavailableError` (include `linked`/`skipped` only when non-zero) — without calling `apply_link_annotations` or `put_vectors_batch` for that `artifact_id`.
- WHEN `_apply_link_metadata_with_cas` needs the existing vector metadata to build the candidate THE SYSTEM SHALL receive it as a new required parameter from its caller, which already fetches it (`vectors.get_vectors(keys)`, called before `_apply_link_metadata_with_cas` today) — no new vector fetch is introduced.
- WHEN `_reindex_artifact` has assembled its full `vector_metadata` dict (including `commit_refs`/`references`, after the existing `if commit_refs_list: ...` / `if references_list: ...` assignments) THE SYSTEM SHALL call `check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)` once, before the first `bedrock.embed`/`put_vector` call in either the per-section loop or the single-document fallback branch.
- WHEN that check raises `MetadataTooLargeError` THE SYSTEM SHALL let it propagate out of `_reindex_artifact` unchanged — `reconcile_index`'s existing generic `except Exception as exc: failed.append(...)` handling in both Phase 1 and Phase 2 already converts any such exception into a structured `failed` entry; no new except clause is required in `reconcile.py`.
- WHEN either guard call is made THE SYSTEM SHALL pass `s3_metadata={}` — neither `link_metadata.py` nor `reconcile.py` writes S3 user-defined object metadata, so there is nothing to measure on that side.
- WHEN `_validate_supplied_link_values` has confirmed a supplied element is non-empty and non-whitespace-only THE SYSTEM SHALL delegate the control-character and comma checks to `Artifact.validate_commit_refs(values)` / `Artifact.validate_references(values)` (called directly as plain classmethods on the full supplied list for the field being checked — verified callable outside model construction, returning the list unchanged on success and raising `ValueError` with a descriptive message on the first violation) rather than re-implementing `_require_no_control_chars`/`_require_no_comma`'s logic inline.
- WHEN that delegated call raises `ValueError` THE SYSTEM SHALL catch it and return its message string as the `validation_error`'s `message` — mirroring the existing return-message shape `_validate_supplied_link_values` already uses for its own checks.
- WHEN the delegated call succeeds for both `commit_refs` and `references` (or an empty list, which both classmethods already accept) THE SYSTEM SHALL proceed exactly as today — this requirement changes no passing-case behaviour.

## Boundaries

**Always:**
- Reuse `check_metadata_budgets` exactly as `write.py` calls it — do not write a bespoke size check inside either file (D1, rejected alternative).
- The `link_metadata.py` check must run **before the annotation write**, not only before `put_vectors_batch` — `link_metadata` writes annotations first, so a check placed only before the vector write would still leave a durably-written oversize annotation behind (this is the specific mechanism of finding B-1). This is the one place this task's guard placement differs from `write.py`'s (which checks before its single durable write, `put_object`, since `write.py`'s annotation write happens *after* `put_object` and is itself best-effort/degradable — see `p12-t47`).
- All vectors belonging to one artifact carry identical metadata content apart from the vector key itself (the write path builds one `vector_metadata` dict and reuses it for every section — see `write.py` and `reconcile.py`'s own `_reindex_artifact`). Using any single existing vector's metadata as the representative base for `link_metadata`'s candidate-budget check is therefore accurate for the whole batch; there is no per-vector variation to miss.
- The `reconcile.py` check runs once per re-index, after `vector_metadata` is fully assembled and before it is used — since the same dict object is reused for every `put_vector` call in the function, checking it once covers every call.
- Delegate the control-character and comma checks to `Artifact.validate_commit_refs`/`validate_references` directly (verified viable — see Requirements) rather than reimplementing `_require_no_control_chars`/`_require_no_comma` a second time. This is the review's own recommendation for I-4 and closes the exact drift risk it flags: a future change to either `_require_*` helper (e.g. a new forbidden character class) would otherwise need to be manually mirrored into `link_metadata.py` to stay correct, and I-4 is proof that mirroring already failed once.
- Keep the existing empty/whitespace-only rejection in `_validate_supplied_link_values` — this is a `link_metadata`-specific constraint the `Artifact` model does not itself enforce (an element `Artifact` would silently accept), and I-4 does not ask for it to be removed, only for the missing control-character check to be added.

**Ask First:**
- Nothing — placement and behaviour are fixed by ADR D1; the I-4 delegation shape (call the classmethods directly, verified callable outside model construction) has no open design choice either.

**Never:**
- Do not implement the control-character check inline in `link_metadata.py` (e.g. by importing `_require_no_control_chars` directly) unless the classmethod-delegation approach above is found to be non-viable during implementation — it was verified viable during spec-writing (`Artifact.validate_commit_refs(["ok"])` and a control-character case were both exercised directly against the current codebase), so this fallback is not expected to be needed. If it is invoked, the spec's Requirements section must be updated with the concrete reason before proceeding — do not silently diverge from the delegation shape specified here.
- Do not check `link_metadata.py`'s budget only before `put_vectors_batch` — see the "Always" note above; this would still allow the annotation write to durably commit an oversize value.
- Do not let a `MetadataTooLargeError` raised inside `_reindex_artifact` abort the whole `reconcile_index` call — it must be caught by the existing per-entry generic exception handling and reported in `failed`, exactly like any other re-index failure.
- Do not introduce a second vector fetch in `link_metadata.py` to obtain existing metadata for the candidate check — `items` (from `vectors.get_vectors(keys)`) is already fetched before `_apply_link_metadata_with_cas` is called; thread it through as a parameter instead.
- Do not add a `reconcile_attempts`/retry-bounding mechanism here — that is T62's independent scope. This task only adds the missing size check; an artifact that fails this new check in `reconcile_index` will replay identically every run until T62 lands.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_link_metadata.py` | Modify | Add: oversize merged value → `validation_error`, zero `put_object_annotation`/`put_vectors_batch` calls (`mocker.spy`); oversize-only-after-merge case; CAS-retry re-checks on each attempt; passing case unchanged; **I-4:** a supplied `commit_refs`/`references` element containing a control character → `validation_error`, zero writes; a supplied element with a control character but otherwise passing the empty/whitespace/comma checks is still rejected (proves the delegated call, not just the pre-existing checks, is exercised) — Red first |
| `src/arkeology/tools/link_metadata.py` | Modify | Add `existing_vector_metadata` parameter to `_apply_link_metadata_with_cas`; assemble candidate and call `check_metadata_budgets` before `apply_link_annotations` inside the per-attempt loop; catch `MetadataTooLargeError` in `_link_metadata_inner` and return `validation_error`. **I-4:** import `Artifact` from `arkeology.artifact`; in `_validate_supplied_link_values`, after the existing empty/whitespace-only check, wrap a call to `Artifact.validate_commit_refs(values)` / `Artifact.validate_references(values)` (selected by `field`) in `try`/`except ValueError as exc: return str(exc)` |
| `tests/unit/test_tools_reconcile.py` | Modify | Add: oversize rebuilt `vector_metadata` → `_reindex_artifact` raises `MetadataTooLargeError`, `reconcile_index` reports it in `failed`, zero `put_vector` calls for that artifact (both Phase 1 and Phase 2 call sites); passing case unchanged — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Add one `check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)` call in `_reindex_artifact`, after `vector_metadata` is fully assembled and before the per-section/fallback embed+write logic; import `check_metadata_budgets` from `arkeology.artifact` |
| `tests/integration/test_tools_link_metadata.py` | Modify (flag) | Real-AWS: an oversize merge is rejected with no annotation or vector write — Red for integration, if a suitable fixture exists |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_link_metadata.py` → `link_metadata.py`** — seed an artifact with an existing `commit_refs`/`references` vector-metadata payload sized so a further merge breaches `VECTOR_FILTERABLE_METADATA_MAX_BYTES`; call `link_metadata` with a supplied value that pushes it over; assert `validation_error`, zero `put_object_annotation` calls, zero `put_vectors_batch` calls (`mocker.spy` on both). Assert a merge that only breaches the budget *after* combining existing + supplied is still rejected (supplied alone would pass). Assert a normal, within-budget call still succeeds unchanged.
2. **`test_tools_reconcile.py` → `reconcile.py`** — seed an S3 object + failure-log entry (or orphan condition) whose annotations, when unioned into `vector_metadata` by `_reindex_artifact`, breach a budget; run `reconcile_index`; assert the artifact appears in `failed` with a size-related reason, zero `put_vector` calls for it (`mocker.spy`), and a normal artifact still reconciles successfully in the same run.
3. **`test_tools_link_metadata.py` → `link_metadata.py`** (I-4) — call `link_metadata` with a supplied `commit_refs` element containing a Unicode `Cc` control character (e.g. `"abc\x01def"`); assert `validation_error`, zero `put_object_annotation` calls, zero `put_vectors_batch` calls (`mocker.spy` on both). Repeat for `references`. Assert a supplied element with no control character, no comma, and no empty/whitespace-only content still succeeds unchanged (regression guard for the delegation change).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings.

## Open Questions

*(none — placement, error mapping, and scope are fixed by ADR D1; this task is a pure prerequisite for T58. The I-4 delegation shape (direct classmethod call) was verified viable against the current codebase during spec-writing — see Boundaries — so it carries no open design question either.)*

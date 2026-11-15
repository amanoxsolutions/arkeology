---
type: Spec
id: p12-t57-guard-coverage
title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
description: "Call the existing check_metadata_budgets guard from the two vector-metadata-writing paths that currently skip it entirely — link_metadata.py (before its annotation write, inside the CAS retry loop) and reconcile.py (before its put_vector call) — so an oversize commit_refs payload is rejected before either path durably writes anything. This is the root cause of the 2026-08-13 incident's permanent partial write. Also closes a related gap: link_metadata.py's `_validate_supplied_link_values` never checks for control characters, unlike Artifact.validate_commit_refs/validate_references — fixed by having it delegate to those classmethods directly instead of maintaining a hand-rolled parallel implementation that can drift."
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/specs/p12-t55-metadata-validation.md
    title: T55 — Write-Path Metadata Size + Charset Validation
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t49-link-metadata.md
    title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t48-reconcile-from-annotations.md
    title: T48 — reconcile_index Rebuilds commit_refs + references from Annotations
    last_modified: 2026-09-06T00:00:00Z
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
generated:
  by: "axians-architect/claude-sonnet-5"
  at: 2026-08-17T00:00:00Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-15T20:36:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T57 — Guard Coverage in `link_metadata.py` and `reconcile.py` + Control-Character Validation Fix

## TL;DR

`check_metadata_budgets` (T55) is called in exactly two places today, both inside `write.py`.
`link_metadata.py` and `reconcile.py` each independently assemble and write vector metadata
(`put_vectors_batch` / `put_vector`) with **zero** budget check, so either path can durably write
metadata that a fresh `write_artifact` call would reject outright — this is the root cause of the
incident's permanent partial write. This task adds one `check_metadata_budgets(s3_metadata={},
vector_metadata=...)` call to each path, at the point that most closely mirrors `write.py`'s own
placement, so a rejection happens before either path durably writes anything.
(adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1.) It also makes
`link_metadata.py`'s `_validate_supplied_link_values` delegate its control-character and comma
checks to `Artifact.validate_commit_refs`/`validate_references`, so a control character in a
supplied `commit_refs`/`references` element no longer bypasses the `Artifact` model's invariant.

## 1. Problem Statement

`link_metadata.py` writes durable S3 annotations **first**, then vector metadata — durable-first
ordering exists precisely so a vector-write failure leaves the annotation side already correct for
`reconcile_index` to heal later (T49). But because no budget check runs anywhere in this path, an
oversize merged `commit_refs` value can pass straight through: the annotation write
succeeds (durably, unrecoverably in the un-budgeted sense — the annotation store itself has generous
headroom, see ADR "Verified real constraints"), and the subsequent vector write then fails against
AWS's real `PutVectors` accounting, which the local approximation under-measures
(adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2, calibration). The artifact is now
permanently desynced: annotation-side link fields say one thing, the vector index has none, and
every later attempt to fix it (a further `link_metadata` call, or `reconcile_index`) re-derives the
identical oversize payload and fails identically, forever.

`reconcile.py`'s `_reindex_artifact` is meant to be the self-heal path for exactly this kind of stuck artifact (via failure-log replay or orphan scan). But it has the same missing guard: it re-derives `vector_metadata` from the annotation copy of `commit_refs` — the sole source of the link fields, read by `annotations.read_link_annotations`, which raises on a failed read rather than returning empty — and calls `put_vector` directly, with no size check. An artifact stuck by that mechanism is therefore **not self-healed** by reconcile — it fails identically, silently, every run, which is precisely the "self-perpetuating failure-log replay" outcome `p12-t55`'s own TL;DR states must never happen.

Both gaps must close together: fixing only `link_metadata.py` leaves `reconcile_index` unable to repair anything that manages to get durably written by some other path; fixing only `reconcile.py` leaves `link_metadata.py` free to keep creating new instances of the same stuck state.

Folded into the same spec: `link_metadata.py`'s hand-rolled `_validate_supplied_link_values` claims to enforce "the same per-element constraints `Artifact.validate_commit_refs`/`validate_references` enforce on write," but only checks for empty/whitespace-only values and commas — it never checks for control characters, the one constraint `_require_no_control_chars` actually enforces on every other write path. A control character in a supplied `commit_refs`/`references` element therefore bypasses the `Artifact` model's invariant entirely via `link_metadata`, because `link_metadata.py` never constructs an `Artifact` instance for the merged result. This task is already reopening `link_metadata.py`'s per-attempt validation dispatch for the guard-coverage fix above, so the fix lands here rather than as a separate task.

This task is a pure prerequisite for T58. All three user stories of the earlier format —
`link_metadata` rejects an oversize merge before writing anything; `reconcile_index` rejects an
oversize rebuild before writing anything; `link_metadata` rejects a control character in a supplied
`commit_refs`/`references` element — are P1.

## 2. Rules — Budget guard in `link_metadata`

### R1 — `link_metadata` checks the merged state before the annotation write, on every CAS attempt

When `link_metadata`'s per-artifact CAS loop (`_apply_link_metadata_with_cas`) has computed the
merged `commit_refs`/`references` for the current attempt, it assembles a candidate vector-metadata
dict — the vector metadata that attempt is about to write, built from the existing indexed vector
metadata of one representative vector of the artifact, with the vector-metadata copy of the merged
`commit_refs` that `arkeology.tools.link_metadata` § link_metadata states (capped, or removed when
empty) and with no `references` key, mirroring the set/pop pattern used before `put_vectors_batch`
— and calls `check_metadata_budgets(s3_metadata={}, vector_metadata=candidate)` **before** the
`apply_link_annotations` call for that attempt. The check measures the merged, about-to-be-written
state, not the caller's raw input, and re-runs against the freshly merged state on every CAS
attempt — not only the first.

**Example**

- Given the oversize condition is only reached *after* the read-forward merge (the supplied values
  alone would have passed), when the call runs, then it is still rejected.
- Given a CAS retry attempt (a concurrent content-changing write raced the annotation write,
  `ArtifactConflictError` on the first attempt), when the cycle re-reads and re-merges the caller's
  original supplied values into fresh state, then the budget check re-runs against the freshly
  merged state on every attempt — not only the first.
- Given a merge whose `references` or uncapped `commit_refs`, were either placed in vector metadata,
  would breach the filterable budget, but whose candidate — capped `commit_refs`, no `references` —
  stays within all three budgets, when the call runs, then it succeeds.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1

### R2 — An oversize `link_metadata` merge returns `validation_error` and writes nothing for that artifact

When that check raises `MetadataTooLargeError`, the error propagates out of
`_apply_link_metadata_with_cas`, and `_link_metadata_inner` catches it and returns
`{"error": ErrorCode.VALIDATION_ERROR, "message": str(exc)}`, naming that `artifact_id` and the
ones already linked as for every per-artifact failure that stops the call
(`p12-t49-link-metadata` R13) — without calling `apply_link_annotations` or `put_vectors_batch`
for that `artifact_id`.
A merge whose candidate stays within all three budgets succeeds exactly as today — no passing-case
behaviour changes.

**Example**

- Given a `link_metadata` call whose candidate built from the merged (existing ∪ supplied)
  `commit_refs` (R1) would breach any of the three budgets measured by `check_metadata_budgets`,
  when the call runs, then it
  returns a structured `validation_error` and makes **no** `put_object_annotation` call and **no**
  `put_vectors_batch` call for that `artifact_id` — the annotation side is never touched, so nothing
  durable is left half-written.
- Given a `link_metadata` call over multiple `artifact_ids` where an earlier `artifact_id` was
  already linked successfully before a later one hits the oversize rejection, then the response
  names the oversize `artifact_id`, its `linked_ids` and `linked` count include the earlier
  success, and the oversize `artifact_id` is counted in neither `linked` nor `skipped`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1; p12-t49-link-metadata R13

### R3 — The candidate's existing vector metadata comes from the caller's existing fetch

When `_apply_link_metadata_with_cas` needs the existing vector metadata to build the candidate, it
receives it as a new required parameter from its caller, which already fetches it
(`vectors.get_vectors(keys)`, called before `_apply_link_metadata_with_cas` today) — no new vector
fetch is introduced.

Source: None

## 3. Rules — Budget guard in `reconcile_index`

### R4 — `_reindex_artifact` checks the assembled `vector_metadata` once, before the first embed or vector write

When `_reindex_artifact` has assembled its full `vector_metadata` dict — including the capped
`commit_refs` read from the annotation, after the existing `if commit_refs_list: ...` assignment,
and never `references` (`s3vectors.artifact` § Storage Shape) — it calls `check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)`
once, before the first `bedrock.embed`/`put_vector` call in either the per-section loop or the
single-document fallback branch.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1

### R5 — An oversize rebuild is reported in `failed` with `validation_error`, with no vector write for that artifact

When that check raises `MetadataTooLargeError`, the error propagates out of `_reindex_artifact`
unchanged, and `reconcile_index`'s per-artifact handling in both Phase 1 and Phase 2 reports the
artifact in `failed` — or, on the failure-log replay once its retry budget is spent, in
`stuck_failures` — with `error` `validation_error`, the code that counts toward the retry bound
(`arkeology.tools.reconcile` § reconcile_index). An artifact whose rebuilt `vector_metadata` stays
within all three budgets re-indexes exactly as today.

**Example**

- Given an artifact whose rebuilt `vector_metadata` (assembled in `_reindex_artifact`, including
  the capped `commit_refs` from `annotations.read_link_annotations`) would breach any of the three
  budgets,
  when `reconcile_index` attempts to re-index it — via failure-log replay (Phase 1) or orphan scan
  (Phase 2) — then no `put_vector` call is made for that artifact, and the failure is reported in
  `failed` with `error: "validation_error"` (not a crash, not a silent skip).
- Given the same artifact is re-indexed via either replay path, then both paths reject it
  identically (they share `_reindex_artifact`).

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1

## 4. Rules — Both guard calls

### R6 — Both guard calls pass an empty `s3_metadata`

When either guard call is made, it passes `s3_metadata={}` — neither `link_metadata.py` nor
`reconcile.py` writes S3 user-defined object metadata, so there is nothing to measure on that side.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1

## 5. Rules — Control-character validation in `link_metadata`

### R7 — `_validate_supplied_link_values` delegates the control-character and comma checks to the `Artifact` classmethods

When `_validate_supplied_link_values` has confirmed a supplied element is non-empty and
non-whitespace-only, it delegates the control-character and comma checks to
`Artifact.validate_commit_refs(values)` / `Artifact.validate_references(values)` (called directly as
plain classmethods on the full supplied list for the field being checked — verified callable outside
model construction, returning the list unchanged on success and raising `ValueError` with a
descriptive message on the first violation) rather than re-implementing
`_require_no_control_chars`/`_require_no_comma`'s logic inline. When that delegated call raises
`ValueError`, it is caught and its message string is returned as the `validation_error`'s
`message` — mirroring the existing return-message shape `_validate_supplied_link_values` already
uses for its own checks. The delegated call carries every per-element check the model makes, so a
supplied `references` element without the scope separator is rejected here exactly as on a write
(`p12-t55-metadata-validation` R10). When the delegated call succeeds for both `commit_refs` and
`references` (or an empty list, which both classmethods already accept), validation proceeds
exactly as today — no passing-case behaviour changes.

**Example**

- Given a `link_metadata` call whose supplied `commit_refs` or `references` list contains an
  element with a Unicode `Cc` control character (e.g. `"abc\x01def"`), when the call runs, then it
  returns a structured `validation_error` and makes **no** `put_object_annotation` call and **no**
  `put_vectors_batch` call for that `artifact_id` — matching the `Artifact` model's existing
  behaviour on every other write path (`write_artifact`, `write_artifacts`, the read-forward
  component of an overwrite).
- Given `link_metadata(artifact_ids=[id], references=["adr-use-postgres-abc12345"])`, when the call
  runs, then it returns a structured `validation_error` naming `references` and makes no write.
- Given a `link_metadata` call whose supplied values contain no control characters, no commas, and
  no empty/whitespace-only elements, and whose `references` elements are full keys such as
  `team-a/payments/adr-use-postgres-abc12345.md`, when the call runs, then validation behaves
  exactly as today.

Source: None

### R8 — A control character rejects the whole call before any `artifact_id` is touched

The supplied `commit_refs`/`references` lists are call-level parameters applied identically to every
`artifact_id`. When a `link_metadata` call over multiple `artifact_ids` carries an element failing
any check delegated in R7 — a control character, or a `references` element without the scope
separator — the whole call is rejected before any `artifact_id` is touched: the existing up-front
validation loop (which runs once per call, before the per-`artifact_id` loop starts) already has
this property for the empty/whitespace/comma checks, and the delegated checks join it at the same
place, unchanged in position.

Source: None

## 6. Boundaries

**Always:**
- Reuse `check_metadata_budgets` exactly as `write.py` calls it — do not write a bespoke size check inside either file (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1, rejected alternative).
- The `link_metadata.py` check must run **before the annotation write**, not only before `put_vectors_batch` — `link_metadata` writes annotations first, so a check placed only before the vector write would still leave a durably-written oversize annotation behind (this is the specific mechanism of the incident described in the ADR). This is the one place this task's guard placement differs from `write.py`'s (which checks before its single durable write, `put_object`, since `write.py`'s annotation write happens *after* `put_object`, and a failure there is an error whose failure-log entry carries the link values — see `p12-t47` R13).
- All vectors belonging to one artifact carry identical metadata content apart from the vector key itself (the write path builds one `vector_metadata` dict and reuses it for every section — see `write.py` and `reconcile.py`'s own `_reindex_artifact`). Using any single existing vector's metadata as the representative base for `link_metadata`'s candidate-budget check is therefore accurate for the whole batch; there is no per-vector variation to miss.
- The `reconcile.py` check runs once per re-index, after `vector_metadata` is fully assembled and before it is used — since the same dict object is reused for every `put_vector` call in the function, checking it once covers every call.
- Delegate the control-character and comma checks to `Artifact.validate_commit_refs`/`validate_references` directly (verified viable — see R7) rather than reimplementing `_require_no_control_chars`/`_require_no_comma` a second time. This closes the exact drift risk of a hand-rolled parallel implementation: a future change to either `_require_*` helper (e.g. a new forbidden character class) would otherwise need to be manually mirrored into `link_metadata.py` to stay correct, and the missing control-character check is proof that mirroring already failed once.
- Keep the existing empty/whitespace-only rejection in `_validate_supplied_link_values` — this is a `link_metadata`-specific constraint the `Artifact` model does not itself enforce (an element `Artifact` would silently accept); only the missing control-character check needs to be added, not removed.

**Ask First:**
- Nothing — placement and behaviour are fixed by
  adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D1; the control-character delegation
  shape (call the classmethods directly, verified callable outside model construction) has no open
  design choice either.

**Never:**
- Do not implement the control-character check inline in `link_metadata.py` (e.g. by importing `_require_no_control_chars` directly) unless the classmethod-delegation approach above is found to be non-viable during implementation — it was verified viable during spec-writing (`Artifact.validate_commit_refs(["ok"])` and a control-character case were both exercised directly against the current codebase), so this fallback is not expected to be needed. If it is invoked, the spec's R7 must be updated with the concrete reason before proceeding — do not silently diverge from the delegation shape specified here.
- Do not check `link_metadata.py`'s budget only before `put_vectors_batch` — see the "Always" note above; this would still allow the annotation write to durably commit an oversize value.
- Do not let a `MetadataTooLargeError` raised inside `_reindex_artifact` abort the whole `reconcile_index` call — it must be caught by the per-entry exception handling and reported in `failed` with `validation_error` (R5).
- Do not introduce a second vector fetch in `link_metadata.py` to obtain existing metadata for the candidate check — `items` (from `vectors.get_vectors(keys)`) is already fetched before `_apply_link_metadata_with_cas` is called; thread it through as a parameter instead.
- Do not add a `reconcile_attempts`/retry-bounding mechanism here — bounding the replay of an artifact that fails this check is `p12-t62-bounded-reconcile-retry` R5's; this task only adds the missing size check.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_link_metadata.py` | Modify | Add: oversize merged value → `validation_error`, zero `put_object_annotation`/`put_vectors_batch` calls (`mocker.spy`); oversize-only-after-merge case; a large `references` or uncapped `commit_refs` whose capped candidate fits → success (R1); CAS-retry re-checks on each attempt; passing case unchanged; **control-character check:** a supplied `commit_refs`/`references` element containing a control character → `validation_error`, zero writes; a supplied element with a control character but otherwise passing the empty/whitespace/comma checks is still rejected (proves the delegated call, not just the pre-existing checks, is exercised); a supplied `references` element without the scope separator → `validation_error`, zero writes — Red first |
| `src/arkeology/tools/link_metadata.py` | Modify | Add `existing_vector_metadata` parameter to `_apply_link_metadata_with_cas`; assemble candidate and call `check_metadata_budgets` before `apply_link_annotations` inside the per-attempt loop; catch `MetadataTooLargeError` in `_link_metadata_inner` and return `validation_error`. **Control-character check:** import `Artifact` from `arkeology.artifact`; in `_validate_supplied_link_values`, after the existing empty/whitespace-only check, wrap a call to `Artifact.validate_commit_refs(values)` / `Artifact.validate_references(values)` (selected by `field`) in `try`/`except ValueError as exc: return str(exc)` |
| `tests/unit/test_tools_reconcile.py` | Modify | Add: oversize rebuilt `vector_metadata` → `_reindex_artifact` raises `MetadataTooLargeError`, `reconcile_index` reports it in `failed` with `error: "validation_error"`, zero `put_vector` calls for that artifact (both Phase 1 and Phase 2 call sites); passing case unchanged — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Add one `check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)` call in `_reindex_artifact`, after `vector_metadata` is fully assembled and before the per-section/fallback embed+write logic; import `check_metadata_budgets` from `arkeology.artifact`; classify `MetadataTooLargeError` as `validation_error` on the `failed` entry |
| `tests/integration/test_tools_link_metadata.py` | Modify (flag) | Real-AWS: an oversize merge is rejected with no annotation or vector write — Red for integration, if a suitable fixture exists |

### Contracts

- `docs/contracts/modules/arkeology.tools.link_metadata.md` § link_metadata — the per-element validation that rejects the whole call, and the budget `validation_error` that stops the call before either store is written for that artifact (R1–R3, R7, R8).
- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the budget check before the vector write, and `validation_error` reported in `failed` or `stuck_failures`, counting toward the bound (R4, R5).
- `docs/contracts/data/s3.artifact.md` § check_metadata_budgets — the guard both paths call, measured over the dicts about to be written and leaving no trace on a breach (R1, R4, R6).
- `docs/contracts/data/s3-annotations.artifact.md` § Storage Shape — the full-key form of a supplied `references` element (R7, R8).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — the capped `commit_refs` copy and the absent `references` key of the vector metadata both guards measure (R1, R4).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_link_metadata.py` → `link_metadata.py`** — seed an artifact whose `commit_refs` annotation and other filterable vector metadata are sized so that merging a further supplied value, capped as it would be written (R1), breaches `VECTOR_FILTERABLE_METADATA_MAX_BYTES`; call `link_metadata` with a supplied value that pushes it over; assert `validation_error`, zero `put_object_annotation` calls, zero `put_vectors_batch` calls (`mocker.spy` on both). Assert a merge that only breaches the budget *after* combining existing + supplied is still rejected (supplied alone would pass). Assert a normal, within-budget call still succeeds unchanged. Assert a call whose merged `references`, or whose merged `commit_refs` before the cap, is larger than the filterable budget still succeeds when the candidate fits (R1) — proving the candidate carries no `references` and only the capped `commit_refs`.
2. **`test_tools_reconcile.py` → `reconcile.py`** — seed an S3 object + failure-log entry (or orphan condition) whose `commit_refs` annotation, capped and placed into `vector_metadata` by `_reindex_artifact`, breaches a budget; run `reconcile_index`; assert the artifact appears in `failed` with `error: "validation_error"` — on the code, never on the wording of `reason` — zero `put_vector` calls for it (`mocker.spy`), and a normal artifact still reconciles successfully in the same run.
3. **`test_tools_link_metadata.py` → `link_metadata.py`** (control-character check) — call `link_metadata` with a supplied `commit_refs` element containing a Unicode `Cc` control character (e.g. `"abc\x01def"`); assert `validation_error`, zero `put_object_annotation` calls, zero `put_vectors_batch` calls (`mocker.spy` on both). Repeat for `references`. Call it with `references=["adr-use-postgres-abc12345"]` (no scope separator) and assert the same `validation_error` and zero writes. Assert a supplied element with no control character, no comma, and no empty/whitespace-only content — a `references` element being a full key — still succeeds unchanged (regression guard for the delegation change).

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings.

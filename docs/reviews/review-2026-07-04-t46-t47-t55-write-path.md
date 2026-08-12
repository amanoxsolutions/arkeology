---
type: code_review
title: "Phase 12 cluster T46/T47/T55 — references field, annotation dual-write, metadata validation"
description: Rigorous review of the write-path cluster (references first-class field, annotation dual-write with overwrite preservation, metadata size/charset validation) on branch phase-12-cross-referencing, diff main...HEAD.
tags: [phase-12, write-path, annotations, references, validation]
timestamp: 2026-07-04T00:00:00Z
okf_version: "0.1"
status: done
references:
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
authored:
  by: "developer"
  date: "2026-07-04"
revised:
  by: ""
  date: ""
---

# Phase 12 cluster T46/T47/T55 — references field, annotation dual-write, metadata validation

## Description
Code review of the T46 (references first-class field), T47 (annotation dual-write + tier-3/tier-2 overwrite preservation), and T55 (metadata size/charset validation) portion of Phase 12, diff range `main...HEAD` on `phase-12-cross-referencing`.

## Spec and ADRs Consulted
- docs/specs/p12-t46-references-field.md
- docs/specs/p12-t47-annotation-dual-write.md
- docs/specs/p12-t55-metadata-validation.md
- docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md (decisions 1, 4, 5)
- docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md (D2, D7, D8, D13)
- AGENTS.md conventions

## Files Reviewed
src/arkeology/artifact.py, tools/write.py, tools/write_artifacts.py, tools/list.py, tools/read.py, tools/reconcile.py, references.py, annotations.py, constants.py, errors.py, clients/s3.py, clients/credentials.py, server.py, resources.py; tests: test_tools_write.py, test_artifact.py, test_tools_list.py, test_tools_read.py, test_references_resolution.py, test_tools_write_artifacts.py, test_tools_migrate_artifacts.py, tests/unit/clients/test_s3.py, tests/integration/.

## Findings

### Critical

1. **Budget check bypassed by the overwrite merge** — `src/arkeology/tools/write.py:427-436` vs `473-502`. `check_metadata_budgets` (Step 3c) runs on `vector_metadata` containing only the caller-supplied `refs`/`references`; Step 4a then merges read-forward values into `vector_metadata` AFTER the check, with no re-check before `put_object`/`put_vectors_batch`. An overwrite of an artifact with an accumulated link trail can push the filterable payload past 2 KB, `put_object` succeeds, `put_vectors_batch` fails → deterministic partial write + failure-log replay loop — the exact defect T55 exists to close ("actual serialized representations about to be written"), reintroduced on the exact path T47 adds. Fix: re-run `check_metadata_budgets` after the merge (before `put_object`); the pre-`head_object` check stays for the fresh-write fast-fail.

### Major

2. **Comma in a link-list entry corrupts the durable annotation copy** — `src/arkeology/annotations.py:32-46` (`encode_link_list`/`decode_link_list`) + missing validator in `artifact.py`. `references=["a,b"]` is one element in vector metadata but decodes to two from the annotation; reconcile (T48) then rewrites vectors from the corrupted durable copy. Fix: reject `,` in `commit_refs`/`references` elements in the model validators (alongside the control-char check), or use a JSON-array annotation payload.

3. **Transient annotation error → hard `internal_error` after a durable put, no failure-log entry** — `src/arkeology/tools/write.py:528-546` catches only `AnnotationUnavailableError` and `CredentialError`; any other exception (e.g. `SlowDown`, `InternalError` ClientError) escapes to the blanket handler with the S3 object already written, no vectors, no failure-log entry. Contravenes T47's Never-clause ("do not invert … into a hard failure over a best-effort annotation problem beyond the CredentialError / T52-taxonomy cases"). Fix: degrade unknown annotation exceptions to the same warning path, or record a failure-log entry.

4. **Crash window between `put_object` (write.py:505) and `apply_link_annotations` (write.py:530) permanently loses the link trail on overwrite** — annotations are wiped by the put; the merged values exist only in process memory (vectors still hold the stale pre-overwrite copy). A subsequent `reconcile_index` rebuilds link fields FROM annotations and erases the vector copy too. No durable capture of the merged values exists before the put. Fix: append a failure-log entry carrying the merged link values before `put_object` (cleared on success), or document the window as accepted in the ADR.

5. **Lost-update race in read-forward merge** — `write.py:473-502` and the `link_metadata` merge are unconditional read-modify-write with no `If-Match`/versioning on annotations or vectors. Two concurrent overwrites (or overwrite + `link_metadata`) each read-forward, merge, and write; last writer silently drops the other's links. Neither spec nor ADR-011 records this as accepted. Fix: document as an accepted single-writer assumption, or add conditional writes.

6. **Spec-mandated integration test missing** — T47 Files-to-Touch lists `tests/integration/test_tools_write.py | Modify | Real-AWS overwrite-preservation round-trip` (unconditional). The branch adds only client-level `tests/integration/clients/test_s3_annotations.py` (T45); no real-AWS write→backfill→overwrite→survive round-trip exists.

### Minor

7. **Budget measurement over-counts vs AWS accounting** — `artifact.py:192,200`: `json.dumps` defaults (`ensure_ascii=True`, spaced separators) inflate non-ASCII values ~2-3× and add separator bytes; conservative but can falsely reject valid writes. Use `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`.
8. **Legacy `%` values mangled on read** — `read.py:105` and `reconcile.py` decode ALL S3 metadata values; a pre-T55 artifact whose title/description contains a literal `%XX`-looking sequence (stored raw by the old NFKD path) is silently altered (e.g. `discount%20code` → `discount code`).
9. **Empty-link writes still issue two annotation calls and can emit spurious warnings** — `annotations.py:76-78` deletes are guaranteed no-ops on the write path (PutObject just wiped annotations); in an annotation-unavailable deployment every write — even with no link fields — returns a degradation warning. Skip annotation calls in write.py when both final lists are empty.
10. **Control-char validation omits `team`/`project`** — inconsistent with `title`/`tags`/etc. (harmless post-encoding; spec omits them — note only).
11. **CredentialError from the annotation write (write.py:541) aborts after a durable put** — returns `credential_error` with the S3 object created, no vectors, no failure-log entry; self-heals only via the reconcile orphan scan. Spec-conformant; note the orphan.

### Test coverage gaps
- No test for finding 1 (overwrite whose merged link lists breach the filterable budget).
- No test for a generic (non-credential, non-unavailable) annotation exception mid-write.
- No test that a no-link-field write in an annotation-unavailable deployment avoids a warning (currently it would warn — finding 9).

## Recommendations
Fix finding 1 before merge (re-check budgets post-merge). Findings 2-5 should be fixed or explicitly accepted in the ADR before Phase 12 closes; add the T47 integration test. Minors at leisure. Everything else in T46/T55 aligns with spec: references plumbing (model, write, read, list filter AND-semantics, bulk write, migrate delegation, server wrappers, resources catalogue), budget constants and NON_FILTERABLE_METADATA_KEYS match the spec/AWS limits, ordering put_object → annotations → put_vectors_batch verified by test, read-forward correctly precedes PutObject and sources vectors, tier-2 explicit overwrite covered.

## Items Resolved Since Last Review
- (initial review)
- **Verification pass (2026-07-06):** findings re-checked in the consolidated master `review-2026-07-04-phase-12-full-review.md` (see its Verification Pass section). Mapping: this cluster's Critical 1 = master C4 (✅ resolved); Major 2 = M2 (still valid), 3 = M1 (still valid), 4 = C5(c) accepted-caveat, 5 = M3 (still valid), 6 = SA-3(a) T47 integration test (still missing). Minors 7–11 still valid.

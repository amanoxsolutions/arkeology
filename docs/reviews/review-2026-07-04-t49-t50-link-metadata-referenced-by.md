---
type: code_review
title: "T49/T50 cluster: link_metadata tool + unified referenced_by warning"
description: Rigorous review of the Phase 12 T49 (link_metadata replacing link_commit) and T50 (unified own-scope referenced_by warning on delete + archive) changes, diff range main...phase-12-cross-referencing.
tags: [phase-12, link_metadata, referenced_by, annotations]
timestamp: 2026-07-04T00:00:00Z
okf_version: "0.1"
status: done
references:
  - docs/specs/p12-t49-link-metadata.md
  - docs/specs/p12-t50-referenced-by-warning.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p10-t38-link-commit.md
authored:
  by: "developer"
  date: "2026-07-04"
revised:
  by: ""
  date: ""
---

# T49/T50 cluster: link_metadata tool + unified referenced_by warning

## Description
Code review of the T49 (`link_metadata` generalizing/superseding `link_commit`) and T50
(unified own-scope `referenced_by` warning on `delete_artifact` + `archive_artifact`) changes
on branch `phase-12-cross-referencing`, diff range `main...HEAD`. All three top findings were
confirmed empirically with a temporary probe test (removed after the run).

## Spec and ADRs Consulted
- docs/specs/p12-t49-link-metadata.md
- docs/specs/p12-t50-referenced-by-warning.md
- docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md (ADR-011, decisions 2, 4, 5)
- docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md (ADR-012, D13)
- docs/specs/p10-t38-link-commit.md (superseded predecessor)
- AGENTS.md non-negotiable rules

## Files Reviewed
- src/arkeology/tools/link_metadata.py (new) vs main:src/arkeology/tools/link_commit.py (deleted)
- src/arkeology/tools/delete.py, src/arkeology/tools/archive.py
- src/arkeology/tools/_search_helper.py (find_referrers), src/arkeology/artifact.py (REFERENCE_FIELDS)
- src/arkeology/server.py, src/arkeology/resources.py, src/arkeology/annotations.py
- src/arkeology/clients/s3.py (annotation ops), src/arkeology/clients/vectors.py (list_vectors_by_metadata)
- tests/unit/test_tools_link_metadata.py, test_tools_delete.py, test_tools_archive.py, test_server.py, conftest.py
- Repo-wide grep for lingering `link_commit` references (plugins/, AGENTS.md, resources)

## Findings

### Critical

1. **archive_artifact wipes the durable link annotations** — `src/arkeology/tools/archive.py:113`.
   `s3.put_object(artifact_id, content, updated_s3_meta)` re-PUTs the object; per ADR-011 an
   overwrite clears all annotations, and archive performs no read-forward/re-apply (unlike
   write.py:530). Confirmed by probe: after `link_metadata` + `archive_artifact`, `commit_refs`
   / `references` annotations are gone. A later `reconcile_index` (which rebuilds link fields
   from annotations, T48) then silently drops them from vector metadata too — the exact loss
   ADR-011 exists to prevent. Fix: in archive, `read_link_annotations` before the re-PUT and
   `apply_link_annotations` after (same pattern as write.py), or extract a shared re-PUT helper.

2. **link_metadata can destroy durable annotation state it never read** —
   `src/arkeology/tools/link_metadata.py:169-183`. Merge input is vector metadata only
   (`items[0]["metadata"]`), but `apply_link_annotations` unconditionally writes/deletes BOTH
   annotations from the merged values. In the exact partial-failure state ADR-011's ordering is
   designed for (annotation written, vector write failed), a subsequent `link_metadata` call
   computes the merge from stale vector metadata and overwrites — or, when the merged list is
   empty, deletes — the durable annotation. Confirmed by probe: annotation `references=
   "artifacts/precious"` + vector metadata without `references`; `link_metadata(commit_refs=[…])`
   deleted the references annotation. The durable side is supposed to be authoritative and
   self-healing; here the tool regresses it. Fix: merge with `read_link_annotations(s3, artifact_id)`
   as a third input (union of annotation + vector + supplied), and/or only touch the annotation(s)
   for fields actually supplied.

### Major

3. **Orphaned vectors abort the whole batch with internal_error** —
   `src/arkeology/tools/link_metadata.py:178` + `src/arkeology/clients/s3.py` (put_object_annotation
   has no NoSuchKey mapping). Vectors exist, S3 object missing → `PutObjectAnnotation` raises
   NoSuchKey ClientError → not caught in the loop → whole call returns
   `{"error": "internal_error"}`; already-linked artifacts' counts are lost and remaining
   artifacts unprocessed. Confirmed by probe. Violates the spec boundary "Do not abort the whole
   batch when one artifact has no vectors — skip and continue" in spirit, and regresses
   link_commit (which linked orphaned-vector artifacts fine). Fix: map NoSuchKey→KeyError in
   `put_object_annotation` (as get does) and skip+count in the loop.

4. **Spec-mandated integration test missing** — `tests/integration/test_tools_link_metadata.py`
   (T49 Files to Touch: real-AWS dual-write + reconcile-survival round-trip) does not exist.
   The T48 reconcile-from-annotations path is never validated end-to-end against real S3.

5. **Dropped value validation from link_commit** — `link_commit` stripped `commit_sha` and
   rejected empty/whitespace (test_m18_empty_commit_sha_returns_error); `link_metadata` accepts
   `commit_refs=[""]` / `[" abc "]` and merges them verbatim; empty-string elements produce
   vector metadata `[""]` whose annotation encodes to `""` and decodes to `[]` (store divergence).
   Comma-containing values silently corrupt the comma-joined annotation encoding. Fix: strip,
   drop empties, reject values containing commas.

6. **Per-vector link metadata silently collapsed to items[0]** —
   `src/arkeology/tools/link_metadata.py:169`. link_commit merged per item; link_metadata merges
   once from the first vector and stamps all sections. If section vectors ever diverge (partial
   batch write), values present only on later sections are dropped. Fix: union across all items.

### Minor

7. **"Server-side $eq" is client-side in practice** — `clients/vectors.py:194`
   `list_vectors_by_metadata` paginates the FULL index (returnMetadata=True) and filters
   in-process; T50's "server-side, not fetch-all-then-filter" AC is met in filter shape only.
   Pre-existing; also means `find_referrers`' two calls = two full-index scans per delete/archive
   (could be one).

8. **Stale comment** — `tests/unit/test_tools_read.py:524-527` still describes the retired
   vector-only `link_commit` behaviour.

9. **CHANGELOG `[Unreleased]` empty** — 13 Phase 12 commits including the breaking
   `link_commit`→`link_metadata` tool removal are unrecorded (keep-a-changelog convention).

10. **No cross-field preservation test** — no unit test that supplying only `references`
    preserves an existing `commit_refs` annotation (and vice versa), the very seam findings
    2 covers.

### Verified clean
Dual-write ordering annotation-first (tested); no Bedrock call (spy-tested); last_edited_ulid
untouched (tested); scope gate `startswith(write_prefix + "/")` everywhere; foreign IDs
skipped+counted; ULID cursor once after loop; find_referrers strictly own-scope on both branches
(scope $eq clause; foreign-referrer tests on delete + archive); no `$eq` on `source_artifacts`
(spy-asserted); synthesis-prefilter behaviour preserved; warn-not-block preserved; delete
phrasing stronger vs archive informational (tested); no pagination cap (ListVectors, not query
top-k); link_commit fully retired — server registration removed + retirement test, resources.py,
plugins skills, and the setting-up-arkeology agents-snippet post-commit protocol all invoke
link_metadata; propose_commit_links retained (tested).

## Recommendations
Fix findings 1-3 before merge (1 and 2 defeat ADR-011's central durability guarantee); add the
integration test (4); tighten value validation (5). 7-10 can follow in a cleanup pass.

## Items Resolved Since Last Review
- (initial review)
- **Verification pass (2026-07-06):** re-checked in the consolidated master `review-2026-07-04-phase-12-full-review.md`. Mapping: Critical 1 = C2 (✅ resolved), Critical 2 = C3 (✅ resolved); Major 3 = M10 (still valid), 4 = SA-3(c) T49 integration test (✅ added, M-16), 5+6 = M9 (partially fixed — items[0] write-collapse fixed, value validation still absent). Minor 7 = SA-4 (✅ docs), 8/9/10 still valid (stale link_commit comment, empty CHANGELOG, cross-field preservation test now partially added via C3).

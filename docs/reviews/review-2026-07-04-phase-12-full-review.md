---
type: code_review
title: "Phase 12 Full Review: Artifact Cross-Referencing + Annotation-Backed Link Storage"
description: Consolidated full review of Phase 12 (T45–T55) covering code, feature coherence, security, and the design concepts themselves, grounded in the brainstorming doc, ADR-011/ADR-012, and all eleven specs.
tags: []
timestamp: 2026-07-04T00:00:00Z
okf_version: "0.1"
status: done
references:
  - docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/specs/p12-t49-link-metadata.md
  - docs/specs/p12-t50-referenced-by-warning.md
  - docs/specs/p12-t51-migration-reference-rewrite.md
  - docs/specs/p12-t52-annotation-availability-graceful.md
  - docs/specs/p12-t53-reference-backfill-skill.md
  - docs/specs/p12-t54-search-age-transparency.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/reviews/review-2026-07-04-t46-t47-t55-write-path.md
  - docs/reviews/review-2026-07-04-t49-t50-link-metadata-referenced-by.md
  - docs/reviews/review-2026-07-04-p12-t48-t51-t54-cluster.md
authored:
  by: "architect"
  date: "2026-07-04"
revised:
  by: ""
  date: ""
---

# Phase 12 Full Review: Artifact Cross-Referencing + Annotation-Backed Link Storage

## Description

Full review of everything delivered in Phase 12 (branch `phase-12-cross-referencing`, diff
`main...HEAD`, 13 commits, ~8,200 insertions): code correctness, security, feature coherence,
cross-document contradictions, and the soundness of the design concepts themselves. Conducted
as five parallel cluster reviews (T45/T52, T46/T47/T55, T49/T50, T48/T51/T53/T54, and a
cross-document coherence pass) plus an architect-level concept and security analysis, each
grounded in the brainstorming decisions D1–D15, ADR-011, ADR-012, and the eleven Phase 12 specs.

Quality gates on the branch are fully green: 890 unit tests pass, ruff check/format clean,
mypy clean. Green gates notwithstanding, the phase is **not merge-ready** — see verdict.

## Spec and ADRs Consulted

- `docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md` (D1–D15, OQ1–OQ3)
- `docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md` (ADR-011)
- `docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md` (ADR-012)
- `docs/architecture-decisions/adr-2026-06-16-artifact-commit-traceability.md` (ADR-009, partially superseded)
- `docs/planning-artifacts/prd.md` (FR-51…FR-58, FR-17/28/32 revisions, NFR-12, Known Limitations)
- `docs/planning-artifacts/plan.md` (Phase 12), all eleven `docs/specs/p12-t*.md`
- Predecessor specs p10-t36/t38/t40, p2-t9, p5-t21 (retrofit edits)

## Files Reviewed

Full Phase 12 diff: `src/arkeology/` (annotations.py, references.py, artifact.py, errors.py,
constants.py, clients/{s3,interfaces,credentials}.py, tools/{write,write_artifacts,link_metadata,
delete,archive,read,list,reconcile,_search_helper}.py, server.py, resources.py), all new/changed
unit + integration tests, `plugins/arkeology/skills/` (setting-up-arkeology, migrating-to-arkeology,
backfilling-references), AGENTS.md, README.md, SERVER-REFERENCE.md, CONTRIBUTING.md, and the
Phase 12 documentation set. Detailed per-cluster logs are in `docs/reviews/` (referenced above).

## Findings

Verification notes: three of the criticals (C2, C3, and the C5(b) window) were **confirmed by
execution** with temporary probe tests against the moto-backed clients, not just by reading.
The load-bearing external claim — that botocore 1.43.36 exposes all four S3 object-annotation
operations — was verified against the installed service model.

### Spec Alignment (critical by definition)

- **SA-1 = C1 below** — the `references` identifier form is contradictory *between specs* (bare
  id in T46/T51/ADR-012 D2/skills vs full S3 key in T50/FR-56/`arkeology://` read gate), and both
  conventions shipped. The delivered migration/backfill flow does not work end-to-end.
- **SA-2** — T51 P1 Story 1 (`../decisions/B.md` resolves to B's id) is unimplemented at the
  layer the spec assigns it to (C6).
- **SA-3 — ⚙️ PARTIALLY RESOLVED (verified 2026-07-06)** — three spec-mandated integration tests are missing: T47 (real-AWS overwrite
  preservation round-trip), T48 (backfill → drop vectors → reconcile restores both fields),
  T49 (`tests/integration/test_tools_link_metadata.py`). The one interplay moto cannot prove
  is unverified against real AWS.
  > **Verified 2026-07-06** — **(c) T49 ✅ done**: `tests/integration/test_tools_link_metadata.py` added by review-2026-07-02 M-16 (`9dd6370`) — durable annotation+vector round-trip, merge/dedup across calls, foreign-scope skip. **(a) T47 and (b) T48 still MISSING**: `test_tools_write.py` has no annotation/overwrite-preservation round-trip; `test_tools_reconcile.py` has no backfill→drop-vectors→reconcile-restores-both-fields assertion. These two remain open.
- **SA-4 — ✅ RESOLVED (2026-07-04, docs via M11)** — T50's "server-side `$eq`" acceptance criterion is satisfied in filter *shape* only;
  `list_vectors_by_metadata` paginates the full index and filters in-process (pre-existing client
  limitation; FR-56/ADR-012 still describe the mechanism as server-side — see M11).

### Critical

- **C1 — ✅ RESOLVED (2026-07-04) — Bare-id vs full-key contradiction makes migration-produced references dead on every
  consuming surface.** `references.py:109` and both skills emit/store bare
  `generate_artifact_id` output; the operative `artifact_id` everywhere else is the full S3 key
  `{write_prefix}/{id}{ext}` (`write.py:377`). Consequences: `arkeology://artifact/{bare-id}` URIs
  rewritten into migrated content fail `read_artifact`'s scope gate; the FR-56 `referenced_by`
  reverse-lookup (`$eq` on the full-key delete target) never matches migration-populated entries;
  the backfilling-references skill's Step 5 eligibility check is always false → permanent silent
  no-op that its own Gotcha text legitimizes as "the normal, complete outcome". A third form
  (full key without extension) appears in T50's tests. **Architect decision required on the
  canonical form before any code fix**; the pragmatic direction is full keys from
  `build_path_to_id_map` (ManifestEntry needs team/project + extension), plus rewording T46/T51.
  > **Resolution (2026-07-04)** — operator chose the **full S3 key** as canonical. `build_path_to_id_map(manifest_entries, write_prefix)` now emits `{write_prefix}/{generate_artifact_id(...)}{ext}` (ext from the manifest path, default `.md`), identical to `write.py`'s stored `artifact_id`. `resources.py`'s `arkeology://artifact/{id}` template became `{id*}` (FastMCP RFC-6570 wildcard-path — not `{+id}`, which the vendored `mcp` SDK mis-parses) so a full-key URI containing slashes resolves through the registered template and the same scope/tier gate as `read_artifact`. Both skills emit full keys and gained a `write_prefix`-discovery step (derive from an existing own-scope artifact via `list_artifacts`, else ask the operator). T46/T51 and ADR-012 D2 reworded bare→full-key. Verified end-to-end: build-map output equals a *live* `write_artifact`'s `artifact_id`; a full-key `arkeology://` read resolves via the actual registered FastMCP template (foreign-scope tier-2 gate holds); `referenced_by` `$eq` matches full-key refs. +6 tests (red→green); suite 918 green. Commit `10db8dd`. (This finding = **SA-1**, also resolved.)
- **C2 — ✅ RESOLVED (2026-07-04) — `archive_artifact` silently destroys durable link annotations** (`archive.py:113`,
  probe-confirmed). The status-flip re-PUT wipes annotations and archive has no
  read-forward/re-apply. Loss is invisible until the next reconcile, which then erases the
  surviving vector copy too. Violates ADR-011's "every in-place re-PUT must read-forward and
  re-apply" invariant. Fix: apply the write.py pattern (or a shared annotation-preserving
  re-PUT helper) in `_archive_artifact_inner`. Also check `purge`/any other re-PUT path.
  > **Resolution (2026-07-04)** — `_archive_artifact_inner` now reads current link fields via `read_current_link_fields` (C5 union helper) *before* the status re-PUT and re-applies them via `apply_link_annotations` *after*, mirroring the write path; `AnnotationUnavailableError` degrades to an `annotation_warning` (archive still succeeds), `CredentialError` aborts. `purge` hard-deletes (no re-PUT) so needs no change — archive was the only remaining re-PUT path. +4 tests (annotation-survives-archive, vector-only source, unavailable-degrades, credential-aborts; red→green); suite 899 green. Commit `663b8ec`.
- **C3 — ✅ RESOLVED (2026-07-04) — `link_metadata` can delete durable annotation state it never read**
  (`link_metadata.py:169–183`, probe-confirmed). It merges from vector metadata only, then
  unconditionally rewrites **both** annotations from the merged values — an empty merged list
  *deletes* the annotation. In the exact partial state its annotation-first ordering is designed
  to survive (annotation written, vector write failed), an ordinary re-run destroys the durable
  copy instead of healing it. Fix: union three sources (annotations, vector metadata, supplied)
  and only touch annotations for fields actually supplied.
  > **Resolution (2026-07-04)** — `link_metadata` now reads existing link fields via `read_current_link_fields` (C5 union of annotation + vector) and merges the *supplied* values into that union; a field the caller didn't supply merges to its existing value and is re-written unchanged rather than deleted. +3 tests (only-references-supplied preserves the `commit_refs` annotation, idempotent-preserves-other-field, union-heals-missing-annotation; red→green); suite 902 green. Commit `90565b6`.
- **C4 — ✅ RESOLVED (2026-07-04) — T55's metadata budget check is bypassed by the T47 overwrite merge**
  (`write.py:427–436` vs `473–502`). The budget check runs before the read-forward merge enlarges
  `commit_refs`/`references`; no re-check before `put_object`/`put_vectors_batch`. A tier-3
  artifact with an accumulated link trail overwrites into a deterministic partial write that the
  failure log + reconcile replay forever — the exact loop T55 exists to prevent, reintroduced on
  the exact path T47 adds. Fix: re-run `check_metadata_budgets` after the Step 4a merge.
  > **Resolution (2026-07-04)** — `write.py` now re-runs `check_metadata_budgets(encoded_s3_metadata, vector_metadata)` inside the `is_existing and overwrite` block, after the Step 4a read-forward merge and before `put_object`; a breach returns `validation_error` with no write and no failure-log append. TDD: a merged-overwrite-exceeds-filterable-budget test (red→green) asserts zero `put_object`/`put_vectors_batch` calls and no failure-log entry, plus an under-budget overwrite still succeeds. Suite 892 green; ruff/format/mypy clean. Commit `8d05542`.
- **C5 — ✅ RESOLVED (2026-07-04) — The three stores have no consistent authority model; "reconcile is lossless / the
  design self-heals" is falsified in three windows.** Root cause: annotations are treated as
  authoritative by reconcile, vector metadata as authoritative by the write path's read-forward,
  and neither reads the other. Manifestations: **(a)** on annotation-unavailable deployments
  (explicitly supported "gracefully" per FR-57/T52) writes succeed with fields in vectors only —
  the next reconcile **erases** them (`reconcile.py:50` returns `[]` when absent), a regression
  vs pre-Phase-12 where write-time `commit_refs` survived reconcile via S3 user metadata;
  **(b)** after a partial `link_metadata` dual-write, a tier-3 overwrite reads forward the stale
  vector copy (`write.py:485`), PutObject wipes the newer annotation, and the link is permanently
  lost unless reconcile happened to run in between — ADR-011 D14's "two equally-valid stores"
  premise is false precisely in the failure mode the ordering was designed for; **(c)** a crash
  between `put_object` (505) and `apply_link_annotations` (530) leaves empty annotations that the
  next reconcile propagates over the surviving vector copy. Fix direction: define one authority
  rule (e.g. union-of-both-stores on every read-forward AND on reconcile restore), or record the
  windows as explicit accepted caveats in ADR-011 — currently the losslessness claims are
  unconditional in ADR-011, the PRD Known Limitations, and FR-54.
  > **Resolution (2026-07-04)** — operator approved **union-of-both-stores** authority. New `annotations.read_current_link_fields(s3, vectors, key)` returns `union(annotation, vector)` (order-preserving dedup); `reconcile_index` restores the union — fixes **(a)** (vector-only fields now survive reconcile on annotation-unavailable deployments) — and the write-path read-forward reads the union — fixes **(b)** (a partial `link_metadata` dual-write self-heals instead of being clobbered). Window **(c)** (mid-write crash between `put_object` and `apply_link_annotations`, before the vector write) is recorded as an explicit **accepted caveat** in ADR-011's revised authority-model consequence — there is no cross-store transaction, and it never affects already-persisted link data. +3 unit tests (C5a/C5b + M6, red→green); suite 895 green; ruff/format/mypy clean. Commit `fe33c7d`. (PRD Known Limitations / FR-54 "lossless" wording reconciliation tracked under M11, docs pass.)
- **C6 — ✅ RESOLVED (2026-07-04) — Relative-path references (`../…`, and `./…` joins against the referencing file's
  directory) never resolve anywhere in the delivered flow.** `references.py:23–26` delegates
  relative joining to the skill; `migrating-to-arkeology/SKILL.md:265` instead lists `../` paths as
  the canonical *unresolvable* example; the backfill skill has no join step either. T51's own P1
  Story 1 example cannot resolve. Fix: add a skill step — POSIX-join `./`/`../` entries against
  the referencing file's directory before the D6 ceiling lookup (this is resolution of
  well-formed relative paths, not the "repair" D6 bounds).
  > **Resolution (2026-07-04)** — added pure `references.join_reference_path(referencing_file_path, reference_path)` (posixpath join + normpath; URLs/non-dotted pass through; root-escaping `../` stays unresolved without raising) and an optional `referencing_file_path` param on `resolve_reference` (default preserves prior behaviour). The `migrating-to-arkeology` and `backfilling-references` skills now join `./`/`../` against the referencing file's directory before the D6 lookup and no longer treat well-formed relative paths as unresolvable. +10 tests (incl. T51 Story 1 `../decisions/B.md`; red→green); suite 912 green. Commit `027fd26`.

### Major

- **M1 — Non-taxonomy annotation exceptions abort the write after content is durably written**
  (`write.py:528–546`; found independently by two reviewers). Only `AnnotationUnavailableError`
  and `CredentialError` are handled; a transient `SlowDown`/timeout escapes to the blanket
  handler → orphaned S3 object, zero vectors, **no failure-log entry**, caller told the write
  failed, retry hits the collision guard. Contravenes T47's Never-clause. Fix: degrade
  (warn + continue) on any annotation failure except `CredentialError`, or at least append a
  failure-log entry.
- **M2 — Commas in link-list values corrupt the comma-joined annotation encoding**
  (`annotations.py:32–46`; `artifact.py` validators reject only control chars; `link_metadata`
  validates even less — see M9). `references=["a,b"]` diverges the two stores and the next
  reconcile propagates the corruption into vector metadata, breaking `$eq` lookups. Fix: reject
  `,` in link-list elements or move the annotation payload to a JSON array.
- **M3 — Lost-update race in every merge-read-modify-write** (`write.py:483`,
  `link_metadata.py`): concurrent overwrite/link operations on the same artifact silently drop
  each other's links (last writer wins, no conditional writes). Either document a single-writer
  assumption in ADR-011 or add conditional writes. Silent loss of the append-only trail is the
  failure mode the feature exists to prevent.
- **M4 — No correction/removal primitive exists for an append-only-by-merge field, and D9's
  "reference healing" guidance is unimplementable.** Overwrite union-merges old values back in
  (you can never shed a stale/typo'd reference via a content update); `link_metadata` only
  merges; no tool exposes removal. Concept-level: the design conflates `commit_refs` (a true
  audit trail — accretion is correct) with `references` (a claim about *current* outbound links
  — forced union on a content replacement produces a field that contradicts the content). The
  uniform-mechanism choice (D12 "not 2 different mechanisms for 2 things very similar") papered
  over a real semantic difference. Needs an architect/operator decision: replace-semantics for
  `references` on overwrite, and/or a removal mode on `link_metadata`.
- **M5 — The cross-team leakage closure rests on an unenforced premise and conflates
  author-reachability with reader-reachability** (ADR-012 "Closed as not applicable", FR-51 last
  sentence). Nothing enforces that `references` entries are resolved ids —
  `validate_references` checks control characters only, and T46 explicitly scopes resolvability
  validation out. Callers can write arbitrary strings, including *computable* foreign tier-2
  private artifact ids (IDs are pure functions of type+title+date, ADR-005). And even genuinely
  resolved ids leak: `references` is returned cross-scope on shared tier-3 artifacts, exposing
  the author team's hidden tier-2 slugs to foreign readers. "Reachable by some existing path"
  ≠ reachable by every reader. Re-open the closed question; minimum fix is an explicit,
  documented acceptance; better is filtering foreign-unreadable entries from cross-scope reads
  or validating entries at write time.
- **M6 — ✅ RESOLVED (2026-07-04, with C5) — `reconcile` swallows `CredentialError` in the annotation read**
  (`reconcile.py:54–62`): expired credentials mid-run → every remaining artifact re-indexed
  *without* link fields, reported as success, never re-indexed again. Fix: re-raise
  `CredentialError` before the blanket handler.
  > **Resolution (2026-07-04)** — fixed alongside C5: the reconcile annotation read now re-raises `CredentialError` before the graceful-degrade handler, so expired credentials abort the run with a structured error instead of silently dropping link fields on every remaining artifact. Covered by a C5 unit test. Commit `fe33c7d`.
- **M7 — ✅ RESOLVED (verified 2026-07-06; fixed by review-2026-07-02 M-15, commit `16f1bc1`)** — The documented "minimum IAM policy" is invalid (`SERVER-REFERENCE.md:176`): the new
  `S3ObjectAnnotations` statement contains a `"Comment"` field, which IAM rejects
  (`MalformedPolicyDocument`) — any operator copy-pasting the T52 deliverable gets a hard
  failure of the whole policy. Fix: move the text to prose.
  > **Verified 2026-07-06** — SERVER-REFERENCE.md IAM policy block contains no `"Comment"` field anywhere; the JSON parses cleanly. Closed by the M-15 reference-docs pass.
- **M8 — The setup probe object lives inside the artifact scope with no guaranteed CLI-path
  cleanup** (`setting-up-arkeology/SKILL.md:~205`): on the AccessDenied failure the probe exists to
  detect, a zero-byte non-artifact object is orphaned where the reconcile orphan scan will try
  to index it. Fix: reserved non-artifact prefix + always-run cleanup instruction.
- **M9 — Value validation was dropped in the link_commit → link_metadata generalization**:
  empty/whitespace/comma-bearing values pass (`link_metadata.py:131–138`; old suite rejected
  empty SHAs); `[""]` diverges the stores. Also the per-vector merge collapsed to `items[0]`
  (`link_metadata.py:169`) — values present only on later section vectors are dropped.
- **M10 — Orphaned vectors abort the whole `link_metadata` batch**: `put_object_annotation`
  lacks the `NoSuchKey→KeyError` mapping its three siblings have (`clients/s3.py:143–158`) →
  raw ClientError → `internal_error`, all accounting lost (probe-confirmed). Regresses
  `link_commit`, which handled orphaned vectors fine. Fix: map + skip-and-count.
- **M11 — ✅ RESOLVED (2026-07-04) — PRD/ADR text contradicts shipped mechanisms in three places**: (a) FR-23/AC-38/AC-50
  still instruct the deleted `link_commit` tool (supersession markers applied to the FR table
  but not the AC table); (b) FR-56/ADR-012 D13 mandate "server-side `$eq`" that T50 itself
  proves impossible for `source_artifacts` (non-filterable key → ValidationException; shipped
  as prefilter + in-process check); (c) ADR-011/FR-57 say the write path surfaces annotation
  errors as *errors* while T52 deliberately resolved it as success-plus-warning. Each is a
  next-agent trap; fold the spec-level resolutions back into PRD/ADR.
  > **Resolution (2026-07-04)** — docs reconciliation pass (commit `95dde5c`): (a) FR-23 + AC-38/AC-39/AC-50 now use `link_metadata`; (b) FR-56 + ADR-012 D13 reworded to the shipped hybrid (server-side `$eq` for `references`; `type=synthesis` prefilter + in-process membership for the non-filterable `source_artifacts`) — also closes **SA-4**; (c) FR-57 split into write-path success+warning vs `link_metadata` structured error. Additionally folded: FR-53/54/55 + Known Limitations → union-of-both + residual caveat, FR-17 reconcile-from-union, the six drifted specs (T47/T48/T49/T55/T42/T51), and two doc-hygiene minors (Scope tool count 15→16 incl. `arkeology_studio`; ADR-009 `status:` → partially superseded). grep-clean of stale `link_commit`/mechanism claims.
- **M12 — ✅ RESOLVED (verified 2026-07-06; ADR-011 D4 reconciled during the C1–C6 cycle)** — Tier-2 explicit replacement has no consistent link-preservation story: ADR-011
  Decision 4 vs its own Consequences vs FR-55 vs T47 each say something different; what ships is
  the tier-agnostic `is_existing and overwrite` (tested for tier-2 by accident of the condition).
  Whether a deliberate tier-2 *replacement* should preserve the old trail (arguably not — see
  M4) is decided nowhere. Record the intended behaviour explicitly.
  > **Verified 2026-07-06** — ADR-011 Decision 4 now explicitly scopes tier-2 ("overwritten only via the explicit opt-in replacement flag … the merged value is written back to both stores") and the Consequences name tier-2 explicit replacement under the same read-forward/re-apply obligation, matching the shipped `is_existing and overwrite` path. *(Note: the deeper semantic question of whether `references` should union-merge vs replace on overwrite remains open as **M4**.)*
- **M13 — `build_path_to_id_map` does not normalize its keys** (`references.py:107–115`):
  a manifest with `./`-prefixed or backslash paths matches nothing and the whole rewrite
  silently no-ops. Normalize map keys with the same `normalize_reference_path` used for lookups.
- **M14 — Untested pagination in `list_object_annotations`** (`clients/s3.py:190–199`): the
  ContinuationToken loop is dead code under every test (mock never truncates; integration test
  writes two annotations). Cheap side_effect unit test closes it.

### Minor

Grouped; full detail in the cluster logs.

- **Docs/state hygiene**: brainstorming frontmatter still lists OQ3 as pending and keeps the
  retired sweep item; ADR-009's `status:` field claims full supersession while body/overview say
  partial; plan.md says both "open — planning" and "all tasks implemented", T55 marked done yet
  "Spec: to be written"; T53's Files-to-Touch describes the pre-consolidation symlink layout;
  T54/T55 cite a gitignored `.docs/` review as provenance; PRD Scope's "15 tools" count omits
  `arkeology_studio`; T55 contradicts itself on which keys are filterable; write.py comments cite
  "ADR-011 D4/D14" (brainstorming numbering) vs ADR-011's decisions 1–5; stale `link_commit`
  comment in `test_tools_read.py:524`; CHANGELOG `[Unreleased]` empty despite a breaking tool
  removal; AGENTS.md repo-structure table missing `annotations.py`, `references.py`,
  `tools/link_metadata.py`; "S3 Express One Zone" and "directory buckets" double-count one
  category everywhere.
- **Concept/docs**: mixed addressing (D3) has no documented consumer — `arkeology://` links render
  dead in the studio HTML app and nothing specifies read-surface treatment; the PRD
  what-not-how convention (AGENTS.md) is violated wholesale by FR-51–58 (consistent with
  pre-existing FR style — the convention and house practice are irreconcilable and FR-54
  duplicates ADR-011, creating the dual-maintenance ADR-012 warns against).
- **Robustness**: `decode_link_list` keeps empty segments from malformed payloads; non-UTF-8
  annotation payload raises unclassified `UnicodeDecodeError`; `annotation_unavailable` response
  from `link_metadata` discards partial `linked`/`skipped` counts; unconditional
  `apply_link_annotations` issues two pointless DeleteObjectAnnotation calls per fresh write
  (and makes *every* write warn on annotation-less deployments); `json.dumps` defaults
  over-count non-ASCII against the 40 KB budget; percent-decode on read can mangle legacy
  values containing literal `%XX` sequences; `_URL_PREFIXES` case-sensitive; skill prose
  reimplements `generate_artifact_id` twice with no drift test and without the server's type/date
  validation; duplicate manifest paths last-win silently; `_ANNOTATION_STORE` never cleared
  between tests; `mocker: pytest.MonkeyPatch` mis-annotation; missing unit tests (list-on-missing
  -object, only-one-field-supplied preserves the other annotation, archive annotation survival,
  orphaned-vector skip); reverse-lookup adds two full-index scans per delete/archive (merge into
  one).

## Recommendations

1. **Do not merge as-is.** Green gates measure the implemented behaviour, not the intended one.
2. **Architect decisions first (blocking, cheap to decide, expensive to re-decide later):**
   (a) canonical `references` identifier form — recommend full S3 key, align T46/T51/skills and
   `build_path_to_id_map`; (b) authority rule across the three stores — recommend union-of-both
   on read-forward and on reconcile restore, with the residual windows recorded in ADR-011;
   (c) `references` overwrite semantics (replace vs merge) and a removal path — resolves M4 and
   half of M12; (d) re-open the leakage closure (M5) with an explicit accepted-risk or a fix.
3. **Then the mechanical criticals**: archive read-forward (C2), link_metadata three-source
   union (C3), budget re-check after merge (C4), relative-path join step in the skill (C6).
4. **Then the majors** — M1/M2/M6/M7/M8/M9/M10/M13/M14 are small, localized fixes; M11/M12 are
   documentation retrofits; add the three missing integration tests (SA-3).
5. **Docs pass last**: fold spec-level resolutions back into PRD/ADR text, fix the state-field
   hygiene items, and add the ADR-011 caveats for whatever windows remain accepted.

**Verdict: NOT merge-ready.** Totals across the consolidated review: **6 critical, 14 major,
~25 minor.** **Update (2026-07-04): all six criticals (C1–C6) are now ✅ RESOLVED** under strict TDD, plus the coupled major M6; 918 unit tests green, ruff/format/mypy clean (commits `8d05542` C4, `fe33c7d` C5+M6, `663b8ec` C2, `90565b6` C3, `027fd26` C6, `10db8dd` C1). SA-1 (=C1) and SA-2 (=C6) are closed with them. **Remaining before merge:** the 14 majors — notably **SA-3** (the three spec-mandated integration tests, which need a live-AWS run) and **SA-4/M11** (fold the spec-level resolutions back into PRD/ADR text) — and the ~25 minors. What *is* solid: scope discipline (own-scope gates verified clean everywhere,
including adversarial `../` probes), dual-write ordering, Bedrock-free/ULID-neutral linking
(spy-verified), link_commit retirement hygiene, T48's reconcile restore logic on the happy
path, T54, and the T55 charset/budget work on fresh writes. The failures are concentrated where
three stores meet one identifier scheme — coherence between components, not competence within
them.

## Items Resolved Since Last Review

- **2026-07-04 — all 6 criticals resolved (+ M6).** C1 full-key alignment (`10db8dd`), C2 archive annotation preservation (`663b8ec`), C3 link_metadata union/only-supplied (`90565b6`), C4 budget re-check after overwrite merge (`8d05542`), C5 union-of-both authority + M6 credential re-raise (`fe33c7d`), C6 relative-path join (`027fd26`). Each TDD red→green; suite grew 890→918 green throughout; ruff/format/mypy clean. Operator decisions: C1→full S3 key, C5→union-of-both (residual mid-write-crash window recorded as an accepted caveat in ADR-011). ADR-011 authority-model consequence + ADR-012 D2 + T46/T51 reworded to match. SA-1/SA-2 closed via C1/C6.
- **2026-07-04 — docs reconciliation (M11 + SA-4 + 2 doc-hygiene minors), commit `95dde5c`.** Retrofitted the six drifted Phase 12 specs (T47/T48/T49/T55/T42/T51), the PRD (FR-23/AC-38/39/50 → `link_metadata`; FR-56 hybrid lookup; FR-57 success-vs-warning; FR-53/54/55 + Known Limitations → union-of-both; FR-17; tool count 15→16), and ADR-012 D13 / ADR-009 status to shipped behaviour. grep-clean. Closes **M11** and **SA-4**.
- **Still open:** ~13 majors (notably **SA-3** — the three spec-mandated integration tests, which need a live-AWS run) + ~23 minors. Not addressed yet.
- (initial review)

## Verification Pass (2026-07-06)

Re-verified every still-open finding against merged `main` (`a4cf881`) after the review-2026-07-02
Major-fix cycle (M-1..M-16) and T56 landed. Method: three read-only agents, evidence-based per finding.

**Majors — now closed (3):** M7 (IAM `"Comment"`, via M-15), M12 (ADR-011 D4 tier-2 scoping),
SA-3(c) (`test_tools_link_metadata.py`, via M-16).
**Majors — partially fixed (2):** M8 (boto3 probe cleans up; aws-cli path + reconcile orphan-scan
exclusion still gap), M9 (items[0] write-collapse fixed; value validation + all-vector read still gap).
**Majors — still valid (8 + 2 tests):** M1, M2, M3, M4, M5, M10, M13, M14; SA-3(a) T47 and SA-3(b)
T48 integration round-trips still missing.
**Minors — now closed (3–4):** #2 (ADR-009 status), #6 (PRD 16-tools), #11 (AGENTS.md table);
#8 substantively (bad "D14" cite removed). **Partially fixed:** #26 (2 of 4 missing tests added).
**Minors — still valid (23):** 1, 3, 4, 5, 7, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
24, 25, 27.

Full cross-review triage (incl. the review-2026-07-02 minors) recorded in the session summary;
the still-valid set is the input to the planned follow-up fix cycle on branch
`review-followup-2026-07-06`.

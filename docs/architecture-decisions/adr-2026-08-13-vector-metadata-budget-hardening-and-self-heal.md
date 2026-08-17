---
type: adr
title: "Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal"
description: "Proposes a coherent fix for three converging findings from a real 57-file migration incident: (1) check_metadata_budgets's local byte-budget approximation under-counts relative to AWS's real PutVectors accounting, producing a permanent partial write (S3 object durably written, vector never indexed); (2) the budget guard is only called from write.py, never from link_metadata.py or reconcile.py, so both paths can durably write metadata that would be rejected on first write; (3) migrate_artifacts' skip-existing filter checks S3 existence only, never live vector-index state, making a partial write permanently un-retryable through the normal migration path, and the operator's manual write_artifact(overwrite=true) workaround silently bypassed the T56 content-rewrite pass. This document lays out verified real constraints, presents options honestly (no hidden winner), and records the operator's locked decision, including a real-AWS calibration test run as a deliberately-sequenced-ahead exception — no code, spec, or existing ADR file is otherwise touched by this document."
tags: []
timestamp: 2026-08-13T00:00:00Z
okf_version: "0.1"
status: "Accepted"
references:
  - docs/specs/p12-t55-metadata-validation.md
  - docs/specs/p12-t56-deterministic-content-reference-rewrite.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/brainstorming/brainstorming-2026-08-13-artifact-metadata-budget-overflow.md
  - tests/integration/test_calibration_vector_metadata_budget.py
  - docs/learnings.md
authored:
  by: architect
  date: "2026-08-13"
---

# Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal

## Description

A real `migrate_artifacts(dry_run=false)` run over a 57-file corpus produced one artifact (tier 2,
`code_review`, a 14-entry `references` list) that passed the local `check_metadata_budgets`
approximation (~1,722 measured bytes, under the local 2,048-byte filterable-metadata threshold) but
was rejected by the real AWS `PutVectors` call (`ValidationException`, filterable metadata over 2,048
bytes). By the time the rejection surfaced, the S3 object and its link-field annotations were already
durably written (S3-first ordering, [adr-2026-07-03-annotation-backed-link-storage.md](adr-2026-07-03-annotation-backed-link-storage.md)) — producing a genuine partial write: content exists,
vector index entry does not.

Three findings converge on this one incident, and this document treats them as one design, not three
patches:

1. **Calibration gap.** `check_metadata_budgets`'s byte-counting approximation (`artifact.py:180-232`)
   under-counts relative to AWS's real accounting for this payload shape. The spec that introduced it
   (`p12-t55-metadata-validation.md`) named this exact risk as a deferred, unresolved open question and
   the named closure (a real-AWS integration test asserting oversize rejection) was never written.
2. **Guard coverage gap.** `check_metadata_budgets` is called from exactly two places in the entire
   codebase — both inside `write.py` (`_write_artifact_inner`, once on the fresh-create path, once
   inside the overwrite compare-and-swap retry loop). `link_metadata.py` and `reconcile.py` both
   assemble and write vector metadata (`put_vectors_batch` / `put_vector`) with **zero** budget check.
   Both can durably write metadata a fresh `write_artifact` call would have rejected outright.
3. **Permanent partial write / idempotency gap.** `migrate_artifacts`' skip-existing filter (Step 5)
   decides "already migrated" solely from `s3.head_object(candidate_key)`. It never checks whether the
   artifact is actually indexed. Re-running the same migration over the same corpus silently reports
   `skipped_existing` for the stuck artifact instead of retrying or healing it — through the normal
   migration path, this state is permanently un-retryable. The operator's manual recovery
   (`write_artifact(overwrite=true)` with a shortened, 5-entry `references` list) worked, but silently
   skipped the T56 content-reference-rewrite pass, which is `migrate_artifacts`-only — leaving that one
   artifact's `references` in raw-path form while every other migrated artifact is
   `arkeology://`-rewritten.

This document does not modify any code, test, or existing spec/ADR file. It proposes a design for
review; the Developer implements only what the operator approves.

## Status

Accepted. Every open question below is resolved (see "Open Questions for the Operator — Resolved" at the
end of this document). D2's original A+C recommendation was subsequently superseded by a structural
split-representation decision reached in a follow-up brainstorming session
([brainstorming-2026-08-13-artifact-metadata-budget-overflow.md](../brainstorming/brainstorming-2026-08-13-artifact-metadata-budget-overflow.md));
see "D2 — Final Decision" below. This document still does not modify any code, test, or existing
spec/ADR file itself — the real-AWS calibration test that closed OQ2 was a separate, deliberately
sequenced-ahead task, not part of this document's own scope. D1-D4 are authorized for the Developer to
implement.

## Context

### Verified real constraints

- **S3 object annotations** (the durable store for `references` / `commit_refs`, [adr-2026-07-03-annotation-backed-link-storage.md](adr-2026-07-03-annotation-backed-link-storage.md)): up to
  **1 MiB per annotation payload**, up to **1,000 annotations per object**, mutable in place via
  `PutObjectAnnotation` without disturbing the object's ETag or `last_edited_ulid`. A 14-entry
  `references` list (~1.7 KB) uses roughly 0.15% of this ceiling. This ceiling is not the constraint
  that failed in the incident.
- **S3 Vectors per-vector metadata** (confirmed against the AWS S3 Vectors limitations documentation,
  independent of the local constants): **filterable metadata is capped at 2 KB**, **total metadata
  (filterable + non-filterable) at 40 KB**, per vector. `VECTOR_FILTERABLE_METADATA_MAX_BYTES = 2048`
  and `VECTOR_TOTAL_METADATA_MAX_BYTES = 40960` in `artifact.py` mirror these published figures
  correctly — the ceilings themselves are not miscopied.
- **What is *not* independently verifiable without a live AWS call**: the exact wire-format /
  serialization overhead AWS's `PutVectors` accounting applies to list-typed filterable values (the
  `references` field is stored as `list[str]` specifically to enable `$eq` element-in-list filtering,
  per `p12-t46-references-field.md`). AWS's own documentation confirms filterable metadata size is
  "combined size of keys and values," which is what `check_metadata_budgets`'s `json.dumps`-based
  approximation also measures — but list-typed values may carry per-element structural overhead in
  AWS's real accounting that a flat JSON string-length count does not capture. This is exactly the gap
  the incident exposed (~1,722 local bytes measured, real rejection at that size) and exactly the gap
  `p12-t55`'s own Open Questions section flagged as deferred. At the time this document was first
  drafted, closing that gap required a real-AWS integration test run (`tests/integration/test_tools_write.py`
  was the file named in `p12-t55`, still absent — confirmed via grep: zero matches for
  oversize/budget/`MetadataTooLarge`/`2048`/filterable anywhere under `tests/integration/`).
  **This gap is now closed**: the test was written as a dedicated file,
  `tests/integration/test_calibration_vector_metadata_budget.py` (rather than an addition to
  `test_tools_write.py` as originally proposed), and run against a live index on 2026-08-13. See
  "D2 — Final Decision" below for the measured results and the operator's final numeric decision.
- **Guard coverage, verified by direct grep of the current codebase**: `check_metadata_budgets` is
  called only at `write.py:405` (fresh create, pre-`put_object`) and `write.py:538` (inside the
  overwrite CAS retry loop, post-merge, pre-write). `link_metadata.py` (`_apply_link_metadata_with_cas`
  at line 49, `_link_metadata_inner` calling it at line 282 then `vectors.put_vectors_batch(batch)` at
  line 307) and `reconcile.py` (`_reindex_artifact` at line 44, `vectors.put_vector` at lines 146 and
  160) contain no call to it anywhere.
- **`migrate_artifacts` skip logic, verified by direct read of `migrate_artifacts.py:321-374`**: Step 5
  decides skip vs. write purely from `s3.head_object(candidate_key)` (line 360). If the object exists,
  the candidate is unconditionally reported `skipped_existing`, regardless of whether it has a live
  vector-index entry. Step 3.5 (T56 content-reference rewrite, lines 288+) runs **before** Step 5, in
  both `dry_run` modes — so by the time a candidate reaches Step 6 (`write_artifacts` delegation), its
  `content` already carries the `arkeology://artifact/{id}` rewrite. This matters for the self-heal
  design below: content already in S3 from *any* successful (even if vector-rejected) first attempt
  already has the correct T56 rewrite baked in.
- **`reconcile_index` failure-log replay, verified by direct read of `reconcile.py:218-302`**: Phase 1
  replays every failure-log entry every run; an entry is pruned only if the artifact resolves into
  `resolved_ids`. An entry that fails identically every time (e.g. a genuinely oversize `references`
  list) is never pruned and is replayed forever — this is precisely the "self-perpetuating failure-log
  replay" `p12-t55`'s own TL;dr states must never happen. Phase 2 (orphan scan, lines 317-337) would
  independently pick up "S3 exists, not indexed, not already in the failure log" artifacts and attempt
  `_reindex_artifact` on them, but its `failed` list is ephemeral per call — not persisted back to the
  failure log — so an orphan-scan failure does not itself create a replay loop, it simply reports
  clearly and stops.

### Why this is one design, not three patches

Finding 2 (missing guards) is a precondition for Finding 3's self-heal to work at all: `reconcile_index`
already has both the failure-log replay path and the orphan-scan path that *should* be able to retry
this stuck artifact today, but neither can currently do so safely — `_reindex_artifact` has no budget
check, so it would re-derive the identical oversize `vector_metadata` from the (already-durable)
annotations and fail identically, silently, every time. Finding 1 (calibration) determines how often
Finding 3's self-heal path is even needed in practice. Fixing only one of the three leaves the other two
symptoms live.

## Decision

### D1 — Guard coverage: close the gap at the shared chokepoint, not per-caller

We added a `check_metadata_budgets(s3_metadata={}, vector_metadata=vector_metadata)` call to both
missing sites, immediately before their respective vector write:

- `link_metadata.py`: inside `_apply_link_metadata_with_cas`'s per-attempt loop, after computing the
  merged (existing ∪ supplied) field values and before the annotation write — not only before
  `put_vectors_batch`, since `link_metadata` writes annotations *first* and a check only before the
  vector write would still leave a durably-written oversize annotation behind. The check re-runs on
  every CAS retry attempt, mirroring `write.py`'s own re-check-per-attempt pattern.
- `reconcile.py`: inside `_reindex_artifact`, once, before its `put_vector` call.

Both sites pass `s3_metadata` empty since neither touches S3 user-defined object metadata. This is the
"fix it once, where callers route through" shape the rest of the codebase already follows
(`_search_helper.py`'s `run_search_loop`, `_section_pipeline.py`) rather than writing three separate
checks. See the D1 table under Alternatives Considered below.

### D2 — Final Decision: split representation by field (locked, operator-approved)

We split treatment by field rather than choosing one answer for both. The decision came out of a
follow-up brainstorming session
([brainstorming-2026-08-13-artifact-metadata-budget-overflow.md](../brainstorming/brainstorming-2026-08-13-artifact-metadata-budget-overflow.md)):
the operator judged native `$eq`/`$in` filtering on these two fields a nice-to-have, not load-bearing at
the project's current stage, and chose a structural fix over a tuning fix. See the D2 table under
Alternatives Considered below for the options weighed and why each was not adopted as originally framed.

- **`references` is removed from S3 Vectors metadata entirely.** The S3 object annotation copy
  ([adr-2026-07-03-annotation-backed-link-storage.md](adr-2026-07-03-annotation-backed-link-storage.md))
  is now the sole durable store and read surface for this field, unbounded (comfortably inside the
  ~1 MiB / 1,000-annotations-per-object ceiling verified above). Accepted, deliberate cost:
  `list_artifacts(references=[...])` filtering on `references` (`search_artifacts` has no
  `references` parameter and is unaffected), and the
  `references`-half of the delete/archive reverse-lookup warning (`find_referrers`,
  [adr-2026-07-03-artifact-cross-referencing.md](adr-2026-07-03-artifact-cross-referencing.md) D13), are
  descoped — a deliberate, operator-confirmed capability loss (brainstorming doc OQ6), not an oversight.
- **`commit_refs` stays in S3 Vectors metadata, filterable, capped at the most recent 20 entries**,
  because it is load-bearing for a real, shipped server-side `$eq` filter clause (`list.py:141-143`,
  `list_artifacts(commit_refs=[...])`). A bounded, most-recently-appended subset is promoted into vector
  metadata for filtering (both fields are already order-preserving, so "most recent" is exactly "last
  N"), while the complete, uncapped list stays durable in annotations.

**OQ2 is closed.** We wrote and ran the real-AWS calibration test named as a deferred open question in
`p12-t55` (`tests/integration/test_calibration_vector_metadata_budget.py`, run 2026-08-13). Binary-searching
`commit_refs` list length against a live index (SHA-1-shaped, 40-hex-char entries, realistic tier-2
`code_review` payload with 9 other filterable fields and 2 tags) found AWS accepts **36 entries**
(1,993 local-approximation bytes) and rejects **37 entries** (2,037 local-approximation bytes — still
under the local `VECTOR_FILTERABLE_METADATA_MAX_BYTES = 2048` threshold), reproducing the original
incident's exact failure mode: a payload the local guard would accept is rejected by real AWS. (Both
figures are local-approximation byte counts, not AWS's real internal accounting, which remains opaque.)

We set the `commit_refs` cap at **20 entries** — deliberately well under the measured 36-entry boundary
— because 20 is already generous for how often a typical artifact (outside true hub documents like this
project's own `plan.md`/`backlog.md`) is revised or cross-referenced by commits, and the margin leaves
headroom if other filterable fields grow later (D1 adds none). The cap functions as a hard entry-count
ceiling delivered through a split-store representation (silently truncate the filterable copy, never
reject the write), calibrated against real, measured AWS behavior rather than a formula.

> **Payload-shape-specific, not a universal constant.** Both the 36/37 boundary and the 20-entry cap are
> calibrated against today's specific filterable-metadata field mix and must be re-run if the set of
> filterable vector-metadata keys ever changes — not derived from a documented AWS formula. Full
> calibration methodology and results: `docs/learnings.md` (2026-08-13 entry,
> "`check_metadata_budgets`'s local `json.dumps`-based filterable-metadata byte count under-measures
> AWS's real `PutVectors` accounting"). This ADR records the decision the calibration fed, not the
> standing re-calibration procedure.

### D3 — `migrate_artifacts` idempotency: detect, don't reinvent

We chose to reuse `reconcile_index`'s existing re-index logic rather than build a second one inside
`migrate_artifacts`. In Step 5, when `s3.head_object(candidate_key)` succeeds, an added bounded check —
`vectors.list_vectors_by_metadata({"artifact_id": {"$eq": candidate_key}})` (or equivalent existence
query), scoped only to already-existing candidates — distinguishes two cases:

- Vectors present → unchanged behavior: `skipped_existing`, fully migrated.
- Vectors absent → report a **distinct** category (`skipped_unindexed`) instead of silently folding it
  into `skipped_existing`, and point the caller at `reconcile_index` as the remediation — which, once
  D1's guard is in place, either succeeds (self-heals) or reports a clear, structured failure.

**This also resolves the T56 rewrite-parity gap by construction, not by extra code.** Content already in
S3 from the *first* migration attempt already carries the T56 `arkeology://` rewrite (Step 3.5 runs
before Step 5/6). `reconcile_index`'s re-index path never touches content — it only re-derives and
re-embeds metadata from what is already durably stored — so a self-heal routed through it cannot
re-introduce the parity gap the manual `write_artifact(overwrite=true)` workaround created. That gap was
specific to the manual fallback (needed only when the fix is to *content itself*, e.g. trimming a
reference list in frontmatter) — worth one documentation note (AGENTS.md or the migration skill) that
such a manual recovery bypasses T56 and must be paired with re-running `rewrite_content_references`. See
the D3 table under Alternatives Considered below.

### D4 — Bound failure-log replay so an unresolvable entry fails loudly, not forever

Independent of D1-D3, `reconcile_index`'s Phase 1 failure-log replay currently retries every entry every
run, indefinitely, with no attempt count — a genuinely oversize entry would fail and be replayed
identically forever. We added a `reconcile_attempts` counter per failure-log entry, incremented on each
failed replay; once it exceeds a threshold, reconcile stops auto-replaying that entry and reports it in a
distinct `stuck_failures` field instead of blending it into `failed` indistinguishably from a first-time
failure. This directly closes the "self-perpetuating failure-log replay" risk `p12-t55`'s own TL;DR
states must never exist, at the reconcile layer, not only the write layer. See the D4 table under
Alternatives Considered below.

## Alternatives Considered

Doing nothing beyond D1 (guard coverage only) was considered and rejected: it stops
`link_metadata`/`reconcile` from *creating* new instances of this bug, but does not address the
calibration gap that caused the original incident via `write.py` (which already has the guard) nor the
permanent-un-retryable state the incident left behind.

### D1 — Guard coverage

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — call the existing `check_metadata_budgets` at every vector-write site (`write.py`, `link_metadata.py`, `reconcile.py`) | One function, one place to fix; matches this codebase's existing shared-chokepoint convention (`_search_helper.py`'s `run_search_loop`, `_section_pipeline.py`) | Still three call sites, each must remember to call it |
| Write a bespoke size check inside `link_metadata.py`/`reconcile.py` | No change to the shared function's call sites | Duplicated logic, drifts from `write.py`'s check over time |

### D2 — Representation options considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — split by field: `references` removed from S3 Vectors metadata entirely (annotation-only, unbounded); `commit_refs` stays filterable, capped at the most-recent 20 entries | Retires the overflow failure mode for `references` outright; `commit_refs`'s cap is evidence-based (well under the measured 36-entry real boundary) and keeps its load-bearing `$eq` filter (`list.py:141-143`) working | Descopes `list_artifacts(references=[...])` filtering (`search_artifacts` has no `references` parameter and is unaffected) and the `references`-half of the delete/archive reverse-lookup warning; `commit_refs` entries older than the most-recent 20 no longer match `$eq` filters |
| A — Tighten the local byte threshold with a calibrated safety margin (closes the deferred `p12-t55` integration test) | Smallest diff; keeps the current one-representation architecture | Closes the bug, not the capability gap — a legitimately-large list (this incident's own 14-entry `references`) still gets rejected outright |
| B — Cap a filterable subset for *both* fields, keep the full list in annotations | A write is never rejected for "too many" entries | Silent false negatives on `references`'s `$eq` filtering and the delete/archive reverse-lookup warning — a completeness regression against this project's own "never silently lose a link" principle ([adr-2026-07-03-annotation-backed-link-storage.md](adr-2026-07-03-annotation-backed-link-storage.md)) |
| C — Upstream guidance + actionable rejection messaging | Zero data-integrity risk; cheap, consistent with existing AGENTS.md guidance | Doesn't solve the legitimately-large-artifact case alone — hub-style artifacts (`plan.md`, `backlog.md`) are a real, legitimate pattern this project's own docs exhibit |
| D — Hard write-time entry-count ceiling, checked before any byte math | Calibration-formula-independent; simple to explain and test | Still an arbitrary line and still rejects the write outright on its own; must run alongside the byte-budget check regardless (a list can have few entries but long IDs and still overflow) |
| E — Reclassify both fields as non-filterable metadata (40 KB budget instead of 2 KB) | 20x more room, no representation change | `references` has no narrow prefilter the way `source_artifacts` does — degrades to the unbounded fetch-all-then-filter scan [adr-2026-07-03-artifact-cross-referencing.md](adr-2026-07-03-artifact-cross-referencing.md) already rejected; gives up the shipped `$eq` filter feature; non-filterable/filterable classification is fixed at index creation, forcing a costly re-index to change later |

### D3 — Migration idempotency

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — per-skip-candidate existence check (`vectors.list_vectors_by_metadata`), remediate via existing `reconcile_index` | Small diff; reuses `reconcile_index`'s existing re-embed logic instead of duplicating it; resolves the T56 rewrite-parity gap by construction | One extra query per already-existing skip candidate |
| Bulk pre-scan (list all vectors under scope once, diff against S3 keys once) | Fewer total AWS calls for large, mostly-already-migrated batches | More complex; only worth it if the per-candidate query becomes a measured bottleneck — noted for the Developer to revisit if needed |
| Teach `migrate_artifacts` to re-index inline | No dependency on a separate tool call | Duplicates `reconcile_index`'s `_reindex_artifact` logic — two re-index code paths to keep in sync |

### D4 — Reconcile give-up threshold

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — reuse `CAS_MAX_ATTEMPTS = 3` (`annotations.py`) as the replay-attempt give-up threshold, surfaced via a new `stuck_failures` field | Reuses an existing, precedented number; no new config surface; a stuck entry now fails loudly and distinctly instead of blending into `failed` | Not independently tunable if reconcile's failure profile ever differs from CAS's |
| Independently configurable threshold | Tunable per deployment | New config surface for a number with no evidence yet that 3 is wrong here |

## Consequences

- **The incident's specific stuck artifact is not automatically healed by this document.** Even with
  every recommendation adopted, that one artifact remains in whatever state the operator's manual
  recovery already left it (S3 content correct, references trimmed to 5, T56 rewrite not reapplied to
  that one artifact). This design prevents *recurrence* and gives future occurrences a real self-heal
  path; it does not retroactively fix the one artifact already manually patched. Whether to also
  reconcile that specific artifact (e.g. re-run `rewrite_content_references` against it manually) is an
  operational follow-up, not an architectural one, and is out of scope here.
- **`commit_refs` payloads exceeding 20 entries will silently promote only the most-recent 20 into the
  filterable vector-metadata copy going forward** (D2 final decision) — the full list remains
  durable and uncapped in annotations, so this is a representation change, not a data-loss or
  write-rejection change. It is nonetheless a user-visible behavior change for any caller relying on
  `$eq` filtering to match a `commit_refs` entry older than the most-recent 20, and should be called out
  in the changelog once implemented.
- **`references` is no longer stored in S3 Vectors metadata at all.** This is a breaking change to a
  shipped, documented capability: `list_artifacts(references=[...])` server-side filtering on
  `references` (`search_artifacts` has no `references` parameter and is unaffected), and the
  `references`-half of the delete/archive reverse-lookup warning, are
  both descoped (see D2 above and brainstorming doc OQ6). This belongs in the changelog as a breaking
  change, not merely a behavior tweak.
- **The local `VECTOR_FILTERABLE_METADATA_MAX_BYTES = 2048` threshold itself is unchanged by this
  decision.** D2's fix is structural (cap `commit_refs`'s promoted-entry count; remove `references`
  from the store) rather than a tightened byte threshold. D1's guard-coverage fix remains a
  defense-in-depth backstop for other filterable fields (e.g. `tags`), not the primary mechanism that
  closes this incident's specific failure mode.
- **New response fields** (`skipped_unindexed` in `migrate_artifacts`, `stuck_failures` in
  `reconcile_index`) are additive and backward compatible — existing callers reading `skipped_existing`
  or `failed` continue to work; new callers can opt into the finer-grained signal.
- **Observability**: no new secrets or credentials surface is introduced. The new response fields and
  the `reconcile_attempts` counter are diagnostic-only, written to the same local failure-log JSONL file
  and MCP response shapes that already exist — consistent with the project's existing "never print
  stdout, log via `logging.getLogger(__name__)`" convention.
- **Testing cost**: the real-AWS integration test `p12-t55` originally named (as a hypothetical addition
  to `tests/integration/test_tools_write.py`) has since been written and run as a dedicated file,
  `tests/integration/test_calibration_vector_metadata_budget.py` — D2's `commit_refs` cap of 20 is
  therefore calibrated, not provisional (see "D2 — Final Decision" above). Unit-test coverage
  (moto) can verify guard placement (D1), the `commit_refs` cap and `references` removal (D2), the
  new skip-classification branch (D3), and the attempt-counter/threshold logic (D4) without AWS
  credentials; only the real byte-accounting discrepancy itself required the real-AWS calibration test,
  which is now done. Per-payload-shape re-calibration remains a future cost if the filterable field mix
  changes — see the "Payload-shape-specific" note under "D2 — Final Decision" and
  `docs/learnings.md`.

## Open Questions for the Operator — Resolved

Every item below was open when this document was first drafted. All are now resolved and this document's
status is Accepted; the questions are retained here as the decision trail, not as pending items.

1. **D2 recommendation** — **Resolved, superseded, not merely picked.** The original A+C recommendation
   (adopt calibrated threshold + messaging, reject split-representation and reclassify) was not the
   decision adopted. A follow-up brainstorming session reframed the question structurally rather than
   choosing a side of the original "never reject a write" vs. "never miss a filter match" trade-off — see
   "D2 — Final Decision" above for the operator's actual locked decision: `references` removed from
   the vector store entirely, `commit_refs` capped at 20 filterable entries.
2. **D2's specific numeric buffer** — **Resolved.** The deferred integration test was written and run
   against real AWS on 2026-08-13
   (`tests/integration/test_calibration_vector_metadata_budget.py`): AWS accepts up to 36 `commit_refs`
   entries (1,993 local-approximation bytes) and rejects at 37 entries (2,037 local-approximation bytes,
   still under the local 2,048-byte threshold). The operator's final numeric call is a **20-entry cap on
   `commit_refs`'s vector-metadata copy**, well under the measured 36-entry boundary — see "D2 —
   Final Decision" above for the full measured results and stated rationale.
3. **D3's bulk-scan performance refinement** — **Resolved: per-candidate existence check approved**
   (D3's primary recommendation, not the bulk-scan alternative). The operator confirmed the
   per-skip-candidate `vectors.list_vectors_by_metadata` existence check as scoped in D3 is acceptable
   as-is; the one-time bulk-listing alternative remains recorded under "Alternatives Considered" for the
   Developer to revisit only if a measured performance problem emerges at implementation time with large,
   mostly-already-migrated batches.
4. **D4's threshold** — **Resolved: reuse `CAS_MAX_ATTEMPTS = 3`, not independently configurable.** The
   operator confirmed reusing the existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`) for the
   reconcile replay-attempt give-up threshold, and confirmed the stuck-entry behavior should fail loudly
   via the new `stuck_failures` response field (D4) rather than blending silently into `failed` every
   run.
5. **Backlog entry** — resolved as not needed. With this ADR Accepted, the PM promoted D1–D4/D6
   directly into the plan's current open Phase 12 as T57–T62, rather than opening a
   `docs/planning-artifacts/backlog.md` entry first — per `backlog.md`'s own convention, work promoted
   straight to an open phase does not also get a backlog row. See `plan.md` Phase 12 and
   `brainstorming-2026-08-13-artifact-metadata-budget-overflow.md`'s OQ5 resolution.
   This document does not open that entry itself — backlog curation remains the PM's domain.

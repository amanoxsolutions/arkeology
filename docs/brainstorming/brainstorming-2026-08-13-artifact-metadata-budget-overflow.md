---
type: brainstorming
title: Artifact Metadata Budget Overflow — Guard Coverage, Calibration, and Migration Self-Heal
description: Explores why an artifact's references/commit_refs metadata can pass this project's local pre-write size approximation yet still be rejected by AWS's real accounting, why two of the codebase's three metadata-writing paths skip that check entirely, why the resulting stuck artifact was un-retryable through normal migration tooling, and resolves the deeper product question by removing references/commit_refs from the size-limited vector store entirely rather than trying to fit them inside it.
tags: []
timestamp: 2026-08-13T00:00:00Z
okf_version: "0.1"
status: complete
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t56-deterministic-content-reference-rewrite.md
authored:
  by: "pm"
  date: "2026-08-13"
revised:
  by: "pm"
  date: "2026-08-13"
---

# Artifact Metadata Budget Overflow — Guard Coverage, Calibration, and Migration Self-Heal

## Description

A real migration run surfaced a case where an artifact's linked-reference metadata passed this
project's own local size check but was rejected once it actually reached AWS, leaving a
permanently stuck, un-indexed artifact that normal tooling could neither detect nor repair. This
session explores the full failure surface that produced that outcome, the options for closing it,
and resolves the deeper question of what should happen when an artifact's genuine reference list
structurally exceeds the size-limited store's ceiling by removing that field from the size-limited
store entirely, rather than trying to make it fit.

## Decisions

### Locked

- D1 — The existing metadata-size guard must run at every point in the codebase that durably writes vector-filterable metadata (not just the primary write path), and — for any path writing more than one durable store in sequence — before each write, not only the last. Unaffected by D2 below; still needed for the fields that remain vector-filterable (e.g. tags, type) and, defensively, for the annotation store's own (much larger) ceiling.
- D2 — commit_refs and references are removed from S3 Vectors metadata entirely. The S3 object annotation copy becomes the sole durable store and sole read surface for both fields (already the union-of-both-stores read helper's job today; it becomes a single-store read once the vector-side copy is gone). This eliminates the metadata-budget-overflow failure mode for these two fields outright — the annotation ceiling (~1 MiB / 1,000 entries per object) is not a realistic constraint for a reference list — and retires the entire calibration/capping trade-off debate (the five previously-weighed representations) as moot for this data.
- D2b — Native $eq/$in filterable search on commit_refs/references (list_artifacts(references=[...]), list_artifacts(commit_refs=[...]), and the vector-metadata half of the delete/archive reverse-lookup warning) is intentionally descoped. This is a deliberate, accepted capability loss, not an oversight: the operator judged it a nice-to-have today. If genuine reference-graph search (e.g. full transitive 'what references this, and what references those') is wanted later, it should be pursued as a dedicated graph-technology capability, not forced into a 2 KB per-vector metadata budget.
- D3 — Migration self-heal: teach migrate_artifacts's 'already migrated' check to also confirm the artifact is actually indexed (not just that its content object exists), and route anything that isn't through the existing repair tool rather than building new repair logic. Unaffected by D2/D2b.
- D4 — Give the repair tool's automatic retry loop a give-up threshold (reusing the existing retry-count precedent already used elsewhere in this codebase) so a genuinely unfixable entry fails loudly once instead of retrying forever. Unaffected by D2/D2b.

### Pending

- OQ2 — A real-AWS verification test for the size-guard's calibration is still worth writing (it was scoped and never completed), but is no longer motivated by references/commit_refs specifically — it now matters only for fields that remain vector-filterable (tags, type, and any future filterable field). Lower urgency than before this session; not blocking D1–D4.
- OQ3 — Should the migration tool's self-heal existence check (D3) run once per already-migrated candidate, or as a single bulk listing up front? Pure performance question.
- OQ4 — Is the existing 3-attempt retry-count precedent the right give-up threshold for D4, or should it be independently configurable?
- OQ6 — Exact fate of the now-orphaned API surface: remove the `references=`/`commit_refs=` filter parameters from `list_artifacts`/`search_artifacts` outright (a breaking change to a shipped, documented, P1-priority capability), or deprecate them with a clear error naming the removal? And the delete/archive reverse-lookup warning: does it keep scanning on `source_artifacts` alone (unaffected — different field, stays in S3 user metadata) and simply drop the `references` half, or is that half missed enough to need a slower, explicitly-opt-in annotation-scan fallback?
- OQ7 — This reverses a shipped, documented capability across two existing ADRs and three specs. Recommend routing D2/D2b through the Architect for a formal amendment/supersession of the relevant ADRs before any implementation, per this project's own design-before-spec precedent — PM recommends yes, operator to confirm before dispatch.

### Closed — Not Applicable

- OQ1 (original framing: is 'never reject a legitimate write' more important than 'never miss a filter match'?) — superseded by D2/D2b. The question assumed both properties had to trade off against each other inside the same store; removing the field from the size-limited store entirely dissolves the trade-off instead of picking a side of it.
- OQ5 (open a backlog entry now, pointing at the pending architecture decision) — premature until OQ7 is resolved and a (possibly revised) ADR exists to point at.

## Session 2026-08-13

### Problem Statement

An operator migrated 57 existing files into Arkeology. One resulting artifact — a tier 2 code
review with a legitimately large, 14-entry list of cross-references — passed Arkeology's own
pre-write size approximation, then was rejected by AWS's real vector-write call once it actually
reached AWS, because the local estimate and AWS's real accounting of list-typed, filterable
metadata don't agree for this data shape. Because Arkeology deliberately writes its durable
content store before its search index (a safe ordering in the general case), the rejection
arrived only after the artifact's content and link-field data were already durably written —
producing a genuine partial write: content present and durable, never indexed, invisible to
search or recall.

A separate, independent whole-codebase review then found that the project's own size guard is
not actually applied at every point that durably writes this kind of metadata — only the primary
write path checks it before writing; two other paths that also durably write reference-style
metadata (a metadata-patching tool, and — critically — the tool whose job is specifically to
repair exactly this kind of stuck state) skip the check entirely. That second gap mattered
directly here: the migration tool's own "already migrated, skip it" logic only confirms that the
durable content object exists, never that it is actually indexed and searchable, so re-running
the same migration reported the stuck artifact as already-done, every time, with no path back to
a working state through the normal tool. The operator's manual recovery got the content itself
un-stuck, but — because it went through a different, general-purpose write path instead of the
migration-specific one — silently skipped a rewrite step that only the migration tool applies,
leaving that one artifact in a shape now inconsistent with its migrated peers.

Underneath the mechanical bug sat a real product question a guard fix alone would not answer:
rejecting a write earlier and more cleanly is strictly better than a silent partial write, but it
does not tell an operator what to do about an artifact whose genuine, honest reference list
simply does not fit inside a hard per-record metadata ceiling. That question is resolved in this
session's Challenge pass below — not by finding a cleverer way to fit the data into the tight
budget, but by recognising the tight budget only applies to one of two stores this data already
lives in, and the data doesn't need to be in that store at all.

### Ideas Explored

**Failure modes and impacts identified:**

- Silent partial write — content durably stored, never indexed, invisible to search/list/recall,
  the exact failure category this memory system exists to prevent.
- False-success idempotency — the migration tool's own "already done" check cannot distinguish
  "done" from "stuck," so re-running the same migration reports success forever without ever
  retrying or surfacing the problem.
- Non-self-healing repair path — the tool built specifically to repair this class of drift has
  the identical missing guard, so it fails identically and silently, forever, rather than fixing
  it.
- Inconsistent manual recovery — the only working workaround bypasses a tool-specific rewrite
  pass, leaving one artifact permanently different in shape from the rest of its migrated cohort
  unless separately, manually re-run.
- Unverified calibration — the size estimate used before ever reaching AWS was never checked
  against AWS's real accounting for this specific data shape; the verification step designed
  specifically to close this risk was scoped, named, and never actually written.
- Deeper, unresolved capability gap (as originally framed) — even a perfectly calibrated guard
  only fails faster and cleaner; it does not let a legitimately large, honest reference list
  actually be stored in full. **Resolved in Challenge, below, by changing which store the field
  lives in rather than accepting the trade-off as permanent.**

**Solution-space ideas:**

- **Guard coverage** — apply the existing size check at every point that durably writes this
  metadata, and — for any path that writes more than one durable store in sequence — run it
  before *each* write, not only the first or the last.
- **Calibration** — empirically determine AWS's real threshold via the verification test that
  was scoped but never written, then tighten the local check with a safety margin below whatever
  that reveals.
- **Split representation** — cap what gets promoted into the size-limited, queryable copy (e.g.
  most-recent N entries) while keeping a complete, uncapped list in the separate durable store
  that already has a much larger ceiling.
- **Upstream guidance** — treat a very large reference count as a content-modeling signal worth
  surfacing rather than silently absorbing: document a soft ceiling, and turn a bare
  size-exceeded rejection into an actionable message naming the offending field and count.
- **Hard count ceiling** — reject on "too many entries," in plain, human-legible terms,
  independent of byte-accounting, as an additional, easier-to-understand early check.
- **Reclassify as non-size-limited (within the vector store)** — move the field into the vector
  store's other, larger (40 KB total vs. 2 KB filterable) metadata bucket, still inside S3
  Vectors.
- **Remove from the vector store entirely** — store commit_refs/references only in the S3
  annotation copy (~1 MiB / 1,000-entries-per-object ceiling), which already exists as the
  durable source of truth for both fields; stop writing a second, size-limited copy into vector
  metadata at all. Raised by the operator directly, with the trade-off named up front: this gives
  up native `$eq`/`$in` filterable search on these two fields (querying "which artifacts
  reference X"), which today only the vector store can answer without an unbounded full-corpus
  scan.
- **Self-heal via existing repair machinery** — teach the migration tool's "already done" check
  to also confirm the artifact is actually indexed, and route anything that isn't through the
  existing repair tool rather than inventing a second repair mechanism.
- **Bounded repair retries** — give the repair tool's automatic retry loop a give-up threshold,
  so a genuinely unfixable entry fails loudly once instead of retrying identically forever.

### Clusters

1. **Failure/Impact** — silent partial write, false-success idempotency, non-self-healing repair
   path, inconsistent manual-recovery side effect, unverified calibration.
2. **Guard placement** — where the existing size check needs to run so no write path can bypass
   it.
3. **Capacity/representation** — what should structurally happen when a reference list is larger
   than a hard ceiling. Resolved this session: stop subjecting the field to the tight ceiling at
   all, rather than finding a better way to live within it.
4. **Recoverability** — how a stuck artifact gets found and fixed without a second, parallel
   repair mechanism.

### Selected Directions

Confirmed this session (Direction 2 superseded the original recommendation after the Challenge
pass below):

- **Direction 1 (Cluster 2 — Guard placement, confirmed).** Apply the existing size check at
  every point that durably writes vector-filterable metadata, before each durable write in any
  multi-store write sequence. Still needed for fields that remain vector-filterable (tags, type)
  and, defensively, for the annotation store's own much larger ceiling.
- **Direction 2 (Cluster 3 — Capacity/representation, final).** Remove `commit_refs`/`references`
  from S3 Vectors metadata entirely; the S3 object annotation copy becomes the sole durable store
  and sole read surface for both fields. This is a structural fix, not a tuning fix — it removes
  the size-overflow failure mode for these two fields rather than managing it, and retires the
  five previously-weighed representations (tighten-and-cap, split-cap, upstream guidance,
  count-ceiling, reclassify-within-vector-store) as moot for this data. The accepted cost:
  `list_artifacts`/`search_artifacts` filtering by `references=[...]`/`commit_refs=[...]`, and
  the `references`-half of the delete/archive reverse-lookup warning, lose their native,
  bounded-query backing. Confirmed by the operator as an acceptable, deliberate trade-off — see
  Challenge below.
- **Direction 3 (Cluster 4 — Recoverability, confirmed, unaffected by Direction 2).** Teach the
  migration tool's "already done" check to also confirm the artifact is actually indexed, and
  route anything that isn't through the existing repair tool.
- **Direction 4 (Cluster 4 — Recoverability, confirmed, unaffected by Direction 2).** Give the
  repair tool's automatic retry loop a give-up threshold, reusing the existing retry-count
  precedent already used elsewhere in this codebase.

### Challenge

Inversion question posed to the operator: *"If we ship the removal of commit_refs/references
from vector metadata and accept losing native `$eq` filterable reference search, what would make
that choice actively harmful in six months, not just incomplete?"*

Operator's response resolved it directly: the lost capability — "give me every artifact that
references artifact X" as a bounded, server-side query — is a nice-to-have at this project's
current stage, not a load-bearing one. The operator also pre-empted the natural follow-up
("what if real reference-graph search is wanted later?") with a structural answer rather than a
deferral: if genuine reference-graph search is ever wanted, the right tool is graph technology,
not a workaround squeezed into a 2 KB per-vector metadata budget that was never designed to hold
an accreting, unbounded relationship graph in the first place. That reframes the original
Cluster-3 question entirely — the five options weighed earlier were all implicitly accepting "the
field must stay filterable inside the vector store" as a constraint; the operator's response
rejects that constraint instead of optimizing within it. No further stress-test angle was raised
by the operator; Challenge closed after one pass.

### Techniques Used

- codebase archaeology (grounding every failure-mode claim in direct source inspection via a dispatched investigation, not memory)
- option enumeration with explicit trade-off weighing (five candidate representations for the calibration/capacity question, one considered and rejected outright)
- inversion ("what would make dropping vector-side filterability on these fields actively harmful, not just incomplete?" — posed to the operator directly; resolved below in Challenge)

### Assumptions Challenged

- Vector-metadata storage of commit_refs/references is required for the project's own $eq filterable-reference capability to stay viable. Overturned: the operator judged native cross-artifact reference filtering a nice-to-have, not a load-bearing capability, and explicitly named graph technology as the correct home for genuine reference-graph search if that's ever wanted, rather than forcing an unbounded, accretive field into a 2 KB per-vector budget.

### Open Questions

See `### Pending` under `## Decisions` above (OQ2, OQ3, OQ4, OQ6, OQ7) — each is a
genuine open question direct investigation could not resolve on its own. OQ7 in particular: this
session's decision reverses a shipped, documented capability described across two existing
architecture decisions and three specs, so — consistent with this project's own precedent of
designing before speccing — the PM recommends routing D2/D2b back through the Architect for a
formal amendment/supersession before any implementation begins, rather than proceeding straight
to a backlog entry.

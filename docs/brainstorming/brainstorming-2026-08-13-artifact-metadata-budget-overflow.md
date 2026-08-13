---
type: brainstorming
title: Artifact Metadata Budget Overflow — Guard Coverage, Calibration, and Migration Self-Heal
description: Explores why an artifact's references/commit_refs metadata can pass this project's local pre-write size approximation yet still be rejected by AWS's real accounting, why two of the codebase's three metadata-writing paths skip that check entirely, why the resulting stuck artifact was un-retryable through normal migration tooling, and resolves the deeper product question with a per-field split — references removed from the size-limited vector store entirely (annotation-only going forward), commit_refs retained as a capped, real-AWS-calibrated filterable copy (20 entries) since its $eq filtering is load-bearing, not a nice-to-have.
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
structurally exceeds the size-limited store's ceiling — not with one answer applied to both fields, but
a per-field split: `references` is removed from the size-limited store entirely (native filtering on it
was judged a nice-to-have); `commit_refs` stays, capped at a real-AWS-calibrated 20 entries, because its
`$eq` filtering (`list_artifacts(commit_refs=[...])`) is a shipped, load-bearing capability. See the
2026-08-13 correction session below for how this session's own first pass initially conflated the two
fields before the operator caught it.

## Decisions

### Locked

- D1 — The existing metadata-size guard must run at every point in the codebase that durably writes vector-filterable metadata (not just the primary write path), and — for any path writing more than one durable store in sequence — before each write, not only the last. Unaffected by D2 below; still needed for the fields that remain vector-filterable (e.g. tags, type) and, defensively, for the annotation store's own (much larger) ceiling.
- D2 (corrected 2026-08-13 — see correction session below) — Per-field split, not uniform removal. `references` is removed from S3 Vectors metadata entirely; the S3 object annotation copy becomes its sole durable store and sole read surface (already the union-of-both-stores read helper's job today; single-store read once the vector-side copy is gone). This structurally removes native `$eq`/`$in` filterable search on `references` (`list_artifacts(references=[...])`, and the `references`-half of the delete/archive reverse-lookup warning) — a deliberate, accepted capability loss, not an oversight; if genuine reference-graph search is wanted later, it should be pursued as a dedicated graph-technology capability, not forced into a 2 KB per-vector metadata budget. `commit_refs` **stays** in S3 Vectors metadata, filterable, capped at the most-recent **20 entries** — real-AWS-calibrated (a live test found AWS accepts up to 36 entries, rejects 37; 20 leaves deliberate margin for future filterable-field growth) — so its equivalent filtering (`list_artifacts(commit_refs=[...])`, already shipped at `list.py:141-143`) is **retained**, not descoped: it was judged load-bearing, not a nice-to-have, unlike `references`. (This was originally tracked as two decisions, D2 and D2b — the storage split and its filtering consequence — but the filtering fate for each field is a mechanical consequence of its storage location, not an independent choice, so the two were merged into one D2 on 2026-08-13; see correction session below.) Full measured evidence lives in `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`'s Decision section, not duplicated here.
- D3 — Migration self-heal: teach migrate_artifacts's 'already migrated' check to also confirm the artifact is actually indexed (not just that its content object exists), and route anything that isn't through the existing repair tool rather than building new repair logic. Confirmed: per-candidate existence check, not a bulk pre-scan (OQ3 resolved). Unaffected by D2.
- D4 — Give the repair tool's automatic retry loop a give-up threshold, reusing the existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`) — confirmed, not made independently configurable (OQ4 resolved) — so a genuinely unfixable entry fails loudly, once, via a new `stuck_failures` field, instead of retrying forever. Unaffected by D2.
- D6 (OQ6 resolved) — API surface fate: `references=` filter parameters are removed outright from `list_artifacts`/`search_artifacts` (breaking change, documented before shipped) since the field is no longer vector-filterable; `commit_refs=` filter parameters are **kept unchanged** — the field remains filterable, per D2. The delete/archive reverse-lookup warning keeps scanning `source_artifacts` only; the `references`-half is dropped with no fallback, and the gap is documented rather than silently absorbed.
- D7 (OQ7 resolved) — D2's revision was routed through the Architect rather than implemented directly. `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md` has been revised to carry the corrected split and the calibration evidence, and its status is now Accepted. `adr-2026-07-03-annotation-backed-link-storage.md` and `adr-2026-07-03-artifact-cross-referencing.md` — the two prior ADRs whose described behaviour D2 changes — each now carry a brief `## Revision — 2026-08-13` backward-link to this decision (verified) so they don't sit silently stale.

### Pending

None — OQ2, OQ3, OQ4, OQ6, and OQ7 were all resolved this session; see Locked above.

### Closed — Not Applicable

- OQ1 (original framing: is 'never reject a legitimate write' more important than 'never miss a filter match'?) — superseded by D2. The question assumed both properties had to trade off against each other inside the same store; removing the field from the size-limited store entirely dissolves the trade-off instead of picking a side of it.
- OQ5 (open a backlog entry now, pointing at the pending architecture decision) — resolved as not applicable in its original form: OQ7 is now resolved and the ADR is Accepted, but rather than parking D1–D4/D6 in `backlog.md`, the PM is promoting them directly into the plan's current open Phase 12 as T57–T62 in this same session — per `backlog.md`'s own stated convention, work promoted straight to an open phase is not also given a backlog row.

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
designing before speccing — the PM recommends routing D2 back through the Architect for a
formal amendment/supersession before any implementation begins, rather than proceeding straight
to a backlog entry.

## Session 2026-08-13 (Correction and Calibration)

Continuation of the same day's session above, not a separate day — recorded as its own section
because it corrects a real error in that session's own output and adds evidence (the real-AWS
calibration) that didn't exist yet when the section above was written.

### Correction

While reviewing this document's `decisions_locked` for staleness, the PM's restatement of D2
mis-described it as removing **both** `references` and `commit_refs` from S3 Vectors metadata
entirely. The operator caught this directly, quoting the PM's own earlier words back — the
original session had explicitly discussed calibrating `commit_refs`'s cap *upward* (from a
conservative 4–6 towards a 20–30 range), which only makes sense if `commit_refs` was staying in
the filterable store, not being removed. The two fields were conflated in the restatement.

Corrected: the decision is a **per-field split**, not a uniform removal —
- `references` — removed from S3 Vectors metadata entirely (annotation-only, unbounded, no `$eq`
  filtering). This part of the original restatement was correct.
- `commit_refs` — **stays** in S3 Vectors metadata, filterable, capped. It backs a real, shipped
  server-side `$eq` filter (`list_artifacts(commit_refs=[...])`, `list.py:141-143`) — load-bearing,
  not a nice-to-have, unlike `references`. This part was dropped in error and is now restored.
- The S3 object annotation copy stays the sole full, uncapped durable record for both fields
  regardless, per D1's durability guarantee — unaffected by the correction either way.

See `### Locked` under `## Decisions` above for the corrected D2 text.

### Calibration

The correction reopened OQ2 as genuinely important rather than low-urgency: with `references` no
longer sharing the 2 KB filterable budget, `commit_refs`'s cap had real headroom to raise from the
old conservative estimate — but the actual safe number required real-AWS measurement, not a guess.
A calibration test (`tests/integration/test_calibration_vector_metadata_budget.py`) was written and
run against a live index: AWS accepts up to **36** `commit_refs` entries and rejects **37**, for a
realistic tier-2 payload shape. Both figures are recorded with full detail in
[adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md](../architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md)'s
Decision section and in `docs/learnings.md` (payload-shape-specific re-calibration caveat), not
duplicated here.

### Final Decisions

The operator set `commit_refs`'s cap at **20 entries** — deliberately well under the measured
36-entry boundary, for headroom against future filterable-field growth — and confirmed OQ3
(per-candidate self-heal check, not bulk pre-scan) and OQ4 (reuse `CAS_MAX_ATTEMPTS = 3`, fail
loudly via a new `stuck_failures` field) as originally proposed. OQ6 and OQ7 were resolved in the
same exchange (API surface: only `references=` is removed, `commit_refs=` is kept; D2 routed
through the Architect for a formal ADR revision). See `### Locked` under `## Decisions` above for
all final text.

### Techniques Used

- Direct operator challenge against the PM's own prior stated words, rather than the document —
  caught a real analytical error (field conflation) that re-reading the document alone would not
  have surfaced, since the document's own decisions_locked text repeated the same error.

### Assumptions Challenged

- The PM's own restated summary of a locked decision is a reliable source of truth equal to the
  operator's original words. Overturned: it was not, in this instance — the operator's direct
  quote-back of an earlier statement was the correction mechanism, not a fresh re-reading of the
  document.

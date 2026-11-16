---
type: Spec
id: p15-t86-per-source-freshness
title: "T86 — Per-Source Freshness"
description: check_synthesis_freshness judges each Arkeology source of a synthesis on its own baseline. A source is stale when its current revision time, revised.at or else generated.at, is strictly later than the last_modified captured on its sources entry, compared as parsed offset-aware datetimes. The synthesis's own provenance and last_edited_ulid are never compared, so revising a synthesis no longer hides a source change. A source whose baseline is absent or whose timestamp cannot be read is reported in a new unchecked_sources list with a reason, and the synthesis's other sources are still checked. External sources are neither looked up nor reported.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr
    resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-09-29T00:00:00Z
  - id: brainstorming
    resource: docs/brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md
    title: OKF v0.2 Adoption for Arkeology
    last_modified: 2026-09-24T00:00:00Z
  - id: requirements
    resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-09-24T00:00:00Z
  - id: plan
    resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: spec-t22
    resource: docs/specs/p5-t22-synthesis-freshness-check.md
    title: T22 — Synthesis Freshness Check Tool
    last_modified: 2026-10-07T13:12:40Z
  - id: spec-t76
    resource: docs/specs/p15-t76-archived-boolean.md
    title: T76 — Archive Marker status → archived (bool)
    last_modified: 2026-10-13T15:57:36Z
  - id: spec-t77
    resource: docs/specs/p15-t77-open-type-list.md
    title: T77 — Open Type List
    last_modified: 2026-10-13T13:04:34Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: spec-t81
    resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: T81 — OKF Lifecycle status and the In-Force Default View
    last_modified: 2026-10-13T16:19:13Z
  - id: spec-t84
    resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:23:06Z
  - id: spec-t85
    resource: docs/specs/p15-t85-link-gate-withheld.md
    title: "T85 — Cross-Scope Gate on sources and relationships, with the {withheld: n} Marker"
    last_modified: 2026-10-13T18:07:52Z
  - id: contract-freshness
    resource: docs/contracts/modules/arkeology.tools.freshness.md
    title: arkeology.tools.freshness
    last_modified: 2026-09-14T00:00:00Z
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: p5-t22-synthesis-freshness-check
    type: amends
  - to: p15-t84-sources-relationships
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T18:19:14Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-16T10:12:15Z
---

# T86 — Per-Source Freshness

## TL;DR

`check_synthesis_freshness` stops comparing a synthesis against its sources and compares each
source against its own baseline. A source is stale when its current `revised.at` (or its
`generated.at`, if it was never revised) is strictly later than the `last_modified` captured on its
`sources` entry, with both parsed as offset-aware datetimes. A synthesis's own revision no longer
affects the verdict. A source whose baseline is absent, or whose timestamp cannot be read, goes in
a new `unchecked_sources` list with a reason. Every other source of that synthesis is still checked
(FR-20, AC-18; brainstorming-2026-09-17-okf-v02-adoption D19, D20, D50).

## 1. Problem Statement

Today a source is stale when its `last_edited_ulid` is later than the synthesis's. That baseline
covers the whole synthesis, so any write to the synthesis moves it forward. A cosmetic edit made
after a source changed therefore hides the change: the source now looks older than the synthesis,
although the synthesis never took it in. This is the false negative ADR-017 `### 4. Link fields`
names, and FR-20 forbids it ("revising the synthesis itself never hides a change to one of its
sources").

T84 already stores a per-entry baseline, `sources[].last_modified`, and moves freshness onto the
`links` annotation. T79 leaves the old ULID comparison in place until this task replaces it. Under
brainstorming-2026-09-17-okf-v02-adoption D19, `last_modified` is a snapshot taken at write time, so
the right comparison is the source's current revision time against that snapshot, made per entry and
as parsed instants. brainstorming-2026-09-17-okf-v02-adoption D50 case 4, and ADR-017 `### 10.
Malformed values in the new fields`, add one rule: a timestamp that cannot be read affects only its
own source.

**What this supersedes in T22** (`docs/specs/p5-t22-synthesis-freshness-check.md`). T22 is left
as written. These statements in it no longer hold:

- `## Revision — 2026-10-07`, in full: the `last_edited_ulid` rule and the `date` fallback. T79's
  interim replacement, "not stale when either side lacks a `last_edited_ulid`", goes with it.
- `## User Stories`, Story 1: staleness is no longer a date comparison between the synthesis and a
  source.
- `## Requirements`: the date-comparison bullet. The response-keys bullet and the `all_fresh`
  bullet are extended by `unchecked_sources`.
- `## Boundaries`: "ISO-8601 date comparison is a string comparison". Timestamps are now always
  parsed (brainstorming-2026-09-17-okf-v02-adoption D19).
- `## Testing Approach`: the "Stale detection" cases, the "both older" all-fresh case, the
  seven-field response case, and the integration test that sets up staleness with an older
  synthesis date.

T22's `source_artifacts`, `status` and lower-case `synthesis` statements were already superseded
by T84, T76 and T77. T86 does not repeat those changes.

**Read-time freshness for non-synthesis documents is not added.**
brainstorming-2026-09-17-okf-v02-adoption D20 makes freshness a reader-side check that applies to
any document. Arkeology meets that duty by returning `sources` with `last_modified`, and each
source's `revised`, on read. ADR-017 `## Deferred to the Specs` calls widening the scheduled audit
"optional", and the plan entry scopes T86 to `check_synthesis_freshness`.

The seven user stories, kept below as labelled examples (Story 1 to Story 7), are all P1.

## 2. Rules — Which sources are checked

### R1 — Every `sources` entry is resolved through T84's resolver against the synthesis; an entry that resolves to no key is not looked up, reported, or counted against `all_fresh`

The system must resolve every `sources` entry of an audited synthesis through T84's resolver in
`_scope.py`, with the synthesis's key as the carrier. An entry that resolves to no key (a URL, an
unresolved path, or any other non-Arkeology `resource`) must not be looked up, reported, or counted
against `all_fresh`.

**Example (Story 6 — External sources are not checked)**

- Given a synthesis whose only sources are a URL and an unresolved path, then nothing is looked up
  or reported for them, the synthesis is counted in `total_checked`, and it is neither malformed
  nor a reason for `all_fresh` to be `false` (FR-20, AC-18).

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D20, D38

### R2 — One batched lookup covers every source, and no S3 object or annotation is read for a source

The system must keep today's single batched lookup for all distinct resolved keys across every
audited synthesis (`fetch_vectors_by_artifact_ids`), and must read no S3 object or annotation for a
source.

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D20, D38

### R3 — The gate is applied first; a source with no vectors or denied by the gate is missing, and nothing else is decided for it

The system must apply `is_cross_scope_readable` to each source vector before using any of its
metadata, as today. A key with no vectors, or whose vectors the gate denies, is **missing**, and
nothing else is decided for that entry. Every other verdict therefore needs the gate's admission
first. This includes `unchecked`, even when its cause lies in the synthesis's own entry.

**Example (Story 7 — Archived, missing and foreign sources behave as before: missing and foreign)**

- Given a source with no vectors, or a foreign source the gate denies, then it is in
  `missing_sources` only. The two cases cannot be told apart, and neither ever appears in
  `unchecked_sources`.

**Why:** `missing` is decided first, and only after the gate. A gate-denied foreign source must
look exactly like an absent one (`arkeology.tools.freshness` contract, gate invariant).

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D20, D38

### R4 — A foreign source the gate admits is judged like an own-scope source

A foreign source the gate admits (tier 3 and `shared`) is judged like an own-scope source.

**Why:** its provenance is already visible to this reader through `read_artifact`, so reporting it
as stale or unchecked reveals nothing. T85 does not touch this tool. It reads only own-scope
carriers and acts on the stored entries, so no `{withheld: n}` marker ever reaches it
(T85 `### Surfaces`).

## 3. Rules — The current time of a source

### R5 — A source's effective time is `revised.at` when `revised` is present and `generated.at` otherwise, read from its newest-write vector

When a source has several vectors the system must use the vector with the newest
`last_edited_ulid`, as today (`_is_newer_write`). This is the same rule T84's baseline fill
applies, so the fill and the check read the same value.

The system must read that vector's provenance with T79's stored-provenance reader. The source's
**effective time** is `revised.at` when `revised` is present and `generated.at` otherwise.

**Why:** effective time comes from the source's newest vector. Freshness already reads only vector
metadata for sources. T79 writes all four provenance keys there, and T84's fill reads the same
vector by the same newest-write rule. Reading S3 object metadata would cost one request per
source, and it could disagree with the value the fill copied. The vector copy lags S3 only after a
failed vector write, which the failure log and `reconcile_index` already repair.

Source: brainstorming-2026-09-17-okf-v02-adoption D19, D40, ADR-017 `### 3. Provenance`

### R6 — `last_edited_ulid` only chooses which of a source's vectors is current, and syntheses are deduplicated by `artifact_id` alone

`last_edited_ulid` is used in one place only: it still chooses which of a source's disagreeing
vectors is current. It is never compared between two artifacts. The synthesis-side
`_is_newer_write` pass is removed: no synthesis metadata reaches a verdict any more, so the
syntheses are deduplicated by `artifact_id` alone.

**Why:** brainstorming-2026-09-17-okf-v02-adoption D19 keeps the ULID for internal ordering, and a
back-dated `revised.at` must not outrank a newer write.

Source: brainstorming-2026-09-17-okf-v02-adoption D19

### R7 — A source whose provenance T79's reader finds unreadable has an unreadable time, with no fallback from `revised` to `generated`

When T79's reader finds the source's provenance unreadable (a key missing or empty, a half-present
`revised`, or an `at` that does not parse or has no UTC offset) the system must treat the source's
time as unreadable. It must not fall back from an unreadable `revised` to `generated`.

"Unreadable" uses T79's reader and T79's strict parser. A naive value is unreadable
(ADR-017 `### 10`), and a bare date is unreadable too. A half-present block can be reported as
`unreadable_timestamp` even when its `at` would parse.

**Why:** one definition of "unreadable", shared with the fill. T84's fill refuses to copy from
unreadable provenance. Because the check uses the same test, it never compares a value the fill
would have refused. The reason names what the audit could not use, and the fault behind a
half-present block is corrupt provenance either way. There is no fallback from `revised` to
`generated`, because that would compare an older time and could hide a stale source.
brainstorming-2026-09-17-okf-v02-adoption D50 fails toward reporting.

Source: brainstorming-2026-09-17-okf-v02-adoption D19, D40, ADR-017 `### 3. Provenance`

## 4. Rules — The verdict for each entry that resolves to a readable source

### R8 — A source whose vector `archived` is the boolean `true` is reported in `archived_sources`, independently of its time verdict

The system must report the source in `archived_sources` when its vector `archived` is the boolean
`true` (T76). This is independent of the time verdict.

**Example (Story 7 — Archived, missing and foreign sources behave as before: archived)**

- Given an archived source, then it is in `archived_sources` and its timestamp is judged as well.

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D19, D50 case 4

### R9 — Each readable entry gets exactly one time verdict, checked in a fixed order; stale only when the effective time is strictly later than `last_modified`

The system must then give the entry exactly one time verdict, checking in this order:

1. `last_modified` absent: **unchecked**, reason `no_baseline`;
2. `last_modified` does not parse to an offset-aware datetime under T79's strict parser:
   **unchecked**, reason `unreadable_timestamp`;
3. the source's time is unreadable: **unchecked**, reason `unreadable_timestamp`;
4. effective time strictly later than `last_modified`, both as parsed instants: **stale**;
5. otherwise **fresh**, which is not reported.

| Entry | Reported in |
|---|---|
| Resolves to no key | nowhere |
| No vectors, or denied by the gate | `missing_sources` |
| Readable, `archived` is `true` | `archived_sources`, plus the time verdict below |
| Readable, no `last_modified` | `unchecked_sources`, `no_baseline` |
| Readable, either timestamp unreadable or naive | `unchecked_sources`, `unreadable_timestamp` |
| Readable, effective time > `last_modified` | `stale_sources` |
| Readable, effective time ≤ `last_modified` | nowhere |

**Example (Story 1 — A source revised after its baseline is stale)**

- Given a synthesis whose source entry carries `last_modified: 2026-01-01T00:00:00Z`, and a source
  whose `revised.at` is `2026-02-01T00:00:00Z`, when the audit runs, then the source's key is in
  that synthesis's `stale_sources` (AC-18).
- Given the source's effective time equals the baseline, or is earlier, then it is not reported.
- Given a source that was never revised, then its `generated.at` is the time compared.

**Example (Story 3 — Instants, not strings)**

- Given `last_modified: 2026-10-13T10:00:00+02:00` (08:00 UTC) and a source `revised.at` of
  `2026-10-13T09:00:00Z`, then the source is stale, although the second string sorts first as
  text (brainstorming-2026-09-17-okf-v02-adoption D19).

**Example (Story 5 — No baseline is unchecked, not fresh)**

- Given an entry that resolves to a readable source but carries no `last_modified`, then it is in
  `unchecked_sources` with reason `no_baseline`.

**Why:** strictly later, and equal is fresh. T84's fill copies the source's `revised.at` (or
`generated.at`) byte for byte. A freshly filled baseline therefore equals the source's current
time. Only a strict comparison lets that entry read as fresh. T79 stores whole seconds, so two
revisions of a source within one second cannot be told apart. T79 accepts that limit. A baseline
later than the source's time (a producer clock ahead, or a back-dated `revised.at`) reads as fresh.
Nothing in brainstorming-2026-09-17-okf-v02-adoption D19 makes that a defect, and reporting it would
only add noise.

**Why:** `no_baseline` is a second unchecked reason, not a silent pass. T84 leaves `last_modified`
absent when the target is missing, unreadable, or has unreadable provenance at write time. The
target can become readable later. With no baseline there is nothing to compare, so FR-20's test
cannot be applied. Reporting the entry as fresh would be a partial result that looks complete,
which the malformed-data ADR forbids for this tool. Reporting it as stale would claim a change
nobody observed. A distinct reason tells the operator what to do: update the synthesis and
re-supply the entry without `last_modified`. `add_artifact_links` cannot refresh a baseline,
because its merge keeps the first entry for each `resource` (T84).

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D19, D50 case 4

### R10 — The synthesis's own `generated`, `revised` or `last_edited_ulid` is read for no verdict, and the source's lifecycle `status` and any `relationships` are never read

The system must not read the synthesis's own `generated`, `revised` or `last_edited_ulid` for any
verdict. It must not read the source's lifecycle `status` or any `relationships`
(brainstorming-2026-09-17-okf-v02-adoption D25). `supersedes` edges are lineage only and are never
read here (brainstorming-2026-09-17-okf-v02-adoption D25).

**Example (Story 2 — Revising the synthesis never hides it)**

- Given the stale source in Story 1, when the synthesis is updated with the same entry and the same
  `last_modified`, then the source is still stale, whatever the synthesis's own `revised.at` or
  `last_edited_ulid` (AC-18, FR-20).
- Given the synthesis is then updated with the entry but without `last_modified`, then T84's fill
  records the source's current time and the source is no longer stale. This is how a baseline is
  refreshed.

**Why:** deprecated sources are not reported. FR-20, AC-18 and
brainstorming-2026-09-17-okf-v02-adoption D20 list exactly three states: stale, archived and
missing. A source's lifecycle `status` is its owner's view of whether it is still in force. It does
not mean that a document built from it is now wrong. The source's content at the baseline is
unchanged, and a lifecycle change never moves `revised` (FR-69). T81 also gives this tool no
lifecycle clause. Reporting deprecation would add a fourth category to a `final` requirement, so it
is out of scope (see Boundaries, Ask First).

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D19, D50 case 4

### R11 — An unchecked or stale verdict affects only its own entry

An unchecked or stale verdict must affect only that entry. The synthesis's other entries are still
judged, and the synthesis is still counted in `total_checked`.

**Example (Story 4 — An unreadable timestamp marks only its own source)**

- Given a synthesis with two sources, one whose `last_modified` does not parse or has no UTC
  offset, and one revised after its baseline, then the first is in `unchecked_sources` with reason
  `unreadable_timestamp`, the second is in `stale_sources`, and `all_fresh` is `false`
  (brainstorming-2026-09-17-okf-v02-adoption D50 case 4, ADR-017 `### 10`).
- Given a source whose stored provenance is unreadable, then it is `unreadable_timestamp`. The
  check never falls back to a time it can read on that source.

Source: FR-20, AC-18, brainstorming-2026-09-17-okf-v02-adoption D19, D50 case 4

## 5. Rules — Response

### R12 — Every successful call returns `unchecked_sources`, one entry per synthesis with at least one unchecked source, and nine always-present keys

The system must return `unchecked_sources` on every successful call, the early no-synthesis return
included. It is a list of `{"artifact_id": <synthesis>, "unchecked_sources": [{"artifact_id":
<source key>, "reason": "no_baseline" | "unreadable_timestamp"}]}`. There is one entry per
synthesis with at least one unchecked source. The always-present keys become nine: `stale`,
`archived_sources`, `missing_sources`, `unchecked_sources`, `malformed`, `deleted_malformed`,
`delete_failed`, `total_checked`, `all_fresh`. The conditional `skipped_malformed_count` and
T84's `skipped_deleted_count` are unchanged.

Source: FR-20, adr-2026-09-14-malformed-persisted-data-policy D3

### R13 — `stale`, `archived_sources` and `missing_sources` keep their shapes; each source is identified by its resolved key and listed once per synthesis, in stored order

`stale`, `archived_sources` and `missing_sources` must keep their shapes. Each source is identified
by its **resolved key**, never by the stored `resource` string.

Within one synthesis's list, the system must list each value once, in stored order: a key in the
three string lists, and a (key, reason) pair in `unchecked_sources`.

**Why:** keep the three lists, add one. AC-18 asks for archived and missing sources to be reported
"separately", and the contract promises lists a caller can act on independently. Only the new
category needs a reason, so only its items are objects. Restructuring every list into a
per-synthesis record of per-source verdicts would break every caller, and it would add nothing
AC-18 needs. Sources are reported by resolved key, which is what `read_artifact` takes. A bare id
in `arkeology://artifact/{id}` cannot be passed there. The bare-id and
full-key forms of one target collapse to one key, which is why the lists deduplicate. Timestamps
are not echoed: a caller who wants them reads the source or the synthesis.

Source: FR-20, adr-2026-09-14-malformed-persisted-data-policy D3

### R14 — `all_fresh` is `false` when `unchecked_sources` is non-empty

`all_fresh` must be `false` when `unchecked_sources` is non-empty, on the same footing as the other
categories. A run that could not judge a source has not shown that everything is fresh.

Source: FR-20, adr-2026-09-14-malformed-persisted-data-policy D3

## 6. Rules — Deletion

### R15 — `confirm=True` keeps deleting only syntheses T84 classes as malformed; `confirm=False` writes nothing

`confirm=True` must keep deleting only syntheses that T84 classes as malformed (no `sources`
entries). A stale, archived, missing or unchecked source never makes a synthesis a deletion
candidate, at any `confirm` value. With `confirm=False` the audit writes nothing.

Source: FR-20, T22 Story 5

## 7. Rules — Unchanged

### R16 — Synthesis selection, T84's annotation read and its skip counts, the `_inner` wrapper, the error codes and the off-event-loop calls are unchanged

**Unchanged.** Synthesis selection (own scope, `type` exactly `Synthesis`, `archived $eq false`; T76,
T77), T84's annotation read and its skip counts, the `_inner` wrapper, the error codes, and the
off-event-loop calls.

Source: T76, T77

## 8. Boundaries

**Always:**
- Parse both timestamps with T79's strict parser, and compare them as offset-aware datetimes. Never
  compare them as strings, and never assume UTC for a naive value
  (brainstorming-2026-09-17-okf-v02-adoption D19, ADR-017 `### 10`).
- Resolve every entry through T84's resolver. Never resolve an `arkeology://artifact/` value
  inline.
- Gate every source vector with `is_cross_scope_readable` before reading its `archived` or its
  provenance.
- Keep one batched lookup for all sources, and `public_fn` → `_inner` inside `try/except Exception`.
- Log counts only, never a source's timestamp values. Logging goes to stderr.

**Ask First:**
- Reporting deprecated sources, or any other new source category. That changes FR-20.
- Widening the audit beyond `Synthesis` (brainstorming-2026-09-17-okf-v02-adoption D20, optional).

**Never:**
- Compare `last_edited_ulid`, `generated` or `revised` between a synthesis and its source.
- Fall back from an unreadable `revised` to `generated`, or treat an unreadable value as fresh or
  stale.
- Give a gate-denied source any category except `missing_sources`. Never add an "inaccessible"
  category.
- Look up or report a source that resolves to no key.
- Write during the audit. Refreshing a baseline is the caller's update.
- Delete a synthesis for anything but T84's malformed rule.

## 9. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_freshness.py` | Modify | Written first and confirmed red. See Testing Approach |
| `src/arkeology/tools/freshness.py` | Modify | Step 3: deduplicate syntheses by `artifact_id` only. Step 7: replace the ULID comparison with a module-private pure function that returns the verdict for one entry, given the entry's `last_modified` and the gated source metadata. Add `unchecked_sources` to both returns, to `all_fresh` and to the completion log line. Narrow the `_is_newer_write` docstring to the source pass. Rewrite the module and Step 7 comments |
| `src/arkeology/server.py` | Modify | `check_synthesis_freshness` docstring wording: per-source baselines, and the unchecked category |
| `tests/integration/test_tools_freshness.py` | Modify | See Testing Approach |

`artifact.py` and `_scope.py` are not touched. T86 uses T79's parser and stored-provenance reader
and T84's resolver as they stand. If T79's reader does not expose the effective time directly,
derive it in `freshness.py` from the reader's output, and do not add a second parser.

### Contracts

Contract amendments. Make these before the tests, on top of the T76, T77, T79 and T84 amendments.

- **`modules/arkeology.tools.freshness.md`**
  - `**Invariants**`: replace the two staleness bullets (the ULID rule, and T79's "not stale when
    either side lacks a `last_edited_ulid`") with the per-entry rule: resolved through T84's
    resolver; effective time is `revised.at`, else `generated.at`, from the source's newest-write
    vector; compared as parsed offset-aware instants; stale only when strictly later. The
    synthesis's own provenance and ULID are never compared.
  - New invariant: an unchecked verdict (`no_baseline` or `unreadable_timestamp`) marks one entry.
    It never skips the synthesis, is never a deletion candidate, and is never given to a
    gate-denied source.
  - New invariant: an entry that resolves to no key is neither looked up nor reported. A source's
    lifecycle `status` and the synthesis's `relationships` are never read.
  - Gate invariant: add that `missing_sources` is decided before every other category.
  - `**Postconditions**`: the always-present keys become nine, with `unchecked_sources` and its
    item shape. Sources are identified by resolved key, and each appears once per list per
    synthesis. A non-empty `unchecked_sources` forces `all_fresh` to `false`. The "eight keys"
    wording and the `skipped_malformed_count` paragraph are updated to match.
  - `description` and `sources` frontmatter: name this spec.

No data contract changes. T86 reads T79's `generated_*`/`revised_*` vector keys and T84's `links`
entries exactly as those contracts define them.

### Testing Approach

**TDD order:** `tests/unit/test_tools_freshness.py` (confirmed red) → `freshness.py` →
`tests/integration/test_tools_freshness.py` (red against real AWS) → green. Fixtures seed source
vectors with `generated_at`/`revised_at` strings and synthesis `links` annotations in T84's shape.

**Rewrite or delete in `test_tools_freshness.py`.** Delete every test whose premise is a `date` or
`last_edited_ulid` ordering between synthesis and source. Under today's names these are
`test_stale_same_day_not_stale`, `test_stale_source_edited_after_synthesis_on_the_same_date`,
`test_source_written_before_synthesis_is_not_stale_despite_a_later_date`, and T79's "not stale when
a side lacks a ULID" case. Rewrite these to per-source baselines:
`test_stale_source_newer_than_synthesis`, `test_stale_two_sources_only_newer_flagged`,
`test_all_fresh_two_sources_both_older_and_active`,
`test_source_both_newer_and_archived_appears_in_both`,
`test_malformed_and_stale_both_reported_in_same_response`,
`test_response_always_has_all_seven_fields` (now nine) and
`test_all_fresh_true_iff_all_issue_lists_empty`. Rewrite
`test_stale_uses_the_newest_ulid_across_a_sources_vectors` so that the newest vector's `revised_at`
decides. Rewrite `test_stale_uses_the_newest_ulid_across_a_syntheses_vectors` as "a synthesis with
several vectors is audited once".

**Unit tests (fakes and moto only):**

- **AC-18, stale.** Effective time later than the baseline → in `stale_sources`. Equal → not
  reported. Earlier → not reported.
- **AC-18, not hidden.** A synthesis whose `revised_at` and `last_edited_ulid` are later than the
  source's still reports the source stale. A source whose ULID is later than the synthesis's, but
  whose `revised_at` equals the baseline, is not stale. Together these prove that no
  synthesis-versus-source comparison remains.
- **Effective time.** With no `revised`, `generated_at` decides. With `generated_at` ≤ baseline <
  `revised_at`, the source is stale, which proves that `revised` wins.
- **brainstorming-2026-09-17-okf-v02-adoption D19, parsed.** `last_modified:
  2026-10-13T10:00:00+02:00` against `revised_at: 2026-10-13T09:00:00Z` → stale. Also a
  fractional-second `last_modified` against a whole-second `revised_at`.
- **brainstorming-2026-09-17-okf-v02-adoption D50 case 4.** In one synthesis, an unparseable
  `last_modified` gives `unreadable_timestamp` while a second, stale source is still in
  `stale_sources`. A naive `last_modified` and a bare date each give `unreadable_timestamp`.
- **Source side.** An unparseable, naive or half-present `revised` gives `unreadable_timestamp`.
  When `generated_at` alone would have made the source stale, it is not in `stale_sources`, which
  proves there is no fallback.
- **No baseline.** A readable source with no `last_modified` → `no_baseline`. A missing source with
  no `last_modified` → `missing_sources` only.
- **Gate.** A foreign tier-2 source, cited with an unparseable `last_modified` and with no
  `last_modified`, → `missing_sources` only in both cases, and neither response mentions it
  elsewhere. A foreign tier-3 `shared` source is judged normally.
- **Archived.** Archived and stale → both lists. Archived and unchecked → both lists.
- **External.** URL, unresolved-path and `arkeology://other/x` entries are absent from the batched
  lookup's id set (spy) and from every list. A synthesis with only such sources is counted in
  `total_checked`, is not malformed, and leaves `all_fresh` `true`.
- **Resolution.** A bare-id entry resolves against the synthesis's scope and is reported by its
  full key. A bare-id entry and a full-key entry for one target appear once.
- **Deprecated.** A source with `status: deprecated` is in no list and leaves `all_fresh` `true`.
- **Response.** All nine keys are present, the empty-store early return included. A non-empty
  `unchecked_sources` alone makes `all_fresh` `false`.
- **Deletion.** With `confirm=True`, syntheses with stale or unchecked sources are not deleted
  (spy on `delete_vectors` and `delete_object`). A malformed synthesis in the same run is deleted.
- **Batching.** Two syntheses citing one source cause one lookup that contains that key once, as
  today.

No AC-80 test. T86 removes no tool, parameter or response key, so
brainstorming-2026-09-17-okf-v02-adoption D42 has nothing to reject here.

**Integration tests this change breaks** (update in this task, per plan.md). By T86 the file
already uses `create_artifact`/`update_artifact`, `generated`/`revised` and `sources` fixtures
(T78, T79, T84).

- `test_freshness_stale_source_detected`: this test is already failing, still keyed on a stale
  date. Rewrite it to create the source with `generated.at` `2026-01-01T00:00:00Z`, create the
  synthesis citing it (the fill records that time), then update the source with `revised.at`
  `2026-02-01T00:00:00Z`. Assert that the source key is in the synthesis's `stale_sources` and that
  the synthesis is absent from `unchecked_sources`. Explicit `at` values keep the test independent
  of same-second writes.
- **Add** `test_freshness_revising_the_synthesis_does_not_hide_a_stale_source` (**AC-18**). Start
  from the state above. Update the synthesis with `revised.at` `2026-03-01T00:00:00Z`, re-supplying
  the entry with `last_modified: 2026-01-01T00:00:00Z`, and assert the source is still stale. Then
  update it again without `last_modified`, and assert that the returned entry carries
  `2026-02-01T00:00:00Z` and that the source is no longer stale. This runs against the real
  vector-metadata round trip of `revised_at`.
- `test_freshness_all_fresh`: not broken. Update its docstring from dates to baselines, and also
  assert that the synthesis is absent from `unchecked_sources`.
- `test_freshness_archived_source_detected`, `test_freshness_missing_source_detected` and both
  malformed tests: not broken. The missing-source case reaches `missing_sources` through the
  precedence rule, although T84's fill left its baseline absent.

**Mutation.** T86 changes no file in `only_mutate`. The gate stays `is_cross_scope_readable`, and
the resolver is T84's, so no mutation run is owed for this task.

**Quality gates.** Unit suite, `ruff check`, `ruff format --check`, `mypy src/` and `npm test`
green. The integration file passes against real AWS before ✅.

### Hand-offs

None.

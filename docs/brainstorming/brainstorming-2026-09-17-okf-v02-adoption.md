---
type: brainstorming
title: "OKF v0.2 Adoption for Arkeology"
description: Explores what the Open Knowledge Format v0.2 release changes for Arkeology — the frontmatter migration, the provenance-block correction, and the ingestion model for the producer-side sources/relationships split, landing on a derivation-versus-association distinction that determines which edges need storage machinery and which need only trust signals, and on an in-force query model keyed on the target's own lifecycle rather than on the supersedes edge.
tags: []
timestamp: 2026-09-17T00:00:00Z
okf_version: "0.1"
status: ready
references:
  - https://openknowledgeformat.com/
  - https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
  - https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/16
  - https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/28
  - https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/22
  - https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/32
  - docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md
  - ../amanox-ai-agents/.docs/brief-2026-09-22-arkeology-okf-0.2-impacts.md
  - ../amanox-ai-agents/docs/brainstorming/brainstorming-2026-09-17-okf-0.2-adoption.md
  - docs/brainstorming/brainstorming-2026-06-15-okf-alignment.md
  - docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md
  - docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/contracts/data/s3-annotations.artifact.md
  - docs/contracts/data/s3vectors.artifact.md
authored:
  by: "analyst"
  date: 2026-09-17
revised:
  by: "pm"
  date: 2026-09-24
---

# OKF v0.2 Adoption for Arkeology

## Description

Google Cloud released Open Knowledge Format v0.2. It deprecates two v0.1 constructs, adds a
provenance/trust/lifecycle layer, and introduces an Attested Computation type. This session
establishes Arkeology's adoption posture (full adoption) and records the per-field decisions.

On 2026-09-22 the producer side — the `amanox-ai-agents` plugin, which writes the documents
Arkeology ingests — settled its own adoption and issued a written brief of what its documents will
emit. Working through that brief surfaced a distinction the session had been circling without
naming: **derivation edges and association edges are different kinds**, and only derivation edges
create a decay relationship. That single distinction resolves what had looked like an arbitrary
asymmetry in how Arkeology treats its link fields, and it decides which edges justify storage
machinery and which need only trust signals.

On 2026-09-23 the remaining structural questions closed. The in-force query model keys on the
retired artifact's own OKF `status`, never on the `supersedes` edge — which reaches issue #22's
third trust rung without the bundle-root `log.md` a store does not have. A producer-supplied `id`
becomes the artifact id, so Git and Arkeology share one namespace. Graph fields are annotation-only;
the existing `source_artifacts` vector-metadata projection is deleted rather than carried over.
Arkeology's own archive marker is renamed to `archived: bool` to stop colliding with OKF `status`.
The small follow-ups closed the same day: the revision-history annotation's shape (D30, D31, D34),
the actor-string and type mappings (D35, D37), and the charset and date-anchoring rules for a
supplied `id` (D32, D33). Nothing remains open.

This document is deliberately stamped `okf_version: "0.1"` like every other document in the repo,
so the mechanical version-keyed migration pass sweeps it up with the rest rather than leaving it
as a special case.

## Current Model

The landing state, stated plainly, because the route here involved two retractions.

| Kind | Arkeology field | OKF v0.2 | Annotation entry shape | Stored where | Target changes ⇒ |
|---|---|---|---|---|---|
| **Derivation** — what this was built from | `source_artifacts` | **`sources`** (§5.1, real OKF) | `{resource, last_modified}` + optional `id`, `title` | structured annotation **only** — no vector-metadata copy (D29) | document may now be **wrong** ⇒ freshness check, delete warning, per-source baselines |
| **Association** — what this relates to | `references` | `relationships` (#16, unruled) | `{to, type}` + optional `generated`, `verified` on edges Arkeology mints | structured annotation (authoritative) — **no projection** | dangling link, document still correct ⇒ trust signals only |
| **External** — git commits | `commit_refs` | out of scope | comma-joined `list[str]` — **unchanged** | **unchanged** — annotation (full, authoritative) + vector metadata (capped 20, derived filter index) | — |

The two new fields share **one structured annotation**, kept distinct inside it:

```yaml
# one annotation, structured payload — replaces the comma-joined `references` annotation
sources:                                    # derivation edges — what this was built from
  - resource: <artifact_id | URL>
    last_modified: <ISO 8601, UTC>          # source's revised.at as observed at write time (D19)
    id: <optional, for body citations>
    title: <optional>
relationships:                              # association edges — what this asserts about others
  - to: <artifact_id>
    type: <supersedes | builds_on | constrained_by | …>
    generated: {by, at}                     # optional; populated only on edges Arkeology mints
    verified: [{by, at}]                    # optional
```

`sources` entries carry `last_modified` per entry — a **native v0.2 field**, read under snapshot
semantics (see D19) — which gives each derivation edge its own freshness baseline.

Both graph fields are **annotation-only** (D29). `source_artifacts` leaves vector metadata
entirely — the projection it has today is deleted, not carried over — so the annotation is the sole
home for every artifact-to-artifact edge and for revision history alike. `commit_refs` is untouched
and remains the one link field with a vector-metadata projection; it points outside the artifact
graph and is not a relationship.

### Lifecycle

Three things that all used to be called `status`, now kept apart:

| Concern | Key | Values | Owner | Stored where | Filterable |
|---|---|---|---|---|---|
| Archived or not | `archived` (was Arkeology `status`) | `true` / `false` | Arkeology — `archive_artifact` | S3 object metadata + vector metadata — where `status` lives today | yes |
| Document lifecycle | `status` (OKF §5.4) | `draft` / `stable` / `deprecated` | the writer of *that* document | S3 object metadata + vector metadata — same as `archived` | yes — newly ingested |
| Succession lineage | `relationships[].type: supersedes` | edge on the **successor** | the writer of the successor | structured annotation | no — annotation only |

Both lifecycle keys are ordinary per-artifact metadata attributes, stored exactly where the
current `status` key is stored today: S3 object metadata as the durable copy (what
`reconcile_index` rebuilds from) and filterable vector metadata as the index. Neither is an
annotation — annotations hold only link fields and revision history.

**In-force** = `status != deprecated AND archived == false`. It is the default view; `draft` is
in force by default with a caller option to exclude it; the `supersedes` edge never decides
anything — it is lineage. See D21–D25 and *How the in-force decision is made*.

## What Changes?

The concrete work implied by the model above. Decisions record *why*; this records *what moves*.

**Storage**

- The annotation payload for link fields becomes **structured**, replacing the comma-joined
  encoding. `encode_link_list` / `decode_link_list` no longer apply to these two fields, and the
  no-comma validators in `artifact.py` become unnecessary for them.
- `source_artifacts` and `references` are replaced by `sources` and `relationships` as the stored
  shapes. Every path that touches link fields moves with them: the compare-and-swap cycle in
  `apply_link_annotations`, the read-forward that re-applies link fields after an overwriting
  `put_object`, and `reconcile_index`'s rebuild of vector metadata from annotations.
- **`source_artifacts` is removed from vector metadata** (D29). It leaves
  `NON_FILTERABLE_METADATA_KEYS` in code; the index's declared non-filterable slot may stay — an
  unused key costs nothing, and this is what keeps the change re-index-free.
- **`find_referrers` becomes prefilter + N annotation reads**, N = own-scope syntheses: list
  syntheses by `type`, read each one's `sources` annotation, match. Bounded by the synthesis count,
  never a corpus scan. `REFERENCE_FIELDS` — a filterability-driven query builder — loses its
  purpose and goes with it.
- **Two destructive paths now read the annotation to decide:** the delete/archive warning and
  `check_synthesis_freshness`'s malformed-synthesis delete. The raise-never-degrade rule of the
  annotations contract applies there with full force — a failed read must never present as "no
  sources".
- Revision history for offloaded artifacts — the edits Git would otherwise have recorded —
  is stored in its **own annotation** (D26, D31), one `{by, at}` entry appended per content write
  (D30), uncapped, and omitted from `list_artifacts` unless requested (D34).

**Ingestion and migration**

- `references.py` — `extract_references_list` and its `^references:` frontmatter regex stop
  matching anything. Replaced by two resolvers with **different mechanisms**: `sources[].resource`
  is a path resolved by reading the target file's own frontmatter `id:` (D43; URLs pass through
  untouched), while `relationships[].to` is already an id and needs lookup, not normalisation.
- The `backfilling-references` skill is kept, retargeted to `sources` only (D43).
- **`id:` in frontmatter becomes the bare artifact id** (D28). `generate_artifact_id` is the
  fallback, not the rule, for migrated content. `_slugify` must **not** run on a supplied id —
  dots are legal in producer stems and would be collapsed. The offline snippet in
  `tests/unit/test_skill_artifact_id_drift.py` gains the "if `id:` present, use it" branch.
- The deterministic-keys Non-Negotiable Rule and ADR-005 gain an amendment recording that a
  supplied `id` is an attribute and the hash suffix is omitted when it is present.
- `migrating-to-arkeology` — `generated.at` moves to the front of the date-derivation chain, and a
  pre-write id uniqueness check is added across the manifest.
- **The type list opens** (D37): OKF `type` stored verbatim, matched exactly, no case-folding.
  Known types become a recommended list; Studio gets a default style for unknown ones. The 16
  legacy snake_case values are rewritten once to their OKF display names by the store-migration
  skill (D42), and code comparisons such as `type == "synthesis"` follow.

**Artifact model**

- `authored` → `generated` (first authorship, written once); `revised` becomes latest-only;
  `verified` is a list; `timestamp` is removed.
- **`author_role` is removed**; `generated: {by, at}` and `revised: {by, at}` become first-class
  metadata in both stores, actor strings per OKF §7 (D35). Every overwrite carries `generated`
  forward.
- **Arkeology's `status` key becomes `archived: bool`** (D21). `ArtifactStatus` is deleted rather
  than renamed — a boolean needs no `StrEnum`. Persisted-shape change in both stores, both data
  contracts, the filter expressions, ~27 tool response/parameter sites, and Studio; existing
  artifacts migrated by the store-migration skill (D42). The `status: all` sentinel ADR gains a note for the boolean shape
  (`archived: false` default, `true`, omitted for all).
- **OKF `status` (`draft | stable | deprecated`) is ingested as artifact metadata** — S3 object
  metadata plus filterable vector metadata, alongside `archived` (D22). Three short values;
  negligible against the 2 KB budget.
- **A lifecycle flip on an existing artifact must be possible without re-embedding.** Both
  lifecycle keys live in S3 object metadata, so a flip takes `archive_artifact`'s existing path:
  in-place object re-PUT carrying current metadata and link annotations forward, then a vector
  metadata update — no embedding. `link_metadata` does not apply: it writes annotations only.
  Being a metadata-only write, a flip never moves `revised.at`. Whether OKF `status` gets its own
  small tool sharing that path or `archive_artifact` is generalised is a tool-surface choice for
  the spec.
- **Ordering:** rename `status → archived` *first*, then introduce lifecycle `status`. Otherwise
  one key means two things for a release.

**Freshness — the reader checks, the source never notifies**

- **OKF's model puts responsibility on the reader, never on the source.** A `sources` entry
  records what a document was built from and, in `last_modified`, when that source last changed.
  Freshness is established by following the edge *forward* from the citing document. Nothing in
  the source's lifecycle seeks out what cites it (D20).
- **How a source is read:** for each `sources` entry whose resource is `arkeology://artifact/{id}`,
  pass it through the cross-scope gate (D38), fetch the source's current metadata, and report it
  as **missing** (deleted or unreadable), **archived** (`archived == true`), or **stale** (current
  `revised.at` later than the captured `last_modified`). External sources — URLs, unresolved
  paths — are not checked.
- **Freshness now applies to every document with Arkeology sources**, not only syntheses — a spec
  citing its brainstorming session gets the same check. `check_synthesis_freshness` stays the
  scheduled audit for syntheses; widening it to all documents is optional.
- **A missing `sources[].last_modified` is filled in at import** from the resolved source's
  current `revised.at`, as an ordinary value with no marker (D40).
- **Deleting or archiving a source changes nothing on the documents that cite it.** No update, no
  cascade, no obligation to warn. Damage surfaces when a citing document is read or audited.
- The staleness baseline moves from one synthesis-wide `last_edited_ulid` to **per-source**
  `last_modified` — an ISO 8601 timestamp, the source's `revised.at` captured at write time —
  compared against each source's current `revised.at` as parsed datetimes. This fixes a
  false-negative class in the current check: a cosmetic edit to a synthesis currently advances
  its baseline and hides a real source change.
- `revised.at` must move only on content writes, never on link backfills, archive flips or
  reconcile re-indexes (D19).
- Same two batched queries — this is an accuracy change, not a cost change.

**Agent-facing schema resource**

- The schema MCP resource is rewritten for the new model: every field — `archived`, OKF `status`,
  `generated`, `revised`, `verified`, `sources` (including `last_modified` and the footnote-label
  `id`), `relationships`, the free-form `type` and the recommended type list, and the in-force
  view — is explained so an agent interprets it the way OKF defines it. Without this, an agent
  reads `status` or `sources[].id` by guesswork. *(PM session with operator, 2026-09-24; FR-18.)*

**Existing-store migration** (D42)

- **A breaking change, with no compatibility aliases.** Old parameter and field names
  (`status` as archive marker, `references`, `source_artifacts`, `author_role`, `timestamp`) are
  rejected once the change lands.
- **A new skill plus scripts migrates any project already holding artifacts in Arkeology** —
  S3 objects, object metadata, vector metadata and annotations: `status` → `archived`, legacy
  types → OKF display names, `authored`/`author_role`/`timestamp` → `generated`/`revised`,
  comma-joined `references`/`source_artifacts` → the structured `sources`/`relationships`
  annotation, and the `source_artifacts` vector-metadata key dropped. `reconcile_index` is not
  a metadata-key migration tool and gains no migration code.

**Explicitly unchanged**

- `commit_refs`, in both stores and in its cap.
- The reverse-lookup model: outbound edges only, inverse computed, never stored.
- The pre-delete/archive `referenced_by` warning, **for syntheses only** — a convenience beyond
  OKF, not a correctness mechanism. It does not reach other documents that now carry sources,
  deliberately. Its *cost profile* changes under D29 (one annotation read per own-scope synthesis
  instead of an in-process scan). See below.
- The vector index's dimension and its declared non-filterable slots. Nothing here requires a
  re-index.

**Why reverse lookup comes through untouched.** OKF's model puts the freshness duty on the
reader: follow each source edge forward and compare. Snapshot semantics (D19) means nothing has to
be updated when a source changes — every citing document holds its own baseline. So reverse
lookup has no *correctness* role at all (D20).

That leaves exactly one consumer: the pre-delete/archive warning, a **convenience beyond OKF**.
It is kept only for syntheses, because the `type == Synthesis` filter bounds the candidates and
makes it nearly free — each candidate's sources now come from its annotation (D29), one read per
synthesis, the same cost class `list_artifacts` already accepts. Documents other than syntheses
also carry sources now (a spec citing its brainstorming session), and the warning does not reach
them; that is deliberate, not a gap. Relationship targets never warranted a warning: deleting
something an ADR `builds_on` leaves a dangling link in a document that is still correct.

A future reader finding a synthesis-only reverse lookup should know it is a deliberate
consequence of OKF's reader-side model, not an unfinished generalisation waiting to be widened.

## Decisions

### Locked

- **D1 — Full OKF v0.2 adoption.** Supersedes the v0.1 adapter-only posture of the 2026-06-15
  session. Nothing forces this — a v0.1 bundle stays consumable by a v0.2 consumer under the
  spec's stated fallbacks — so this is a deliberate choice, not a compatibility repair.
- **D2 — House `status` values move to the OKF vocabulary** (`draft | stable | deprecated`).
  Performed by the plugin. *(Amended 2026-09-23.)* The 09-22 claim that no product-level
  collision exists was true for the *code* and false for the *agent*: after migration a
  `read_artifact` response would carry the content's `status: stable` next to the metadata's
  `status: active` — one word, two meanings, in one payload. Resolved by D21.
- **D3 — `references` and `sources` are different things and must be split.** Confirmed, and
  confirmed *twice* — it was briefly abandoned mid-session and reinstated on the evidence of
  §5.1. See D17.
- **D4 — `okf_version` stays a per-document custom key at artifact level.** Off-convention versus
  the spec's bundle-root `index.md`, but legal, and the only thing that makes a mechanical
  version-keyed migration possible.
- **D5 — `index.md` files will be created within this project** where the specification calls for
  them.
- **D6 — `verified` is adopted.** Recording review events. It also supplies something the current
  design cannot express: confirming a synthesis still holds *without rewriting it*.
- **D7 — `stale_after` and `usage_window` are not adopted.** Validity here is event-driven — an
  amendment keeps a document valid, a supersession retires it — so no date can be written in
  advance. `check_synthesis_freshness` must not expect the key. **Conceded upstream on
  #28 (2026-09-22)** by the Data Olympus maintainer for event-driven corpora: leaving it absent
  *"simply declares no date-based staleness, which is honest."*
- **D8 — `Attested Computation` is adopted.** Template capability; nothing is retrofitted.
- **D9 — `generated` replaces house `authored` and carries first-authorship meaning; `revised` is
  a single latest-only `{by, at}` object; `timestamp` is removed.** *(Amended 2026-09-22 — see
  below.)*
- **D10 — Division of labour.** Document migration is the plugin's. Arkeology's work is to verify
  the migrated result fits this project, and to make the server and its skills OKF v0.2 compatible.
- **D13 — Relationship direction is settled: outbound only.** The producer commits never to emit a
  `direction` key and never to write inverse spellings. Arkeology's computed reverse lookup is
  therefore the confirmed model; no inbound edge will ever arrive. **Independently
  confirmed** on #16 by three implementations; PGM states an authored `direction: inbound`
  *"would be outside PGM Core"*, and #22 forbids inverse spellings outright.
- **D17 — Derivation and association are different edge kinds, and the distinction is load-bearing.**
  OKF §5.1 defines `sources` as *"the materials a concept derives from"*; #16's `relationships`
  are assertions about other concepts. Only derivation creates decay: if a source moves, the
  derived document may now be wrong, whereas an association whose target moved is merely pointing
  at something that changed. This is why the two get different machinery, and it is a principled
  split rather than an accident of history.
- **D18 — `source_artifacts` maps to OKF `sources`, not to `relationships`.** *(Reverses a
  mid-session correction — see `## Assumptions Challenged`.)* "Artifacts used to create this
  summary" is the definition of §5.1 `sources`. The spec's recursion rule confirms these are graph
  edges: when a source is itself a concept, *"the derivation edge already exists in the bundle
  graph."*
- **D19 — `sources[].last_modified` is read under snapshot semantics, and supplies the per-edge
  freshness baseline.** It records what the producer observed at write time, not a live mirror of
  the source's current state. Two independent arguments: the live-mirror reading would require
  rewriting every citing concept on every source change *and* would make the field useless as a
  staleness signal, since stored and current could never disagree; and the sibling `usage_window`
  establishes observation-snapshot semantics for `usage_count` in the same signal block. The spec
  does not state this explicitly — see `## Upstream Items`. The value is an ISO 8601 datetime, as
  §5.1 requires: the source's `revised.at` (D35) as observed when the citing artifact was written.
  A source is stale when its current `revised.at` is later than the captured `last_modified`. Two
  conditions make that comparison sound. `revised.at` moves **only on content writes** — a
  link backfill, an archive flip or a reconcile re-index must leave it alone, or every synthesis
  citing the artifact would falsely report stale. And timestamps are **compared as parsed
  datetimes, never as strings** (`…10:00:00+02:00` sorts after `…09:00:00Z` as text but is
  earlier); Arkeology writes UTC with a `Z` suffix at fixed precision and parses whatever a
  producer supplies. `last_edited_ulid` remains an internal token — archive's compare-and-swap
  and reconcile's ordering depend on it — but never appears in an OKF field.
- **D20 — Freshness is a reader-side check that works for any document with sources; the
  delete/archive warning is a synthesis-only convenience beyond OKF.** OKF puts the duty on the
  reader, never on the source: a `sources` entry records what a document was built from, and
  `last_modified` when that source last changed. Checking freshness means following the edge
  *forward* — compare each source's captured `last_modified` against its current `revised.at`,
  and flag sources that are missing or archived. Nothing in OKF makes a change to, or deletion
  of, a source seek out what cites it; that is also why relationships are outbound only.
  Therefore:
  - **Deleting or archiving an artifact carries no obligation** to notify, warn, or update the
    documents that cite it — whether they cite it as a source or through a relationship.
  - **Freshness applies to every document with Arkeology sources**, not only syntheses, and is
    evaluated when the citing document is read (or audited). `check_synthesis_freshness` stays
    scoped to syntheses; widening the scheduled audit to all documents is optional, not required.
  - **The pre-delete/archive warning is kept, for syntheses only**, because the `type ==
    Synthesis` filter makes it nearly free: list own-scope syntheses, read each one's `sources`
    annotation (D29), warn if the target is cited. It does not cover a spec citing a
    brainstorming document, and that is not a gap — nothing required that coverage.
  - **Relationship targets get nothing on delete or archive.** An archived target still exists
    and resolves; a deleted target leaves a dangling edge, which #22 rules is not an error. Known
    limitation carried over: on read, an own-scope target passes the gate by prefix alone, so a
    deleted own-scope target still appears in `relationships` as if live.
- **D21 — Arkeology's archive marker is renamed from `status` to `archived: bool`.** It names the
  thing rather than the category, it *is* a boolean, and it frees the `status` key for the OKF
  lifecycle it now collides with. `ArtifactStatus` is deleted, not renamed. `ArkeologyStatus` /
  `ArkeologyLifecycle` were considered and rejected: they keep the colliding word.
- **D22 — OKF document `status` is ingested as artifact metadata — S3 object metadata plus
  filterable vector metadata, the same two stores `archived` (and today's `status`) use.** It is
  the writer's statement about its own document and the key the in-force filter turns on.
- **D23 — In-force is `status != deprecated AND archived == false`, and it is the default view.**
  Same discipline as the archive convention: default hides, an explicit option reveals lineage.
  Nothing is ever *hidden* — every artifact stays readable by id and listable on request, exactly
  as a deleted file stays readable in Git history. In-force is one view the caller may ask for,
  not a visibility policy.
- **D24 — `draft` is in force by default, with a caller option to exclude it.** "Currently
  governing" arguably excludes a draft, but agents want in-progress specs; the default follows
  what agents want, the option covers the stricter reading.
- **D25 — The `supersedes` edge never drives exclusion. The in-force decision keys on the
  target's own lifecycle.** The producer already writes both ends of a supersession —
  `type: supersedes → A` on the successor B *and* `status: deprecated` on A — so the filter
  needs only A's own metadata. `supersedes` remains what an untrusted `type:` value should be: a
  **fact** used for lineage and navigation ("what replaced this?"), and for consistency audits
  (deprecated with no successor edge; superseded but still `stable`), never a switch.
- **D26 — Revision history for offloaded artifacts is stored in the annotation store, not vector
  metadata.** Stated publicly on #28 (2026-09-23), reversing an earlier remark on the same thread.
  Annotations already hold the mutable, unbounded, per-object data; vector metadata is per-section
  duplicated and budget-bound.
- **D28 — A producer-supplied `id:` becomes the bare artifact id (was D12; idea 13).** Operative
  key stays `{write_prefix}/{id}{ext}` — cross-project uniqueness still comes from the prefix.
  Fallback to `generate_artifact_id` when `id:` is absent, so ordinary `write_artifact` callers see
  no change. Decided over idea 16 (id as a resolvable metadata field, key unchanged) on one
  question: *does the id need to be the key, or merely resolvable?* The answer is the key —
  `arkeology://artifact/{id}` and the plugin's `relationships[].to` share one namespace, so an
  agent moves between the Git corpus and Arkeology with the same names and no translation step.
  16 would have resolved `to:` correctly at ingest and then made every subsequent cross-over pay a
  lookup. Consequences: the deterministic-keys rule is *amended by ADR, not violated* — a frozen
  filename stem is deterministic and becomes an attribute once supplied; the rule's real target
  (randomness, UUIDs) is untouched; the hash suffix is simply not appended when `id` is present.
  Retitle churn disappears for supplied ids (the producer measured 10 retitles against 4 renames).
  Uniqueness follows the brief's own division — the producer guarantees, Arkeology verifies: a
  pre-write check across the migration manifest, plus `write_artifact`'s existing rejection of an
  existing key without `overwrite`. Charset and case handling are D33; tier-2 date
  anchoring is D32.
- **D29 — Graph fields are annotation-only; the existing `source_artifacts` vector-metadata
  projection is deleted, not carried over (was D11; idea 17).** The question was never "add a
  second copy" — the projection already exists and `reconcile_index` already handles the class. It
  was "keep or delete when the authoritative copy moves into the structured annotation." Delete.
  The only thing keeping it bought was the D20 warning at zero annotation reads; freshness gains
  nothing from it because the per-source `last_modified` baseline (D19) lives only in the
  annotation, so freshness pays the per-synthesis read regardless. One UX warning is not worth a
  second representation to keep honest. The filterable variant (ideas 18/19) would have made the
  warning *better* than today, but under OKF's reader-side model (D20) nothing needs to find a
  source's citers, so it is unnecessary (NA8).
  Consequence: `sources`, `relationships`, and revision history share one store; `commit_refs`
  remains the sole projected link field, and it is not a graph edge.
- **D30 — One revision-history entry is `{by, at}`.** The OKF `revised` shape, the same one the
  operator landed on in #28, repeated per write. `at` is the write's ISO 8601 UTC timestamp —
  the same value set as `revised.at` (D35); `by` is the writer's §7 actor string. A diff or change summary would be a different feature.
- **D31 — Revision history lives in its own annotation, decoupled from the link annotation.** The
  two have different mutation profiles: the link annotation is replaced whole whenever links
  change (`link_metadata`, ingest, reconcile), while history is appended on every content write.
  Sharing a payload would make every link update rewrite history it has no business touching, and
  every content write rewrite links it did not change. The object-ETag compare-and-swap guard
  already covers both, since it is the object's ETag rather than the annotation's.
- **D32 — Supplied ids carry no date-anchoring guarantee (was OQ3).** Tier-2 date-anchoring was
  a property of `generate_artifact_id`'s formula, where it kept a recurring title unique across
  days. Nothing in `src/` parses a date out of a key, and under D28 the producer guarantees
  uniqueness. *(Amended 2026-09-24.)* The `date` metadata field is removed — it is not an OKF field, and `generated.at` / `revised.at` carry both meanings it had. A generated tier-2 id anchors on the calendar day of `generated.at`; the store-migration skill (D42) drops `date` from existing artifacts.
  Generated ids keep the formula unchanged.
- **D33 — Supplied ids are validated and never repaired, and are case-preserving (was OQ2,
  OQ10).** Charset `[A-Za-z0-9._-]`; first and last character alphanumeric; no `/` (the
  `arkeology://artifact/{id*}` URI template expands across slashes, so an id with `/` would
  silently nest the key and turn ids back into paths); no `..`; at most 128 characters. Anything
  else is a `validation_error`. Neither slugification nor lowercasing ever runs on a supplied id —
  either would break byte-identity with `relationships[].to`. Uppercase is accepted verbatim: a
  supplied id is the producer's name, a generated id is Arkeology's own, and the two coexisting is
  two *sources* of ids rather than two conventions to keep aligned. Matching is exact and
  case-sensitive, as S3 keys already are, so an agent must carry an id with its case intact.
- **D34 — Revision history is uncapped, not returned by `list_artifacts` by default, returned by
  `read_artifact`, and returned by other tools on an explicit option (was D27).** Measured on
  2026-09-23 (see `## Measurement`): the 1 MiB limit holds exactly and about 14,500 `{by, at}`
  entries fit, so a cap would guard against something years away. Payload size barely affects
  read latency; the real cost is the extra annotation round trip D31 introduces, which
  `list_artifacts` would otherwise pay per artifact on every page.
- **D35 — `author_role` is dropped; `generated` and `revised` are first-class metadata (was
  D15).** The field predates OKF and, once it held a §7 actor string, duplicated `revised.by` —
  each write overwrote it. `generated: {by, at}` (written once) and `revised: {by, at}` (absent
  until the first revision, then set on every later content write — *clarified 2026-09-24*, as
  D40 already assumed) are stored in S3 object metadata and vector metadata as first-class
  fields, set by the writer. They are **not** derived from the revision-history annotation: that
  annotation is the log, whose first and last entries coincide with them. Actor values follow
  OKF §7 verbatim, unsplit — `<producer>/<version>`, `human:<id>`, `process:<id>`. Neither `by`
  (meaningless outside a `{by, at}` block) nor `author` (already `sources[].author` in OKF, a
  second subject for one key) was adopted as a rename. Two consequences: an overwriting `PUT`
  replaces all object metadata, so every overwrite must carry `generated` forward — the same
  trap the annotation read-forward already handles; and both fields may be **filterable** at no
  index cost, since only non-filterable keys are fixed at index creation (two pairs are about
  140 bytes of the 2 KB budget). `author_role`'s declared non-filterable slot stays, unused, so
  no re-index.
- **D36 — The artifact bucket is dedicated to Arkeology; a shared bucket is unsupported.** Creating
  a bucket costs nothing, so there is no reason to design around mixed content. Recorded in the
  README's prerequisites and the `setting-up-arkeology` skill (2026-09-23). Consequence for
  `reconcile_index`: its "is this object an artifact" check exists to avoid embedding stray files
  in a shared bucket; in a dedicated bucket, any object under the write prefix carrying
  Arkeology's own object metadata (`type`, `artifact_id`) is an artifact, and the startup probe
  keys are already filtered by name. No extra ownership tag is needed.
- **D37 — The artifact type list is open; OKF `type` is stored verbatim and matched exactly (was
  D16).** OKF's `type` is a free-form display string (`Attested Computation`, `BigQuery Table`)
  and consumers MUST tolerate unknown values, so Arkeology stops rejecting types outside
  `ARTIFACT_TYPES`. **No normalisation of the stored value** — folding case or turning spaces
  into `_` would rewrite what the producer wrote and diverge from the spec. The known types
  become a *recommended* list in the schema resource; Studio gains a default style for unknown
  types. Transformation happens in exactly one place, and never to the stored value: a
  **generated** id slugifies the type into the key (`Attested Computation` →
  `attested-computation-…`), which leaves existing ids unchanged because `Code Review` slugifies
  to the same `code-review` today's `code_review` produces. **Consequence — one-time rewrite of
  legacy values:** the corpus stores `spec`, `code_review`, `synthesis`; migrated plugin
  documents store `Spec`, `Code Review`. Under exact matching those would split every type
  filter, so the 16 legacy values are rewritten once to their OKF display names by the
  store-migration skill (D42), and code comparisons follow (`type == "Synthesis"` in `find_referrers` and
  freshness). Case-insensitive matching was rejected: S3 Vectors filters are exact, so it would
  need a second normalised copy of `type`. Accepted loss: the typo guard — `Sepc` becomes a new
  type. `Contract` is likely out of scope regardless: contracts sit closer to code and are often
  not markdown.
- **D38 — `sources` entries that point into Arkeology go through the cross-scope gate (was OQ5).**
  The old asymmetry — `references` gated, `source_artifacts` not — was a gap, not a choice:
  sources used to be external only. At ingest a resolved source stores its resource as
  `arkeology://artifact/{id}`, a URL §5.1 permits and a scheme Arkeology already registers. On
  read, entries with that scheme pass through the existing `resolve_readable_targets` unchanged
  (own-scope by prefix, foreign only if tier 3 and `shared`, unreadable **redacted**, not dropped — amended by D47); URLs and unresolved paths pass untouched. Reusing the one
  gate function adds nothing new to the mutation scope. `relationships[].to` stays a bare id
  because #16 types it as an id; `sources[].resource` is typed as a URI — each follows its field.
- **D39 — Arkeology does not wait for OKF rulings; it decides now and adapts later (was OQ8,
  OQ9).** Maintainer rulings could take months, and every other decision here was taken the same
  way. Concretely: `sources[].last_modified` is read under snapshot semantics (D19) and
  `relationships` is carried with optional per-edge `generated` / `verified` blocks, as #16
  proposes. If a ruling goes against either, the storage shape does not move — only the field's
  name or its spec standing, handled by a later migration keyed on `okf_version`. The fallbacks
  are recorded below so the adaptation is already scoped: for `last_modified`, a house custom key
  carrying the same snapshot value; for #16, the per-edge trust blocks become a house extension
  (still tolerated, since consumers must accept unknown keys). The PGM authority question — body
  links versus frontmatter as authoritative — is the one ruling that would reach further, since
  it would put the cross-referencing ADR's frontmatter-only D1 in question.
- **D40 — A missing `sources[].last_modified` is filled in at import from the source's current
  `revised.at`, and stored as an ordinary value.** When a producer omits it for a source that
  resolves into Arkeology, the import records the source's `revised.at` at that moment (its
  `generated.at` if never revised). No marker distinguishes a filled-in value from a supplied one:
  resolving the source during import confirms it exists at that version, which is itself a
  verification, so treating the citing document as fresh against it from that point is sound.
  External sources are left without it.
- **D41 — "Unverified since revised" is an advisory signal, never a change to the trust tier.**
  When an artifact's newest `verified.at` is older than its `revised.at`, Arkeology surfaces that
  as an advisory flag beside the tier, not as a demotion. §5.3 derives the tier from verifiers
  alone, with no timestamp ordering, so an artifact with a human verification stays
  human-reviewed however many revisions follow; §5.2 already allows content to change without
  re-confirmation. Keeping it advisory also keeps the failure direction safe: a consumer that
  ignores `revised` misses a warning, rather than reading a stale confirmation as current. The
  operator has argued on #28 (2026-09-23) that §5.3 *should* grow a tier for content updated
  since its last verification; if the spec adopts one, Arkeology maps the flag onto it (D39).

- **D43 — `sources[].resource` resolves through the target file's own `id:`; the backfill skill
  is kept for `sources` only.** *(PM session with operator, 2026-09-24.)* Under D28 every target
  file carries a frozen `id:`, so a path resolves by opening the file it names and reading that
  key — no path→id map, and correct across file renames. The result is stored as
  `arkeology://artifact/{id}`. `sources[].id` is **not** used for resolution: §5.1 defines it as a
  per-document footnote label joining body citations to entries, optional, and unrelated to the
  target's identity — reading it as a target id would resolve a coincidental label silently to the
  wrong artifact. `relationships[].to` is already an id, so it never needs backfilling; a source
  whose target was not yet in Arkeology at import still does, so `backfilling-references` stays,
  scoped to `sources`, and records the resolved source's current `revised.at` as `last_modified`
  (D40).
- **D47 — Cross-scope filtering of `sources` and `relationships` redacts rather than drops
  (amends D38).** *(PM session with operator, 2026-09-24.)* Silent dropping breaks OKF's trust
  framework: a foreign reader sees a list that looks complete but is not, and judges the document
  on provenance it does not actually rest on. Returning the hidden id is not acceptable either —
  a tier-2 id can itself be sensitive. So the entries the reader cannot read are removed and
  **one** redaction marker per list is appended carrying only their count — no id, resource,
  title or timestamp. One marker per hidden entry was rejected: list positions carry no meaning
  once the entries are gone, and the count is the only thing the reader needs. Own-scope readers still see the full list; the
  stored annotation is never touched; a deleted source stays in the list and is reported
  *missing* by freshness, as OKF's write-time-record semantics require. Stated limit: the gate
  governs the structured field, which is emitted mechanically and in bulk, not the body, which is
  authored — a shared document's author is responsible for what its prose names, as in any sharing
  system. The provenance-honesty purpose (the reader learns the list is incomplete) does not
  depend on the body at all. Raised upstream as OKF issue #32 (2026-09-24): partial visibility of
  `sources` across a trust boundary, proposing a single counted `withheld` marker per list.
- **D46 — `link_metadata` is renamed `add_artifact_links`; verifications get their own tool,
  `add_artifact_verification`.** *(PM session with operator, 2026-09-24.)* The old name read as
  "link the metadata" and did not say what the tool changes: it **adds** commit references,
  sources and relationships — merge and dedupe, never remove (removal happens only through an
  overwriting write). Storage location is deliberately kept out of the name. A verification is an
  event appended to the `verified` annotation (D44), not a set merge, so it is a separate tool
  rather than a parameter on the links tool; both build on one shared compare-and-swap
  annotation-append helper, which the revision history (D30) needs anyway. The "revised after
  verification" check is not a tool: `read_artifact` computes it (FR-71). Part of this release's
  breaking change (D42) — no alias for the old name.
- **D45 — The D41 flag is surfaced on read only for now.** *(PM session with operator,
  2026-09-24.)* Listings and search are deferred to backlog item B-14, which records the chosen
  approach — a vector-only `last_verified` projection derived from the `verified` annotation —
  and the alternatives rejected.
- **D44 — `verified` lives in its own annotation.** *(PM session with operator, 2026-09-24.)*
  Not object or vector metadata: S3 user-defined object metadata is capped at 2 KB per object,
  and a new vector-metadata key is filterable by default, so it would count against the 2 KB
  filterable budget on every section vector. A list that grows with each review would eventually
  trip the write-path budget check and block ordinary content writes. Its own annotation, apart
  from the link annotation and the revision-history annotation, for D31's reason: reviewers
  append to it on their own schedule, independently of link edits and content writes. Recording
  a verification after the write is an annotation-only write — no re-PUT, no re-embedding, no
  `revised` change. Nothing filters on it.
- **D42 — Breaking change; existing stores migrated by a dedicated skill plus scripts, not by
  `reconcile_index`.** *(PM session with operator, 2026-09-23.)* No deprecated aliases — the
  no-fallback-paths rule applies to parameter names as much as to stores. `reconcile_index`
  repairs index drift from S3; it is not a metadata-key migration tool, so the one-time rewrite
  of objects, metadata, vectors and annotations lives in the migration skill's scripts.

#### How the in-force decision is made (2026-09-23)

The question was first written as *"should `supersedes` drive in-force queries?"* — which
conflated two axes and mis-stated a third.

| Axis | Question | Belongs to |
|---|---|---|
| **View** | latest-only, or full lineage? | the **caller**, per query (D23) |
| **Trust** | how does the server honour an in-force request when it cannot verify `type: supersedes` from one frontmatter line? | the **server**, as policy (D25) |

The trust axis is *not* about hiding. Issue #22's threat is the inverse of hiding: an automated
writer emits `type: supersedes` against a real spec, a caller asks for in-force, and the real spec
drops out of that answer while the impostor stands in for it. #22 guards this with three rungs —
edge provenance authorises nothing; source eligibility (the asserting concept is itself in force)
is what Data Olympus ships; only an **attributed resolution** authorises exclusion — and puts the
resolution in a bundle-root `log.md`. Arkeology has no `log.md`. It does not need one:

| #22 rung | Their evidence | Arkeology equivalent | Effect on in-force |
|---|---|---|---|
| 1 — edge provenance | `generated` / `verified` on the edge | edge exists on B | **none** — lineage only |
| 2 — source eligibility | B is itself in force | B `stable` and not archived | A's read result may show *"proposed successor: B"* |
| 3 — attributed resolution | entry in bundle-root `log.md` | **`status: deprecated` on A**, attributed via A's `revised.by` | A excluded |

Why keying on the target dissolves the threat rather than solving it: the #22 edge is cheap,
machine-derived, and written on a *different document* than the one it retires. `status:
deprecated` on A has none of those properties. It is a write **to A**, governed by whatever
governs writes to A — the own-scope write authority that can already archive or delete A. So
deprecation is no escalation of power over what any writer to A already holds, and it is
attributed. Cross-scope falls out for free: team X's B may declare it supersedes our A; it cannot
write our A, so A stays in force in *our* results and their claim is visible as lineage only. The
edge-without-deprecation state — B says supersedes, A still `stable` — is exactly #22's "proposed,
not affirmed", and here it is visible rather than hidden.

#### D9 as amended (2026-09-22)

Recorded on 09-17 as: keep `authored` / `revised` unchanged, remove `timestamp`, add `generated`
as a spec-compliant *copy of the last revision*. That is wrong. The producer withdrew the
mirroring decision after adopting §5.1's reading, under which `generated.at` is *when the concept
was first written*.

| Key | Meaning | Mutation |
|---|---|---|
| `generated: {by, at}` | first authored, by whom | written once, **never rewritten** |
| `revised: {by, at}` | latest touch only | replaced in place; **never a list** |
| `verified: [{by, at}]` | confirmation events | appended |

House `authored` ceases to exist rather than being retained. Every `at` is an explicit-offset ISO
8601 datetime. Actors follow §7: agents `amanox-<role>/<model-id>`, humans `human:<git user>`.

### Pending

_None._

### Closed — Not Applicable

- **NA1 — Storing inbound edges.** No producer will emit them; Arkeology computes the inverse.
- **NA2 — Flattening `sources` and `relationships` into one untyped list (the former D14).**
  **Struck.** It was the producer's stated *floor*, recorded here as a selected direction, and it
  contradicted D3 outright. Both fields are structured objects, so the comma-joined payload cannot
  hold them regardless.
- **NA3 — Treating the annotation payload format change as avoidable.** Struck with NA2. Once
  entries are objects, a structured payload is required, not optional.
- **NA4 — Generalising `source_artifacts` to carry all relationship types.** Its cheap reverse
  lookup depends on the fact that only syntheses have one, which gives `find_referrers` a bounded
  `type == "synthesis"` prefilter. Generalising the field destroys that prefilter and makes the
  lookup a full-corpus scan — independent of which store the field lives in.
- **NA5 — Edge-driven exclusion: evaluating `supersedes` trust at query time to decide what an
  in-force query drops.** Superseded by D25. It would need the three-rung evaluation, a home for
  attributed resolutions (#22's bundle-root `log.md`, which a store does not have), and a reverse
  lookup on every in-force query. Keying on the target's own `status` needs none of it.
- **NA6 — Renaming `ArtifactStatus` to `ArkeologyStatus` / `ArkeologyLifecycle`.** Rejected under
  D21: both keep the word that collides, and renaming only the enum fixes the code reader's
  confusion while leaving the agent's untouched — the wire would still say `status: active`.
- **NA7 — Honouring `id:` but appending the 8-hex hash suffix (idea 15).** Dead on arrival: the
  stored key would no longer equal the producer's `id`, so `relationships[].to` could not resolve
  to it — defeating the only purpose of accepting the id.
- **NA8 — A filterable projection of source targets in vector metadata (ideas 18/19).** Rejected
  as unnecessary under D20: OKF's reader-side model means nothing needs to find a source's citers
  when it changes, so the projection would only have widened a convenience warning. *Correction
  to the earlier reasoning:* it does **not** need a re-index. Only reusing the `source_artifacts`
  name — declared non-filterable at index creation — would; a new key name (e.g. `derived_from`)
  is filterable by default. The cost that remains is a second copy for `reconcile_index` to keep
  in sync and a cap for the 2 KB budget (syntheses can cite up to 100 sources).

## Problem Statement

OKF v0.2 turns two things Arkeology had settled into open questions again.

The first is the repo's own documents: a version migration, plus a `status` key that now collides
with a house key of the same name and a different vocabulary. That work is owned by the plugin.

The second is ingestion. Arkeology reads documents the plugin writes, and those documents are
changing shape in four ways at once — the untyped `references` list splits into `sources` plus
typed `relationships`, the `authored` block becomes `generated` with a different meaning, the
`status` vocabulary collapses to three values, and every document gains a frozen house `id`. The
first three are additive work against a stated contract. The fourth asks Arkeology to stop minting
its own identifiers for migrated content, which reaches into ADR-005 and a Non-Negotiable Rule.

## Known Constraints

| Constraint | Source |
|---|---|
| #16 (typed relationships) and #28 (`generated` semantics) are **open with no maintainer reply** — every commenter is `NONE` association. What exists instead is **six independent implementations converging in public** (Roteiro, Data Olympus, telamon, PGM, andrewcrenshaw's exporter, the amanox plugin). Community convergence is not ratification | GitHub issues #16, #22, #28 — read via `gh`, 2026-09-23 |
| `sources[].last_modified` has **no stated capture semantics** in the spec — it does not say whether a producer re-checks at write time or copies a previously observed value | OKF SPEC §5.1 |
| The current annotation payload is comma-joined with no escaping; `validate_references` rejects commas | `s3-annotations.artifact` contract, **Compatibility Guarantees** |
| `references` is absent from vector metadata; restoring queryability is "a graph-technology decision, not a storage tweak" | `s3vectors.artifact` contract |
| Filterable vector metadata is capped at 2 KB per vector; non-filterable keys share a 40 KB total. Non-filterable keys are fixed at index creation (1–10 keys), so adding one requires a re-index | `artifact.py` budget constants; AWS `CreateIndex`; budget ADR **Option E** |
| An artifact is N vectors (one per section), each carrying a full metadata copy, and they can disagree after a failed partial-overwrite cleanup | `freshness.py` `_is_newer_write` |
| Annotations carry a far larger ceiling, are mutable in place, leave the ETag stable — and are **wiped when the object is overwritten**, requiring read-forward on every overwriting write | `s3-annotations.artifact` contract |
| `list_artifacts` **already** performs one annotation read per artifact per page; `search_artifacts` reads no annotations at all | `list.py`, `search.py` |
| Artifact ids carry a mandatory 8-hex SHA-256 suffix disambiguating the empty-slug, truncation and punctuation-collapse collision classes — **for generated ids**; D28 omits it when the producer supplies `id`, and the producer's uniqueness guarantee replaces it | AGENTS.md **Working Conventions**; ADR-005 |
| `_slugify` collapses any non-`[a-z0-9]` run to a hyphen, so a producer stem containing dots does not survive slugification | `artifact.py` `_slugify` |
| Arkeology has **no bundle-root `log.md`**. #22 puts its attributed-resolution rung there and states a resolution entry anywhere else *"is not an affirmation"*. Any Arkeology equivalent must live on the artifact | OKF issue #22; this is a store, not a bundle |
| **Nothing parses artifact-id structure.** The only split is a `/` prefix split in `reconcile.py` for the probe-key marker | verified 2026-09-22 across `src/arkeology/` |

## The Producer Contract (inbound)

What the plugin commits to emitting. Decided, not yet implemented.

- **`id:`** — house key seeded from the filename stem at creation, frozen thereafter. Charset is
  whatever a filename stem is, including dots. Uniqueness is the producer's guarantee; Arkeology
  is asked to verify it before ingest.
- **`sources:`** — OKF §5.1. Each entry carries `resource` (bundle-relative path or URL) plus
  optional `id` and `title`. Cross-repo targets become `sources` with a repository URL.
- **`relationships:`** — house key, shape from #16, constrained to `{to, type}`, outbound only.
  `to` is an `id`, **never a path**. The constraint exists so that if #16 rules "frontmatter is a
  derived index over body links", the ingested list is byte-identical to a projection.
- **`generated` / `revised` / `verified`** — as tabulated under D9 amended.
- **`status`** — three values. **`type`** — free-form, capitalised.

The two link fields resolve by **different mechanisms**: `sources[].resource` is a path resolved by
reading the target file's own `id:` (D43; URLs pass through), while `relationships[].to` is already an id and needs
lookup, not normalisation. `references.py`'s `extract_references_list` and its `^references:`
regex, and the equivalent match in `backfilling-references`, stop matching anything.

The producer explicitly parks typed edges with us: *"Later, on your schedule: typed edges in
metadata; `supersedes`-aware in-force queries; per-write revision history."*

**One discrepancy to raise with the producer.** The brief treats a dangling `supersedes` target as
an error, citing *"the Data Olympus / Roteiro split on #16 — we take both."* That split has since
closed the other way: #22, revised 2026-09-14, rules for **both** registered types that a dangling
target is *"not an error — if the target is absent, the carrying concept is current."* The brief
is following a position its sources have abandoned.

## Ideas Explored

**Payload shape** *(settled — idea 2, D29)*

1. Untyped `list[str]` with a type prefix per entry (`builds_on:<id>`). Superseded — entries are
   objects, not strings.
2. Structured payload (JSON) in a single annotation, `sources` and `relationships` kept distinct
   inside. The operator's stated preference.
3. One annotation per relation type, each a comma-joined id list. Cheapest typing route, but
   superseded for the same reason as idea 1.
4. Do not store link structure in Arkeology at all; keep it in the document body, which Arkeology
   stores verbatim, and synthesise at export.
12. Flatten everything into the existing untyped list. **Struck — NA2.**

**Storage location** *(settled — D29)*

17. Authoritative structured copy in the annotation; **no** vector-metadata copy. Coherent single
    home; the D20 warning pays one annotation read per synthesis. **Selected — D29.**
18. Authoritative in the annotation **plus a derived filterable projection** of derivation targets
    in vector metadata — the `commit_refs` pattern, where the projection is *"written so the index
    can answer … via a server-side filter clause, never read back as a source of truth."* Keeps the
    D20 warning as a single server-side `$eq`, better than today's prefilter-then-scan. Constrained
    by the 2 KB filterable budget, so it needs a cap.
19. As 18, but cap the projection **semantically rather than numerically** — project only edge
    types with operational meaning (`synthesises`, and `supersedes` if in-force queries arrive)
    instead of an arbitrary most-recent-N cut that silently drops real edges. **18 and 19
    rejected — NA8.**

**Identity** *(settled — D28)*

13. Honour `id:` when present, fall back to `generate_artifact_id` when absent — the brief's ask.
    **Selected — D28.**
14. Ignore `id:` and keep minting from attributes. **Rejected** — ignores measured evidence (43
    wrong links from path derivation) and keeps retitle churn.
15. Honour `id:` but append the existing 8-hex suffix. Keeps collision disambiguation; breaks the
    byte-identity with `relationships[].to` that is the whole point of accepting it.
16. Honour `id:` as a separate indexed field rather than as the key, resolving `to` through it.
    **Rejected** — correct at ingest, but every later Git↔Arkeology cross-over pays a lookup.

**Freshness** *(settled — D19)*

20. Per-source baselines from `sources[].last_modified` (ISO 8601) instead of one synthesis-wide
    `last_edited_ulid`.
21. Synthesis-level `generated.at` as the baseline. **Rejected** — written once and never updated,
    so a genuine re-synthesis would report stale forever.
22. Per-edge `generated`/`verified` borrowed from #16. **Superseded by 20** — `last_modified` is
    native v0.2 and needs no unruled proposal.
**In-force mechanism** *(settled — D23–D25)*

23. Never act on `supersedes`; return everything and let the agent sort it out. Zero risk, zero
    benefit. **Rejected** — the archive convention already establishes "default hides, option
    reveals" as the house model.
24. Exclude the target when the edge exists and the asserting artifact is itself in force — #22's
    rung 2, what Data Olympus ships. **Rejected** — one machine-written line on B can still
    remove A from every in-force answer.
25. Exclude only once a human or trusted process has affirmed the specific retirement — #22's rung
    3. Correct, but needs an affirmation store. Two candidate homes: `verified: [{by: human:<id>}]`
    on the `supersedes` edge itself, or —
26. **Key the decision on the target's own `status: deprecated`, which the producer already
    writes.** Rung 3 by construction: the affirmation is a governed, attributed write to the
    document being retired. **Selected — D25.**

## Clusters

- **Payload shape** (1, 2, 3, 4, 12) — how structured entries are encoded.
- **Storage location** (17, 18, 19) — one home or one home plus a derived index. Settled: one home.
- **Identity** (13–16) — who mints the artifact id.
- **Freshness** (20, 21, 22) — what the staleness baseline is measured against.
- **In-force mechanism** (23, 24, 25, 26) — what evidence an in-force query acts on.

## Selected Directions

**Idea 2 + idea 17**: a single structured annotation holding `sources` and `relationships`
distinctly, and **nothing about either in vector metadata**. One authoritative home for every
artifact-to-artifact edge, no derived index to keep honest, no re-index. The delete/archive
warning pays one annotation read per own-scope synthesis, bounded by the synthesis count — the
same cost class `list_artifacts` already accepts per page.

Confirmed 2026-09-23 (D29).

## Techniques Used

- **Codebase archaeology before ideation** — established that Arkeology already stored typed edges
  by giving each type its own field, reframing "add typing" as "generalise an existing pattern".
- **Constraint-first framing** — establishing the no-escaping payload as a hard boundary before
  generating options eliminated whole families of shapes up front.
- **Blast-radius probe before trade-off analysis** — checking whether anything parses artifact-id
  structure (nothing does) moved D12 from "violates the scheme" to "violates a stated rule whose
  practical reach is one prefix split".
- **Reductio, operator-supplied** — "does every source change force a rewrite of every citing
  document?" collapsed the live-mirror reading of `last_modified` far faster than argument from
  convenience, because that reading is simultaneously the most expensive and the least useful.
- **Argument from the spec's internal consistency** — `usage_window` exists to frame `usage_count`
  as an observation. `last_modified` sits in the same block, so snapshot semantics follow from the
  document's own structure rather than from what suits us.
- **Retraction discipline** — two positions taken in this session were reversed on evidence. Both
  are recorded below rather than quietly edited away.
- **Perspective shift, operator-supplied — "when I look at Git history I can see everything, even
  deleted files."** Reframed the trust question from *when may the server hide* to *how faithfully
  can the server honour a request it cannot verify*. Nothing is hidden; one view is filtered on
  request.
- **Move the decision to where the authority already is.** The `supersedes` edge is untrusted
  because it is written on a different document than the one it retires. Keying on the target's
  own `status` puts the decision under the write authority that already governs that document,
  which dissolves the trust problem instead of adding rungs to solve it.
- **Read GitHub through `gh`, not a rendered page.** Two fetches of #16 and #28 reported zero
  comments; `gh` showed eight on #28 alone. Every upstream state recorded here was re-read through
  the API.

## Assumptions Challenged

- "Adopting the plugin's `sources` + `relationships` shape is OKF adoption" → **half true.**
  `sources` is real OKF v0.2. `relationships` is a house key tracking open proposal #16, hedged by
  the producer to stay byte-identical under either ruling. Neither #16 nor #28 has a maintainer
  reply.
- "`direction: inbound` contradicts Arkeology's model" → **true, and resolved in our favour.**
- "The comma-joined payload is the crux" → **true, but not for the reason first given.** It does
  not block *ingestion*; it blocks storing structured entries, which is what both fields turned
  out to require.
- "The `status` key collides at product level" → **false.** `ArtifactStatus` is an archive marker.
- "Arkeology's id formula is more stable than a filename stem" → **false on this corpus.** The
  producer measured 10 retitles against 4 renames, and the formula is a function of `title`.
- **Retraction 1 — "`source_artifacts` is a relationship, not a source."** Accepted mid-session on
  the reading that OKF `sources` means evidence-proving-correctness. §5.1 says otherwise: `sources`
  *"records the materials a concept derives from"*, with citation a secondary role keyed into the
  same list. `source_artifacts` is a `sources`. See D18.
- **Retraction 2 — "moving `source_artifacts` to annotations loses the `find_referrers`
  prefilter."** False. `type` is filterable and stays where it is, so the prefilter still narrows
  to syntheses; what is lost is that the field is no longer in hand afterwards, costing one read
  per candidate. The unbounded case comes from *generalising the field's semantics* (NA4), not
  from the storage choice. These were conflated twice.
- "Losing `source_artifacts` from `search_artifacts` is a regression" → **false, it is a
  cleanup.** `search_artifacts` already omits `references`; today's inclusion of one and not the
  other is an inconsistency nobody chose.
- "Per-edge metadata improves freshness query efficiency" → **false.** It improves *accuracy*. The
  source-side batched `$in` query is unavoidable either way, and today's two batched queries are
  already near-optimal.
- "`ArtifactStatus` and OKF `status` do not collide" → **false for the agent.** They do not
  collide in code; they collide in every `read_artifact` payload after migration. D21.
- "'Exclusion follows affirmation' answers the in-force question" → **it answers half of it.** It
  is a trust rule about honouring one request the server cannot verify. It says nothing about
  whether a caller wants the latest or the lineage, which is the caller's choice per query. The
  two axes were conflated in the original OQ7 (now resolved).
- "Arkeology needs an equivalent of #22's `log.md` to reach rung 3" → **false.** The producer
  already writes `status: deprecated` on the retired document; that write *is* the attributed
  resolution, on the artifact, under the authority that governs it.
- "`supersedes` is the one edge with lifecycle meaning, so the in-force filter should turn on it"
  → **the meaning is real, the mechanism is wrong.** The edge is lineage; the lifecycle key is
  `status`.
- "D11 is about adding a second copy" → **false.** The projection already exists; the decision
  was keep-or-delete. Framing it as an addition made keeping look free and deleting look like
  work, when the upkeep cost runs the other way.
- "Freshness argues for keeping the projection" → **false under D19.** The per-source baseline
  lives only in the annotation, so freshness reads the annotation per synthesis whether or not a
  target-id projection exists. That removed the strongest reason to keep it.

## Upstream Items

State as of 2026-09-23, read through `gh`. **No maintainer has replied to any of them.**

- **#28 — `generated` semantics.** Filed by the operator 2026-09-17; eight comments, a real design
  exchange with the Data Olympus maintainer. Landed on exactly the plugin's D12 shape: `generated`
  written once with first-authorship meaning, `revised` a **single object, not a list** (revisions
  subsume where attestations do not, so a list is the one field that grows without bound),
  `verified` a list. The operator's 2026-09-23 comment states this shape and that Arkeology's
  revision history goes to annotations (D26). `stale_after` conceded for event-driven corpora (D7).
- **#16 — typed relationships carrier.** Filed 2026-09-01 by Roteiro. Six implementations now in
  the thread. Convergence on: outbound only (D13); **stable ids over paths** — pixie79 derived
  paths from keys and *"guessed wrong for 43 links on a real render, each a valid-looking path to
  a file that did not exist"*; andrewcrenshaw: a file move *"silently reattaches an edge to the
  wrong incumbent"* (decided D28). PGM raises the authority question — is the frontmatter list
  authoritative or a derived projection over body links? — see D39. The operator's own
  2026-09-17 comment on this thread still shows `direction: outbound` / `direction: inbound` on
  three edges, a shape the plugin has since abandoned; worth a follow-up so the thread does not
  carry it.
  The Data Olympus maintainer's latest comment (2026-09-23) asked two things: whether `revised`
  is a single object or the one-element form of a list, and whether "unverified since revised"
  changes the §5.3 tier or is advisory. Arkeology's answers: a single object, latest only (D9) —
  full history lives in Git for a repository and in an annotation for Arkeology, never in the
  frontmatter; and advisory (D41). The operator replied accordingly and proposed that §5.3 gain
  a tier for content updated since its last verification.
- **#22 — query-time semantics for `supersedes` and `contradicts` on the #16 carrier.** Kept
  deliberately separate from #16 so a maintainer can accept the carrier and defer the registry.
  Supplies the three-rung model Arkeology's in-force mechanism maps onto (D25), and settles the
  dangling-target question for both types as *not an error*.
  **The operator posted Arkeology's mapping on 2026-09-23:** rung 3 reached without a `log.md` by
  keying on the retired concept's own `status: deprecated`; the in-force clause with its
  `archived` term; the four-row table; and an ask that the registration name "the target itself
  carries `status: deprecated`, attributed" as a second acceptable form of attributed resolution.

- **#32 — partial visibility of `sources` across a trust boundary.** Filed by the operator
  2026-09-24 out of D47. Asks the spec to rule drop / reveal / redact when a served document's
  `sources` include entries the reader may not see, and proposes a single `withheld: <count>`
  entry per list, emitted by the serving party and surfaced by consumers. Arkeology ships the
  proposed shape now (D39 applies: adapt the marker's key if the ruling differs, storage is
  untouched either way). No reply yet.

Two items previously drafted here — a #16 comment on inverse cost and a new issue on
`last_modified` capture semantics — were dropped; the operator wrote their own.

## Note to the Plugin Maintainers

Arkeology will populate the optional per-entry blocks on edges **it mints**, and will not add them
to edges ingested from plugin documents — preserving the byte-identity property the `{to, type}`
constraint exists to protect. If the plugin's migration or validation round-trips a document, it
must not strip unknown sub-keys from a `sources` or `relationships` entry.

Two further points from the 2026-09-23 upstream read:

- **Dangling `supersedes` is not an error under #22 as revised.** The brief's "treat as error"
  rule follows a split that has since closed the other way. Arkeology will treat it as benign —
  the carrying concept is current — and would rather the producer's validator agreed.
- **`status: deprecated` on the retired document is load-bearing for Arkeology.** The brief
  describes it as the producer's side of a supersession; D25 makes it the *only* thing the in-force
  filter turns on. If the producer ever writes the `supersedes` edge without flipping the target's
  `status`, the target stays in force — by design, and worth knowing.

## Measurement

**Annotation payload calibration (for D34) — measured 2026-09-23** against the real test account,
by a one-off test, `tests/integration/test_calibration_annotation_payload_budget.py`, since
deleted at the operator's request — these results are the record. It annotated a
throwaway object inside the run-scoped `integration-tests/<run-id>` prefix only, and cleaned up.

- **The limit is exactly 1 MiB of payload bytes, and the annotation name does not count against
  it.** 14,563 entries were accepted at 1,048,536 bytes; 14,564 were rejected at 1,048,608 bytes
  with `EntityTooLarge`. The same payload was accepted under a 125-byte name. There is no hidden
  overhead of the kind the 2026-08-13 vector-metadata calibration found.
- **Practical ceiling: about 14,500 `{by, at}` entries** of about 72 bytes each, within the
  10,000–20,000 arithmetic estimate.
- **Read latency (median / p90), `GetObjectAnnotation`:** ~1 KB 63 / 66 ms · ~100 KB 70 / 89 ms ·
  ~1 MiB 135 / 212 ms. Put: 88 / 100 · 92 / 116 · 143 / 173 ms. Payload size barely matters until
  close to the ceiling.
- **Method, for re-running:** put a small object under the run-scoped prefix; exponentially then
  binary-search the entry count of a JSON list of `{"by": "amanox-analyst/claude-opus-5-5",
  "at": "<ISO 8601>"}` entries until `PutObjectAnnotation` returns `EntityTooLarge`; re-put the
  maximum under a 125-byte name; time 7 put/get repetitions at each size; delete the object.

**What this means for revision history (D34):** size is not the problem, even for a returned history. The cost of
returning history by default is the **extra round trip**: D31 puts history in its own annotation,
so returning it on `list_artifacts` doubles that tool's per-artifact annotation GETs (about 65 ms
each) — whatever the history's length.

## Open Questions

_None._

## Resolved Questions

- **Does anything in v0.2 break Arkeology today?** No. A v0.1 bundle stays consumable under the
  spec's fallbacks, so adoption is voluntary.
- **Where does `okf_version` belong per the spec?** A bundle-root `index.md`. Not prohibited on a
  concept document. See D4.
- **Stored versus computed inbound edges?** Outbound only, inverse computed — D13.
- **Is `generated` a copy of the last revision?** No — first authorship, written once. D9 amended.
- **Is `source_artifacts` a relationship or a source?** A source. D18, retraction 1.
- **Does keeping `last_modified` accurate require rewriting every citing document?** No — snapshot
  semantics. D19.
- **Does freshness need reverse lookup?** No. OKF puts the duty on the reader: follow each source
  edge forward and compare, for any document with sources. Reverse lookup serves only the
  synthesis pre-delete warning, a convenience beyond OKF. D20.
- **Must the annotation payload become structured?** Yes — both fields carry objects. NA3.
- **Does `referenced_by` survive?** Yes, for syntheses only, as a convenience. Deleting or
  archiving a source carries no obligation towards the documents that cite it. D20.
- **Should `supersedes` drive in-force queries (was OQ7)?** No — the question conflated the
  caller's view choice with the server's trust problem, and mis-framed trust as hiding. In-force
  is a default view the caller can widen (D23); the filter keys on the target's own `status`,
  which the producer already writes and which sits under the write authority that governs that
  document (D25). `supersedes` is lineage, never a switch.
- **Does `ArtifactStatus` collide with OKF `status`?** Yes, in the agent-facing payload. Resolved
  by renaming the archive marker to `archived: bool` (D21).
- **Where does per-write revision history live (was OQ6)?** In its own annotation (D26, D31), one
  `{by, at}` per write (D30), uncapped (D34).
- **Does Arkeology accept a foreign id-minting authority (was OQ1)?** Yes — D28. The id needs
  to be the key, not merely resolvable, because the value is one namespace across Git and
  Arkeology. Three implementations converging on stable ids, one with a measurement, made the
  case; the interchangeability requirement decided it.
- **Does the derived projection earn its second copy (was OQ4)?** No — D29. Delete the existing
  `source_artifacts` vector-metadata copy; graph fields are annotation-only. Freshness gains
  nothing from it, the delete warning pays one bounded read per synthesis, and under OKF's
  reader-side model nothing needs to find a source's citers. (A projection under a new key would
  not have needed a re-index — NA8.)
- **Tier-2 date-anchoring under a supplied id (was OQ3)?** Dropped for supplied ids — D32.
- **Is a supplied id validated or accepted verbatim (was OQ2)?** Validated, never repaired —
  D33.
- **Uppercase supplied ids (was OQ10)?** Accepted verbatim, case-sensitive — D33. Lowercasing at
  migration alone would have broken byte-identity with the Git corpus.
- **Is revision history capped, and returned by default (was D27)?** No cap; `read_artifact`
  returns it, `list_artifacts` does not unless asked — D34.
- **How does `author_role` receive the §7 actor string (was D15)?** It doesn't — dropped in
  favour of first-class `generated` / `revised` metadata. D35.
- **What happens to a `type` outside `ARTIFACT_TYPES` (was D16)?** The list opens; types are
  stored verbatim and matched exactly; legacy values are rewritten once to display names — D37.
- **Is the `sources` ungated / `references` gated asymmetry deliberate (was OQ5)?** A gap.
  Arkeology-internal sources now go through the same gate — D38.
- **What if `last_modified` is ruled a live mirror (was OQ8), or #16 is rejected (was OQ9)?**
  Not waited on. Decided now, fallbacks recorded, adapt on ruling — D39.

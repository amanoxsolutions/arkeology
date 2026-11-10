---
type: Spec
id: p15-t84-sources-relationships
title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
description: Replaces the comma-joined references annotation and the source_artifacts field with one JSON link annotation holding OKF sources and relationships, deletes the source_artifacts vector projection without a re-index, fills a missing sources[].last_modified from the cited artifact's revision time, rewrites the synthesis delete/archive warning as a type prefilter plus one annotation read per own-scope synthesis, and renames link_metadata to add_artifact_links. Removed names are rejected with validation_error naming the replacement.
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
  - id: adr-annotations
    resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-studio-links
    resource: docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md
    title: Studio-Side Resolution of arkeology:// Links on the Human Read Surface
    last_modified: 2026-09-25T00:00:00Z
  - id: spec-t76
    resource: docs/specs/p15-t76-archived-boolean.md
    title: "T76 — Archive Marker status → archived (bool)"
    last_modified: 2026-10-13T15:57:36Z
  - id: spec-t77
    resource: docs/specs/p15-t77-open-type-list.md
    title: "T77 — Open Type List"
    last_modified: 2026-10-13T13:04:34Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: "T78 — Split Writing into create_artifact / update_artifact; Drop overwrite"
    last_modified: 2026-10-13T13:02:46Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: spec-t80
    resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:40:30Z
  - id: spec-t81
    resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: "T81 — OKF Lifecycle status and the In-Force Default View"
    last_modified: 2026-10-13T16:19:13Z
  - id: spec-t87
    resource: docs/specs/p15-t87-supplied-ids.md
    title: "T87 — Producer-Supplied id Becomes the Artifact Id"
    last_modified: 2026-10-13T16:38:44Z
  - id: contract-s3-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-link-metadata
    resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-delete
    resource: docs/contracts/modules/arkeology.tools.delete.md
    title: arkeology.tools.delete
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-archive
    resource: docs/contracts/modules/arkeology.tools.archive.md
    title: arkeology.tools.archive
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-freshness
    resource: docs/contracts/modules/arkeology.tools.freshness.md
    title: arkeology.tools.freshness
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-purge
    resource: docs/contracts/modules/arkeology.tools.purge.md
    title: arkeology.tools.purge
    last_modified: 2026-09-04T00:00:00Z
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format — Specification
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-07-03-annotation-backed-link-storage
    type: constrained_by
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
  - to: p15-t78-create-update-split
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t80-revision-history
    type: builds_on
  - to: p15-t77-open-type-list
    type: builds_on
  - to: p15-t76-archived-boolean
    type: builds_on
  - to: p15-t87-supplied-ids
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T17:23:06Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T22:03:18Z
---

# T84 — `sources` + `relationships` in One Structured Annotation; `link_metadata` → `add_artifact_links`

## TL;DR

An artifact's OKF `sources` (what it was built from) and `relationships` (typed edges to other
artifacts) live together in one JSON annotation, `links`, and nowhere else. It replaces the
comma-joined `references` annotation and the `source_artifacts` field in both metadata stores.
A source that points into Arkeology without a `last_modified` gets the cited artifact's current
revision time when it is written. The synthesis delete/archive warning becomes a `type` prefilter
plus one annotation read per own-scope synthesis, and `link_metadata` becomes `add_artifact_links`
(D17, D18, D29, D40, D46).

## Open Questions

Item 1 is resolved; it is kept, with its number and status, in R24 ("Open Questions item 1").

2. **Non-blocking — bare-id links on read surfaces.** Under AC-58, migrated content and fields
   carry `arkeology://artifact/{bare id}`. Today the `arkeology://artifact/{id*}` resource, and
   Studio through `read_artifact`, accept only full keys, and the studio link resolution ADR's
   revision leaves this open. No plan task owns it. *Recommended:* T88 or T85 routes both surfaces
   through this spec's resolver, with the reader's own scope as the carrier.
3. **Non-blocking — upgrade order (T91).** An update or archive before T90 runs re-PUTs the
   object, and that drops its legacy `references` annotation, which nothing reads. A failure-log
   entry written before the upgrade keeps a `references` copy that replay ignores. *Recommended:*
   T91's **Breaking** CHANGELOG entry says to run `reconcile_index` until the log is empty, then
   the store migration, before any write on the new version.

## 1. Problem Statement

OKF v0.2 splits the untyped link list into derivation edges (`sources`, objects with a resource
and a revision-time baseline) and association edges (`relationships`, objects with a target and a
type). Today's link annotation is a comma-joined string with no escaping, so it cannot hold
objects (ADR-017 `## Context`, "Forces"). `source_artifacts` sits in S3 object metadata, which is
capped at 2 KB, and in a vector projection whose only remaining job is a zero-read delete warning.
Freshness pays an annotation read anyway, because the per-source baseline lives only there (D29).
The tool name `link_metadata` does not say what the tool does (D46). This task moves both fields
into one structured annotation, deletes the projection, and renames the tool. No compatibility
aliases are kept (D42).

All seven of this spec's user stories are P1: both fields round-trip and are never filters (R17,
R28), an update replaces both fields and carries `commit_refs` forward (R15), a missing baseline is
filled at write (R18), `add_artifact_links` adds, never removes, and never re-embeds (R21),
replay never resurrects a replaced link (R26), the synthesis-only delete/archive warning (R32,
R33), and removed names are rejected, not aliased (R36).

**Where T85 and T86 hook in.** T85 replaces the cross-scope reference filtering step in
`read_artifact` and in `list_artifacts` with redaction plus the `{withheld: n}` marker. It extends
that to sources that resolve to an Arkeology key, and adds the frontmatter rewrite in read,
synthesis preparation and the data resources. T86 replaces the comparison inside
`check_synthesis_freshness`. It consumes the per-synthesis `sources` list read here: resolved keys
plus `last_modified` as stored. Both use this spec's link-target resolver (R12) and do not
re-decide it.

## 2. Rules — Storage

### R1 — `sources` and `relationships` are stored in one `links` annotation, a JSON object with exactly two list keys

THE SYSTEM SHALL store `sources` and `relationships` in one S3 object annotation named `links`.
Its payload is a JSON object with exactly two keys, `sources` and `relationships`, each a JSON
array of objects. It is encoded the way T80 encodes `revision_history`: non-ASCII characters are
escaped, so the bytes are stable. Entries keep the key order they were supplied in.

**Why:** D29 fixes "one annotation", and ADR-017 `## Deferred to the Specs` leaves the name and
serialisation to the data contract. A keyed object keeps the derivation/association split (D17)
visible in the stored bytes and lets each list be replaced separately. JSON with escaped non-ASCII
matches T80, so one encoder and one size check serve every structured annotation.

Source: FR-51, FR-54, C-01, C-07, C-08; D29, D17; ADR-017 `## Deferred to the Specs`; T80

### R2 — Both lists empty deletes the `links` annotation; an absent annotation reads as two empty lists

WHEN both lists are empty THE SYSTEM SHALL delete the `links` annotation, the way an empty
`references` list deletes its annotation today. An absent annotation reads as two empty lists.

Source: FR-51, FR-54, C-01, C-07, C-08; D29

### R3 — `sources`, `relationships`, `source_artifacts` and `references` are never written to object or vector metadata, and the legacy `references` annotation and `source_artifacts` key are never read

THE SYSTEM SHALL never write `sources`, `relationships`, `source_artifacts` or `references` to S3
object metadata or vector metadata. It SHALL never read the legacy `references` annotation or
`source_artifacts` metadata key: T90 migrates them (D42), and no dual-store read is kept.
`source_artifacts` stays in `NON_FILTERABLE_METADATA_KEYS`, declared and unwritten, so the index
needs no re-creation (C-01).

**Metadata budgets.** Removing `source_artifacts` from S3 object metadata frees its key plus its
comma-joined value. Today those keys share the 2 KB object budget with every other field, so a
synthesis citing a few dozen full keys is rejected before any write. After this task its sources
are bounded only by the 1 MiB annotation, which covers FR-19's ceiling of 100. In vector metadata
`source_artifacts` was a declared non-filterable key, so it counted against the 40 KB total and
never against the 2 KB filterable budget. Removing it therefore changes neither the filterable
budget nor the `commit_refs` cap calibration that T81 re-runs.

Source: FR-51, FR-54, C-01, C-07, C-08; D29; D42; FR-19; T81, T90

### R4 — `commit_refs` keeps its own comma-joined annotation and its 20-entry vector copy

`commit_refs` SHALL keep its own comma-joined annotation, and its 20-entry vector copy,
unchanged (C-07).

Source: FR-51, FR-54, C-01, C-07, C-08; D29

## 3. Rules — Entry validation

### R5 — A `sources` entry that is not an object, or lacks a non-empty string `resource`, is refused with `validation_error` naming the entry

At every write path, before any storage call, failure-log append or embedding: WHEN a `sources`
entry is not an object, or its `resource` is missing or not a non-empty string, THE SYSTEM SHALL
return `validation_error` naming the entry, for example `sources[2].resource`. `id` and `title`,
when present, SHALL be non-empty strings with no control characters.

Source: FR-51; OKF §4.1, §5.1

### R6 — An `arkeology://artifact/` remainder must be a clean Arkeology target; any other `resource` is stored as it is and never interpreted

At every write path, before any storage call, failure-log append or embedding: WHEN `resource`
starts with `arkeology://artifact/` THE SYSTEM SHALL treat the remainder as an Arkeology target,
and SHALL reject it unless it is non-empty and contains no `#`, `?`, whitespace or control
character. A remainder with no `/` SHALL also pass T87's id rule (D33). Any other `resource` (a
URL, an unresolved path, or an OKF scope descriptor) is stored as it is and never interpreted.

Source: FR-51; OKF §4.1, §5.1; D33; T87

### R7 — A present `last_modified` must be an offset-aware ISO 8601 timestamp, and is stored as supplied

At every write path, before any storage call, failure-log append or embedding: WHEN
`last_modified` is present THE SYSTEM SHALL require a string that T79's parser reads as an
offset-aware ISO 8601 timestamp, and SHALL otherwise return `validation_error` naming the entry.
The accepted string is stored as supplied, not normalised (D19). The write rejects a bad
`last_modified` rather than storing it.

**Why:** This matches T79, which rejects offset-naive `at` because accepting it "stores exactly
what the reader must refuse". The writer gets the error while it can still fix the input. D50 case
4 stays as the reader's defence for values that arrived another way. The alternative was to store
any string and let T86 mark it unchecked, which is closer to OKF §11's soft-guidance clause. It was
rejected because the reader-side rule already covers that case, and this spec does not need to
rely on it.

Source: FR-51; OKF §4.1, §5.1; D19; D50 case 4; T79

### R8 — A `relationships` entry needs non-empty string `to` and `type`; `to` is an id or a full key, and `type` is stored as given

At every write path, before any storage call, failure-log append or embedding: WHEN a
`relationships` entry is not an object, or `to` or `type` is missing or not a non-empty string,
THE SYSTEM SHALL return `validation_error`. `to` SHALL either pass T87's id rule or contain a `/`
(a full key), and it SHALL contain no `://`, `#`, `?`, whitespace or control character. `type` is
stored as given and is case-sensitive (`supersedes`, `builds_on`, `amends`, or any other value).

Source: FR-51; OKF §4.1, §5.1; T87

### R9 — An entry carrying a `withheld` key is refused with `validation_error`

At every write path, before any storage call, failure-log append or embedding: WHEN any entry in
either list carries a `withheld` key THE SYSTEM SHALL return `validation_error`. That key is
reserved for T85's redaction marker.

**Why:** `withheld` is rejected so that no stored entry can look like T85's marker.

Source: FR-51; OKF §4.1, §5.1; T85

### R10 — Every other key on an entry is stored as supplied, unvalidated, and Arkeology adds no per-edge `generated` or `verified`

THE SYSTEM SHALL store every other key on an entry as supplied, without validating it: `author`,
`usage_count` and `usage_window` on sources (OKF §5.1), and `generated`, `verified` or unknown
keys on relationships (OKF §4.1; OKF GitHub issue #16). Arkeology adds no per-edge `generated` or
`verified`, because no Phase 15 path mints an edge (ADR-017 `### 4`).

**Why:** OKF §4.1 says consumers "SHOULD preserve unknown keys when round-tripping and MUST NOT
reject documents with unrecognized fields", and §5.1 defines `author`, `usage_count` and
`usage_window`. Storing them unvalidated is also the smallest code.

Source: FR-51; OKF §4.1, §5.1; OKF GitHub issue #16; ADR-017 `### 4`

### R11 — An encoded payload over the 1,048,576-byte annotation limit is refused with `validation_error` before anything is written; no other cap applies

At every write path, before any storage call, failure-log append or embedding: WHEN the encoded
payload would exceed the annotation limit (1,048,576 bytes, T80's `ANNOTATION_PAYLOAD_MAX_BYTES`)
THE SYSTEM SHALL return `validation_error` before writing anything. No other count or length cap
applies.

Source: FR-51; OKF §4.1, §5.1; T80

## 4. Rules — Arkeology targets

### R12 — One resolver in `_scope.py` turns a link target into a full key, resolving a bare id against the carrying artifact's scope

THE SYSTEM SHALL resolve a link target to a full key in one function in `_scope.py`. The target is
a source's `arkeology://artifact/` remainder or a relationship's `to`. `{id}` in
`arkeology://artifact/{id}` may be a bare id or a full key; a bare id is relative to the carrying
artifact. The function is given the key of the artifact that carries the link:

- a target containing `/` is already a full key and is returned unchanged;
- a bare id resolves to `{scope of the carrying artifact}/{id}.md`, where the scope is the
  carrying key up to its last `/`;
- any other `resource` resolves to nothing, because it does not point into Arkeology.

Bare ids assume `.md`, the default extension migration uses. Any other extension must be cited by
full key. A bare id resolves against the carrying artifact's scope, not the reader's: a foreign
artifact's bare `secret-a` must resolve to `P/secret-a.md` in its own scope P.

**Why:** The ADR assumes a bare id (`## Deferred to the Specs`). AC-58 has migration write
`arkeology://artifact/{id}` with the id the target file declares, and the producer writes bare ids
in `relationships[].to` (D28). Every tool, though, returns `artifact_id` as the full key, and a
synthesis can cite a foreign shared artifact. A bare id cannot name another scope, so both forms
are needed. Ids cannot contain `/` (D33) and full keys always do, which keeps the two forms apart.
Resolving a foreign artifact's bare id against the reader's prefix would make the target look like
the reader's own and slip past the gate. That is why the resolver sits in `_scope.py`, inside the
mutation scope. Storing the targets as written keeps `relationships` byte-identical to what the
producer wrote (ADR-017 `### 4`).

Source: D28, D38; ADR-017 `## Deferred to the Specs`, "How a bare id resolves"; AC-58; D33; ADR-017 `### 4`

### R13 — Every consumer resolves link targets through this one function, never inline

Every consumer SHALL use this function: the baseline fill below, the reverse lookup, purge,
freshness, the relationships filter, and later T85 and T86. None SHALL resolve a target inline.

Source: D28, D38; ADR-017 `## Deferred to the Specs`, "How a bare id resolves"

## 5. Rules — Create, update and bulk

### R14 — Create, update and the bulk descriptors take `sources` and `relationships` in place of `source_artifacts` and `references`

`create_artifact` and `update_artifact` SHALL take `sources` and `relationships` in place of
`source_artifacts` and `references`. `create_artifacts` and `update_artifacts` descriptors carry
the same keys, and `migrate_artifacts` inherits them through delegation.

Source: FR-01, FR-51, FR-55, FR-75, FR-76, C-07; D51

### R15 — A create or update sets each field to exactly the supplied list; an omitted field clears it, and an unreadable stored payload does not block an update

WHEN an artifact is created or updated THE SYSTEM SHALL set each field to exactly the supplied
list, after the baseline fill and with no deduplication. An omitted field clears it. The update
never reads the stored `links` forward, so an unreadable stored payload does not block an update:
the update replaces it.

**Example**

- Given a tier-3 artifact with `commit_refs` C, sources S and relationships R, when
  `update_artifact` supplies `commit_refs` C2, sources S2 and no relationships, then it stores
  C ∪ C2, exactly S2, and `relationships: []`. `generated` and the revision history are carried
  forward (AC-60; FR-55, C-07).

Source: FR-01, FR-51, FR-55, FR-75, FR-76, C-07; D51; AC-60

### R16 — `links` is written in the same post-PUT annotation step as `commit_refs` and `revision_history`, and every re-PUT restores it

THE SYSTEM SHALL write `links` in the same post-PUT annotation step as `commit_refs` and
`revision_history` (T78, T80). Every re-PUT restores it under the same compare-and-swap cycle.

Source: FR-01, FR-51, FR-55, FR-75, FR-76, C-07; D51; T78, T80

### R17 — A successful create or update returns `sources` and `relationships` as stored; bulk result entries are unchanged

WHEN a create or update succeeds THE SYSTEM SHALL return `sources` and `relationships` as stored
(FR-51). Bulk result entries are unchanged.

**Example**

- Given `create_artifact` with one source `arkeology://artifact/<id of A>` and one relationship
  `{to: <id of A>, type: builds_on}`, when it succeeds, then the response carries both, and
  `read_artifact` and `list_artifacts` return them unchanged. Given neither, all three return
  `sources: []` and `relationships: []` without error (AC-56).

Source: FR-01, FR-51, FR-55, FR-75, FR-76, C-07; D51; AC-56

## 6. Rules — Baseline fill

### R18 — A written `sources` entry that resolves to an Arkeology key and has no `last_modified` gets the readable target's stored `revised.at`, or its `generated.at`

WHEN a written `sources` entry resolves to an Arkeology key and has no `last_modified` THE SYSTEM
SHALL look the target up in the vector index. This is one batched lookup per call, through the
chunked `$in` helper, and none when no entry needs it. Only a target the writer may read is used:
own scope by prefix, or foreign tier 3 `shared`, through the existing gate functions. The entry
then gets the target's stored `revised.at`, or its `generated.at` when it was never revised,
copied verbatim. When sections disagree, the newest write wins, as freshness already decides.

**Example**

- Given a readable artifact A whose `revised.at` is T, when a write supplies
  `{resource: arkeology://artifact/<A>}` with no `last_modified`, then the stored entry carries
  `last_modified: T`. A never revised gives its `generated.at`. A URL source, or one pointing at
  an artifact that does not exist or that the writer cannot read, is stored without it (FR-51;
  D40).

Source: FR-51, FR-58; D19, D40

### R19 — A target with no vectors, that is not readable, or with unreadable provenance leaves `last_modified` absent and reports nothing

WHEN the target has no vectors, is not readable, or has unreadable provenance THE SYSTEM SHALL
leave `last_modified` absent and report nothing. A different outcome for each case would reveal
whether a foreign artifact exists.

Source: FR-51, FR-58; D19, D40

### R20 — The fill runs once per call before any write, retries reuse it, and it applies to create, update, both bulk tools, migration and entries `add_artifact_links` adds

The fill runs once per call before any write, and retries reuse it (T79's resolve-once rule). It
applies to create, update, both bulk tools, migration, and to entries that `add_artifact_links`
adds. It changes only the structured field, never the stored content.

Source: FR-51, FR-58; D19, D40; T79

## 7. Rules — `add_artifact_links`

### R21 — `link_metadata` becomes `add_artifact_links(artifact_ids, commit_refs, sources, relationships)`, needing at least one non-empty list; its return shape, skips, error codes and partial-progress keys stay as today

`link_metadata` SHALL become `add_artifact_links(artifact_ids, commit_refs, sources,
relationships)`. At least one of the three lists must be non-empty. Its return shape, own-scope
skip, no-vector skip, error codes and partial-progress keys stay as they are today.

The module and contract keep their names: the tool is renamed in `server.py` and in the public
function, while `tools/link_metadata.py` and the contract id `arkeology.tools.link_metadata` stay.
T91 updates AGENTS.md's Repository Structure row.

**Example**

- Given an artifact, when `add_artifact_links` adds a commit reference, a source and a
  relationship, then all three are in the artifact's annotations. No Bedrock call is made, and
  `last_edited_ulid`, `revised` and the revision history are unchanged. `commit_refs` also reaches
  vector metadata; sources and relationships do not. A later `reconcile_index` rebuild restores
  the `commit_refs` vector copy from the annotation. Re-running the call adds nothing (AC-59;
  FR-53).

**Why:** Following T78, which kept `write.py` for `create_artifact`, the module and the contract
keep their names. Renaming them would break the frozen contract id for no change in behaviour.

Source: FR-53, C-06; D46; `### 10`, D50 case 1; AC-59; T78, T91

### R22 — Each supplied field is merged into the stored value by key, existing entries first; nothing stored is changed or removed

WHEN supplied THE SYSTEM SHALL merge each field into the value read from its annotation, existing
entries first, keeping the first entry seen for each key. The keys are: a `commit_refs` value; a
source's `resource`; a relationship's (`to`, `type`) pair. Existing entries are never changed or
removed. A field the call does not supply is written back as it was read (FR-53).

Source: FR-53, C-06; D46; `### 10`, D50 case 1

### R23 — An unreadable stored `links` or `commit_refs` payload fails that artifact with `corrupt_metadata` and writes nothing

WHEN the stored `links` or `commit_refs` payload is unreadable THE SYSTEM SHALL fail that artifact
with `corrupt_metadata` and write nothing (D50, case 1).

Source: FR-53, C-06; D46; `### 10`, D50 case 1

### R24 — `add_artifact_links` keeps its own object-ETag compare-and-swap cycle over both annotations, and rewrites vector metadata only when `commit_refs` is supplied

THE SYSTEM SHALL keep today's object-ETag compare-and-swap cycle, which reads and writes both
annotations under one ETag. It SHALL rewrite vector metadata only when `commit_refs` was supplied.
A failure-log entry from a failed vector write carries `commit_refs` only.

**Why:** ADR-017 `### 8` says it builds on T80's shared append helper. That helper, as T80
specifies it, appends one `{by, at}` entry to one log annotation. A links merge is a keyed set
merge across two annotations (`commit_refs` and `links`) under one ETag, which is the cycle
`link_metadata` already runs. Widening T80's helper to take a merge callback would change T80's
contract for one caller. Both cycles share `CAS_MAX_ATTEMPTS` and the object-ETag `if_match`, and
the residuals are the same.

**Open Questions item 1 — Resolved 2026-10-13 — C-06 now accepts it.** C-06 was amended to accept
two annotation-only writes to the *same annotation* racing, which covers a source-only and a
relationship-only add on the shared `links` annotation. *Original question:* C-06 accepts that two
`add_artifact_links` calls changing the *same* field of one artifact at the same instant can lose
one addition, which implies that calls changing different fields cannot. D29 puts `sources` and
`relationships` in one annotation. S3 offers no annotation-level precondition (verified
2026-09-06), so a call that only adds a source and a concurrent call that only adds a relationship
can now lose one another's additions. Neither one is detected. No mechanism inside D29 closes
this. *Recommended:* fold it into the PM pass that T80's blocking Open Question 1 already asks
for, and amend C-06 through `writing-requirements` to say "the same link annotation (sources and
relationships share one)". This spec does not change either way.

Source: FR-53, C-06; D46; `### 10`, D50 case 1; ADR-017 `### 8`; T80; D29

## 8. Rules — Re-PUT carry-forward and repair

### R25 — Archive and T82's lifecycle change carry `links` across the re-PUT by the `references` rule, and refuse an unreadable `links` with `corrupt_metadata`

`archive_artifact`, and T82's lifecycle change on the same path, SHALL read `links`, carry it
across compare-and-swap attempts by the rule `references` follows today, and restore it after the
re-PUT. That rule accumulates while `last_edited_ulid` is unchanged and resets to the fresh read
when it moves. WHEN `links` is unreadable they SHALL return `corrupt_metadata` and write nothing
(D50, case 1).

Source: FR-17, FR-54, AC-68; D50; T82

### R26 — A failure-log entry carries `links` in place of `references`, and `reconcile_index` restores it under the `references` token rule, ignoring a legacy `references` key

A failure-log entry written after an object PUT SHALL carry the `links` value being written as one
optional `links` object in the annotation's shape, replacing `references`. `reconcile_index` SHALL
restore it under today's `references` token rule: tokened entries count only while their
`last_edited_ulid` equals the artifact's current one, tokenless entries always count, and both
merge with the current annotation by the merge keys (a `commit_refs` value; a source's `resource`;
a relationship's (`to`, `type`) pair). An entry's legacy `references` key is ignored.

**Example**

- Given a write that failed after its object PUT and left a failure-log entry carrying links L1,
  when a later successful update sets links L2 and `reconcile_index` then replays the entry, then
  the artifact keeps L2. The entry's `commit_refs` is still restored by union (AC-68).

Source: FR-17, FR-54, AC-68; D50

### R27 — The reconcile rebuild reads only `commit_refs` and never reads or writes `source_artifacts`

The reconcile rebuild SHALL read only `commit_refs`. It no longer reads or writes
`source_artifacts`.

Source: FR-17, FR-54, AC-68; D50

## 9. Rules — Reading

### R28 — Read and list return `commit_refs`, `sources` and `relationships` from their annotations after the gate; search and synthesis return neither `sources` nor `relationships`; list has no parameter for either

`read_artifact` and `list_artifacts` SHALL return `commit_refs`, `sources` and `relationships`,
read from their annotations after the cross-scope gate. They no longer return `references` or
`source_artifacts`. `search_artifacts` and `synthesise_artifacts` drop `source_artifacts` and
return neither field (ADR-017 `### 7`).

`list_artifacts` has no parameter for either field, and the `commit_refs` filter still applies AND
semantics (AC-57).

Source: FR-51, FR-10, AC-56, AC-57; malformed-data ADR D2–D6; ADR-017 `### 7`

### R29 — A malformed `links` payload makes `read_artifact` return `corrupt_metadata` without echoing it, and makes `list_artifacts` skip and count the artifact

WHEN the `links` payload is not a JSON object with exactly the two list keys, or an entry lacks its
required string keys, the read is unreadable. `read_artifact` SHALL then return `corrupt_metadata`
naming `links`, never echoing the payload. `list_artifacts` SHALL skip the artifact and count it
under `skipped_malformed_count`. Decoding checks shape and types only. It never parses
`last_modified`, so one bad timestamp marks only its own source (D50, case 4).

Source: FR-51, FR-10, AC-56, AC-57; malformed-data ADR D2–D6; D50, case 4

### R30 — For a foreign-scope reader, `relationships` keep today's `references` filter retargeted to resolved targets; `sources` are returned unfiltered

For a foreign-scope reader, `relationships` SHALL keep today's `references` filter, retargeted:
each `to` is resolved and an entry whose target the reader cannot read is dropped. `sources` are
returned unfiltered, as `source_artifacts` is today. T85 replaces both with redaction.

Source: FR-51, FR-10, AC-56, AC-57; malformed-data ADR D2–D6; T85

### R31 — Callers that need only `commit_refs` read only that annotation

Callers that need only `commit_refs` (`reconcile_index`, `propose_commit_links`) SHALL read only
that annotation, so a corrupt `links` payload never breaks them.

Source: FR-51, FR-10, AC-56, AC-57; malformed-data ADR D2–D6

## 10. Rules — Reverse lookup, purge, freshness

### R32 — `find_referrers` prefilters own-scope, non-archived `Synthesis` artifacts and reads each one's `links` once; a failed read fails the call

`find_referrers` SHALL run one vector query for own-scope, non-archived artifacts whose `type` is
exactly `Synthesis` (T76, T77), metadata only. It then reads each distinct synthesis's `links`
once, with at most 5 reads at a time, and returns the syntheses with a source that resolves to the
target's key. `REFERENCE_FIELDS` is deleted.

Per synthesis read outcome:

- absent annotation: no sources;
- `ObjectNotFoundError`: the synthesis is gone and is skipped;
- unreadable payload: the synthesis is listed as not checked, by own-scope id;
- any other failure (credential, `annotation_unavailable`, bare `KeyError`, transient):
  `find_referrers` SHALL raise. `delete_artifact` and `archive_artifact` then return the
  structured error and change nothing.

The warning never blocks because of what it finds. A failed read is a failed call, never "no
referrers" (ADR-017 `### 4`, on the annotations contract's raise-never-degrade rule).

**Example**

- Given an own-scope synthesis whose `links` payload cannot be decoded, then the operation still
  completes, and that synthesis is listed as not checked (D50, case 2).

Source: FR-20, FR-21, FR-22, FR-56; D13, D20, D29; D50 case 2; T76, T77; ADR-017 `### 4`

### R33 — Delete and archive add `unchecked_referrers` when non-empty, and every response that ran the check carries `referrer_check_scope`

On success, `delete_artifact` and `archive_artifact` SHALL add `unchecked_referrers` when that list
is non-empty. Every response that ran the check SHALL carry `referrer_check_scope`, a fixed
sentence: only own-scope, non-archived syntheses that list the artifact as a source were checked;
relationships and non-synthesis sources were not (FR-56).

**Example**

- Given an own-scope, non-archived `Synthesis` whose sources cite A, when A is deleted or archived,
  then the operation completes and returns A's referrers with a warning, stronger for delete than
  for archive. An artifact that cites A only through a relationship, or a non-synthesis artifact
  that lists A as a source, produces no warning, and every such response states that gap. No
  foreign-scope identifier ever appears (AC-61; FR-21, FR-56).

Source: FR-20, FR-21, FR-22, FR-56; D13, D20, D29; D50 case 2; AC-61

### R34 — The `purge_archived` cascade reads each candidate synthesis's `links`, and cascades only a synthesis with at least one Arkeology source and every one in the purge set

The `purge_archived` cascade SHALL read each candidate synthesis's `links`. A synthesis cascades
only when it has at least one Arkeology source and every one is in the purge set (FR-22). An
unreadable payload means no cascade, counted under `skipped_malformed_count`. A gone synthesis is
skipped. Any other failure fails the call before anything is deleted.

**Why:** Freshness and purge change here, not in T86. Deleting the projection would make every
synthesis look like it has no sources, and purge would cascade none. Both must read `links` in the
same task.

Source: FR-20, FR-21, FR-22, FR-56; D13, D20, D29; D50 case 2

### R35 — `check_synthesis_freshness` reads each synthesis's source list from `links`; "malformed" means no `sources` entries

`check_synthesis_freshness` SHALL read each synthesis's source list from `links`. "Malformed" now
means no `sources` entries. An unreadable payload is counted under `skipped_malformed_count` and is
never a deletion candidate. A gone synthesis is counted under a new conditional
`skipped_deleted_count`, which does not affect `all_fresh`. Only sources that resolve to an
Arkeology key are compared. The comparison itself stays as T79 leaves it until T86.

**Why:** Freshness and purge change here, not in T86. Deleting the projection would make every
synthesis look like it has no sources. Freshness would then call every synthesis malformed, and
with `confirm=True` it would delete them all. Both must read `links` in the same task. T86 still
owns the per-source comparison. `skipped_deleted_count` is the name the malformed-data ADR revision
leaves to "the spec", and it follows `list_artifacts`' precedent.

Source: FR-20, FR-21, FR-22, FR-56; D13, D20, D29; D50 case 2; T79, T86

## 11. Rules — Removed names

### R36 — `link_metadata`, `source_artifacts` and `references` are rejected with `validation_error` naming the replacement, never aliased

T84 SHALL add rows to T78's removed-name table in `server.py`:

| Tool | Name | Replacement named |
|---|---|---|
| `link_metadata` (tool) | — | `add_artifact_links` |
| `create_artifact`, `update_artifact`, `add_artifact_links` | `source_artifacts` | `sources` |
| `create_artifact`, `update_artifact`, `add_artifact_links` | `references` | `relationships` |

WHEN a `create_artifacts` or `update_artifacts` descriptor carries `source_artifacts` or
`references` THE SYSTEM SHALL fail that entry with the same `validation_error`.
`migrate_artifacts` inherits this through delegation.

**Example**

- Given a caller using `link_metadata`, a `references` argument, or a `source_artifacts` argument
  or descriptor key, when it calls the server, then it gets `validation_error` naming
  `add_artifact_links`, `relationships` or `sources` (AC-80; D42).

Source: AC-80; D42, D46; T78

## 12. Boundaries

**Always:**
- Read a link annotation in full before any write that carries it or merges into it. Raise on
  every failed read. Only `NoSuchAnnotation` is empty (`s3-annotations.artifact`
  `## Not-Found Semantics`).
- Resolve every link target through the `_scope.py` resolver, and gate every lookup that returns
  a target's metadata to the writer or reader.
- Keep `startswith(scope + "/")` for every scope test, and the public / `_inner` pattern with
  `try/except Exception`. Log to stderr only.
- After changing `annotations.py`, `_scope.py` or `_reference_filter.py`, all of which are in
  `only_mutate`, run mutmut alone and triage the survivors as AGENTS.md describes.

**Ask First:**
- Returning `sources` or `relationships` from search, synthesis or bulk results.
- Any mechanism that narrows the residual in Open Question 1.
- Deduplicating on create or update, or adding a count or length cap per entry.

**Never:**
- Keep `source_artifacts`, `references` or `link_metadata` as aliases, or read the legacy
  `references` annotation or `source_artifacts` key as a fallback (D42).
- Copy `sources` or `relationships` into vector or object metadata, or add a filter on them
  (AC-57; D29).
- Mint per-edge `generated`/`verified`, or normalise `type`, `to` or `resource`.
- Redact, add the `withheld` marker, gate `sources`, or rewrite returned frontmatter (T85). Change
  the freshness comparison (T86). Touch `references.py`, the `migrating-to-arkeology` or
  `backfilling-references` skills (T88), the schema resource beyond renaming fields (T89), or
  README, SERVER-REFERENCE, CHANGELOG, AGENTS.md and agent snippets (T91). Until T88 lands, both
  skills get `validation_error` naming the replacement, and never write wrong data.

## 13. For the developer agent

### Files to Touch

T84 lands after T79 and T80, and edits the code as T76–T81 and T87 leave it.

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/annotations.py` | Modify | `LINKS_ANNOTATION = "links"`. Add a strict structural decode raising T80's `CorruptAnnotationError`, plus the encoder and size check (reuse T80's), a keyed merge, and split readers: one for `commit_refs`, one for links. `apply_link_annotations` writes `commit_refs` and `links`. Retire `REFERENCES_ANNOTATION`. Update the docstring |
| `src/arkeology/tools/_scope.py` | Modify | Add the link-target resolver |
| `src/arkeology/artifact.py` | Modify | `Artifact.sources` / `relationships` replace `source_artifacts` / `references`. Add entry validation using T79's parser and T87's id rule. Drop both no-comma validators and `REFERENCE_FIELDS`. `NON_FILTERABLE_METADATA_KEYS` keeps `source_artifacts`, with a C-01 comment |
| `src/arkeology/tools/_reference_filter.py` | Modify | Retarget the candidate loop to resolved `relationships[].to`. Add the gated metadata lookup for the baseline fill, sharing the batched fetch and the gate check rather than duplicating them |
| `src/arkeology/failure_log.py` | Modify | `build_failure_entry`: `links` replaces `references` |
| `src/arkeology/tools/write.py` | Modify | Create and update take the new fields, fill baselines once, check size before the PUT, write `links` post-PUT, return both fields, and record `links` in failure entries |
| `src/arkeology/tools/write_artifacts.py` | Modify | Descriptor keys. Reject the removed keys per entry |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Forward `sources`/`relationships` only. *Uncertain:* confirm nothing else threads `references` |
| `src/arkeology/tools/link_metadata.py` | Modify | Public `add_artifact_links`. Three fields, keyed merge, fill, corrupt handling, vector write only for `commit_refs` |
| `src/arkeology/tools/archive.py` | Modify | Carry `links` under the `references` rule. Add `corrupt_metadata`, `unchecked_referrers` and `referrer_check_scope` |
| `src/arkeology/tools/delete.py` | Modify | Add `unchecked_referrers` and `referrer_check_scope`. Update the docstring gap text |
| `src/arkeology/tools/_search_helper.py` | Modify | Rewrite `find_referrers`. `build_artifact_summary` loses `source_artifacts` |
| `src/arkeology/tools/read.py`, `list.py` | Modify | Return the three fields, retarget the filter, add the corrupt handling |
| `src/arkeology/tools/search.py`, `synthesise.py` | Modify | Drop `source_artifacts` |
| `src/arkeology/tools/purge.py`, `freshness.py` | Modify | Read the source list from `links` as specified |
| `src/arkeology/tools/reconcile.py` | Modify | Restore `links` by the token rule. Read only `commit_refs` in the rebuild. Drop `source_artifacts` |
| `src/arkeology/tools/propose_commit_links.py` | Modify | Use the `commit_refs`-only reader |
| `src/arkeology/server.py` | Modify | Register `add_artifact_links`, remove `link_metadata`, rename the create/update parameters and docstrings, add the removed-name rows |
| `src/arkeology/resources.py` | Modify | Rename the field rows, the `link_metadata` guidance and the synthesis write-back guidance to `sources=[{resource: "arkeology://artifact/<artifact_id>", last_modified: <revised.at or generated.at>}]`. The full rewrite belongs to T89 |
| `src/arkeology/errors.py`, `clients/vectors.py` | Modify | Wording only |
| Tests | Modify | See Testing Approach |

### Contracts

Make these before the tests, on top of the T76–T81 and T87 amendments:

- **`data/s3-annotations.artifact.md`**
  - `## Storage Shape`: a `links` row (JSON object, two lists, entry shapes, both-empty deletes,
    1 MiB) replaces `references`.
  - Symbols: the links decode, encode, merge and readers. The commit_refs-only reader.
    `apply_link_annotations` gains `sources`/`relationships`. The comma-free precondition now
    covers `commit_refs` only.
  - `## Compatibility Guarantees`: the "references never in vector metadata" rule now names both
    fields. The re-PUT carry-forward and failure-log bullets name `links`. The CAS boundary states
    that sources-only and relationships-only writers race on one annotation (Open Question 1).
- **`data/s3.artifact.md`**: delete the `source_artifacts` object-metadata row. The failure-log
  entry shape gets `links` in place of `references`.
- **`data/s3vectors.artifact.md`**: `source_artifacts` is declared and never written (C-01).
- **`modules/arkeology.tools.link_metadata.md`**: `### add_artifact_links` replaces
  `### link_metadata`. Merge keys, baseline fill, `corrupt_metadata`, vector write only for
  `commit_refs`, failure entry `commit_refs` only.
- **`modules/arkeology.tools.write.md`**, **`.write_artifacts.md`**, **`.migrate_artifacts.md`**:
  the new parameters and descriptor keys, validation, fill, size limit, response fields, update
  replace semantics, and the removed-key rejection.
- **`modules/arkeology.tools.read.md`**, **`.list.md`**: fields, `corrupt_metadata` and skip,
  the retargeted relationships filter, sources unfiltered until T85, no filter on either field.
- **`modules/arkeology.tools.delete.md`**, **`.archive.md`**: the referrer check is rewritten
  (synthesis-only via `links`, unchecked list, gap sentence, failed read fails the call). Archive
  also carries `links` and adds `corrupt_metadata`.
- **`modules/arkeology.tools.purge.md`**, **`.freshness.md`**: the source list comes from
  `links`. Purge gets `skipped_malformed_count`. Freshness gets the new "malformed" meaning and
  `skipped_deleted_count`.
- **`modules/arkeology.tools.reconcile.md`**: `references` becomes `links` in every restore
  rule, and the legacy key is ignored. The rebuild never reads or writes `source_artifacts`.
- **`modules/arkeology.tools.search.md`**, **`.synthesise.md`**, **`.propose_commit_links.md`**:
  `source_artifacts` is dropped, and the reader is renamed.

### Testing Approach

**TDD order** (each test file is confirmed red before the implementation file it gates):

1. `tests/unit/test_annotations.py` → `annotations.py`. A round trip with non-ASCII and unknown
   keys. Both-empty deletes. Absent gives `([], [])`. Each malformed shape raises
   `CorruptAnnotationError`: not JSON, not an object, an extra top-level key, a list that is not a
   list, an entry missing `resource`/`to`/`type`. A bad `last_modified` string decodes. Over 1 MiB
   raises before the put (spy). The keyed merge keeps the first entry seen. `ObjectNotFoundError`
   and bare `KeyError` propagate.
2. `tests/unit/test_tools__scope.py` → `_scope.py`. Bare id against `a/b/x.md` gives `a/b/id.md`.
   A full key is unchanged. A URL or a path gives nothing. A foreign carrier never resolves into
   the reader's prefix.
3. `tests/unit/test_artifact.py` → `artifact.py`. Each validation rule, including `withheld`,
   `://` in `to`, a naive `last_modified`, a bare remainder outside D33, and unknown keys kept.
4. `tests/unit/test_failure_log.py` → `failure_log.py`. `links` is carried and omitted when empty.
5. `tests/unit/test_tools_write.py` → `write.py`.
   - **AC-56** create and read.
   - **AC-60** update.
   - Baseline fill: own `revised`, `generated` fallback, foreign tier-2 not filled, URL not
     filled, one vector call (spy), same value on a CAS retry.
   - Over the limit writes nothing.
   - A corrupt stored `links` does not block an update.
   - The failure entry carries `links`.
6. `tests/unit/test_tools_write_artifacts.py`, `test_tools_migrate_artifacts.py` →
   `write_artifacts.py`, `migrate_artifacts.py`. Descriptor round trip, and the removed keys fail
   only their own entry.
7. `tests/unit/test_tools_link_metadata.py` → `link_metadata.py`.
   - **AC-59**: Bedrock spy not called, ulid, `revised` and history unchanged, `commit_refs` in
     vectors, links absent from vectors, reconcile restores the vector copy, re-run idempotent.
   - A links-only call makes no `put_vectors_batch` (spy).
   - Fill on added entries only.
   - Corrupt `links` gives `corrupt_metadata` and no put.
   - Foreign ids are skipped.
8. `tests/unit/test_tools__reference_filter.py`, `test_tools_read.py`, `test_tools_list.py` →
   `_reference_filter.py`, `read.py`, `list.py`.
   - **AC-56** and **AC-57**, including `list_artifacts`' schema with no `sources`/`relationships`
     parameter.
   - A foreign reader loses an unreadable bare-id relationship.
   - Corrupt → `corrupt_metadata` without the payload, or skip and count.
   - **AC-70** (T81 hand-off): B carries `relationships: [{to: A, type: supersedes}]`, and A is
     still listed by default.
9. `tests/unit/test_tools__search_helper.py`, `test_tools_delete.py`, `test_tools_archive.py` →
   `_search_helper.py`, `delete.py`, `archive.py`.
   - **AC-61**: warning on delete and archive, stronger on delete. Relationship-only and
     non-synthesis citers give no warning. `referrer_check_scope` is always present. No foreign id.
   - A corrupt synthesis payload gives `unchecked_referrers`, and the operation completes.
   - A read raising `CredentialError` gives an error and nothing deleted or archived.
   - Archive carries `links` byte-for-byte equal in value. A corrupt `links` writes nothing.
10. `tests/unit/test_tools_purge.py`, `test_tools_freshness.py` → `purge.py`, `freshness.py`.
    - Cascade by `links`, and URL-only syntheses never cascade.
    - Unreadable → `skipped_malformed_count`.
    - Freshness: no-sources is malformed, unreadable is skipped and never deleted with
      `confirm=True`, gone is `skipped_deleted_count`.
11. `tests/unit/test_tools_reconcile.py` → `reconcile.py`.
    - **AC-68**.
    - The tokenless entry unions.
    - A legacy `references` entry is ignored.
    - The rebuild writes no `source_artifacts` and makes no links read (spy).
12. `tests/unit/test_tools_search.py`, `test_tools_synthesise.py`,
    `test_tools_propose_commit_links.py` → their modules. No `source_artifacts`. A corrupt `links`
    does not affect `propose_commit_links`.
13. `tests/unit/test_server.py`, `test_resources.py` → `server.py`, `resources.py`.
    - **AC-80** through a real `fastmcp.Client(_app)` for each row.
    - `add_artifact_links` is registered and `link_metadata` is not.
    - The resource text names no removed field.

Not broken, and left alone: `tests/unit/clients/test_s3_annotations.py`, whose `"references"` is
an arbitrary annotation name, and the `test_references_*` and `test_skill_artifact_id_drift.py`
files, which belong to T88.

**Mutation.** All three changed files are in `only_mutate`. After the unit suite is green, run
`uv run mutmut run` alone, clear `__pycache__`, and triage each survivor in the new resolver,
decode and filter code against the equivalence classes.

**Integration tests this change breaks** (update in this task, per plan.md):
- `test_tools_link_metadata.py`: call `add_artifact_links`. `references=` becomes
  `relationships=[{"to": …, "type": "builds_on"}]`, and the assertions read the `links`
  annotation.
- `test_tools_write.py`, `test_tools_propose_commit_links.py`: the `link_metadata` import and
  call are renamed.
- `test_tools_reconcile.py`: the backfill uses `relationships`. Assert that no `source_artifacts`,
  `sources` or `relationships` key is in rebuilt vector metadata.
- `test_tools_freshness.py`, `test_tools_purge.py`, `test_tools_delete.py`: `source_artifacts`
  fixtures become `sources: [{"resource": f"arkeology://artifact/{source_id}"}]`. The empty-source
  malformed cases become "no sources". The delete test also asserts `referrer_check_scope`.
- **Add** to `test_tools_write.py`: a real-AWS **AC-56** round trip with a non-ASCII title and an
  unknown source key, plus the baseline fill against a real `revised.at`.
- Not broken (docstrings only): `test_calibration_per_artifact_vector_lookup.py`,
  `test_calibration_vector_metadata_budget.py` (`source_artifacts` was never filterable), and
  `clients/test_s3_annotations.py`.

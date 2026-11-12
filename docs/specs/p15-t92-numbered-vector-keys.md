---
type: Spec
id: p15-t92-numbered-vector-keys
title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
description: Every vector of an artifact is keyed {artifact_id}#{n}, n = 0..k-1 in the document order of its embedded sections, with a single document vector at #0 when nothing is embeddable; EMBED_MAX_SECTIONS gets a maximum of 100, the GetVectors per-call limit, so one GetVectors over #0..#99 returns exactly the vectors one artifact holds. Delete, purge, the overwriting write's clean-up, the metadata rewrites and reconcile's re-index find an artifact's vectors that way, and multi-artifact metadata lookups read each id's #0. No per-artifact path scans the shared index or enumerates by filtered query, which a calibration on real AWS showed is not exhaustive. Heading-slug keys and their disambiguation are retired; the store migration (T90) re-keys existing vectors.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr-aws-backend
    resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T14:38:17Z
  - id: calibration-results
    resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
  - id: calibration-test
    resource: tests/integration/test_calibration_enhanced_filtered_query.py
    title: Calibration test — filtered, paged QueryVectors on ENHANCED
  - id: aws-s3vectors-limits
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html
    title: Amazon S3 User Guide — S3 Vectors limitations and restrictions
  - id: aws-getvectors
    resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetVectors.html
    title: Amazon S3 API Reference — GetVectors
  - id: requirements
    resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-11-10T17:12:55Z
  - id: vision
    resource: docs/planning-artifacts/vision.md
    title: "Arkeology — Persistent Artifact Memory"
    last_modified: 2026-11-09T09:27:45Z
  - id: spec-t5
    resource: docs/specs/p1-t5-startup-validation-sequence.md
    title: T5 — Startup Validation Sequence
    last_modified: 2026-11-12T13:11:40Z
  - id: spec-t85
    resource: docs/specs/p15-t85-link-gate-withheld.md
    title: "T85 — Cross-Scope Gate on sources and relationships, with the {withheld: n} Marker"
    last_modified: 2026-11-09T22:23:38Z
  - id: spec-t86
    resource: docs/specs/p15-t86-per-source-freshness.md
    title: T86 — Per-Source Freshness
    last_modified: 2026-11-09T22:44:57Z
  - id: spec-t90
    resource: docs/specs/p15-t90-store-migration.md
    title: T90 — Store Migration Skill and Command
    last_modified: 2026-11-12T14:38:17Z
  - id: contract-s3vectors
    resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
    last_modified: 2026-11-12T14:38:17Z
  - id: contract-reconcile
    resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
    last_modified: 2026-11-12T14:38:17Z
relationships:
  - to: adr-2026-05-29-aws-backend-selection
    type: implements
  - to: p15-t78-create-update-split
    type: builds_on
  - to: p15-t82-lifecycle-change
    type: builds_on
  - to: p15-t84-sources-relationships
    type: builds_on
  - to: p15-t85-link-gate-withheld
    type: builds_on
  - to: p15-t86-per-source-freshness
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T13:11:40Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T21:15:39Z
---

# T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key

## TL;DR

Each vector of an artifact is keyed `{artifact_id}#{n}` — its section's position among the
embedded sections — and an artifact never holds more than 100, so one `GetVectors` over `#0..#99`
returns exactly the vectors it holds, whatever the size of the index every team shares. Every path
that works on one artifact's vectors, and every lookup of several artifacts' metadata, then reads
by key: no per-artifact path scans the index or enumerates by filtered query, which real AWS showed
silently drops vectors. Developer agents and operators get single-artifact work whose cost and
correctness do not depend on other teams' areas (NFR-17, AC-88).

## 1. Problem Statement

Delete, purge, an overwriting write's clean-up, archive, the lifecycle change, the link backfill,
reconcile's re-index, the freshness check, the cross-scope link gate and the import candidate check
all need either every vector of one artifact or one artifact's metadata. Today each finds them with
a `ListVectors` scan of the whole shared index, filtered in memory. At the documented target —
dozens of teams of up to low thousands of artifacts each (`vision.md` § Operating Context), about
240,000 vectors — that is at least 240 sequential pages, about a minute, per lookup.

A filtered `QueryVectors` paged to completion on an `ENHANCED` index was measured on real AWS on
2026-11-12 (`.docs/review-fixes/calibration-2026-11-12.md`). It is complete only for artifacts of 10
or fewer vectors. Above that it returned 48–86% of an artifact's vectors — 190 or 213 of 300 for the
large one — with well-formed pages, no error, and no continuation token after the last page, so
nothing tells the caller that vectors are missing. A delete or an update's clean-up built on it
would leave vectors behind silently. An `$in` filter of 100 real artifact ids was also rejected:
AWS's error message limits a filter to 10,240 bytes. The two rejections are consistent with AWS
counting the filter's JSON as sent, which would fit about 93 ids, but that counting is not
confirmed.

Keys, by contrast, can be read exactly. `GetVectors` takes up to 100 keys per call. In the same
calibration it returned every key of a request whose keys all existed, and nothing, with no error,
for a request whose keys had all been deleted. A request mixing present and missing keys — what a
read of `#0..#99` over an artifact of fewer vectors is — was not made, and AWS documents neither
case; this spec's first integration test observes it. Making the key set of an artifact known —
numbered slots under a fixed ceiling — turns every per-artifact lookup into one such read. The
operator ruled on 2026-11-12: "Agree with option B and have it put in place together in phase 15."

The `ENHANCED` index requirement (startup check 5, `p1-t5-startup-validation-sequence` R12) is not
changed by this spec. It stays for scoped-search recall and for the store-shape check 9: under
`CLASSIC`, scoped lookups lost vectors even for small artifacts (16 of 21 with 10 or fewer vectors
were incomplete).

Ten earlier specs state rules this spec replaces, and where they disagree with it, this spec holds:

- `p2-t6-artifact-model` R8 — `section_slug` as the suffix of a vector key: no key takes a heading
  slug (R3).
- `p2-t7-write-artifact` R9 and R15 — heading-slug section keys, the document vector at the bare
  `artifact_id`, and the overwrite clean-up by a `list_vectors_by_metadata` lookup: numbered keys
  (R1) and the clean-up by key (R6).
- `p3-t11-archive-artifact` R5, `p12-t49-link-metadata` R3 — finding the vectors to re-put with
  `list_vectors_by_metadata`: the read by key (R7).
- `p3-t12-delete-artifact` R5, `p3-t13-purge-archived` R6 — finding the vectors to delete with
  `list_vectors_by_metadata`: the read by key, deleting only what it returned (R5).
- `p5-t22-synthesis-freshness-check` R7 and `p12-t61-migration-self-heal` R1 — a source's or a
  candidate's vectors looked up with `list_vectors_by_metadata`: its `#0` read by key (R9).
- `p8-t28-section-caps` R6 — `EMBED_MAX_SECTIONS` valid from 1 with no maximum: at most 100 (R2).
- `p12-t67-orphan-vector-retry-and-selfheal` R6 — the `list_vectors_by_metadata` read that computes
  an overwrite's leftover keys: R6's read of `#k..#99`, whose failure is handled as that rule
  handles a failed read.

Every rule below is P1: the vector key, the by-key read and the paths built on it ship together, or
an artifact written under one scheme is invisible to paths reading the other.

## 2. Rules — The vector key

### R1 — Each vector is keyed `{artifact_id}#{n}`, numbered from 0 in the document order of the embedded sections; an artifact with nothing to embed has one document vector at `#0`

WHEN the system writes an artifact's vectors THE SYSTEM SHALL key each section vector
`{artifact_id}#{n}`, where `n` is the section's position, from 0, among the sections that survive
the shared section pipeline (minimum length, section cap, truncation), in document order; and WHEN
no section survives — no `##` section, or every one filtered out — THE SYSTEM SHALL key the single
document-level vector `{artifact_id}#0`. `n` is written in decimal with no padding and no sign. No
key is ever derived from heading text, and no vector is ever keyed by the bare `artifact_id`.

Every indexed artifact therefore holds `#0`, and every vector of an artifact carries the same
artifact-level metadata (`s3vectors.artifact` § Storage Shape). The numbering carries no meaning
beyond that: nothing reads a section from its key, so an artifact the store migration re-keyed
keeps the migration's numbering until its next update or re-index (T90 R44).

**Example**

- Given content with sections "Summary", "Details" and "Notes", each long enough to embed, when it is
  created, then its vector keys are exactly `{id}#0`, `{id}#1` and `{id}#2`, in that order, and
  `sections_indexed` is 3.
- Given content with no `##` section, when it is created, then its one vector key is `{id}#0`.
- Given two sections both headed "Notes", when the artifact is created, then their keys are `#0` and
  `#1`, and neither vector overwrites the other.

Source: adr-2026-05-29-aws-backend-selection; FR-01; the numbered-key ruling (Operator, 2026-11-12)

### R2 — `EMBED_MAX_SECTIONS` accepts at most 100, checked at startup like its existing range; the default stays 20

WHEN `EMBED_MAX_SECTIONS` is set above 100 THE SYSTEM SHALL refuse to start, through the same
settings validation that already refuses a value below 1, with a message naming the variable and
its maximum. The default stays 20. `arkeology-migrate-store` loads settings exactly as the server
does (T90 R2), so it refuses the same value.

**Why (The ceiling is the `GetVectors` per-call limit):** 100 slots, `#0..#99`, are exactly one
`GetVectors` call, so reading every vector one artifact can hold costs one request.

**Example**

- Given `EMBED_MAX_SECTIONS=101`, when the server starts, then it exits before serving requests and
  the message names `EMBED_MAX_SECTIONS` and 100; with `EMBED_MAX_SECTIONS=100` it starts.

Source: FR-01, FR-07, NFR-03; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html; the numbered-key ruling (Operator, 2026-11-12)

### R3 — Heading-slug keys and their disambiguation are retired

THE SYSTEM SHALL derive no vector key from a section heading: the heading-slug suffix and the
disambiguation of colliding slugs are removed from the write path and from reconcile. Vector
metadata carries no section heading, and the only code that parses a vector key — reconcile's split
of a key on `#` to recover its artifact id — reads the same artifact id from a numbered key and is
unchanged (T87 R9). Nothing that a reader sees changes.

Source: the numbered-key ruling (Operator, 2026-11-12)

## 3. Rules — Every vector of one artifact

### R4 — All of one artifact's vectors are read with one `GetVectors` over `#0..#99`, which returns exactly the keys present

WHEN a path needs every vector of one artifact THE SYSTEM SHALL read them with one `GetVectors`
over the 100 keys `{artifact_id}#0` to `{artifact_id}#99`, asking for each vector's data only when
the path uses it — its metadata always comes back — and SHALL treat the keys it returns as the
artifact's complete vector set. It makes no `ListVectors` call, no `QueryVectors` call and no
embedding call for that purpose.

**Why (Exact, and independent of index size):** a read by key either returns a stored vector or
does not; there is no recall to trust. The range is always the full 100 slots, never the live
`EMBED_MAX_SECTIONS`: an artifact written under a higher setting keeps its vectors above a lowered
one, and a range derived from the setting would miss them. That `GetVectors` returns the keys that
exist and omits the others without failing the call was observed on 2026-11-12 only for requests
whose keys were all present or all missing, and AWS does not document it; the integration test
below observes the mixed request first, before the code that relies on it, so a different behaviour
fails the suite rather than a delete.

**Example**

- Given an artifact holding `#0..#4` in an index of 100,000 other vectors, when its vectors are read,
  then one `GetVectors` call is made with exactly the keys `#0..#99`, it returns exactly `#0..#4`,
  and no `ListVectors` or `QueryVectors` call is made.

Source: adr-2026-05-29-aws-backend-selection; NFR-17; https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetVectors.html; calibration of 2026-11-12

### R5 — Delete, purge and the freshness clean-up delete only the keys that read returned, and make no delete call when it returned none

WHEN `delete_artifact` deletes an artifact's vectors, `purge_archived` deletes each purged or
cascade-deleted artifact's vectors, or `check_synthesis_freshness` with `confirm=True` deletes a
malformed synthesis's vectors, THE SYSTEM SHALL read them by R4 and delete exactly the keys that
read returned, in one `DeleteVectors` call; WHEN it returned no key THE SYSTEM SHALL make no
`DeleteVectors` call. Ordering, error codes and the `vectors_deleted` field are unchanged
(`arkeology.tools.delete`): a failed read returns its existing error before anything is deleted.

**Why:** deleting only what was read leaves nothing that depends on how `DeleteVectors` treats a
key that does not exist, which AWS does not document.

**Example**

- Given an own-scope artifact holding `#0..#2`, when it is deleted with `confirm=True`, then one
  `DeleteVectors` call carries exactly `#0`, `#1` and `#2`, and a `GetVectors` over `#0..#99`
  afterwards returns nothing.
- Given an artifact with no vector — a never-indexed partial write — when it is deleted, then no
  `DeleteVectors` call is made and the S3 object is deleted.

Source: FR-20, FR-21, FR-22; the numbered-key ruling (Operator, 2026-11-12)

### R6 — An overwriting write puts `#0..#k-1`, then reads `#k..#99` and deletes what that read returned; a create makes no clean-up read

WHEN an overwriting write (`update_artifact`, and `update_artifacts` per entry) has put its `k`
vectors at `#0..#k-1` THE SYSTEM SHALL read the keys `#k..#99` by `GetVectors` and delete the keys
that read returned, under the existing orphan-cleanup retry and, when the retry is exhausted, the
existing failure-log entry, whose `orphan_keys` are those numbered keys. WHEN a create writes an
artifact THE SYSTEM SHALL make no clean-up read. The new version's puts replace the previous
version's vectors at the same slots in place, so the artifact is never without vectors between the
two versions.

**Example**

- Given an artifact indexed with 30 sections (`#0..#29`, written with `EMBED_MAX_SECTIONS` 30), when
  it is updated to content with 10 sections, then afterwards a `GetVectors` over `#0..#99` returns
  exactly `#0..#9`, each carrying the new version's metadata.
- Given the same update whose delete fails after its retry, when the update returns, then it reports
  success as today and a failure-log entry lists `orphan_keys` `#10..#29`.

Source: FR-01, FR-75, NFR-06, NFR-13; the numbered-key ruling (Operator, 2026-11-12)

### R7 — A metadata rewrite reads the artifact's vectors with data and metadata by R4, then re-puts each returned key with its embedding unchanged

WHEN `archive_artifact` checks whether an artifact is already archived or flips it, `set_artifact_status`
changes its lifecycle status (T82), or `add_artifact_links` rewrites its `commit_refs` vector copy
(T84), THE SYSTEM SHALL read the artifact's vectors with data and metadata by R4 and re-put each key
that read returned, under the same key, with its embedding unchanged and the new metadata, in one
`PutVectors` call. An artifact whose read returns no key is handled as each tool handles an artifact
with no indexed vector today — for `add_artifact_links`, it is counted in `skipped`.

**Example**

- Given an artifact holding `#0..#3`, when it is archived, then one `GetVectors` over `#0..#99` with
  data is made, one `PutVectors` re-puts exactly `#0..#3` with their stored embeddings, and no
  embedding call is made.

Source: FR-05, FR-53, FR-68; the numbered-key ruling (Operator, 2026-11-12)

### R8 — Reconcile's re-index puts `#0..#k-1` and prunes from a read of `#k..#99`; its orphan-cleanup replay reads the recorded keys by key

WHEN `reconcile_index` re-indexes an artifact THE SYSTEM SHALL write its rebuilt vectors at
`#0..#k-1`, then read `#k..#99` with metadata by `GetVectors`, and apply the existing prune rule to
the keys that read returned: a key whose vector carries a strictly newer `last_edited_ulid` than the
object's current one is spared, and every other returned key is deleted, with a failed delete
recorded as today (`arkeology.tools.reconcile`). WHEN it replays an orphan-cleanup entry THE SYSTEM
SHALL read the recorded `orphan_keys` with metadata by `GetVectors`, apply the existing token test to
the keys that read returned, and treat a recorded key it did not return as already gone — nothing is
deleted for it.

Reconcile's own-scope sweep — the one whole-index enumeration its orphan scan, dangling-vector
prune and T76's `archived` repair work from — stays one per run, so its number does not grow with
how many artifacts the run repairs.

**Why (A legacy key needs no special case):** an orphan-cleanup entry naming heading-slug keys can
still reach this release — appended from an old log (T15 R10), since the store migration's first
step empties only the failure log of the server that runs it (T90 R3). The migration re-keyed every
vector of the artifact, the stale ones such an entry names included, so the replay finds its keys
gone and resolves with nothing deleted. Those stale vectors stay searchable, at numbered keys, until
the artifact's next update or re-index removes them.

**Example**

- Given an artifact holding `#0..#5` whose content now yields 3 sections, when it is re-indexed, then
  `#0..#2` carry the rebuilt vectors and `#3..#5` are deleted.
- Given an orphan-cleanup entry recording `#4` and `#5`, of which only `#5` still exists with an older
  token, when it is replayed, then only `#5` is deleted and the entry resolves.

Source: FR-17; the numbered-key ruling (Operator, 2026-11-12); stale vectors re-keyed, not deleted (Operator, 2026-11-12)

## 4. Rules — Metadata of many artifacts

### R9 — A metadata lookup over several artifacts reads each id's `#0` by `GetVectors`, up to 100 ids per call; an id whose `#0` is not returned has no indexed vector

WHEN the system looks up artifact-level metadata for a set of artifact ids — the freshness check's
batched source lookup (T86 R2), the cross-scope link gate and its baseline fill
(`resolve_readable_targets`, T84, T85), the store migration's foreign source lookup (T90 R20) and
`migrate_artifacts`' per-candidate indexing check — THE SYSTEM SHALL read `{id}#0` for each id by
`GetVectors`, at most 100 ids per call, without data, and SHALL treat an id whose `#0` is not
returned as having no indexed vector. An empty set makes no call. Every result still passes the
cross-scope gate in `_scope.py` exactly as before.

**Why:** every indexed artifact holds `#0` and every one of its vectors carries the same
artifact-level metadata (R1), so one key per id answers. This replaces the `$in` lookups by
`artifact_id`, each of which costs a whole-index scan today, and which a filter of 10,240 bytes
would cap below 100 ids.

**Example**

- Given 250 source ids, when the freshness check resolves them, then three `GetVectors` calls carry
  100, 100 and 50 keys, each of the form `{id}#0`, and no `ListVectors` call is made.

Source: FR-10, FR-20, FR-26; the numbered-key ruling (Operator, 2026-11-12)

### R10 — Until another team migrates its store, a cross-scope key lookup finds no `#0` for its artifacts, and each caller handles them as having no vector

WHILE another team's store still holds vectors under the earlier release's keys THE SYSTEM SHALL
treat that team's artifacts, in every by-key lookup, as having no indexed vector:

- the freshness check reports a source among them as missing (T86 R3);
- the link gate withholds an entry pointing at one, counted in the `{withheld: n}` marker (T85 R5);
- the store migration gives a converted source among them no `last_modified` (T90 R20).

The first two effects end once that team runs the store migration. The third does not: the store
migration never touches an artifact it has already migrated, so a synthesis migrated before its
source's team keeps that source without a baseline — reported `unchecked` with reason `no_baseline`
by the freshness check — until the synthesis is updated with the entry re-supplied.

Own-scope lookups are unaffected: an upgraded server does not start until its own scope is migrated
(T90 check 9). How that team's artifacts appear in search and listings is unchanged by this spec
(T90 R6).

**Example**

- Given a synthesis citing a tier-3 `shared` artifact of a team still on the earlier release, when
  the freshness check runs, then that source is reported missing; after that team migrates, the same
  check reports it fresh or stale as its timestamps say.
- Given a team that migrated first, whose synthesis cites another team's shared artifact, when that
  other team migrates a week later, then the freshness check still reports that source `unchecked`
  with `no_baseline`.

Source: FR-10, FR-20, FR-74; T85 R5, T86 R3, T86 R9, T90 R6; the numbered-key ruling (Operator, 2026-11-12)

## 5. Rules — What stays a query or a scan

### R11 — No per-artifact path uses a whole-index scan or a filtered query to enumerate vectors; similarity search, check 9 and whole-scope enumerations keep theirs

THE SYSTEM SHALL use no `ListVectors` scan and no filtered `QueryVectors` to find one artifact's
vectors or one artifact's metadata. Filtered `QueryVectors` stays for similarity search, synthesis
preparation and check 9's existence probe. The whole-scope enumerations — listing, purge's two
discovery steps, the freshness check's synthesis enumeration, the commit-link proposal, the
delete and archive referrer check, and reconcile's per-run sweep — keep the `ListVectors` scan,
which is a separate decision (`adr-2026-05-29-aws-backend-selection` § Consequences).

**Why (Check 9 needs one vector, not all):** check 9 asks whether any own-scope vector lacks
`archived`, and needs one hit. In the calibration every `ENHANCED` lookup with matches returned at
least one vector, though above 10 matches not all of them; it is the completeness of an
enumeration, not the existence of a hit, that the filtered query cannot provide.

Source: adr-2026-05-29-aws-backend-selection; calibration of 2026-11-12

## 6. Boundaries

**Always:**
- Read one artifact's vectors with one `GetVectors` over exactly `#0..#99`, and delete only keys a
  read returned.
- Put an overwrite's or a re-index's new vectors before reading and pruning the slots above them.
- Gate every foreign lookup through `_scope.py`; use `startswith(scope + "/")` for every scope test.
- Keep every vector of an artifact on the same artifact-level metadata, written in one `PutVectors`
  call.

**Ask First:**
- Changing the key shape, its separator or the 100-slot ceiling. Every stored vector carries the
  key, and the store migration (T90) re-keys to exactly this shape.
- Adding a path that works on one artifact's vectors by anything other than R4 or R9.

**Never:**
- Derive the slot range from the live `EMBED_MAX_SECTIONS` — a lowered setting would hide the
  vectors written under a higher one. Revisit: never; it is the defect this rule exists for.
- Fall back to a scan or a filtered query when a by-key read fails or returns nothing — revisit only
  if AWS documents `GetVectors` failing on a missing key.
- Keep the artifact's key list in an annotation or another store — extra state that can drift from
  the index. Revisit if an artifact must hold more than 100 vectors.
- Zero-pad `n` — revisit if a path ever needs an artifact's keys in document order by sorting them as
  strings.
- Key the document vector by the bare `artifact_id` — revisit if a reader outside Arkeology must
  address an artifact's vector without knowing the numbering.
- Migrate existing vectors here: the store migration re-keys them (T90) — revisit if the store
  migration ever ships apart from the numbered keys.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|---|---|---|
| `src/arkeology/constants.py` | Modify | The 100-slot ceiling, imported by `config.py` and the key helper. Widen the module docstring, which describes only string literals, to name the ceiling |
| `src/arkeology/config.py` | Modify | `EMBED_MAX_SECTIONS` gains `le=` the ceiling; its description names it (R2) |
| `src/arkeology/tools/_vector_keys.py` | Create | *Name uncertain.* Builds `{artifact_id}#{n}`; reads one artifact's vectors over `#0..#99` (R4); reads `#k..#99` for the clean-up (R6, R8); reads `{id}#0` for a set of ids, 100 per call (R9). All through `vectors.get_vectors`, which already chunks at 100, always returns metadata, and asks for data only when told to |
| `src/arkeology/tools/_section_pipeline.py` | Modify | Delete `disambiguate_section_slugs`; `PreparedSection.heading` no longer feeds a key (docstring) |
| `src/arkeology/artifact.py` | Modify, uncertain | Delete `section_slug` if no caller remains after the line above |
| `src/arkeology/tools/write.py` | Modify | Step 7 keys `#0..#k-1` and `#0` for the document vector (R1); Step 8's `list_vectors_by_metadata` becomes R6's read of `#k..#99` |
| `src/arkeology/tools/delete.py`, `purge.py` | Modify | The per-artifact `list_vectors_by_metadata` becomes R4's read; delete only what it returned (R5). Purge's two discovery steps unchanged |
| `src/arkeology/tools/freshness.py` | Modify | Malformed-synthesis delete per R5; source resolution through the R9 helper. Synthesis enumeration unchanged |
| `src/arkeology/tools/_reput.py` (T82), `archive.py`, `lifecycle.py` | Modify | The vector read of the re-PUT cycle and of the already-archived check per R7. *Uncertain:* where T82 left each lookup |
| `src/arkeology/tools/link_metadata.py` | Modify | `add_artifact_links`' per-id vector read per R7 |
| `src/arkeology/tools/reconcile.py` | Modify | Re-index keys and prune per R8; the orphan-cleanup replay reads its recorded keys by key; drop `disambiguate_section_slugs`. The sweep and the `#` split are unchanged |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | The per-candidate indexing check reads `{key}#0` (R9) |
| `src/arkeology/tools/_search_helper.py` | Modify | `fetch_vectors_by_artifact_ids` reads `{id}#0` by key (R9) and loses its `$in` chunking. `fetch_vectors_by_metadata` stays for enumerations. Correct the `_NIN_EXCLUSION_BYTE_BUDGET` comment, which cites a filter limit of about 2 KB: AWS's error message states 10,240 bytes, and its counting is consistent with the filter as sent but not confirmed. The budget value is unchanged |
| `src/arkeology/tools/_reference_filter.py` | Modify | Docstring only: one `#0` read per 100 candidates. The candidate loop is unchanged |
| `src/arkeology/clients/vectors.py`, `interfaces.py` | None expected | `get_vectors` already chunks at 100, returns metadata on every call and returns only the keys found; `list_vectors_by_metadata` keeps the scan for enumerations |
| Tests | Create / Modify | See Testing Approach |

### Contracts

These contracts state the by-key behaviour and the key shape, amended with this spec:
`data/s3vectors.artifact.md` (the key shape, `#0` always present, the 100-slot ceiling) and the
module contracts `arkeology.tools.write`, `.archive`, `.delete`, `.purge`, `.link_metadata`,
`.freshness`, `.migrate_artifacts` and `.reconcile` (each one's by-key read). The Phase 15 tool
renames (T78, T82, T84) carry into those contracts.

Two contracts take the same statement once T82 and T85 have written their parts:

- **`modules/arkeology.tools.lifecycle.md`**, `### set_artifact_status`: archive's by-key invariant —
  one `GetVectors` over `#0..#99` with data and metadata, a re-put of exactly the keys it returned,
  and no scan or filtered query per artifact.
- **`modules/arkeology.tools.read.md`, `.list.md` and `.synthesise.md`**, the link-gate redaction
  lookup T85 states there: each foreign target's `#0` read by key, up to 100 per call, a target with
  no `#0` withheld as one with no vector.

### Testing Approach

TDD: each test file below is written and confirmed failing before the implementation file it gates.
moto 5.2.2 implements `GetVectors` — it returns only the stored keys among those requested and
raises nothing for a missing one — and `DeleteVectors`, which ignores missing keys. It enforces
neither per-call limit, so call sizes are asserted with `mocker.spy` on the vectors client. Every
per-artifact test below also spies that `list_vectors_by_metadata` and `query_vectors` are never
called. Unit fixtures that seed vectors by hand for a per-artifact path seed numbered keys;
fixtures for enumeration paths may keep any key.

1. Integration (real AWS, run-scoped prefix), `tests/integration/clients/test_vectors_client.py` →
   `_vector_keys.py` (R4): after putting `#0..#4` for one artifact id, a `GetVectors` over `#0..#99`
   returns exactly those 5 keys and raises nothing. This is the first observation of the mixed
   request every by-key read rests on, so it runs, and passes, before the key helper is written.
2. `tests/unit/test_config.py` → `constants.py`, `config.py` (R2): 100 accepted, 101 rejected with
   the variable named, default 20.
3. `tests/unit/test_tools__vector_keys.py` → `_vector_keys.py` (R1, R4, R9): key format; one
   `get_vectors` call with exactly `#0..#99`; only stored keys come back; 250 ids give calls of 100,
   100 and 50 `#0` keys; an empty set makes no call.
4. `tests/unit/test_tools_section_pipeline.py`, `test_artifact.py` → `_section_pipeline.py`,
   `artifact.py` (R3): delete the disambiguation tests, and the `section_slug` tests if it goes.
5. `tests/unit/test_tools_write.py`, and the integration test in `tests/integration/test_tools_write.py`
   → `write.py` (R1, R6): keys in document order; `#0` for a document vector; duplicate headings get
   distinct keys; 30 sections then 10 leaves exactly `#0..#9`; a create makes no clean-up read; an
   exhausted delete records numbered `orphan_keys`. The integration test creates an artifact with
   30 sections and updates it to 10 against real AWS, with `EMBED_MAX_SECTIONS` set to 30 in its own
   settings, and asserts that a `GetVectors` over `#0..#99` returns exactly `#0..#9`; it makes 40
   embedding calls.
6. `test_tools_delete.py`, `test_tools_purge.py`, `test_tools_freshness.py` → `delete.py`, `purge.py`,
   `freshness.py` (R5, R9): one delete call with exactly the keys read; none when the read is empty;
   freshness sources resolved by `#0`.
7. `test_tools_archive.py`, the T82 lifecycle tests, `test_tools_link_metadata.py` → `_reput.py`,
   `archive.py`, `lifecycle.py`, `link_metadata.py` (R7): one read with data, one re-put of exactly
   the returned keys, embeddings byte-identical, no embedding call; an id with no `#0` is skipped.
8. `test_tools_reconcile.py` → `reconcile.py` (R8): the re-index prune of `#k..#99` with the
   newer-token exemption; the replay deletes only recorded keys the read returned; one
   `list_vectors_by_metadata` call per run, however many artifacts it repairs.
9. `test_tools__search_helper.py`, `test_tools__reference_filter.py`, `test_tools_migrate_artifacts.py`
   → `_search_helper.py`, `_reference_filter.py`, `migrate_artifacts.py` (R9, R10): `#0` lookups; a
   foreign artifact seeded only under a heading-slug key is withheld, missing, or unindexed.

**Integration tests broken by this change:** `tests/integration/test_tools_write.py` reads
`artifact_id + "#summary"`; it reads `#0` instead. The run-scoped prefixes are fresh per run, so no
other test meets an earlier key.

**Calibration instruments.** `tests/integration/test_calibration_enhanced_filtered_query.py`
measured the filtered query on 2026-11-12; it needs a `boto3`/`botocore` whose model declares
`QueryVectors.queryMode`, layered over the lock with `uv run --with`, as its module docstring says.
`tests/integration/test_calibration_per_artifact_vector_lookup.py` compared the scan with one query
on a 371-vector index on 2026-09-14. Both seed under an ephemeral `integration-tests/<run-id>`
prefix and tear down what they wrote; neither is part of this spec's gates.

**Development stores.** Until T90 lands, a development store written before this spec holds
heading-slug keys that the by-key paths do not see. Run `uv run arkeology` and manual checks against
a fresh write prefix, or migrate the store with T90's command once it exists.

**Mutation.** `_reference_filter.py` is in `only_mutate`; only its docstring changes. After the unit
suite is green, run `uv run mutmut run` alone and triage survivors as AGENTS.md describes.

### Hand-offs

The documentation hand-off:

- AGENTS.md § Repository Structure: a `_vector_keys.py` row; the `_search_helper.py` row no longer
  calls `fetch_vectors_by_artifact_ids` an `$in` chunker — it reads each id's `#0` by key; and the
  `constants.py` row, which says "string-literal constants", also names the 100-slot vector
  ceiling.
- AGENTS.md § High-Friction Areas or § Working Conventions: the key shape, and that a per-artifact
  path reads by key, never by scan or filtered query.
- SERVER-REFERENCE's `EMBED_MAX_SECTIONS` row: the 1–100 range.
- The CHANGELOG **Breaking** entry: a server configured with `EMBED_MAX_SECTIONS` above 100 no longer
  starts, and the store migration re-keys every vector.

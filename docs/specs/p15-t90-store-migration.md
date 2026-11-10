---
type: Spec
id: p15-t90-store-migration
title: T90 — Store Migration Skill and Command
description: Adds an operator-run console command, arkeology-migrate-store, run outside the MCP server with servers stopped, and a migrating-arkeology-store skill that bring an existing deployment's own scope (never another team's prefix) from the pre-Phase-15 shape to the OKF v0.2 shape — archived, display-name types, generated/revised provenance, the links annotation, a seeded revision history — in S3 object metadata, annotations and vector metadata, without re-embedding. A dry run reports every change; changes happen only on --apply after the operator confirms; a local journal written before each re-PUT makes a crash between the re-PUT and the annotation restore recoverable; a second run reports nothing to change. Adds a ninth startup check (FR-07) that refuses to start while the own scope is unmigrated.
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
    title: Plan for Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
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
  - id: spec-t80
    resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:40:30Z
  - id: spec-t81
    resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: T81 — OKF Lifecycle status and the In-Force Default View
    last_modified: 2026-10-13T16:19:13Z
  - id: spec-t82
    resource: docs/specs/p15-t82-lifecycle-change.md
    title: T82 — Change Lifecycle status Without Re-Embedding
    last_modified: 2026-10-13T17:40:25Z
  - id: spec-t84
    resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:23:06Z
  - id: spec-t86
    resource: docs/specs/p15-t86-per-source-freshness.md
    title: "T86 — Per-Source Freshness"
    last_modified: 2026-10-13T18:19:14Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-s3vectors
    resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format — Specification
  - id: okf-issue-16
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/16
    title: OKF GitHub issue #16 — typed relationships
  - id: aws-s3vectors-filtering
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html
    title: S3 Vectors — Metadata filtering
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-09-14-malformed-persisted-data-policy
    type: constrained_by
  - to: p15-t76-archived-boolean
    type: builds_on
  - to: p15-t77-open-type-list
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t80-revision-history
    type: builds_on
  - to: p15-t81-lifecycle-status-in-force
    type: builds_on
  - to: p15-t84-sources-relationships
    type: builds_on
  - to: p15-t86-per-source-freshness
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T21:13:59Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T23:21:06Z
---

# T90 — Store Migration Skill and Command

## TL;DR

An operator who upgrades a deployment that already holds artifacts runs one command,
`arkeology-migrate-store`, guided by a new `migrating-arkeology-store` skill. A dry run reports
every change. Nothing changes until the operator confirms and the command is re-run with
`--apply`. It then rewrites the own scope's object metadata, annotations and vector metadata to the
Phase 15 shape, never re-embeds, survives a crash at any point, and a second run reports nothing to
change (FR-74, AC-79; D42).

## 1. Problem Statement

Tasks T76–T87 change what every stored artifact looks like and ship no compatibility aliases (D42).
A store written before them keeps the old shape: the archive marker in `status`, snake_case types,
`date` and `author_role`, `source_artifacts` in both metadata stores, and a comma-joined
`references` annotation. The new server reads none of these (T76 Open Questions item 3 lists the
effects): default views return nothing, `read_artifact` returns `corrupt_metadata`, and freshness
reports `all_fresh: true` while checking nothing. `reconcile_index` repairs index drift from S3 and
gains no migration code (D42), so a separate tool must convert the store once. That tool is the
first one that rewrites every artifact in place (plan.md `## Risks and Open Questions`). Every
rewrite wipes the object's annotations until they are restored, and a crash in between loses them
(C-07). The migration must be recoverable from its own record.

The seven user stories of this spec are kept as labelled examples under the rules they illustrate
(Story 1 to Story 7); all seven are P1. The decisions taken in this spec keep their titles as
labelled **Why** lines on the rules they settle, and the answered question keeps its number (Open
Questions item 1).

## 2. Rules — Delivery

### R1 — `arkeology-migrate-store` is an operator-run console command: a dry run with no flag, writes only with `--apply`

The system provides an operator-run command, `arkeology-migrate-store`. It is a console entry
point declared in `pyproject.toml` beside `arkeology`, so it installs with the package and runs the
way the server runs. The documented clone install runs it as
`uv run --directory <clone> arkeology-migrate-store`. With no flag it is a dry run; `--apply`
writes.

**Why (A package command, not a script in the skill directory):** The conversion must use the server's
own decoders, encoders and validators: T77's table, T79's parser and actor check, T84's entry
validation, keyed merge and encoder, T80's history encoder, `check_metadata_budgets`, and the gate.
A standalone script would copy them and drift. As a console script it runs from the same clone and
configuration as the server, and it runs while the server refuses to start.

Source: FR-74; D42

### R2 — The command runs outside the MCP server, on the package's own clients and settings, calls no MCP tool, and acts on the configured write prefix only

The command runs outside the MCP server. The old server has no migration capability, and the
upgraded server cannot read the old shape (T76 Open Questions item 3). It uses the package's S3 and
S3 Vectors clients and the `annotations.py` helpers directly. It loads settings exactly as the
server does (`.env` plus environment), and calls no MCP tool. It acts on the configured write
prefix only (see "Shared stores" below).

**Why (A package command, not a script in the skill directory, continued):** It is not an MCP tool:
ADR-017 §9 chose "a skill plus scripts", and with check 9 the server cannot serve it.

Source: FR-74; D42

### R3 — The `migrating-arkeology-store` skill walks the operator through seven steps and never passes `--apply` before the operator's confirmation

The system provides a skill, `migrating-arkeology-store`, that walks an Admin / DevOps through this
sequence:

1. On the old version, run `reconcile_index` until the failure log is empty (T84 Open Questions
   item 3);
2. stop every server that writes this write prefix, on every team member's MCP client, whatever
   its version;
3. install the new version;
4. run the dry run with the same configuration values as the MCP client entry, show the report,
   and wait for the operator's explicit confirmation in the conversation;
5. run `--apply`, and run it again after any interruption or any `remaining` entry;
6. confirm that a final dry run reports nothing to change;
7. start the servers.

The skill never passes `--apply` before that confirmation. Started before step 6, an upgraded
server refuses to start with an error naming this command (check 9 below), which is the intended
signal to run it.

**Why (Confirmation is a flag plus the skill's rule):** The default run is the dry run, and only
`--apply` writes. An interactive prompt would hang an agent-driven run. A token passed between the
dry run and `--apply` proves nothing about a human, because an agent can copy it. What FR-74 needs
is that the operator decides, and the skill states that rule.

Source: FR-74; D42

### R4 — `reconcile_index` does not change in this task

`reconcile_index` does not change in this task.

Source: FR-74; D42

## 3. Rules — Shared stores — own scope only

### R5 — Only the configured write prefix and own-scope vectors are migrated, never another prefix

The system migrates only artifacts under the configured write prefix and own-scope vectors. It
never writes under another prefix, even when the credentials would allow it. An Admin with write
access to several prefixes migrates them one after another, running the command once per prefix
with that prefix as `WRITE_PREFIX`. Resume considers only journal records whose artifact id is in
the current own scope.

**Why (Rationale):** The requirements settle this. FR-74 migrates "an existing deployment's stored
artifacts". Throughout the requirements a deployment's storage is its own scope: every capability
that writes is confined to it (FR-05, FR-17, FR-68, FR-75), and startup proves only read access
to subscribed foreign scopes (FR-07). A whole-store mode would be the first path that writes a
foreign scope. It would need foreign write permissions the setup never grants. It would also
rewrite another team's artifacts while that team's old servers may still run, and an old server's
overwrite of a migrated artifact drops the `links` and `revision_history` annotations it does not
know about (see "Writes during a run"). Own-scope migration has no cross-team write race at all.
What it leaves is visibility across scopes during a staggered rollout, which the operators
coordinate as below.

Source: FR-74, FR-05, FR-07, FR-10, FR-68, FR-75

### R6 — What the operators of a shared store coordinate: required, recommended, and the staggered rollout

What the operators of a shared store coordinate:

- **Required, for data safety:** every server writing a prefix is stopped while that prefix
  migrates. Servers of other prefixes may keep running; nothing they do writes this prefix.
- **Recommended:** one window in which every team sharing the bucket and index stops, installs
  the new version, migrates its own prefix, and starts.
- **Staggered rollout:** an upgraded server starts once its own scope is migrated, whatever its
  `READ_PREFIXES` hold (check 9 probes the own scope only). Another team's unmigrated artifacts
  follow the malformed-data policy for foreign data: they are skipped and counted under
  `skipped_malformed_count` in listings, and `read_artifact` returns `corrupt_metadata` for them
  (T76 Open Questions item 3). A team still on the old version does not see migrated teams'
  artifacts correctly until it upgrades. Old code reads the archive marker from `status`, and
  this release cannot change old code.

Source: FR-74, FR-05, FR-07, FR-10, FR-68, FR-75

## 4. Rules — Writes during a run, and late writes

### R7 — An object changed between the read and the re-PUT is detected by the ETag condition, retried, and reported as `conflict` when the retries run out

When an artifact's object changes between the command's read and its re-PUT, the system detects it
through the ETag condition, retries from a fresh read, and reports `conflict` when the retries run
out.

Source: FR-74, C-06, C-07

### R8 — A legacy-shaped artifact or vector that appears after the scan is not migrated in that run, is listed under `remaining`, and the next run migrates it

When a legacy-shaped artifact or vector appears after the scan listed the scope, the system does
not migrate it in that run. The final verification scan lists it under `remaining` and the exit
code is non-zero. The next run migrates it, because every run scans the whole own scope from
scratch and skips only what is already migrated.

Example (Story 7, late writes are caught, not lost):

- Given an `--apply` run during which a legacy-shaped artifact is written after the scan, when the
  run ends, then verification lists it and the exit code is non-zero. A second `--apply` migrates
  it.

Source: FR-74, C-06, C-07

### R9 — The skill states both consequences of writes the command cannot detect when it asks for the servers to be stopped

Writes the command cannot detect are why step 2 of the sequence is required. An annotation-only
write, such as an old server's `link_metadata`, landing between the command's read and its restore
is overwritten (S3 offers no annotation-level precondition). An old server overwriting an
already-migrated artifact returns it to the legacy shape. A re-run migrates it again, but the
`links` and `revision_history` that the old server wiped and could not restore are lost. The skill
states both consequences when it asks for the servers to be stopped.

Source: FR-74, C-06, C-07

## 5. Rules — Dry run

### R10 — Without `--apply`, no write call and no Bedrock call is made; the report lists every change, every artifact that cannot migrate, and every dangling legacy vector

When the command runs without `--apply`, the system makes no write call to S3 or S3 Vectors, and no
Bedrock call. It reports: each artifact to migrate with its changes; each artifact it cannot
migrate with the reason; each legacy-shaped vector whose S3 object does not exist; counts of
already-migrated artifacts; and `nothing_to_change`, true exactly when the three lists are empty.

Example (Story 1, see every change before anything changes):

- Given a store in the pre-Phase-15 shape, when the operator runs the command without `--apply`,
  then it reports each artifact to migrate with its changes, every artifact it cannot migrate with
  the reason, and every legacy vector with no S3 object. It makes no write call to S3 or S3 Vectors
  (FR-74).

Source: FR-74

### R11 — The report is one JSON document on stdout; progress is logged to stderr

The report is one JSON document on stdout. Progress is logged to stderr.

**Why (Report on stdout):** AGENTS.md's stdout rule protects the MCP stdio transport. This command never
serves MCP, and the server's entry point is unchanged. T91 qualifies the rule's wording.

Source: FR-74

## 6. Rules — What counts as legacy

### R12 — An artifact needs an object migration when any one of the listed legacy conditions holds

An artifact needs an object migration when its S3 object metadata has no `archived` equal to
`"true"` or `"false"`, OR no `generated_at`, OR it carries `date`, `author_role`,
`source_artifacts` or `commit_refs`, OR its `status` is `active` or `inactive`, OR its `type` is a
legacy value in T77's display-name table, OR the object carries a `references` annotation.

Source: AC-79; D21, D29, D35, D37

### R13 — A vector needs migration when any one of the listed legacy conditions holds

A vector needs migration when its `archived` is not a native boolean, OR it has no
`generated_at`, OR it carries `date`, `author_role`, `source_artifacts` or `references`, OR its
`status` is `active` or `inactive`, OR its `type` is a legacy value.

Source: AC-79; D21, D29, D35, D37

### R14 — Every other key is left as it is; content bytes, `last_edited_ulid`, embeddings and content frontmatter are never changed

Every other key is left as it is. Content bytes, `last_edited_ulid` and each vector's embedding are
never changed. Content frontmatter is not touched (D10).

Source: AC-79; D10, D21, D29, D35, D37

## 7. Rules — Target shape per field

Each rule in this section defers to the task that owns the field.

### R15 — `archived` comes from an existing boolean marker or from the legacy `status`; a lifecycle `status` is kept and never added

`archived` (T76): an `archived` already equal to `"true"` / `"false"` is kept. Otherwise `status`
`inactive` gives `"true"` and `active` gives `"false"`. A legacy `status` is then removed. A
lifecycle `status` (`draft`, `stable`, `deprecated`) is kept, and no lifecycle `status` is ever
added (T81, AC-69).

Source: AC-69; T76, T81

### R16 — A legacy `type` becomes its display name from T77's table, in both stores, and ids do not change

`type` (T77, D37): a legacy value becomes its display name from T77's table, in both stores. Ids do
not change, because the slug of each display name equals its legacy slug.

Source: D37; T77

### R17 — Provenance is derived from the stored `date` (D) and the `last_edited_ulid` instant (U); `by` is the stored `author_role` only when it passes T79's actor-form check; `date` and `author_role` are removed

Provenance (T79; D9, D32, D35) — given D, the stored `date`, and U, the instant of the stored
`last_edited_ulid` truncated to whole seconds:

- When U exists and falls on UTC day D, the system sets `generated_at` to U and writes no
  `revised`.
- Otherwise the system sets `generated_at` to `{D}T00:00:00Z`. When U exists and is later than
  that, the system sets `revised_at` to U.
- `generated_at` therefore always falls on UTC day D. Values use T79's `YYYY-MM-DDTHH:MM:SSZ`
  form.
- `by` (OKF §7): when `revised` is written, `revised_by` is the stored `author_role` if it passes
  T79's actor-form check, else `process:arkeology-store-migration`, and `generated_by` is
  `process:arkeology-store-migration`. When `revised` is not written, `generated_by` is
  `author_role` if it passes that check, else `process:arkeology-store-migration`.
- `date` and `author_role` are removed. No store holds `timestamp` or `authored`, so neither
  needs a rule. The failure log's own `timestamp` is not an artifact field (T79).

Example (Story 3, keys keep their meaning):

- Given a migrated tier-2 artifact whose old `date` was D, when a later create uses the same type
  and title with a `generated.at` on UTC day D, then it is rejected with `validation_error` and one
  artifact remains (AC-04).

**Why (Provenance from `date` and `last_edited_ulid`):** The ULID is the only recorded instant of the
last content write. When it falls on the `date` day, it is the best available first-authorship
time, and nothing was revised after it. When it does not, `date` gives the authorship day and the
ULID the latest revision. Effective time is then the ULID instant whenever the ULID is not earlier
than `date`, so per-source freshness reproduces today's ULID comparison (Story 4). The
`generated.at` day always equals D, which keeps AC-04 for every existing tier-2 key (plan.md T90
entry).

**Why (`by` never claims more than was recorded):** `author_role` was rewritten on every write, so it
names the last writer (D35: it "duplicated `revised.by`"). It becomes `revised.by`, or
`generated.by` when nothing was revised, only when it is already an OKF §7 actor the writer
supplied. A bare role name such as `developer` is not an actor. OKF §7 has no form for an unknown
author, and `generated` is required by T79. `process:arkeology-store-migration` names the actual
origin of the record. It never triggers §5.3's `human:` trust, and since the key is filterable, a
reader can find every reconstructed record.

Source: AC-04; D9, D32, D35; T79

### R18 — An absent `revision_history` is seeded with `[generated]`, followed by `revised` when one is written; a present, readable history is kept

`revision_history` (T80; D26, D30): when the annotation is absent, the system seeds it with
`[generated]`, followed by `revised` when one is written. A present, readable history is kept.

**Why (History seeded):** This resolves T80 Open Questions item 2. ADR-017 states that the history's
first and last entries coincide with `generated` and `revised`. Seeding keeps that true for
migrated artifacts.

Source: D26, D30; T80

### R19 — `source_artifacts` and legacy `references` become `links` entries in stored order, merged into an existing `links`, each validated and encoded by T84

`links` (T84; D17, D18, D29):

- each `source_artifacts` entry becomes `{resource: "arkeology://artifact/<entry>"}`, in stored
  order. A full key stays a full key;
- each legacy `references` annotation entry becomes `{to: <entry>, type: "references"}`, in
  stored order;
- when a readable `links` annotation already exists, the converted entries are merged into it by
  T84's keyed merge, existing entries first;
- every entry passes T84's write-path entry validation and T84's encoder.

**Why (Relationship type `references`):** The legacy edge asserted only that A references B. A specific
type such as `builds_on` would invent a claim. OKF GitHub issue #16 leaves `type` producer-defined,
and `references` already appears there as an edge type.

Source: D17, D18, D29; T84

### R20 — A converted source that resolves to a readable Arkeology key gets as `last_modified` the earlier of its own and the citing artifact's effective time; one that is missing, unreadable or has no derivable time gets none

Source baselines (D19, D40; T86 Open Questions item 1): for each converted source that resolves to
an Arkeology key the migrating server may read, the system sets `last_modified` to the earlier of
the source's effective time and the citing artifact's own effective time. Effective time is
`revised_at`, else `generated_at`, as migrated by this run for own-scope artifacts. A foreign
tier-3 `shared` source uses the same derivation applied to its vector metadata, read through the
existing cross-scope gate in `_scope.py`. Parsed datetimes are compared, never strings. A source
that is missing, unreadable, or has no derivable time gets no `last_modified`.

Example (Story 4, freshness verdicts survive the migration):

- Given a synthesis S written after source A and before a revision of source B, when the store is
  migrated and `check_synthesis_freshness` runs, then B is reported stale and A is not, as the
  pre-migration check reported (FR-20, D19).

**Why (Baseline = earlier of source and citer):** This resolves T86 Open Questions item 1, refining its
second option. When the source has not changed since the synthesis was written, its current
effective time is exactly the revision the synthesis observed, which is OKF §5.1's literal meaning.
When the source changed later, the revision observed is unrecorded. The synthesis's own time is
then earlier than the source's, so the source reports stale, as today's ULID check reports it.
Using the source's current time (D40's import rule) would declare every migrated synthesis fresh
and hide real staleness. D40 is sound at import because resolving the source confirms the version.
At store migration that confirmation does not exist.

Source: FR-20; D19, D40; T86 Open Questions item 1

### R21 — `commit_refs` is carried across the re-PUT, a legacy object-metadata copy is merged in and removed, and the vector copy is capped

`commit_refs`: the annotation is carried across the re-PUT. A legacy object-metadata `commit_refs`
is merged in after it with the existing `merge_link_field` and removed from object metadata. Each
vector's `commit_refs` becomes the merged list capped by `cap_commit_refs_for_vectors`, and is
omitted when empty.

Source: —

### R22 — Vector metadata drops the legacy keys and takes `archived`, `type`, provenance and `status` from the migrated object metadata

Vector metadata: the legacy keys above are removed; `archived` (boolean), `type`, the provenance
keys and `status` (present exactly when the S3 object has a lifecycle `status`) are set from the
migrated S3 object metadata; every other key is kept.

Source: —

### R23 — `source_artifacts` and `author_role` stay declared non-filterable slots, now unwritten

`source_artifacts` and `author_role` stay declared non-filterable slots, now unwritten (C-01).

Source: C-01

## 8. Rules — Cannot migrate — reported, never guessed

### R24 — An artifact that cannot be migrated is reported with the reason, nothing is written for it, and the run continues

When an artifact has no usable archive marker, no valid ISO `date` while lacking `generated_at`, an
entry that fails T84's validation, an unreadable `links` or `revision_history`, migrated metadata
over a `check_metadata_budgets` budget, or content the S3 client cannot return, the system reports
it with the reason and writes nothing for it. The run continues with the next artifact.

Source: malformed-data ADR; D50 case 1

### R25 — An annotation read treats only `NoSuchAnnotation` as empty; every other failure fails the artifact

Any annotation read treats only `NoSuchAnnotation` as empty. Every other failure fails the artifact
(`s3-annotations.artifact` `## Not-Found Semantics`).

Source: malformed-data ADR; D50 case 1

## 9. Rules — Apply — order of operations and the journal

### R26 — `--apply` first runs startup checks 1, 2, 4 and 8, stops before any change if one fails, and runs no Bedrock check and constructs no Bedrock client

When `--apply` is given, the system first runs startup checks 1, 2, 4 and 8 (credentials, write
prefix, vector index, annotations) and stops before any change if one fails. It runs no Bedrock
check and constructs no Bedrock client.

Source: FR-74, C-07

### R27 — Each artifact needing an object migration goes through six steps in order, with a flushed journal `start` record before its re-PUT

For each artifact needing an object migration, the system, in order:

1. reads the object metadata and ETag, the content, and the `commit_refs`, `references`, `links`
   and `revision_history` annotations, then computes the target and checks budgets;
2. appends a `start` record to the journal, holding the artifact id and the target `commit_refs`,
   `links` and `revision_history`, and flushes it to disk. When the append fails, the system stops
   the run before any write;
3. re-PUTs the same content bytes with the target object metadata, conditional on the ETag from
   step 1. When the ETag no longer matches, it starts again at step 1, at most
   `CAS_MAX_ATTEMPTS` times, then reports the artifact as `conflict` and continues;
4. writes the target annotations, each conditional on the new ETag. The legacy `references`
   annotation is not restored, because the re-PUT already removed it;
5. re-puts every vector of the artifact with its stored embedding and the target vector metadata;
6. appends a `done` record.

Example (Story 2, migrate on confirmation):

- Given that report and the operator's confirmation, when the command runs with `--apply`, then no
  artifact carries a legacy field or type name. Reading, listing and searching return every
  artifact in the new shape, and no embedding call is made. A second run reports nothing to change
  (AC-79).

**Why (Journal-ahead, local, one artifact at a time):** C-07's residual is a process death between the
re-PUT and the restore. Recording the target annotations before the re-PUT closes it for this tool.
Stopping on any post-re-PUT failure bounds the exposure to one artifact. The journal is a run's
recovery record and is never read as a source. It mirrors the failure log's precedent of a local
JSONL file, and it is not a second store. S3 was rejected for the journal: one object per artifact
doubles the PUTs, and a key under the write prefix must avoid reconcile's orphan scan.

**Why (Not T82's re-PUT cycle):** T82's cycle carries the annotation set it reads. The migration must
restore a different set: `references` becomes `links`, and the history is seeded. It must also
journal before the re-PUT. Widening T82's cycle for one caller would change its contract.

Source: FR-74, C-07

### R28 — A failing step after step 3 has landed stops the whole run; at most one artifact is ever between its re-PUT and its restore

When any step after step 3 has landed fails, the system stops the whole run and reports the
artifact and the step. At most one artifact is ever between its re-PUT and its restore.

Source: FR-74, C-07

### R29 — An already-migrated object with unmigrated vectors gets only those vectors re-put, with no journal record

When an artifact's object is already migrated but some of its vectors are not, the system re-puts
those vectors only. No journal record is needed, because nothing is wiped.

Source: FR-74, C-07

### R30 — A legacy-shaped vector whose S3 object is confirmed gone by a fresh read is deleted

When a legacy-shaped vector's artifact has no S3 object, confirmed by a fresh read, the system
deletes that vector.

**Why (Dangling legacy vectors are deleted):** With check 9, a dangling legacy vector would keep the
server down, and only `reconcile_index` could remove it. The command deletes it after confirming,
by a fresh read, that its object is gone, and the dry run lists it first.

Source: FR-74, C-07

### R31 — On resume, an artifact whose last journal record is `start` is finished from the journal, left to the scan, or recorded `done`, by its object's state

Resume: when `--apply` starts and the journal holds an artifact whose last record is `start`, the
system reads its object before scanning:

- object migrated: apply steps 4–6 from the journal record;
- object still legacy: do nothing, because the scan migrates it as usual;
- object gone: record `done` and report it.

Example (Story 5, a crash loses nothing):

- Given an `--apply` run killed after an artifact's re-PUT and before its annotations are restored,
  when the operator runs `--apply` again, then that artifact's `commit_refs`, links and revision
  history are restored from the run's journal, and the store ends as an uninterrupted run leaves it
  (C-07).

Source: FR-74, C-07

### R32 — The journal is a local file, `.arkeology_store_migration.jsonl` by default, that no server path reads

The journal is local, defaulting to `.arkeology_store_migration.jsonl` in the working directory,
with `--journal` to override. No server path reads it. A later run ignores completed records.

Source: FR-74, C-07

### R33 — After `--apply`, a verification scan reports what is still unmigrated, and the exit code is non-zero when either verification list, the cannot-migrate list or the failed list is non-empty

Verification (D50 case 3): when `--apply` finishes, the system scans the own scope again and
reports every vector without a native boolean `archived`, and every artifact still needing a
change. It exits non-zero when either list, the cannot-migrate list or the failed list is
non-empty.

Source: FR-74, C-07; D50 case 3

## 10. Rules — Startup check 9 — store shape, own scope only

**Open Questions item 1 — Resolved 2026-10-13 — startup check 9 accepted, own scope only.** The
operator accepted the check, and FR-07 now requires "that the deployment's own stored artifacts are
in the current storage shape, so a deployment upgraded without migrating its store refuses to start
and names the migration to run". Foreign read prefixes are not probed. Another team's unmigrated
artifacts follow the existing malformed-data policy for foreign data. *Original question:* should
the server refuse to start while its own scope holds vectors in the pre-upgrade shape, and also
while a `READ_PREFIXES` entry holds readable pre-upgrade artifacts?

### R34 — The server runs a ninth startup check, after check 8: one top-k-1 `query_vectors` call for an own-scope vector without `archived`

When the server starts, the system runs a ninth check, after check 8. It makes one
`query_vectors` call with top-k 1 and the filter
`{"$and": [{"scope": {"$eq": <write prefix>}}, {"archived": {"$exists": false}}]}`. The query
vector is a unit basis vector of the index dimension that check 4 already read, so no embedding
is needed.

**Why (Check 9 probes by query, not by scan or marker):** A scan costs one ListVectors page per 1,000
vectors on every start. A marker object would not see legacy vectors written after it. One filtered
query costs one request. On an `ENHANCED` index, S3 Vectors pre-filters, so any match is returned.
A `CLASSIC` index may return fewer than top-k when few vectors match (AWS S3 Vectors metadata
filtering documentation). A store that was never migrated matches on every vector, and a
partially migrated one is caught by the command's own verification.

Source: FR-07; D42, D50

### R35 — A returned vector fails startup with `StartupValidationError` check `store_shape`, naming the artifact and the command

When the call returns a vector, the system raises `StartupValidationError` with check
`store_shape`. The message names the returned `artifact_id`, states that the store is in the
pre-upgrade shape, and gives the command and skill that migrate it. The server exits through the
existing startup-failure path. A credential failure propagates as today, and any other failure
fails the check.

Example (Story 6, the new server refuses an unmigrated store):

- Given an own scope holding a vector without `archived`, when the server starts, then it exits
  before serving requests with a message that names the migration command. The command itself
  still runs (FR-07; D42).

Source: FR-07; D42, D50

### R36 — An empty result passes the check; a fresh or empty store passes, and foreign read prefixes are not probed

When the call returns nothing, the check passes. A fresh or empty store passes. Foreign read
prefixes are not probed.

Example (Story 6, continued):

- Given a migrated own scope and a foreign read prefix still in the pre-upgrade shape, when the
  server starts, then it starts. Those foreign artifacts follow the malformed-data policy: skipped
  and counted in listings, `corrupt_metadata` on read.

Source: FR-07; D42, D50

### R37 — `arkeology-migrate-store` does not run check 9 and never calls the full startup sequence

`arkeology-migrate-store` does not run check 9. It never calls the full startup sequence.

Source: FR-07; D42, D50

## 11. Boundaries

**Always:**
- Write a flushed journal `start` record before every re-PUT, and re-PUT the content bytes read,
  conditional on their ETag.
- Treat only `NoSuchAnnotation` as empty. Report an artifact rather than infer a value for it.
- Compare timestamps as parsed datetimes. Gate every foreign source lookup through `_scope.py`.
  Use `startswith(scope + "/")` for every scope test.
- Log to stderr. Delegate to the shared encoders, validators and tables named above.

**Ask First:**
- Changing the provenance derivation, the `by` rule, the baseline rule or the relationship type.
  Each one is persisted in every migrated artifact.
- Adding concurrency to the run.

**Never:**
- Call Bedrock, construct a Bedrock client, call an MCP tool, or change an embedding or the content
  bytes.
- Write under any prefix other than the configured write prefix.
- Add migration code to `reconcile_index`, or translate a legacy key anywhere in the server (D42).
- Write when the run is a dry run, or pass `--apply` in the skill without the operator's
  confirmation.
- Set a lifecycle `status`, append to the server's failure log, or touch an artifact that is already
  migrated.
- Edit README, SERVER-REFERENCE, CHANGELOG or AGENTS.md (T91).

AC-80 does not apply: T90 removes no name.

## 12. For the developer agent

### Files to Touch

| File | Action | Notes |
|---|---|---|
| `src/arkeology/store_migration.py` | Create | `main()`: argument parsing (`--apply`, `--journal`), logging as `__main__.configure_logging`, settings via `load_settings`, S3 and S3 Vectors clients only. Scan, plan, report, resume, apply, verify. Constants: the actor `process:arkeology-store-migration`, the relationship type `references`, the default journal path |
| `pyproject.toml` | Modify | `[project.scripts]`: `arkeology-migrate-store = "arkeology.store_migration:main"` |
| `src/arkeology/startup.py` | Modify | Add check 9 (`_check_store_shape`), taking check 4's index info. Add one public function that runs checks 1, 2, 4 and 8 only, for the command. Module docstring and log lines: nine checks |
| `src/arkeology/annotations.py` | Modify | A public read of the legacy `references` annotation, through the same single-annotation read `commit_refs` uses (absent gives `[]`, everything else raises). It is the durable link-field invariant, so it stays in the mutation scope. *Uncertain:* after T84 the shared reader's name may differ, so reuse whatever reads `commit_refs` |
| `plugins/arkeology/skills/migrating-arkeology-store/SKILL.md` | Create | The skill as specified in Requirements, "Delivery". Its description sends documentation imports to `migrating-to-arkeology` |
| `plugins/arkeology/.claude-plugin/plugin.json` | Modify | The description names store migration |
| `.gitignore` | Modify | `.arkeology_store_migration.jsonl` |
| `docs/contracts/modules/arkeology.store_migration.md` | Create | Contract step, before tests: command, flags, exit codes, report fields, journal records |
| Tests | Create / Modify | See Testing Approach |

### Contracts

Make these after the T76–T87 amendments and before the tests:

- **`modules/arkeology.store_migration.md`** (new, via `writing-contracts`): `main` and its exit
  codes (0 clean, 1 any cannot-migrate, failed, conflict or remaining entry, 2 a configuration or
  prerequisite failure); the report's fields; the journal record shapes; the invariants of no
  Bedrock client, no dry-run write, and at most one artifact between re-PUT and restore.
- **`data/s3.artifact.md`** `## Compatibility Guarantees`: a pre-Phase-15 object reaches this shape
  only through `arkeology-migrate-store`. Its re-PUT keeps the content bytes and `last_edited_ulid`
  (add it to the `last_edited_ulid` row's list of writers that never add one). Name
  `process:arkeology-store-migration` as the reconstructed-provenance actor.
- **`data/s3-annotations.artifact.md`**: the legacy `references` read and its not-found semantics.
  A migrated object's `revision_history` starts with its `generated` entry. The migration restores
  from its journal, not from a failure-log entry.
- **`data/s3vectors.artifact.md`** `## Compatibility Guarantees`: the migration re-puts vectors with
  their stored embedding. The startup check 9 filter depends on `archived` existing on every
  migrated vector.

### Testing Approach

TDD: each test file below is written and confirmed failing before the implementation it gates. The
pre-Phase-15 fixture shape is taken from the `## Storage Shape` tables of `s3.artifact`,
`s3vectors.artifact` and `s3-annotations.artifact` at commit 2b99648, before T76 amends them. A
seeding helper in the test file writes it directly through the moto clients.

1. `tests/unit/test_annotations.py` → `annotations.py`. Legacy `references` read: absent gives
   `[]`; `ObjectNotFoundError`, a bare `KeyError` and `CredentialError` propagate.
2. `tests/unit/test_startup.py` → `startup.py` (Story 6):
   - a store with one own-scope vector lacking `archived` fails check 9, and the message names its
     `artifact_id` and `arkeology-migrate-store`;
   - an empty store, a migrated store, and a legacy vector under a `READ_PREFIXES` entry all pass;
   - `bedrock.embed` is called once only (check 6), so check 9 adds no embedding;
   - the prerequisites function runs checks 1, 2, 4 and 8 and never check 9.
   Update the "all checks pass" and count assertions for nine checks.
3. `tests/unit/test_store_migration.py` → `store_migration.py`, `pyproject.toml`:
   - Dry run (Story 1): the report lists every change; a snapshot of S3 objects, metadata,
     annotations and vectors is identical before and after; the moto clients' write methods are
     never called.
   - AC-79 (Story 2): seed tier-2 and tier-3 artifacts covering all 16 legacy types, archived and
     active, `author_role` both actor and role name, `source_artifacts`, `references` and
     `commit_refs`, plus a synthesis. Run `--apply` with `BedrockClientImpl` patched to raise on
     construction. Then:
     - no legacy key in either store or among annotation names;
     - embeddings and content are byte-identical;
     - `read_artifact`, `list_artifacts` and `search_artifacts` return every artifact with
       `archived`, display-name `type`, `generated`, `sources` and `relationships`;
     - a second dry run reports `nothing_to_change: true`.
   - Field rules: one test per provenance branch (U on day D; U later; U absent; U before D); the
     `by` rule's four cases; the history seed; `links` order and merge into an existing `links`; a
     legacy object-metadata `commit_refs` merged and the vector copy capped; a lifecycle `status`
     kept and none added (AC-69).
   - AC-04 (Story 3): after migration, `create_artifact` with the same type and title and a
     `generated.at` on day D returns `validation_error`.
   - Freshness (Story 4): pre-migration ULID verdicts for A and B equal post-migration T86
     verdicts; A's `last_modified` equals A's effective time, and B's equals S's.
   - Cannot migrate: a bad `status`, a bad `date`, an invalid entry, a corrupt `links` and a budget
     breach are each reported with nothing written, and the exit code is 1.
   - Crash and resume (Story 5): make `put_object_annotation` raise once, after the re-PUT. The run
     stops and the journal ends on `start`. A second `--apply` restores the annotations and the
     final state equals an uninterrupted run. A crash before the re-PUT is redone by the scan, and
     a crash in the vector step is completed. A failing journal append stops the run before any
     write.
   - Conflict: an ETag change between the read and the re-PUT is retried, then reported as
     `conflict`.
   - Late write (Story 7): a legacy artifact seeded after the scan, through a hook on the first
     re-PUT, is listed under `remaining` with exit code 1, and a second `--apply` migrates it.
   - Own scope only: a legacy artifact under another prefix in the same bucket and index is neither
     reported nor touched; a journal record for another prefix is ignored on resume.
   - Dangling: a legacy vector with no object is listed by the dry run and deleted by `--apply`.
   - Verification (D50): a vector left without a boolean `archived` makes the exit code 1 and is
     listed.
   - Skill drift: every flag in `migrating-arkeology-store/SKILL.md` is accepted by the parser.
4. Integration (real AWS, run-scoped prefix), new:
   - `tests/integration/test_store_migration.py` — one seeded legacy artifact with `commit_refs` and
     `references` survives `--apply` with annotations restored after a real re-PUT. This proves the
     real wipe-and-restore, which the moto extension only models.
   - `tests/integration/clients/test_vectors_filter_semantics.py` — the check 9 filter matches a
     vector without `archived` and not one with it, on real S3 Vectors.

**Integration tests broken by this change:** none. The suite does not call `validate_startup`, and
its fixtures write the new shape. One quality gate is affected: `uv run arkeology` refuses to start
on an operator's `.env` store until that store is migrated. Migrate the development store with this
command before running the gate.

**Mutation.** `annotations.py` is in `only_mutate`. After the unit suite is green, run
`uv run mutmut run` alone and triage survivors as AGENTS.md describes.

### Hand-offs

T91 hand-offs: AGENTS.md Repository Structure rows for `store_migration.py` and the new skill; the
startup line ("nine checks"); the stdout rule scoped to the MCP server process; and the CHANGELOG
**Breaking** entry giving the upgrade order from Requirements, "Delivery".

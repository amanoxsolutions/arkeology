---
type: Spec
id: p15-t90-store-migration
title: T90 — Store Migration Skill and Command
description: Adds an operator-run console command, arkeology-migrate-store, run outside the MCP server with servers stopped, and a migrating-arkeology-store skill that bring an existing deployment's own scope (never another team's prefix) from the pre-Phase-15 shape to the OKF v0.2 shape — archived, display-name types, generated/revised provenance, the links annotation, a seeded revision history — in S3 object metadata, annotations and vector metadata, and re-keys every own-scope vector to its numbered key (T92) by copy, without re-embedding. A dry run reports every change and prints a bucket-policy write fence; changes happen only on --apply after the operator confirms and the command has proved the fence applied, so an install still on an earlier release, whose object writes carry no store-schema tag, can neither overwrite a migrated artifact nor start; every object write by this release carries that tag; a local journal written before each re-PUT makes a crash between the re-PUT and the annotation restore recoverable; a second run reports nothing to change. Adds a ninth startup check (FR-07) that refuses to start while the own scope is unmigrated.
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
  - id: vision
    resource: docs/planning-artifacts/vision.md
    title: "Arkeology — Persistent Artifact Memory"
    last_modified: 2026-11-09T09:27:45Z
  - id: aws-s3-tagging-policies
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/tagging-and-policies.html
    title: Amazon S3 — Tagging and access control policies
  - id: aws-s3-putobject
    resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html
    title: Amazon S3 API Reference — PutObject
  - id: aws-iam-condition-operators
    resource: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html
    title: IAM JSON policy elements — Condition operators
  - id: architecture-review-2026-11-10
    resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
  - id: adr-aws-backend
    resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T14:38:17Z
  - id: spec-t5
    resource: docs/specs/p1-t5-startup-validation-sequence.md
    title: T5 — Startup Validation Sequence
    last_modified: 2026-11-10T16:40:30Z
  - id: aws-s3vectors-index-mode
    resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-index-mode.html
    title: Amazon S3 User Guide — Changing a vector index's mode
  - id: spec-t31a
    resource: docs/specs/p9-t31a-setting-up-arkeology-skill.md
    title: T31a — Setting-Up-Arkeology Skill
    last_modified: 2026-11-12T10:00:13Z
  - id: architecture-review-2026-11-10-recheck
    resource: .docs/reviews/architecture-review-2026-11-10-arkeology-recheck.md
    title: "Architecture review — Arkeology (whole design record), re-check of C-1 to C-3"
    last_modified: 2026-11-10T16:49:29Z
  - id: spec-t15
    resource: docs/specs/p3-t15-partial-write-failure-log.md
    title: T15 — Partial Write Failure Log
    last_modified: 2026-11-12T10:00:13Z
  - id: spec-t92
    resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T14:38:17Z
  - id: calibration-2026-11-12
    resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-05-29-aws-backend-selection
    type: constrained_by
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
  - to: p15-t92-numbered-vector-keys
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T21:13:59Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T21:15:39Z
---

# T90 — Store Migration Skill and Command

## TL;DR

An operator who upgrades a deployment that already holds artifacts runs one command,
`arkeology-migrate-store`, guided by a new `migrating-arkeology-store` skill. A dry run reports
every change and prints a write fence: a bucket-policy statement refusing any object write without
the store-schema tag this release puts on every write, so an install still on an earlier release
can neither overwrite a migrated artifact nor start. Nothing changes until the operator confirms,
the Admin has applied the fence, and `--apply` has proved it; the command then rewrites the own
scope's object metadata, annotations and vector metadata to the Phase 15 shape, moves every
vector to its numbered key (T92), never re-embeds, survives a crash at any point, and a second run reports nothing to change (FR-74, NFR-16, AC-79;
D42).

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

A rewrite the migration completes can still be undone by a write it never sees. Every agent starts
its own server from the copy installed on its machine or pipeline runner, and the target is dozens
of teams of dozens of engineers (`vision.md` § Operating Context), so an install that misses the
upgrade is to be expected. Its code cannot be changed after the fact. When it overwrites or
archives a migrated artifact, it re-PUTs the object, S3 wipes all of the object's annotations, and
it restores only `commit_refs` and `references`: `links`, `revision_history` and `verified` are lost
with no second copy, and its vector lacks `archived`, so every upgraded server of that team fails
check 9. The protection must therefore sit in the store, which every release writes through.

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

### R3 — The `migrating-arkeology-store` skill walks the operator through eight steps and never passes `--apply` before the operator's confirmation

The system provides a skill, `migrating-arkeology-store`, that walks an Admin / DevOps through this
sequence:

1. On the old version, run `reconcile_index` until its count of failure-log entries under this
   write prefix is zero (T15 R12; T84 Open Questions item 3);
2. stop every server that writes this write prefix, on every team member's MCP client and every
   pipeline runner, whatever its version;
3. install the new version;
4. run the dry run with the same configuration values as the MCP client entry, with
   `EMBED_MAX_SECTIONS` at most 100 — this release refuses a higher value — show the report, and
   wait for the operator's explicit confirmation in the conversation. When the report lists an
   artifact it cannot migrate because the artifact holds more than 100 vectors, the way out comes
   before step 5, whose write fence refuses the earlier release's writes: start one server of the
   earlier release for this alone, rewrite the artifact with `EMBED_MAX_SECTIONS` at most 100, so it
   is re-indexed within 100 vectors, or delete it; stop that server again, so that every server is
   stopped as step 2 requires (R6), then run the dry run again;
5. show the report's write-fence statement (R39), have the Admin add it to the bucket policy, and
   wait for the operator to say it is applied;
6. run `--apply`, and run it again after any interruption or any `remaining` entry;
7. confirm that a final dry run reports nothing to change;
8. start the servers.

The skill never passes `--apply` before that confirmation. Started before step 7, an upgraded
server refuses to start with an error naming this command (check 9 below), which is the intended
signal to run it. When it asks for the servers to be stopped, the skill also states what the fence
does not refuse (R9) and how an install that was missed shows itself afterwards (R40).

Step 1 empties the failure log of the server that runs it. The earlier release keeps one log per
working directory, so another engineer's log can still hold an orphan-cleanup entry naming
heading-slug keys. Appended to this release's log after the upgrade (T15 R10), such an entry finds
its keys gone and resolves with nothing deleted (T92 R8): the migration re-keyed every vector of the
artifact, the stale ones the entry names included, and those stay searchable, at numbered keys,
until the artifact's next update or re-index removes them.

**Why (Confirmation is a flag plus the skill's rule):** The default run is the dry run, and only
`--apply` writes. An interactive prompt would hang an agent-driven run. A token passed between the
dry run and `--apply` proves nothing about a human, because an agent can copy it. What FR-74 needs
is that the operator decides, and the skill states that rule.

**Why (The way out for an artifact over 100 vectors):** the migration refuses such an artifact and
writes nothing for it (R24), so its earlier vectors would keep check 9 refusing to start; once the
fence is applied, the earlier release — the only one that could rewrite or delete it through a
tool — cannot write the prefix either. The fix therefore happens before the fence.

Source: FR-74; D42; the refusal of an artifact over 100 vectors (Operator, 2026-11-12); stale vectors re-keyed, not deleted (Operator, 2026-11-12)

### R4 — `reconcile_index` does not change in this task

`reconcile_index` does not change in this task.

Source: FR-74; D42

### R43 — Before the servers start, the skill has the vector index switched to `ENHANCED` when it is not

Before step 8 of R3 (start the servers), the `migrating-arkeology-store` skill reads the vector
index's mode with `aws s3vectors get-index --vector-bucket-name <bucket> --index-name <index>`. When
the mode is not `ENHANCED`, the skill shows the Admin
`aws s3vectors update-index-mode --vector-bucket-name <bucket> --index-name <index> --index-mode ENHANCED`
and states three things: the switch takes effect in place, with no re-ingestion and no additional
charge; the index is shared, so every team's servers on it change with it; and it must not be
switched back while any server uses it. The switch is part of this release's breaking upgrade, made
in the same window as the rest of it, while the servers are stopped and upgraded (steps 2 to 8).
The skill then waits for the operator to say the switch is done, and reads the mode again before step 8.
`arkeology-migrate-store` itself neither reads nor changes the index mode.

**Why (An upgraded server refuses a `CLASSIC` index):** A server of this release refuses to start on
an index that is not `ENHANCED` (`p1-t5-startup-validation-sequence.md` R12), and an index in a vector
bucket created before 30 September 2026 is `CLASSIC` — the case for a store old enough to need this
migration. The upgrade is the one moment the Admin is already changing the deployment, so the switch
belongs here rather than in a refused start. The command does not need the mode: it enumerates the
own scope rather than looking artifacts up by id.

**Example**

- Given a vector index whose mode is `CLASSIC`, when the skill reaches step 8, then it has shown the
  `update-index-mode` command and starts no server until a fresh read reports `ENHANCED`.
- Given an index already `ENHANCED`, when the skill reaches step 8, then it reports the mode and
  continues.

Source: adr-2026-05-29-aws-backend-selection; NFR-03; the release coupling (Operator, 2026-11-10)

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
rewrite another team's artifacts while that team's old servers may still run: unfenced, an old
server's overwrite of a migrated artifact drops the `links` and `revision_history` annotations it
does not know about, and fenced, every such server is locked out of its own prefix before its team
has upgraded (see "Writes during a run"). Own-scope migration has no cross-team write race at all.
What it leaves is visibility across scopes during a staggered rollout, which the operators
coordinate as below.

Source: FR-74, FR-05, FR-07, FR-10, FR-68, FR-75

### R6 — What the operators of a shared store coordinate: required, recommended, and the staggered rollout

What the operators of a shared store coordinate:

- **Required, for data safety:** the write-fence statement covers a prefix before that prefix
  migrates and stays in place afterwards (R39), and every server writing the prefix is stopped
  while it migrates, because the fence refuses object writes only (R9). Servers of other prefixes
  may keep running; nothing they do writes this prefix, and the fence on this prefix does not touch
  theirs.
- **Recommended:** one window in which every team sharing the bucket and index stops, installs
  the new version, migrates its own prefix, and starts. Where teams migrate apart, a team whose
  syntheses cite another team's shared artifacts migrates in the same window as that team, or after
  it: a synthesis migrated first keeps such a source without a baseline (R20, T92 R10).
- **Staggered rollout:** an upgraded server starts once its own scope is migrated, whatever its
  `READ_PREFIXES` hold (check 9 probes the own scope only). Another team's unmigrated artifacts
  follow the malformed-data policy for foreign data: they are skipped and counted under
  `skipped_malformed_count` in listings, and `read_artifact` returns `corrupt_metadata` for them
  (T76 Open Questions item 3). A team still on the old version does not see migrated teams'
  artifacts correctly until it upgrades. Old code reads the archive marker from `status`, and
  this release cannot change old code. An install of the old version configured with a migrated
  prefix cannot start (R40).

Source: FR-74, FR-05, FR-07, FR-10, FR-68, FR-75, NFR-16

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

### R9 — The skill states what the write fence does not refuse when it asks for the servers to be stopped

The write fence (R39) refuses any object write without this release's tag, so an old server cannot
overwrite, archive or create an artifact under a fenced prefix, and the overwrite that wipes an
object's annotations never lands. It refuses nothing else. An old server that was already running
when the statement was applied keeps its annotation, vector and delete writes until it is stopped,
and these are why step 2 of the sequence stays required:

- an annotation-only write, such as an old server's `link_metadata`, landing between the command's
  read and its restore is overwritten (S3 offers no annotation-level precondition);
- an annotation or vector write after the migration, `link_metadata`'s for one, leaves legacy-shaped
  annotations or vector metadata, and an old server's re-index writes vectors under heading-slug
  keys, which no by-key path of this release reads. The next run migrates them again (R12, R13,
  R44); until it does, a vector left without `archived` makes every upgraded server of that team
  fail check 9.

The skill states both consequences when it asks for the servers to be stopped.

Source: FR-74, NFR-16, C-06, C-07

### R38 — Every object write this release makes carries the store-schema tag `arkeology-store-schema` = `2`

⚠️ Hard to reverse: the key and value are written into every object of every store and into every
applied fence statement; changing either means another store migration and a policy change at
every deployment.

Every S3 object write the system makes sends the object tag `arkeology-store-schema` with the value
`2`: an artifact's create and update, its archive and lifecycle change, `migrate_artifacts`, this
command's re-PUT (R27), and the startup and health probe writes. The fence probe of R26 is the one
write made without it. Every object write goes through the S3 client's one put path, and the system
makes no `CopyObject` call. Outside the server, the setting-up skill's Step 2 annotation probe sends
the same tag on its object write (T31a R29). No read path reads the tag, and it counts against no
metadata budget: it exists for the fence.

**Why (A store-shape generation, not the OKF version):** The value names the shape of the store,
which is what the fence protects. A pre-Phase-15 object is generation 1 and carries no tag. A later
breaking store change repeats the fence with `3`, whether or not it comes with a new OKF version.

Example:

- Given any tool or probe of this release writing an object under the write prefix, plain,
  conditional on `If-None-Match` or conditional on `If-Match`, when the object's tags are read back,
  then they are exactly `arkeology-store-schema=2`.

Source: NFR-16, FR-74; adr-2026-09-25-okf-v02-adoption § 9; https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html

### R39 — The dry-run report carries the write-fence statement for the configured bucket and write prefix, and the Admin keeps it applied

The dry-run report carries `write_fence`: a bucket-policy statement, built from the configured
bucket and write prefix, that denies `s3:PutObject` on the prefix to every principal unless the
request carries the R38 tag:

```json
{
  "Sid": "ArkeologyStoreSchemaFence",
  "Effect": "Deny",
  "Principal": "*",
  "Action": "s3:PutObject",
  "Resource": ["arn:aws:s3:::<bucket>/<write prefix>/*"],
  "Condition": {"StringNotEquals": {"s3:RequestObjectTag/arkeology-store-schema": "2"}}
}
```

The Admin adds it to the bucket policy before `--apply` and keeps it there after the migration.
Where the bucket policy already holds a statement with this `Sid`, the Admin adds this prefix's
resource to that statement's `Resource` list rather than adding a second statement, so one
statement fences every migrated prefix of the bucket. A deployment set up on this release gets the
same statement, built from its configured bucket and write prefix, from the setting-up skill before
its first write (T31a R30). The system never reads, writes or applies a bucket policy.

`StringNotEquals` is true when the request carries no such tag, so the statement refuses an
untagged write as well as one tagged with another value. S3 cannot condition an overwrite on the
tags of the object already stored — `s3:ExistingObjectTag` is not supported for `PutObject` — so
the fence tests what the writer sends. The dry run still makes no write call (R10): it prints the
statement and cannot prove it applied; `--apply` proves it (R26).

**Why (The command prints the statement; the skill does not compose it):** The command already
holds the configured bucket and prefix, so the statement cannot name another prefix than the one it
migrates. Arkeology never provisions AWS resources, so the Admin applies it.

Source: NFR-16, FR-74; adr-2026-09-25-okf-v02-adoption § 9; https://docs.aws.amazon.com/AmazonS3/latest/userguide/tagging-and-policies.html; https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html; a deployment set up on this release is fenced too (Operator, 2026-11-12)

### R40 — An install of the old version cannot write to or start against a fenced prefix, and the skill says how that shows

Once the fence covers a prefix, every object write an earlier release makes to it is refused with
access denied before it changes anything. v0.7.1's startup write probe (check 2) writes under the
write prefix, so an install of it configured with a migrated prefix exits before serving requests.
v0.7.1 reports S3's access denied as a credential error, so it exits with `Startup failed —
credential error: AWS credentials are invalid or expired. Re-authenticate (e.g. aws sso login) and
restart the server.`, and an old server already running when the statement was applied returns
`credential_error` from every tool call that writes an object. The skill tells operators that this
message, from an install configured with a migrated prefix whose credentials work, means that
install must be upgraded, and that re-authenticating does not clear it.

Example (an install that missed the upgrade fails closed):

- Given a migrated prefix covered by the fence and an install of v0.7.1 configured with it, when
  that install's server starts, then it exits at its write-prefix check with the message above,
  and no object, annotation or vector under the prefix has changed.

Source: NFR-16, FR-07; adr-2026-09-25-okf-v02-adoption § 9

### R41 — This release's write-prefix check names `s3:PutObjectTagging` when its tagged probe write is refused

When the startup write probe of check 2 is refused with access denied, the system fails check
`write_prefix` instead of reporting a credential error. The message names `s3:PutObject` and
`s3:PutObjectTagging` on the write prefix — S3 requires both to write an object with a tag — and
states that a write fence requiring a newer store schema refuses the write as well. The server exits
before serving requests. Credentials that check 1 rejects still fail as a credential error.

Example:

- Given credentials that pass check 1 and a role without `s3:PutObjectTagging`, when the server
  starts, then it exits at check `write_prefix`, and the message names `s3:PutObjectTagging`.

Source: FR-07, NFR-03, NFR-16; https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html

## 5. Rules — Dry run

### R10 — Without `--apply`, no write call and no Bedrock call is made; the report lists every change, every artifact that cannot migrate, and every dangling legacy vector

When the command runs without `--apply`, the system makes no write call to S3 or S3 Vectors, and no
Bedrock call. It reports: each artifact to migrate with its changes, each vector's move from its
current key to its numbered key (R44) among them; each artifact it cannot
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
`status` is `active` or `inactive`, OR its `type` is a legacy value, OR its key is not
`{artifact_id}#{n}` with `n` a whole number from 0 to 99 written without padding (T92 R1).

Source: AC-79; D21, D29, D35, D37; T92 R1

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
tier-3 `shared` source uses the same derivation applied to its vector metadata, read from its `#0`
by key (T92 R9) through the existing cross-scope gate in `_scope.py`. Parsed datetimes are
compared, never strings. A source that is missing, unreadable, or has no derivable time gets no
`last_modified` — as does a foreign source whose team has not yet migrated its store, since it has
no `#0` (T92 R10).

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
migrated S3 object metadata; every other key is kept. This target metadata is written only on the
vector at its numbered key (R44), never at an earlier key, so a vector not yet re-keyed keeps its
legacy metadata, and check 9 still finds an interrupted migration.

Source: T92 R1

### R23 — `source_artifacts` and `author_role` stay declared non-filterable slots, now unwritten

`source_artifacts` and `author_role` stay declared non-filterable slots, now unwritten (C-01).

Source: C-01

## 8. Rules — Cannot migrate — reported, never guessed

### R24 — An artifact that cannot be migrated is reported with the reason, nothing is written for it, and the run continues

When an artifact has no usable archive marker, no valid ISO `date` while lacking `generated_at`, an
entry that fails T84's validation, an unreadable `links` or `revision_history`, migrated metadata
over a `check_metadata_budgets` budget, content the S3 client cannot return, or more vectors still
needing a numbered key than the 100 numbered keys hold (T92 R2), the system reports it with the
reason and writes nothing for it. The run continues with the next artifact. The vectors still
needing a numbered key are counted after R45 has set aside those an interrupted run already copied,
so an interrupted re-key is never counted twice. More than 100 is possible only where
`EMBED_MAX_SECTIONS` was set above 100; the skill gives the way out before the write fence (R3).

Source: malformed-data ADR; D50 case 1; the refusal of an artifact over 100 vectors (Operator, 2026-11-12)

### R25 — An annotation read treats only `NoSuchAnnotation` as empty; every other failure fails the artifact

Any annotation read treats only `NoSuchAnnotation` as empty. Every other failure fails the artifact
(`s3-annotations.artifact` `## Not-Found Semantics`).

Source: malformed-data ADR; D50 case 1

## 9. Rules — Apply — order of operations and the journal

### R26 — `--apply` first runs startup checks 1, 2, 4 and 8 and proves the write fence, stops before any change if one fails, and runs no Bedrock check and constructs no Bedrock client

When `--apply` is given, the system first runs startup checks 1, 2, 4 and 8 (credentials, write
prefix, vector index, annotations), then proves the write fence (R39), and stops before any change
if one fails. It runs no Bedrock check and constructs no Bedrock client.

To prove the fence, it writes one probe object under the write prefix without the R38 tag:

- refused with access denied: the fence is in place, and the run continues. Check 2 has just
  written a tagged probe to the same prefix, so this refusal can come only from a statement that
  tests the tag;
- accepted: the fence is absent. The system deletes the probe (a failed delete is logged with the
  probe's key), reports that the write fence is not applied, names the statement to apply, and
  exits with the prerequisite-failure code, having changed nothing else;
- any other failure: the fence is not proved, and the run stops the same way.

Example (the fence is proved, not trusted):

- Given a write prefix that no write-fence statement covers, when the operator runs `--apply`,
  then the command writes nothing to the store but its own probe, deletes that probe, exits
  non-zero, and its message names the statement to apply.

Source: FR-74, NFR-16, C-07

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
5. re-keys every vector of the artifact to its numbered key, with its stored embedding and the
   target vector metadata (R44);
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

### R29 — An already-migrated object with unmigrated vectors gets only those vectors re-keyed, with no journal record

When an artifact's object is already migrated but some of its vectors are not, the system re-keys
those vectors only (R44). No journal record is needed, because nothing is wiped.

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

- object migrated: apply steps 4 and 6 from the journal record — restore the annotations and record
  `done`. Its vectors are left to the scan, which gives their keys and re-keys them as R29 does for
  any migrated object with unmigrated vectors;
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
reports every vector without a native boolean `archived` or not at a numbered key (T92 R1), and
every artifact still needing a change. It exits non-zero when either list, the cannot-migrate list or the failed list is
non-empty.

Source: FR-74, C-07; D50 case 3

### R44 — Every own-scope vector is re-keyed to its numbered key by copy, with its embedding unchanged and no embedding call

WHEN an artifact's vectors need migration (R13) THE SYSTEM SHALL read every vector of the artifact,
at the keys the scan found (R46), with data and metadata by `GetVectors`, and then:

1. assign each vector still needing migration a numbered key, in ascending order of its current key:
   the lowest `n` from 0 to 99 that no other vector of the artifact holds and no earlier vector in
   this order was assigned. The first vector, the bare-`artifact_id` document vector included,
   therefore takes `#0`. A vector whose current key already has that form — a section headed with
   a number — is assigned like any other, and keeps its key only when it is assigned its own
   number;
2. put every such vector at its numbered key with its stored embedding and the target vector
   metadata (R22), in one `PutVectors` call;
3. delete, in one `DeleteVectors` call, every earlier key it moved away from.

No embedding call is made, and no earlier key is deleted before its copy is put. When no free `n`
remains, the artifact cannot be migrated (R24).

**Why (Copy, then delete):** a crash at any point leaves every vector either at its earlier key,
at its numbered key, or at both — never at neither. Taking only free numbers means a put never lands
on a vector not yet copied. The numbering carries no meaning: nothing reads a section from its key,
and the artifact's next update or re-index renumbers in document order (T92 R1).

**Example**

- Given an artifact whose vectors sit at `{id}#summary` and `{id}#details`, when `--apply` re-keys
  it, then `#details` moves to `#0` and `#summary` to `#1`, both heading-slug keys are deleted, and
  both embeddings are byte-identical.
- Given an artifact whose one vector sits at the bare `{id}`, when it is re-keyed, then it sits at
  `{id}#0` with the new metadata, and `{id}` is gone.

Source: FR-74, AC-79; T92 R1, R2; the numbered-key ruling (Operator, 2026-11-12)

### R45 — A re-key resumed after an interruption only deletes an earlier key whose copy already exists

WHEN an artifact being re-keyed already holds a vector in the migrated shape whose embedding equals
that of a vector still needing migration THE SYSTEM SHALL treat the latter as already copied: it
deletes that earlier key and puts no second copy. Every other vector is re-keyed by R44. No journal
record is needed: nothing is deleted before its copy exists, so the store itself records how far
the re-key got.

**Why (Embedding equality identifies the copy):** a copy carries its original's embedding
unchanged, and re-numbering from scratch after an interruption would put a second copy at another
number. Two distinct sections can share an embedding only when their embedding texts are
identical, so dropping one of them changes no search result.

**Example**

- Given an `--apply` run killed after an artifact's `PutVectors` and before its `DeleteVectors`,
  when `--apply` runs again, then each earlier key is deleted, no numbered key is written twice, and
  the artifact ends as an uninterrupted run leaves it.

Source: FR-74, C-07; the numbered-key ruling (Operator, 2026-11-12)

### R46 — One own-scope sweep plans the whole run; per-artifact work reads by key

THE SYSTEM SHALL plan the dry run, and `--apply`, from one sweep of the own scope's vectors with
metadata — the existing own-scope enumeration — which gives every own-scope vector's key and
metadata. Each artifact's work then reads by key (R44, T92 R4). The verification of R33 makes one
more sweep. No per-artifact scan and no filtered query is made to find an artifact's vectors.

**Why:** a filtered query does not return every vector of an artifact above 10 vectors (calibration
of 2026-11-12), and a scan per artifact would page the whole shared index once per artifact.

Source: FR-74; T92 R11; calibration of 2026-11-12

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
query costs one request. On an `ENHANCED` index, S3 Vectors pre-filters, so a query whose filter
matches returns at least one match: every `ENHANCED` lookup with matches did in the calibration of
2026-11-12, though above 10 matches not all of them, and the check needs only one.
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

### R42 — Check 9's empty result is trusted only because check 5 has already required an `ENHANCED` index

Check 9 runs after check 5, which refuses a vector index whose mode is not `ENHANCED`
(`p1-t5-startup-validation-sequence.md` R12). Check 9 relies on that and does not read the mode
itself. Check 9 stays as specified only while check 5 keeps that requirement; removing it means
redesigning check 9.

**Why (Top-1 is only a proof on an `ENHANCED` index):** On a `CLASSIC` index, S3 Vectors searches and
filters in tandem, and a filtered query may return fewer results than requested when few vectors
match — so an own scope in which only a handful of vectors are still in the pre-upgrade shape could
return nothing, and an upgraded server would start on a partly unmigrated store. On an `ENHANCED`
index the filter is evaluated before the search, so a query whose filter matches returns at least
one matching vector — not necessarily all of them above 10 matches (calibration of 2026-11-12) —
and check 9 needs only one.

**Example**

- Given a `CLASSIC` index and an own scope with three pre-upgrade vectors among 50,000, when the
  server starts, then it stops at check 5 with the index-mode message, and check 9 never runs.

Source: FR-07; adr-2026-05-29-aws-backend-selection; D50; calibration of 2026-11-12

## 11. Boundaries

**Always:**
- Write a flushed journal `start` record before every re-PUT, and re-PUT the content bytes read,
  conditional on their ETag.
- Treat only `NoSuchAnnotation` as empty. Report an artifact rather than infer a value for it.
- Compare timestamps as parsed datetimes. Gate every foreign source lookup through `_scope.py`.
  Use `startswith(scope + "/")` for every scope test.
- Log to stderr. Delegate to the shared encoders, validators and tables named above.
- Send the R38 tag on every object write but the fence probe, and prove the fence before any
  change (R26).
- Re-key by copy: put every numbered copy of an artifact's vectors before deleting any earlier key,
  and write the target vector metadata only at numbered keys (R22, R44).

**Ask First:**
- Changing the provenance derivation, the `by` rule, the baseline rule or the relationship type.
  Each one is persisted in every migrated artifact.
- Adding concurrency to the run.
- Changing the tag key or value, or adding an object write that bypasses the S3 client's put path
  — a copy, a multipart or presigned upload. The key and value are in every object and every
  applied fence statement, and a bypassing write would be refused by the fence.

**Never:**
- Call Bedrock, construct a Bedrock client, call an MCP tool, or change an embedding or the content
  bytes.
- Write under any prefix other than the configured write prefix.
- Add migration code to `reconcile_index`, or translate a legacy key anywhere in the server (D42).
- Write when the run is a dry run, or pass `--apply` in the skill without the operator's
  confirmation.
- Read, write or apply a bucket policy — the Admin applies the R39 statement — or go on with
  `--apply` after the untagged fence probe landed.
- Set a lifecycle `status`, append to the server's failure log, or touch an artifact that is already
  migrated.
- Edit README, SERVER-REFERENCE, CHANGELOG or AGENTS.md (T91).

AC-80 does not apply: T90 removes no name.

## 12. For the developer agent

### Files to Touch

| File | Action | Notes |
|---|---|---|
| `src/arkeology/store_migration.py` | Create | `main()`: argument parsing (`--apply`, `--journal`), logging as `__main__.configure_logging`, settings via `load_settings`, S3 and S3 Vectors clients only. Scan (one own-scope sweep, R46), plan, report, resume, apply, verify. The vector re-key and its resume (R44, R45), reading by key through T92's key helper. Constants: the actor `process:arkeology-store-migration`, the relationship type `references`, the default journal path. The `write_fence` report field (R39) and the fence probe after the prerequisite checks (R26) |
| `pyproject.toml` | Modify | `[project.scripts]`: `arkeology-migrate-store = "arkeology.store_migration:main"` |
| `src/arkeology/clients/s3.py` | Modify | `S3ClientImpl.put_object` sends the R38 tag (`Tagging`) on every call — plain, `if_none_match` and `if_match` — with one keyword that omits it, used only by the fence probe. Every object write (create, update, archive, lifecycle change, `migrate_artifacts`, the re-PUT, the startup and health probes) already goes through this method, so none of their call sites changes. `S3ClientInterface.put_object` in `clients/interfaces.py` gains the same keyword |
| `src/arkeology/constants.py` | Modify | The tag key `arkeology-store-schema`, its value `2`, and the statement `Sid` `ArkeologyStoreSchemaFence`, imported by `clients/s3.py` and `store_migration.py` |
| `src/arkeology/startup.py` | Modify | Add check 9 (`_check_store_shape`), taking check 4's index info. Add one public function that runs checks 1, 2, 4 and 8 only, for the command. Module docstring and log lines: nine checks. In `_check_write_prefix`, map a refused probe write to check `write_prefix` naming `s3:PutObject` and `s3:PutObjectTagging` (R41): `wrap_credential_errors` raises S3's `AccessDenied` as a `CredentialError`, so the check tells that case apart by the original error code and still re-raises every other credential error |
| `plugins/arkeology/skills/setting-up-arkeology/SKILL.md` | Modify | Names `s3:PutObjectTagging` on the write prefix as a required IAM action beside the core S3 ones; without it a new deployment fails check 2 (R41). Step 2's annotation probe sends the R38 tag on its object write — `--tagging 'arkeology-store-schema=2'` on the aws-cli path, `Tagging` on the boto3 path — or a fenced prefix refuses it and setup stops at Step 2 (T31a R29, which also adds the drift test holding both to `constants.py`). For a new deployment, Step 2 first gives the Admin the R39 statement for the configured bucket and write prefix and waits until it is applied (T31a R30) |
| `src/arkeology/annotations.py` | Modify | A public read of the legacy `references` annotation, through the same single-annotation read `commit_refs` uses (absent gives `[]`, everything else raises). It is the durable link-field invariant, so it stays in the mutation scope. *Uncertain:* after T84 the shared reader's name may differ, so reuse whatever reads `commit_refs` |
| `plugins/arkeology/skills/migrating-arkeology-store/SKILL.md` | Create | The skill as specified in Requirements, "Delivery": the eight steps (R3), the fence statement it shows and the merge into an existing `Sid` (R39), what the fence does not refuse (R9), the message that marks an install still on the old version (R40), and the index-mode read and switch before the servers start (R43). Its description sends documentation imports to `migrating-to-arkeology` |
| `plugins/arkeology/.claude-plugin/plugin.json` | Modify | The description names store migration |
| `.gitignore` | Modify | `.arkeology_store_migration.jsonl` |
| `docs/contracts/modules/arkeology.store_migration.md` | Create | Contract step, before tests: command, flags, exit codes, report fields, journal records |
| Tests | Create / Modify | See Testing Approach |

### Contracts

Make these after the T76–T87 amendments and before the tests:

- **`modules/arkeology.store_migration.md`** (new, via `writing-contracts`): `main` and its exit
  codes (0 clean, 1 any cannot-migrate, failed, conflict or remaining entry, 2 a configuration or
  prerequisite failure, the write fence not proved included); the report's fields, `write_fence`
  among them; the journal record shapes; the invariants of no Bedrock client, no dry-run write, no
  change before the fence is proved, and at most one artifact between re-PUT and restore.
- **`data/s3.artifact.md`** `## Compatibility Guarantees`: a pre-Phase-15 object reaches this shape
  only through `arkeology-migrate-store`. Its re-PUT keeps the content bytes and `last_edited_ulid`
  (add it to the `last_edited_ulid` row's list of writers that never add one). Name
  `process:arkeology-store-migration` as the reconstructed-provenance actor.
- **`data/s3.artifact.md`** `## Storage Shape`, in the same change: every object written in this
  shape carries the object tag `arkeology-store-schema` = `2` (R38), outside the user metadata and
  its budget, and no reader depends on it; an object without it was written by an earlier release
  or by a writer outside Arkeology. `## Compatibility Guarantees`: the key and value never change
  for this shape — a later breaking store change takes the next value — and the bucket-policy
  write fence (R39) relies on every object write carrying the tag.
- **`data/s3-annotations.artifact.md`**: the legacy `references` read and its not-found semantics.
  A migrated object's `revision_history` starts with its `generated` entry. The migration restores
  from its journal, not from a failure-log entry.
- **`data/s3vectors.artifact.md`** `## Compatibility Guarantees`: the migration re-keys every vector
  of the earlier release to its numbered key by copy, with its stored embedding; a vector at an
  earlier key never carries the migrated metadata. The startup check 9 filter depends on `archived`
  existing on every migrated vector.

### Testing Approach

TDD: each test file below is written and confirmed failing before the implementation it gates. The
pre-Phase-15 fixture shape is taken from the `## Storage Shape` tables of `s3.artifact`,
`s3vectors.artifact` and `s3-annotations.artifact` at commit 2b99648, before T76 amends them. A
seeding helper in the test file writes it directly through the moto clients.

1. `tests/unit/test_annotations.py` → `annotations.py`. Legacy `references` read: absent gives
   `[]`; `ObjectNotFoundError`, a bare `KeyError` and `CredentialError` propagate.
2. `tests/unit/clients/test_s3.py` → `clients/s3.py`, `constants.py` (R38): a plain, an
   `if_none_match` and an `if_match` `put_object` each store exactly the tag
   `arkeology-store-schema=2`, read back with moto's `get_object_tagging`; the omitting keyword
   stores no tag. The annotation self-mock's `S3Backend.put_object` wrapper passes extra arguments
   through, so the tag reaches moto unchanged.
3. `tests/unit/test_startup.py` → `startup.py` (Story 6, R41):
   - a store with one own-scope vector lacking `archived` fails check 9, and the message names its
     `artifact_id` and `arkeology-migrate-store`;
   - an empty store, a migrated store, and a legacy vector under a `READ_PREFIXES` entry all pass;
   - `bedrock.embed` is called once only (check 6), so check 9 adds no embedding;
   - the prerequisites function runs checks 1, 2, 4 and 8 and never check 9;
   - check 2's probe write raising a `CredentialError` whose original error code is `AccessDenied`
     fails check `write_prefix`, and the message names `s3:PutObject` and `s3:PutObjectTagging`;
     one whose code is `ExpiredToken` still propagates as a credential error.
   Update the "all checks pass" and count assertions for nine checks.
4. `tests/unit/test_store_migration.py` → `store_migration.py`, `pyproject.toml`. moto evaluates no
   bucket policy, so every untagged write lands there: every `--apply` test below except the fence
   tests patches `put_object` to raise the access-denied `CredentialError` when the tag is omitted,
   which stands for a fence in place.
   - Fence (R26, R39): the dry-run report's `write_fence` names the configured bucket and write
     prefix in its resource and the R38 key and value in its condition. `--apply` with no fence
     (unpatched moto) leaves the store identical to a snapshot taken before it, deletes its probe,
     exits 2, and names the statement; any other probe failure stops it the same way. With the
     fence patched in, the run proceeds.
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
   - Re-key (R44–R46): heading-slug keys and a bare-id document vector end at numbered keys with
     byte-identical embeddings and the earlier keys gone; a vector at a numbered-form legacy key is
     assigned like any other; a kill between the `PutVectors` and the `DeleteVectors` is resumed
     with no key written twice; an artifact with 101 legacy vectors is reported as cannot-migrate
     with nothing written, while one of 60 legacy vectors interrupted after its `PutVectors` is
     not; a journaled artifact resumed after its re-PUT has its annotations restored before the
     sweep and its vectors re-keyed from the sweep; a spy shows one own-scope sweep per run plus the
     verification's, and no `query_vectors` call.
   - Verification (D50): a vector left without a boolean `archived` makes the exit code 1 and is
     listed.
   - Skill drift: every flag in `migrating-arkeology-store/SKILL.md` is accepted by the parser.
5. Integration (real AWS, run-scoped prefix), new. Both store-migration tests need the R39
   statement covering the run-scoped prefix. The suite's fence (Operator, 2026-11-12): the Admin
   applies, once, a standing R39 statement whose resource is
   `arn:aws:s3:::<ARTIFACT_BUCKET>/integration-tests/*`, covering every run-scoped
   `integration-tests/<run-id>` prefix, and the suite never writes a bucket policy itself, which
   would need policy-write permission and a read-modify-write of the operator's live policy. It is
   applied when this release's tagged object writes (R38) land, not before: under it, every untagged
   object write of the earlier release's integration suite is refused. The suite's principal also
   needs `s3:PutObjectTagging`. A test that finds the statement absent fails naming it. A seeding
   helper that writes an object directly sends the R38 tag, or the fence refuses it:
   - `tests/integration/test_store_migration.py` — one seeded legacy artifact with `commit_refs` and
     `references` survives `--apply` with annotations restored after a real re-PUT, and its
     heading-slug vectors end at numbered keys with their embeddings unchanged. This proves the
     real wipe-and-restore, which the moto extension only models.
   - `tests/integration/test_store_migration.py` — the fence on real S3 (AC-87): an untagged
     `PutObject` under the prefix is refused with `AccessDenied` and changes nothing; a tagged one
     lands; `--apply`'s fence proof passes. Only real S3 evaluates the statement, so only this test
     proves the R39 statement refuses what it must and admits what it must.
   - `tests/integration/clients/test_s3_client.py` — a tagged `put_object`, plain and `if_match`,
     lands on real S3 carrying the tag, so the client's grant of `s3:PutObjectTagging` and the tag
     on a conditional write are proved.
   - `tests/integration/clients/test_vectors_filter_semantics.py` — the check 9 filter matches a
     vector without `archived` and not one with it, on real S3 Vectors.

**Integration tests broken by this change:** none. The suite does not call `validate_startup`, and
its fixtures write the new shape. One quality gate is affected: `uv run arkeology` refuses to start
on an operator's `.env` store until that store is migrated. Migrate the development store with this
command before running the gate. The gate also needs `s3:PutObjectTagging` in the `.env`
credentials' policy, or check 2 fails (R41).

**Mutation.** `annotations.py` is in `only_mutate`. After the unit suite is green, run
`uv run mutmut run` alone and triage survivors as AGENTS.md describes.

### Hand-offs

T91 hand-offs: AGENTS.md Repository Structure rows for `store_migration.py` and the new skill; the
startup line ("nine checks"); the stdout rule scoped to the MCP server process; and the CHANGELOG
**Breaking** entry giving the upgrade order from Requirements, "Delivery", the write-fence step
among it, and the v0.7.1 startup message that marks an install not upgraded (R40). AGENTS.md
§ Component Dependencies and SERVER-REFERENCE's IAM permissions name `s3:PutObjectTagging` as
mandatory beside `s3:PutObject`, and § Component Dependencies states that every write prefix,
migrated or set up on this release, carries the write-fence statement in the bucket policy (R39).
AGENTS.md § Conventions' Integration target names as prerequisites the standing R39 statement over
`arn:aws:s3:::<ARTIFACT_BUCKET>/integration-tests/*`, applied once when this release's tagged object
writes (R38) land and not before, and `s3:PutObjectTagging` for the suite's principal.

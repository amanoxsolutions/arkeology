---
type: brainstorming
title: Artifact Cross-Referencing (Migration and Ongoing Writes)
description: Explores how cairn-mcp should handle references between artifacts — repo-relative paths embedded in migrated frontmatter and new artifacts written by ongoing sessions — given that a file path and a cairn artifact_id are fundamentally different addressing schemes.
tags: []
timestamp: 2026-07-01T00:00:00Z
okf_version: "0.1"
status: complete
references:
  - docs/brainstorming/brainstorming-2026-05-30-existing-project-migration.md
  - docs/specs/p4-t20-migration-skill.md
  - docs/specs/p9-t31b-migration-skill-exclusion-gate.md
  - skills/migrating-to-cairn/SKILL.md
  - src/cairn_mcp/artifact.py
  - src/cairn_mcp/tools/write.py
  - src/cairn_mcp/tools/link_commit.py
  - src/cairn_mcp/tools/delete.py
  - src/cairn_mcp/resources.py
  - docs/architecture-decisions/adr-2026-05-29-tier-based-access-control.md
authored:
  by: "analyst"
  date: "2026-07-01"
revised:
  by: "analyst"
  date: "2026-07-02"
techniques_used:
  - inversion ("what would make this actively harmful, not just incomplete?")
  - scope-reframing (migration-only vs. general cross-referencing capability)
  - codebase archaeology (grounding option generation in existing shipped precedents rather than inventing new mechanisms)
  - assumption interview (challenging-assumptions skill — relentless one-question-at-a-time drill-down with recommended answers on each branch)
  - AWS documentation research (2026-07-02 — grounding the S3 metadata-type choice in primary AWS docs plus boto3/moto feasibility checks rather than memory)
  - cross-pollination / foreign lens (2026-07-02 — evaluating S3 annotations, a feature built for AI/ML payloads and data lineage, as a home for link-data storage)
assumptions_challenged:
  - "Rewriting cross-references requires new content-mutation machinery → reframed: cairn already ships a resolvable URI scheme (`cairn://artifact/{id}`) and a generic list-membership query operator (`$eq`) — the design reuses both instead of inventing new plumbing."
  - "Fixing a stale link is not a content change, it's just plumbing → examined in depth and split: a structured metadata field can be safely backfilled post-hoc (precedented by `link_commit`), but rewriting the stored content text is a genuine content mutation with re-embedding cost, and was NOT given the same treatment."
  - "Tier 2 'append-only' is an absolute rule with no established backfill precedent → found `link_commit` already backfills tier 2 artifacts' structured metadata today, without touching stored content — the append-only principle turned out to be about content, not all metadata."
  - "Cross-team reference leakage via a human-readable artifact_id needs new validation → challenged, then explicitly closed as not applicable, since a `references` entry can only exist as a resolved artifact_id if the target is already a real cairn artifact."
  - "(2026-07-02) D8's 'vector-metadata-only, no S3 touch' is the optimal mechanism → revised: writing the durable S3-side copy too makes `reconcile_index` lossless. `reconcile_index` already rebuilds `commit_refs` from S3 object metadata; it returns empty only because `link_commit` never writes it there. OQ2's fix belongs on the write side, not in reconcile."
  - "(2026-07-02) User-defined S3 metadata is the only place to store these fields → challenged via AWS docs: S3 annotations (mutable in place, 1 MiB, no re-PUT, ETag-stable) are a stronger fit for unbounded/high-churn link-data, but moto lacks support and object overwrite wipes annotations — a real trade-off, not a free win. Storage-type left as a pending operator decision."
  - "(2026-07-02) Generalizing the delete reference-check needs new cross-scope validation → closed: the reverse-lookup queries vector metadata (references as list[str]) and must stay own-scope-only per the existing non-negotiable rule, identical to the synthesis check; no new validation needed."
decisions_locked:
  - "D1 — Scope: only the frontmatter `references:` YAML list is mechanically rewritten during migration; in-body markdown links are explicitly out of scope for automated rewriting."
  - "D2 — `references: list[str]` becomes a first-class field on the `Artifact` model, storing only resolved bare `artifact_id` values (no URI prefix), dual-stored exactly like `source_artifacts` (S3 object metadata: comma-joined string; S3 Vectors metadata: `list[str]`), queryable via the existing generic `$eq` list-membership filter."
  - "D3 — Content rewrite target format: resolved references are rewritten in stored content to the existing `cairn://artifact/{id}` MCP resource URI. Unresolved or excluded targets keep their original raw path text untouched — mixed addressing across the corpus (`cairn://...` next to `/docs/...`) is the correct permanent steady state, not a defect."
  - "D4 — Forward-reference resolution: migration builds a single authoritative path→artifact_id map from the FULL `CAIRN_IMPORT.yaml` manifest (every entry, any status, across sessions) as soon as each entry's title+date are known and before any writes happen — since `generate_artifact_id` is a pure function, this resolves same-batch and multi-session forward references with no dependency on write order."
  - "D5 — `http://`/`https://` entries in `references:` are always left untouched, never treated as path-resolution candidates."
  - "D6 — Path normalization ceiling (best-effort, explicitly bounded): convert backslashes to forward slashes; try the lookup stripping common leading-prefix variants (`./`, a single leading `/`, or none). No match → leave completely untouched and fall through to the general search-based fallback. Repairing genuinely broken/inconsistent source references beyond this is explicitly not cairn's job."
  - "D7 — General applicability: any ordinary `write_artifact` call, not just migration, may populate `references` directly with known artifact_ids — the same mechanism serves ongoing agent sessions."
  - "D8 — Mutability is split by representation, not by a single retroactive-editing rule: the structured `references` field may be backfilled post-hoc on ANY tier, mirroring `link_commit`'s exact mechanism (re-fetch existing vector + embedding, merge metadata, re-put without re-embedding — no content touch, no re-embedding cost). Stored content text is only ever rewritten to `cairn://artifact/{id}` at first-write time (migration or new session write); it is never retroactively patched into an already-written tier 2 artifact. Tier 3 keeps its existing 'updated in place' freedom for content as well."
  - "D9 — AGENTS.md gains two new guidance snippets: (1) new artifact writes should proactively use `cairn://artifact/{id}` when referencing a target already known to be a cairn artifact; (2) 'reference healing' — an agent that encounters a broken or unresolved reference during normal work should search for the likely target and propose a fix to the operator, never silently rewrite it."
  - "D10 — A deferred, optional cleanup skill/step (mirroring the existing commit-refs backfill pattern: separate, decoupled, skippable by default) is the vehicle for the post-hoc structured-field backfill described in D8."
  - "D11 (2026-07-02) — Direction α confirmed: generalize `link_commit` into a single `link_metadata` primitive (fetch → merge+dedup → re-put, no re-embed) that backfills the structured link fields (`commit_refs`, `references`), operator-invoked via a skill that content-scans against the path→id map and presents a dry-run batch report. It writes a *dual-write*: the durable S3-side copy AND vector metadata. This REVISES D8 (mechanism is dual-write, not vector-metadata-only) and folds OQ2's fix onto the write side — `reconcile_index` already rebuilds these fields from the S3 side, so making the durable copy authoritative is the fix, not changing reconcile. Write durable-side first, vectors second (recoverable-state ordering, mirroring `delete_artifact`)."
  - "D12 (2026-07-02) — Storage-type CONFIRMED: the durable S3-side copy of BOTH `commit_refs` and `references` is stored as **S3 object annotations** (`PutObjectAnnotation`, mutable in place, 1 MiB, ETag-stable), NOT user-defined metadata. One uniform mechanism for both similar fields (operator rejected the split). Vector metadata is unchanged (both fields remain `list[str]` there for `$eq` filtering). moto remains the default AWS-testing tool; annotations are self-mocked via a conftest extension, exactly as `query_vectors` already is (repo currently pins moto 5.2.2). Consequences now live: (a) object overwrite WIPES annotations, so any overwriting write must re-apply them (see D14); (b) write-time `references` (D7) becomes `put_object` + `put_object_annotation`; (c) `reconcile_index` must read both fields via `ListObjectAnnotations`/`GetObjectAnnotation`. Annotation availability (region/bucket-type) and IAM validation are handled per D15 (annotations unavailable in UAE/Bahrain, S3 Express/Outposts/directory buckets, and require new IAM actions)."
  - "D13 (2026-07-02) — OQ3 CONFIRMED: generalize `delete_artifact`'s synthesis-reference check into a single unified own-scope 'referenced_by' warning covering BOTH `source_artifacts` (synthesis, existing) and the new `references` field (any type). Warn-but-don't-block. Applied to `delete_artifact` (permanent → stronger warning) and `archive_artifact` (reversible → informational). Own-scope only per the existing non-negotiable rule (never reveal foreign-scope identifiers); use server-side `$eq` list-membership filtering rather than fetch-all-then-filter-in-process."
  - "D14 (2026-07-02) — Overwrite preservation CONFIRMED (analyst default; Architect finalizes mechanics): on an overwriting `write_artifact` (tier-3 update-in-place, the only case that re-PUTs the same key), the write path must read-forward the artifact's existing `commit_refs` (and any backfilled `references`) and re-apply them, because `write_artifact` can restore `references` from its inputs but does NOT know `commit_refs` (added post-hoc by `link_commit`). Read-forward SOURCE is a free choice between two equally-valid stores, since these fields are dual-stored (D11): (a) the S3 annotations via `GetObjectAnnotation` before the `PutObject` wipes them, or (b) the existing VECTOR metadata via `get_vectors` — which is NOT touched by the S3 `PutObject` and still holds the old `commit_refs` until the write re-puts the vectors. Option (b) is likely simpler since the write path already touches vectors. Either way the merged value must be written back to BOTH stores. CopyObject's COPY-directive does not apply (it cannot carry a new body). Chosen 'Preserve' over 'Accept clearing' because silent loss of an append-only trail is exactly what cairn exists to prevent."
  - "D15 (2026-07-02) — Annotation availability/IAM validation placement CONFIRMED: NOT a hard server-startup gate. Rationale: annotations back only the feature-level `commit_refs`/`references`, not the core store (S3 content + vectors + embeddings all work without them), so refusing to boot the whole memory server over an annotation problem would be disproportionate. Instead: (1) add a one-time availability + IAM-permission check to the `setting-up-cairn` skill, alongside its existing resource-reachability checks (Checks 4–7), for a friendly early failure with operator guidance; (2) handle the annotation-unavailable / AccessDenied error gracefully at runtime in `link_metadata`/write to cover post-setup DRIFT (IAM edit, bucket/region change) that a one-time setup check cannot catch. Concrete findings (verified 2026-07-02): (i) AWS CLI support for annotation operations is VERSION-GATED — absent in aws-cli 2.34.44 (`aws s3api put-object-annotation` → 'invalid choice') but present from 2.35.14 (all four ops). So the setup-skill probe CAN stay CLI-native like the other checks, provided it guards on a minimum aws-cli version (≥ 2.35.14); otherwise fall back to a boto3 snippet via `uv run` (the repo's botocore 1.43.36 supports the APIs regardless). (ii) The four IAM actions the deployment policy must grant are `s3:PutObjectAnnotation`, `s3:GetObjectAnnotation`, `s3:ListObjectAnnotations`, `s3:DeleteObjectAnnotation` (confirmed from the CLI operation help)."
  - "D16 (2026-07-06) — Extend the migration content rewrite (D1/D3) so an already-resolved frontmatter `references:` path is rewritten to `cairn://artifact/{id}` everywhere it occurs in stored content — frontmatter AND body — executed as deterministic server-side code inside `migrate_artifacts` (reversing, for this bounded case only, the prior 'no server-side rewrite' ownership call in cluster F / ADR-012). Does NOT reopen D1's exclusion of in-body link *discovery*: only occurrences of paths already resolved from frontmatter are rewritten; no scanning for undeclared body-only links is added."
decisions_pending:
  - "OQ1-cleanup — Remaining detail of the D10/D11 cleanup skill beyond the confirmed shape: discovery scan specifics and per-artifact vs batch approval nuance. Architect/PM territory, not blocking."
  - "Sweep — one-time re-link of `commit_refs` already backfilled by the current vector-only `link_commit`, so they land in annotations and survive future reconciles. Migration/ops detail, not blocking the design."
  - "OQ3 — Analyst recommendation captured, awaiting operator confirmation: unified own-scope, warn-only `referenced_by` scan (covering both `source_artifacts` and `references`) applied to both `delete` (stronger warning, permanent) and `archive` (informational, reversible), using server-side `$eq` filtering. Must stay own-scope only per the non-negotiable rule."
decisions_resolved_pending_implementation:
  - "OQ2 (2026-07-02) — Resolved via D11's dual-write + D12's annotations choice: `reconcile_index` becomes lossless for these fields by reading both `commit_refs` and `references` from S3 annotations (`ListObjectAnnotations`/`GetObjectAnnotation`) and re-adding them to rebuilt vector metadata. Supersedes the original 'fix reconcile to carry vector-only fields' framing — annotations are durable on the object, so reconcile rebuilds from them."
decisions_closed_not_applicable:
  - "Cross-team reference leakage via a human-readable artifact_id appearing in another team's shared artifact — raised, examined, and explicitly closed as not applicable. A `references` entry can only ever hold a resolved artifact_id, which means the target is already a real cairn artifact; no special validation or restriction is being added for the cross-scope case."
---

# Artifact Cross-Referencing (Migration and Ongoing Writes)

## Description

Existing project documentation frequently references other files by repo-relative path —
either in the project's house/OKF frontmatter `references:` YAML list, or as in-body markdown
links. Once a file becomes a cairn-mcp artifact, its address is a deterministic `artifact_id`
(e.g. `adr-use-postgres-for-sessions`), not a file path — a fundamentally different addressing
scheme. This session explores what should happen to those embedded references, both during
one-time migration of an existing repo and for artifacts written by ongoing agent sessions,
without adding fragility to the existing migration skill.

## Session 2026-07-01

### Problem Statement

The existing migration capability (`skills/migrating-to-cairn/SKILL.md`, backed by the
server-side `migrate_artifacts` tool) solves discovery, classification, metadata enrichment,
import, and post-migration file treatment — but nothing in it touches embedded cross-references
between files. Once a file is migrated, a reference embedded in it (or in another file) pointing
to that file by relative path may point at: an artifact already migrated, one scheduled for
migration later in the same batch, one permanently excluded (e.g. ADRs kept git-only per the
project's `adr_strategy` setting), or a target that no longer exists. Grounding check confirmed
this is a genuine gap: `src/cairn_mcp/artifact.py` has no `references` field today (the
frontmatter convention exists only in this project's own documentation style, never reaching the
`Artifact` model), and the live migration skill's descriptor-building steps (3.A1, 3.B3, 3.B5)
read file content verbatim into the stored `content` field with no rewriting logic anywhere.

### Ideas Explored

**A — What counts as a reference to handle**
- Frontmatter `references:` list entries that are repo-relative paths (vs. URLs, already fine)
- In-body markdown links `[text](path/to/file.md)`
- Bare prose mentions of a path with no link syntax
- Relative image/asset links (out of scope — assets aren't migrated as artifacts)
- References to files entirely outside the migration's scoped directories

**B — When resolution happens**
- Migration-time rewrite (content mutated before `migrate_artifacts` is called)
- Read-time resolution (raw text stays stored; a client/agent resolves it when displaying)
- Hybrid: store raw text but also emit a structured, resolved mapping alongside it
- Do nothing programmatic — leave text as historical record, human-readable but dead

**C — Target format if rewritten**
- Bare `artifact_id` string dropped into the link target
- The existing `cairn://artifact/{id}` MCP resource URI, already registered in `resources.py`
- A promoted first-class `references: list[str]` field on the `Artifact` model
- Leave the link text but append a translation footnote/table mapping old path → new identifier

**D — Forward references (target not yet written in this batch)**
- Key insight: `generate_artifact_id` is a pure function of type + title + (date for tier 2) —
  an agent can compute a target's future `artifact_id` from the classification table alone,
  before that file is ever migrated. Forward references are a non-problem if the map is built
  early enough.
- Two-pass approach: build a full path→artifact_id map from the classification table first,
  then rewrite, then write
- Placeholder-then-backfill: write raw now, backfill in a second pass once the batch completes

**E — References to excluded, missing, or never-migrated targets**
- Leave the original path untouched (transparent but dead outside the repo)
- Annotate inline ("file not migrated — see repo history")
- Drop silently (risky — loses information without telling anyone)
- Surface in a migration report for the operator to decide per-case

**F — Mechanism / who performs the rewrite**
- Agent does it in-context per file (fine for the small-batch path; harder for the large-batch
  path where full content isn't read until the final write step)
- A manifest-driven rewrite pass added to the skill, using the manifest's own path list
- A server-side capability inside `migrate_artifacts` (more invasive; the original migration
  brainstorming explicitly avoided adding server complexity for a one-time operational concern)

### Clusters

1. **Scope** (A) — what text patterns count as a reference
2. **Timing** (B, D) — migration-time vs. read-time vs. hybrid, and how forward references resolve
3. **Target format** (C) — plain id vs. `cairn://` URI vs. promoted schema field
4. **Failure handling** (E) — what happens when the target isn't in cairn at all
5. **Ownership** (F) — skill-only vs. touching the server

### Selected Directions

An inversion question ("what would make this actively harmful?") surfaced **migration
complexity/fragility** as the primary risk to avoid — not silent broken links or content
mutation per se. A scope question resolved that this should be treated as a **general
cross-referencing gap** (cairn-mcp has no first-class way for any artifact to reference
another), not a migration-only concern. Four candidate directions were proposed against that
lens (first-class schema field; reusing the existing `cairn://` URI via a general resolver;
pure convention/search-based resolution with no new mechanism; a decoupled optional backfill
step) and then synthesised together rather than choosing one:

- **Frontmatter-only, mechanical rewrite** for migration (D1) — deliberately excludes in-body
  links, which would require fragile regex-matching over inconsistent free-form prose (the
  original example, a Windows-style backslash path, illustrated exactly this messiness).
- **`references` promoted to a first-class `Artifact` field** (D2) — justified once it was
  shown to reuse 100% existing plumbing: `source_artifacts` (used today by the `synthesis`
  type) already establishes the exact dual-storage pattern needed, and `clients/filter.py`'s
  `$eq` operator already does generic list-membership matching for any field name, not just
  `tags`. `delete_artifact`'s synthesis-reference check already proves the reverse-lookup
  pattern in production.
- **`cairn://artifact/{id}`** (D3) as the content-embedded target format — an existing,
  already-registered MCP resource URI, not a new scheme.
- **Single authoritative resolution map** (D4) built from the migration's own manifest,
  extended to carry each entry's `artifact_id` as soon as it's computable — turning "forward
  references" and "multi-session retries" into non-problems without a separate parallel
  structure.
- **Bounded, best-effort normalization only** (D6) — explicitly not attempting to repair
  genuinely inconsistent source content; anything that doesn't match a small set of common
  path-prefix variants falls through to the general fallback.
- **General applicability** (D7) — the same field and mechanism serve ordinary `write_artifact`
  calls in ongoing sessions, not just the one-time migration.

### Challenge

A deeper challenge pass (via the `challenging-assumptions` skill) surfaced and resolved two
substantial findings not caught in the initial synthesis:

**Tier semantics vs. retroactive fixes.** `adr-2026-05-29-tier-based-access-control.md`
explicitly describes tier 3 as "updated in place" but tier 2 only as "append-only" — no such
mutability claim. The originally proposed deferred cleanup step (fixing references on
already-written artifacts once new targets become resolvable) would have retroactively mutated
tier 2 content, in tension with that documented distinction. Inspecting `link_commit`'s actual
implementation resolved this cleanly: it already backfills structured vector metadata on any
tier — re-fetching the existing vector and embedding, merging in the new value, and re-putting
without touching S3 content or re-embedding. That gave a principled split: the **structured**
`references` field may be backfilled post-hoc on any tier (D8, same mechanism as
`commit_refs`), but the **content text** itself is only ever rewritten at first-write time,
never patched into an already-written tier 2 artifact. This also surfaced a real, non-obvious
cost that a "just fixing a link" framing understates: content rewrites re-trigger
`parse_sections` and Bedrock re-embedding, and shift `last_edited_ulid` (a freshness signal
`check_synthesis_freshness` depends on) — reasons beyond "append-only" alone to avoid
retroactive content mutation.

**`link_commit`'s own documented limitation transfers directly.** Its docstring already
states that `reconcile_index` rebuilds vector metadata from S3 object metadata and does not
carry `commit_refs`, so a reconcile run silently drops backfilled commit links. A
`references`-backfill mechanism built the same way (vector-metadata-only, mirroring
`link_commit` for consistency, per D8/D10) would inherit the identical risk. Decided:
accept the same trade-off for now, and log a backlog item to fix both fields together later
(OQ2) rather than solving it piecemeal for `references` alone.

A cross-team leakage question was also raised — artifact IDs are deliberately human-readable
slugs, not opaque UUIDs, so a `references` entry naming a foreign team's hidden artifact could
leak its existence/subject to a reader who could never access it directly. This was examined
and explicitly closed as not applicable: a `references` entry can only ever hold a *resolved*
artifact_id, meaning the target is already a real cairn artifact reachable by *some* existing
path — no new validation is being added for this case.

A multi-session migration gap was closed by requiring the resolution map (D4) to always be
built from the *full* manifest, not just the subset being actively retried in a given session
— otherwise a file successfully written in an earlier session could wrongly appear unresolved
to a reference discovered during a later retry.

### Open Questions

- **OQ1** — Exact design of the deferred cleanup skill/step (D10): trigger conditions, tool
  shape (new MCP tool vs. skill-only orchestration of existing tools), and operator UX for
  reviewing proposed backfills.
- **OQ2** — Backlog item, explicitly out of scope for this feature: fix `reconcile_index`
  dropping vector-only-stored fields (`commit_refs` today, `references` once shipped) when
  rebuilding from S3 object metadata.
- **OQ3** — Whether the existing `delete_artifact` synthesis-reference-check pattern should be
  generalized into a broader "referenced by" delete/archive warning covering the new
  `references` field, beyond the current `synthesis`/`source_artifacts` special case.

## Session 2026-07-02

### Focus

Continuation session to work the three open questions (OQ1, OQ2, OQ3) left by the
2026-07-01 session. Selection agreed with the operator: **Direction α** for OQ1 —
generalize `link_commit` into a single `link_metadata` primitive, operator-invoked, that
content-scans against the path→id map and presents a dry-run batch report. The operator
then added a decisive refinement that reshaped the relationship between OQ1 and OQ2.

### OQ1 — Direction α refined; OQ2 folds into the write side

The operator's refinement: `link_metadata` must write the field to the **durable S3-side
store as well**, not only vector metadata. Grounding confirmed why this is the correct
fix for OQ2 rather than a change to `reconcile_index`:

- `reconcile_index._reindex_artifact` (`reconcile.py`) **already** rebuilds `commit_refs`
  from the S3 side via `coerce_list_field(raw_s3_meta, "commit_refs")` and re-adds it to
  vector metadata. It returns empty today **only** because `link_commit` never writes
  `commit_refs` to the S3 object at all (`link_commit.py` leaves `s3` unused: `_ = s3`).
- Therefore OQ2's "fix" is not in `reconcile_index` — it needs **zero** change for
  `commit_refs` and a ~3-line addition for `references`. The real fix is on the **write
  side**: make the durable S3-side copy authoritative, which reconcile already rebuilds
  from. **This supersedes/revises D8**: the mechanism is a *dual-write* (durable S3-side +
  vector metadata), not "vector-metadata-only." Writing structured metadata still does not
  touch content body and does not re-embed, so D8's core principle (no content mutation,
  no re-embed, preserve `last_edited_ulid`) holds.

Write-ordering (mirroring `delete_artifact`'s recoverable-state reasoning): write the
durable S3-side copy **first**, vectors **second** — if the vector write fails, a later
`reconcile_index` rebuilds vectors from the durable side and self-heals. Merge+dedup makes
re-runs idempotent. Note also: existing vector-only `commit_refs` already backfilled by the
current `link_commit` remain at risk until re-linked (a one-time sweep may be warranted).

### The S3 metadata-type question (raised by operator, researched against AWS docs)

The operator asked which of S3's three custom-metadata types we use, and whether
**annotations** (a newer feature: named payloads up to 1 MiB, mutable in place) would be a
better home. Researched against primary AWS docs + boto3/moto feasibility checks:

- **Today we use user-defined metadata** (`x-amz-meta-*`): **2 KB total cap, immutable
  after upload** — the only way to change it is to copy/re-PUT the whole object.
- **Object tags**: 10 max, 256-char values — too small, rejected.
- **Annotations**: **1 MiB per payload, up to 1,000 per object, mutable via
  `PutObjectAnnotation` without re-PUT and without changing the object's ETag**, any UTF-8
  format. Durable on the object, so `reconcile_index` can still rebuild from them. This
  kills **both** original risks at once (2 KB ceiling *and* full-body re-PUT / re-embed /
  `last_edited_ulid` disturbance) and draws a clean line: immutable identity metadata stays
  in user-defined metadata; mutable, accreting link-data (`commit_refs`, `references`) moves
  to annotations — exactly the feature's intended use ("data lineage," "audit trails").

**Verified feasibility & caveats:**
- ✅ **boto3 ready** — `PutObjectAnnotation`/`GetObjectAnnotation`/`ListObjectAnnotations`/
  `DeleteObjectAnnotation` are all present in the installed botocore 1.43.36 service model.
- ⚠️ **moto is NOT** — moto 5.2.2 has zero annotation request handling; the project's
  testing convention mandates moto for S3 ops. Needs a custom moto extension (precedent: the
  `query_vectors` cosine patch in `conftest.py`) or integration-only coverage.
- ⚠️ **Overwrite wipes annotations** — overwriting an object *replaces* its annotations;
  cairn's tier-3 "updated in place" re-writes would silently drop accumulated link-data
  unless re-copied. Direct interaction with a cairn invariant.
- ⚠️ **Deployment-agnostic tension** — annotations are unavailable in UAE/Bahrain regions
  and on S3 Express One Zone / Outposts / directory buckets; becomes a startup-check or
  documented constraint, plus new IAM actions.
- ⚠️ **Cannot be set during `PutObject`** — only after upload. So a write-time `references`
  (D7) becomes `put_object` + `put_object_annotation`, and is exposed to the overwrite-wipe.
  This pushes `references` (bounded, write-settable) toward user-defined metadata and
  `commit_refs` (unbounded, pure post-hoc churn) toward annotations — a possible **split**.

**Storage-type decision: CONFIRMED 2026-07-02 (D12) — annotations for BOTH fields.** The
operator chose one uniform mechanism over the split ("let's not use 2 different mechanisms
for 2 things very similar"), accepting the moto gap (self-mock via a conftest extension, as
`query_vectors` already is). This makes three consequences live: object overwrite wipes
annotations (any overwriting write must re-apply them — see OQ1-overwrite); write-time
`references` becomes `put_object` + `put_object_annotation`; and `reconcile_index` reads
both fields via the annotation APIs. Annotation availability (region/bucket-type) + IAM
validation is placed in the `setting-up-cairn` skill plus graceful runtime handling, NOT a
hard startup gate (D15) — since annotations back only a feature, not the core store.

### OQ3 — Generalized "referenced by" delete/archive warning

Decoupling: the reverse-lookup queries **vector metadata** (`references` stored as
`list[str]` per D2), so OQ3 is **independent of the S3 storage-type decision**. Directions:
unified `referenced_by` scan (both `source_artifacts` and `references`, delete + archive);
delete-only; or a parallel non-unified check. Two hard constraints from grounding: the
check **must stay own-scope only** (existing non-negotiable rule — else it re-opens the
cross-scope leakage closed in the prior session), and a `references` reverse-lookup can
filter **server-side** (`{"references": {"$eq": target}}`) rather than fetch-all-then-filter.

Analyst recommendation (PENDING operator confirmation): **unified `referenced_by` scan**,
own-scope only, warn-only/non-blocking, applied to both `delete` (stronger warning —
permanent) and `archive` (informational — reversible).

### Open Questions (updated)

- **OQ1 — storage-type CONFIRMED (D12): annotations for both fields.** Overwrite
  preservation CONFIRMED (D14): the write path reads-forward and re-applies annotations on
  an overwriting `PutObject`, so tier-3 edits don't drop the `commit_refs` audit trail.
  Remaining non-blocking items: cleanup-skill detail and a one-time re-link sweep for
  already-backfilled `commit_refs`.
- **OQ2 — RESOLVED (write-side + annotations):** `reconcile_index` rebuilds both fields from
  durable annotations via `ListObjectAnnotations`/`GetObjectAnnotation`; no more vector-only
  data loss.
- **OQ3 — CONFIRMED (D13):** unified own-scope `referenced_by` warn-only check across delete
  (permanent, stronger) and archive (reversible, informational), server-side `$eq` filtered.

## Session 2026-07-06

_Recorded by the architect while scoping task T56, at the operator's request; the two calls in
D16 below were made by the operator before any design work began — this entry documents them,
it does not re-open the analysis._

### Focus

A follow-up, bounded extension to the migration content rewrite (T51/FR-52): the SAME path
already resolved from a file's frontmatter `references:` list frequently reappears, verbatim, as
an in-body markdown link pointing at the identical target — a common documentation pattern this
project's own house style uses. Today those body occurrences are left as dead raw paths even
though the target is fully known and resolved. Separately, the *mechanism* by which the
frontmatter rewrite itself happens today — an agent hand-editing text in-context, per the skill's
current instructions — is not deterministic (an LLM find/replace has no byte-exact guarantee, and
the skill runs no local scripts to make it one).

### D16 (2026-07-06) — Deterministic, server-side, frontmatter+body content rewrite of already-resolved references (FR-52 extension)

Two operator calls, both frozen before design work started:

1. **Scope stays narrow — no in-body link *discovery*.** This does NOT reopen D1's exclusion of
   in-body markdown links from *discovery*. The only references ever rewritten are those already
   resolved from a file's frontmatter `references:` list — the same narrow set D1/T51 already
   resolves. No new scanning for undeclared body-only links is added, and D1's core
   risk-management intent (avoid fragile regex over inconsistent free-form prose) is preserved:
   the body rewrite only fires on structured, unambiguous occurrences of an
   ALREADY-known-resolved path — markdown link targets (`](path)`) and the frontmatter YAML list
   item itself — never bare prose mentions with no link syntax.
2. **Ownership moves server-side and unifies frontmatter+body into one step.** "Deterministic"
   rules out the current agent-in-context find/replace — so the rewrite must execute as tested
   server-side code. This REVERSES ADR-012's "no server-side rewrite in `migrate_artifacts` beyond
   threading the `references` descriptor key" for this one bounded, resolved-path-only case (see
   the ADR-012 Revision, 2026-07-06). The agent still runs the `references.py` resolution
   algorithm in-context to BUILD the `{original_text -> artifact_id}` map per file — unchanged
   from T51 — but now passes that map into the `migrate_artifacts` descriptor instead of
   hand-editing the file's content; the server applies the rewrite once, uniformly, to both the
   frontmatter block and the body, before the artifact is ever written or embedded.

This closes the fragility the original ownership analysis (cluster F, 2026-07-01 session) already
flagged in the "agent does it ad-hoc in-context" row — "fine for the small-batch path; harder for
the large-batch path" — by removing the in-context rewrite from BOTH paths, not just the
large-batch one, and doing so without reopening undeclared-link discovery.

Mechanics (the helper's contract, the descriptor shape, anchor handling, and the
markdown-awareness rules) are recorded in the ADR-012 Revision and in
`docs/specs/p12-t56-deterministic-content-reference-rewrite.md` — this entry records only the
decision, not the implementation.

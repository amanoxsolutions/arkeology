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
  by: ""
  date: ""
techniques_used:
  - inversion ("what would make this actively harmful, not just incomplete?")
  - scope-reframing (migration-only vs. general cross-referencing capability)
  - codebase archaeology (grounding option generation in existing shipped precedents rather than inventing new mechanisms)
  - assumption interview (challenging-assumptions skill — relentless one-question-at-a-time drill-down with recommended answers on each branch)
assumptions_challenged:
  - "Rewriting cross-references requires new content-mutation machinery → reframed: cairn already ships a resolvable URI scheme (`cairn://artifact/{id}`) and a generic list-membership query operator (`$eq`) — the design reuses both instead of inventing new plumbing."
  - "Fixing a stale link is not a content change, it's just plumbing → examined in depth and split: a structured metadata field can be safely backfilled post-hoc (precedented by `link_commit`), but rewriting the stored content text is a genuine content mutation with re-embedding cost, and was NOT given the same treatment."
  - "Tier 2 'append-only' is an absolute rule with no established backfill precedent → found `link_commit` already backfills tier 2 artifacts' structured metadata today, without touching stored content — the append-only principle turned out to be about content, not all metadata."
  - "Cross-team reference leakage via a human-readable artifact_id needs new validation → challenged, then explicitly closed as not applicable, since a `references` entry can only exist as a resolved artifact_id if the target is already a real cairn artifact."
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
decisions_pending:
  - "OQ1 — Exact design of the deferred cleanup skill/step from D10: trigger conditions, tool shape (new MCP tool vs. skill-only orchestration of existing tools), and the UX for presenting proposed backfills to the operator."
  - "OQ2 — Backlog item, explicitly deferred and out of scope for this feature: `reconcile_index` rebuilds vector metadata from S3 object metadata and currently drops any field stored only in vector metadata (`commit_refs` today, `references` once shipped, per D8/D10). Needs a fix, to be tackled for both fields together, not blocking this design."
  - "OQ3 — Whether/how the existing `delete_artifact` synthesis-reference-check pattern (which warns when deleting an artifact that a `synthesis`'s `source_artifacts` depends on) should be generalized to also warn on deleting or archiving any artifact that other artifacts' `references` field points to. Raised as a natural consumer of the new field but not designed in this session."
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

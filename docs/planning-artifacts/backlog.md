---
type: Plan
id: backlog
title: Backlog
description: All work waiting to be started for Arkeology — deferred improvements, issues, and not-yet-built features organised by topic with stable IDs.
tags: []
okf_version: "0.2"
sources:
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: Architecture review — Arkeology (whole design record)
    last_modified: 2026-11-10T11:21:17Z
  - resource: docs/specs/p3-t15-partial-write-failure-log.md
    title: T15 — Partial Write Failure Log
    last_modified: 2026-11-10T16:24:49Z
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: Architecture review — Arkeology, plan phases 9, 10 and 12
    last_modified: 2026-11-15T16:30:41Z
generated:
  by: "axians-pm/claude-sonnet-4.6"
  at: 2026-06-13T18:25:19Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-15T20:46:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Backlog

The single home for all work **waiting to be started** — issues, deferred improvements, and
not-yet-built features. Tasks are pulled from here into the current open phase in
[`plan.md`](plan.md) when we decide to tackle them; there is no pre-planned schedule.

Organised by topic. Each item keeps a stable ID so brainstorming docs, specs, and reviews can
reference it:
- **`B-…`** — deferred backlog items (features, improvements, or design-first items that
  require brainstorming before they can be specced).
  When a `B-` item is completed, delete its entire row from `docs/planning-artifacts/backlog.md`
  and remove all cross-references to it in specs, ADRs, and `plan.md`.

Items that were promoted to a phase are **not** listed here — see the phase history in
[`plan.md`](plan.md).

---

## Retrieval quality

- **B-1 — Retrieval-quality benchmark harness.** Reusable harness measuring recall/precision of
  Arkeology semantic search vs OKF-style `index.md` progressive-disclosure navigation over a fixed
  corpus at N≈10/100/1000 artifacts; repeatable as corpus and embedding model evolve. Substantiates
  the "semantic memory beats progressive-disclosure wiki at scale" positioning claim.
  Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (OQ1).

- **B-6 — Recency-weighted search ranking.** Blend an age signal into
  `search_artifacts` ranking so a fresher artifact is not tied by pure cosine similarity with a
  superseded older one. The temporal data already exists (`last_edited_ulid` on every vector — no
  re-index needed) and the ranking choke point is single (`_search_helper.py` `run_search_loop`
  final sort, shared by search + synthesise). **Design-first — requires an ADR before spec** for
  three non-trivial decisions: (1) **tier/type-aware decay** — tier-3 canonical ADRs are *meant* to
  age slowly while tier-2 session notes should decay fast, so a blanket penalty is likely wrong;
  (2) **score combination** — cosine scores are in [−1, 1], so a naive multiplicative decay
  misbehaves on negative scores and needs normalization; (3) **default-on vs opt-in per query**,
  and the caveat that post-hoc reranking only reorders the fetched candidate pool, not the whole
  index. This item is the *ranking* half of the recency work; the *transparency* half — surface
  the artifact's age on each result and let the agent discount stale hits itself, with ranking
  left untouched — shipped separately, see
  [`p12-t54-search-age-transparency.md`](../specs/p12-t54-search-age-transparency.md).

## Cross-scope security

- **B-5 — Hard cross-scope security boundary.** Today the tier/visibility gate is a soft
  control: S3 Vectors authorization is all-or-nothing per index, so every team sharing the
  vector index can technically read all teams' vector metadata (titles, descriptions, tags)
  and embeddings, including tier 2 — cross-scope deployment is a mutual-trust topology
  (documented 2026-07-02 in ADR-007 revision, the requirements.md Constraints table, and the
  SERVER-REFERENCE Cross-Scope Security Model). Two candidate solutions, design-first
  (brainstorming + ADR before spec):
  1. **Hosted MCP server** — deploy Arkeology as a shared service (requires the HTTP
     transport, NFR-05): the server holds the AWS credentials, clients authenticate to it,
     and the tier/visibility gate runs on the trusted side of the boundary. Turns the
     existing gate into a real access control without index topology changes.
  2. **Split vector index** — each team owns a private vector index; tier 3 `shared`
     vectors are additionally replicated into a shared discovery index. Index-level IAM
     (resource tags / separate ARNs) then provides a true hard boundary. Costs: dual
     writes on tier 3 shared artifacts, a cross-index reconcile story, and a search path
     that queries two indexes.
  Source: [`adr-2026-05-29-tier-based-access-control.md`](../architecture-decisions/adr-2026-05-29-tier-based-access-control.md)
  (Revision 2026-07-02).

## OKF interoperability

- **B-2 — OKF export adapter (+ governance).** `arkeology export --okf <scope>` emitting an OKF
  bundle (git repo + `index.md` + `log.md` + cross-links) on a **best-effort** basis: preserve
  each document's existing agent-authored frontmatter, fill gaps from Arkeology's stored metadata
  (`tags`; OKF `timestamp` ← `last_edited_ulid`; Arkeology `date` → custom key; add `resource`),
  and append Arkeology's extra tags. Arkeology does **not** transform non-OKF content into OKF
  (the authoring agent's job) and makes no internal schema change; vector index stays
  OKF-agnostic. Must reuse the scope/tier/visibility gate at export time, exclude/partition
  `hidden`/cross-scope artifacts, and stamp the bundle as ungoverned downstream. Open detail:
  precedence when existing frontmatter and Arkeology metadata disagree (default: existing
  frontmatter authoritative, Arkeology fills gaps only). Also resolves the
  visual-reading-interface export path.
  Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D1, D2a, D4).

- **B-13 — Freshness check for every document that carries sources.** Under OKF's reader-side
  model (D20), any document with `sources` — a spec citing its brainstorming session, not only a
  synthesis — can be checked by following each source edge forward: report a source missing,
  archived, or stale against its captured `last_modified`. Undecided whether this surfaces on
  read, in a widened scheduled audit, or not at all; `check_synthesis_freshness` stays
  synthesis-only regardless. Needs a decision before it can be specced.
  Source: [`brainstorming-2026-09-17-okf-v02-adoption.md`](../brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md) (D20).

- **B-14 — "Unverified since revised" flag in listings and search results.** FR-71 surfaces the
  advisory flag (D41) on `read_artifact` only, where it is free: the read already loads the
  `verified` annotation and `revised` from object metadata. Showing it in `list_artifacts` and
  `search_artifacts` too is deferred here. *Approach chosen (PM session with operator,
  2026-09-24):* a **`last_verified: {by, at}`** key in **vector metadata only**, derived from the
  entry with the latest `at` in the `verified` annotation (entries may be backdated, so not
  simply the last appended) — the `commit_refs` pattern: the annotation stays the
  sole source of truth (D44), the vector copy is a derived projection that `reconcile_index`
  rebuilds from it and that is never read back as truth. Recording a verification then becomes
  annotation append → vector metadata update, the same two-store path and failure-log repair
  `link_metadata` already uses.
  - *Why not the other options.* Per-artifact reads of the `verified` annotation: annotations
    are one GET each, so a listing would go from two to three GETs per artifact per page, and
    search — which reads no annotations today — would gain one per result. `last_verified` in
    **object** metadata, mirroring `revised`: unlike `revised`, which only moves on a content
    write that re-PUTs the object anyway, a verification is not a content write and S3 object
    metadata cannot be edited in place, so every verification would need an archive-style
    re-PUT that first reads and then re-applies the link, revision-history and `verified`
    annotations the re-PUT wipes — the heaviest write path, for a small append.
  - *Constraints.* A new vector-metadata key is filterable by default, so it counts against the
    2 KB filterable budget on every section vector (one `{by, at}` is ~70 bytes); non-filterable
    slots are fixed at index creation, so making it non-filterable would need a re-index.
    `last_verified` is a house key, not OKF — the schema resource (FR-18) must say it is the
    latest entry of `verified`. D35's objection to deriving `revised` from the history annotation
    does not apply: `verified` has no durable home other than its annotation.
  - *When promoted.* Recording a verification is `add_artifact_verification`, separate from
    `add_artifact_links` (D46). Adding the vector update makes it duplicate `add_artifact_links`'
    vector-write-and-failure-log path — extract that into a shared helper at that point rather
    than copying it. Migration of existing verifications is moot (none exist before this phase).
  Source: [`brainstorming-2026-09-17-okf-v02-adoption.md`](../brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md) (D41, D44).

- **B-4 — OKF import of foreign bundles.** Ingest an external OKF bundle into an Arkeology scope:
  the `migrating-to-arkeology` skill accepts an OKF bundle as an input source, and/or an
  `import_okf` tool that reads each concept, stores its content, and embeds it. Map OKF free-form
  `type` onto Arkeology's enum with a fallback for unmapped types (OKF consumers must not reject
  unknown types). In scope per the first-class OKF commitment (D6).
  Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D6).

- **B-16 — Match an artifact `type` regardless of case and punctuation.** Types are stored
  verbatim and matched exactly (T77 R3), so `attested computation` does not find
  `Attested Computation` — in Studio's "Other type…" box (T77 R6) or in any `type` filter of the
  tools. brainstorming-2026-09-17-okf-v02-adoption D37 rejected case-insensitive matching because
  S3 Vectors filters compare exactly, so it needs a second, normalised copy of `type`. *Idea to
  evaluate first:* store beside `type` a normalised copy — letters and digits only, lower-cased —
  in filterable vector metadata, and apply the same conversion to the `type` argument on the
  server before filtering, so `Attested Computation`, `attested-computation` and
  `attested_computation` all find it. The stored `type` stays verbatim and is what readers see.
  *To settle before it can be specced:* the new key counts against the filterable metadata budget
  on every section vector; existing vectors need it added (a store-migration step or a reconcile
  pass); two types differing only in case or punctuation (`Spec` and `spec`) would share one
  filter group, as T77 R7 already makes them share one id slug — intended? And whether a better
  option exists, for example a Studio dropdown built from the types actually in use. Needs a
  decision before it can be specced.
  Source: brainstorming-2026-09-17-okf-v02-adoption D37; T77 R6 (Operator, 2026-11-15).

## Operational tuning

- **B-11 — Repair a `link_metadata` vector-write failure without re-embedding the artifact.** When
  `link_metadata`'s vector-metadata write fails, it records a failure-log entry, and `reconcile_index`
  replays that entry through its full re-index path — re-embedding every section of the artifact
  through Bedrock. But `link_metadata` never changed the content or the embeddings; the divergence is
  metadata-only, and `link_metadata` itself repairs exactly that shape of divergence at zero Bedrock
  cost. A transient vector blip part-way through a 100-artifact `link_metadata` call therefore costs
  100 artifacts' worth of embedding on the next reconcile, to restore data no embedding is needed for.
  The fix is a metadata-only repair path in reconcile's Phase 1, selected by the entry's
  `failure_step`, falling back to the full re-index for entries that genuinely need one. Correctness
  is unaffected either way — the current behaviour produces the right result expensively, which is why
  this is an efficiency item rather than a defect and was deliberately excluded from the task that
  fixed its sibling findings.
  Source: 2026-09-06 diff review of commits since `35b04a8`.

- **B-7 — Unify per-tool concurrency bounds under one configurable mechanism.** `write_artifacts.py`
  is the only tool whose bounded-concurrency fan-out is caller-configurable (`artifact_concurrency`,
  default 3, clamped to `[1, 15]`). The Phase 12 T63 codebase-hygiene pass converted four more tools'
  sequential per-artifact loops to the same bounded-concurrency pattern
  (`purge.py`, `freshness.py`, `link_metadata.py`, `reconcile.py`) but each hardcodes its own fixed
  bound (`5`, matching `SECTION_CONCURRENCY`'s default) with no caller or operator override —
  reviewed and accepted as non-blocking for T63 itself, but the inconsistency is worth resolving.
  Two more instances hardcode the same bound of `5`: `list.py`'s `_fetch_link_fields` (the
  per-artifact link-field read) and, mirroring it, `propose_commit_links.py` (T58). With
  `include_links` off by default (T10 R11) the default listing makes none of those reads, so the
  `list.py` instance only matters for a caller that asks for the link fields. Include both in the
  unification.
  Propose a single, simple mechanism instead of independent bounds — e.g. one shared setting/
  constant, or extending `artifact_concurrency`-style per-call override to every tool that fans out — design-first:
  decide whether this should be a global server setting (env var, one source of truth, no per-call
  tuning) or a per-call parameter matching `write_artifacts.py`'s existing shape.
  Source: Phase 12 T63 review (2026-08-19).

- **B-8 — Two residual hand-rolled duplicates of patterns T68 just centralized, outside T68's own scope.**
  Phase 12 T68's review surfaced these while confirming F-2/F-6's extractions were complete — both
  predate T68 and are genuinely outside the findings' originally-cited scope, not something T68 missed:
  (1) `_error_code(exc)` (F-2, `credentials.py`) has two more hand-rolled copies of the identical
  `exc.response.get("Error", {}).get("Code", "")` idiom outside the client layer — `write.py`'s
  `_delete_orphan_vectors_with_retry` (landed with T67) and `startup.py`'s credential check — now
  importable and reusable now that `_error_code` lives in `credentials.py`. (2) `derive_last_edited_at`
  (F-6, `_search_helper.py`) has a third near-identical copy in `resources.py`'s markdown-resource
  `last_edited_at` deriver, with a slightly different warning message — F-6's originally-cited scope
  was only `search.py`/`propose_commit_links.py`. Low priority; fold into a future hygiene batch.
  Source: Phase 12 T68 review (2026-08-19).

- **B-17 — Let a migration descriptor name a repository file instead of carrying its text
  (design-first).** The migration skill reads every file and places its whole text in the
  descriptor's `content`, twice per document: once in the dry run, once in the write. The 2026-11-15
  specs trim the dry-run echo (T30 R16: the response returns the index and the description, not the
  document), but the write call still has the model compose every document into the tool call, and
  what is stored is whatever it emitted — no rule compares the submitted `content` with the file, so a
  dropped paragraph or a "tidied" table becomes the migrated artifact silently. *Idea:* a descriptor
  names a repository-relative file that the server reads, and keeps inline `content` for a caller with
  no file; the path form holds only while the server runs beside the files (stdio, on the developer's
  machine). *To settle before it can be specced:* **path confinement** — the server would read files
  named by the caller, and a prompt-injected document could name any readable file, so decide the root
  it may read under (the project directory, a configured root), how `..` and symlinks are handled, and
  where the contract states it; how the T56 content rewrite and the path-to-id map apply to text the
  server read; and whether the server returns a content hash so the skill can detect an edit between
  dry run and write. Needs an operator answer on the security question.
  **Resolve when Phase 15's tasks are planned** — build it, spec it, or drop it.
  Source: architecture review of 2026-11-15 (`.docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md`).

- **B-18 — Slim the agent-instruction snippet that setup copies into each project's `AGENTS.md`.**
  The 2026-11-15 specs give the snippet opening and closing markers carrying the release version, a
  replace-in-place rule, and a stamp check in the sync and migration skills (T31a R36–R37, T34 R8), so
  a project's copy can be refreshed. What is not done: the copy still carries tool names and call
  shapes that change with the server (the tool-call example's parameters, the post-commit linking
  steps, the pipeline reconcile and recovery rules), so every server release that changes one leaves
  every earlier project's copy wrong until someone refreshes it. *Idea:* leave in `AGENTS.md` only
  what is the project's own (the never-write lists, the ADR variant) and what must be read before the
  server answers, and point to the server's guidance resources (`arkeology://schema/*`) for tool
  names and call shapes. *To settle:* whether an agent reliably reads a resource at session start in
  every host, and whether, once the copy is small, the stamp and refresh machinery still pays for
  itself. Phase 15 renames the tool surface and so changes every project's snippet, which is why this
  has to be decided before that release.
  **Resolve when Phase 15's tasks are planned** — before the renaming release.
  Source: architecture review of 2026-11-15 (`.docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md`).

- **B-19 — Make post-commit link discovery independent of the commit and free of gaps.** Two
  defects in how an agent finds the artifacts a commit should link. (1) `propose_commit_links` takes a
  `commit_sha` that it only echoes back (T37 R6, response shape): the agent must run `git rev-parse
  HEAD` before it may ask "what is unlinked?", although discovery returns the same result for any
  SHA. Make it optional or drop it and its echo; the caller passes the SHA to the link call. (2) The
  cursor for the next proposal, `next_since_ulid`, is minted by the link call after its loop (T49), so
  an artifact written between the proposal and the link — the same agent's session summary, or another
  of the developer's agents — is later than the cursor and is never proposed again. Return the cursor
  from `propose_commit_links`, minted before its scan, adopt it after a successful link, and have the
  link tool return none. Both change the `propose_commit_links` and `link_metadata` contracts and the
  post-commit protocol (T31a R35); the contracts are unchanged for now by ruling.
  **Resolve when Phase 15's tasks are planned** — T84 rewrites the link tool, so decide there whether
  the cursor and the parameter change with it.
  Source: architecture review of 2026-11-15 (`.docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md`).

## Test isolation

- **B-15 — Unit tests write into the real failure log.** `tests/unit/conftest.py`'s settings
  helper redirects `FAILURE_LOG_PATH` to a temporary file only when a test passes `tmp_path`, so a
  test that drives a failure path without it appends to the default log. Every entry in this
  repository's root `.arkeology_failures.jsonl` — 790 on 2026-11-10, all under the unit-test write
  prefix `artifacts`, five of them from that day's run — came from unit tests. Once the default
  moves to the per-user location (T15 R7), the same tests would write into the developer's real
  per-user log for that artifact bucket, which every server that developer runs against the
  bucket reads, so this lands with or before that change. Fix direction: every unit test runs with `FAILURE_LOG_PATH` redirected to a
  per-test temporary file — for example an autouse fixture in `tests/unit/conftest.py` — and a
  test that needs a specific path still overrides it.
  Source: architecture review of 2026-11-10 (`.docs/reviews/architecture-review-2026-11-10-arkeology.md`).

## Design alignment

- **B-20 — Bring the code, skills and installer in line with the specs the 2026-11-15 architecture
  review changed.** The review's fixes edited specs, contracts, ADR revisions and requirements only;
  shipped code, skills and scripts still do what the older text said. One group per area:
  - *Server code:* `migrate_artifacts.py` — dry run returns `{index, description}` (the rewritten
    content only when the reference map is non-empty), stop honouring a descriptor's `overwrite`, an
    empty generated description is a generation failure; `link_metadata.py` — the stopping error
    carries the failing `artifact_id` and `linked_ids`; `reconcile.py` — an `error` code on every failed
    or stuck entry, the stuck-group check with `failure_log_superseded`, re-apply the link values to
    the annotation before pruning; `artifact.py` — `validate_references` rejects an element without
    `/`, remove `REFERENCE_FIELDS` (one single-field reverse lookup, with `_search_helper.py`);
    `write.py` — delete `_delete_orphan_vectors_with_retry` and its constants; `resources.py` — remove
    `_artifact_last_modified`; `list.py` and `server.py` — `include_links`, default off;
    `propose_commit_links.py` — stop putting `$gte since_ulid` in the index filter.
  - *Remove the fourth annotation operation:* `list_object_annotations` in `interfaces.py`, `s3.py`,
    the `credentials.py` message, `startup.py` `_check_annotations`, `tests/unit/conftest.py`, the
    tests and the integration test; `s3:ListObjectAnnotations` in the README and SERVER-REFERENCE.md
    IAM lists and in the setup skill's "four required IAM actions"; the two `AGENTS.md` lines that
    still say four.
  - *Skills and scripts:* `migrating-to-arkeology` (no concurrency prompt, batches of 15, the status
    mapping, no last completion step, no `unresolved_references`, the stamp check); `schema.yaml`
    (`artifact_id`); delete `scripts/validate_manifest.py` and
    `plugins/arkeology/skills/backfilling-references/` with its README row; the setup skill
    (restart and resume steps, absolute path, text model); `agents-snippet.md` (markers, stamp,
    rewritten post-commit protocol); the sync skill (Copilot pull before install, OpenCode check before
    clearing the cache, final snippet check); `install.sh` (print the exact `git -C … pull`
    pre-approval with `~` unexpanded — verify Claude Code matches it — remove the old wildcard
    rule, the `claude plugin list` check, name `claude plugin marketplace update arkeology`);
    `scripts/validate.py` (exit 1 on a missing skills folder).
  - *Tests:* new `test_snippet_stamp_drift.py`; `test_skill_artifact_id_drift.py` drops the backfill
    parameter; `test_tools_list`, `test_server`, `test_data_resources` for `include_links`.
  - *Release process:* `agents-snippet.md` becomes a version file.
  **Resolve when Phase 15's tasks are planned** — as tasks of Phase 15, each alongside the task whose
  spec it implements (T30, T31a, T33c, T34, T39, T40, T49, T51), none left to the end.
  Source: architecture review of 2026-11-15 (`.docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md`).

---
type: plan
title: Backlog
description: All work waiting to be started for Arkeology — deferred improvements, issues, and not-yet-built features organised by topic with stable IDs.
tags: []
timestamp: 2026-06-16T00:00:00Z
okf_version: "0.1"
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
  and remove all cross-references to it in specs, ADRs, the review register, and `plan.md`.

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

- **B-9 — Cross-scope gate raises on malformed foreign metadata, aborting the whole
  operation.** `is_cross_scope_readable` coerces `tier` with a bare `int(meta.get("tier", 0))`.
  That coercion is required — `read_artifact` passes S3 object metadata where `tier` is a
  stringified int, while `list_artifacts` and `search_artifacts` pass vector metadata where it
  is an int — but it is unguarded, so a non-numeric or non-scalar value raises instead of
  denying:

  | `tier` value | Result |
  |---|---|
  | `3`, `"3"` | readable (both encodings, pinned by test) |
  | `2`, `"2"` | denied (pinned by test) |
  | absent | denied (pinned by test) |
  | `"abc"` | **raises `ValueError`** |
  | `None`, `[3]` | **raises `TypeError`** |

  Confidentiality is unaffected: the exception is caught by the tool's outer
  `try/except Exception` and returned as `internal_error`, so nothing leaks. **Availability is
  the problem.** The gate is applied per candidate inside a loop in `list.py`,
  `_reference_filter.py`, and `freshness.py`, so one artifact with malformed metadata aborts the
  entire listing or reference resolution for that scope rather than skipping that one candidate.

  Why this is not hypothetical: cross-scope reads consume metadata **this deployment did not
  write**. Own-scope metadata is written from a validated `Artifact` whose `tier` is constrained
  to `{2, 3}`, but a foreign scope's records come from another team's deployment — possibly a
  different version, a partially-completed `migrate_artifacts` run, or a manually-edited record.
  A data-quality problem in another team's scope becomes an outage in yours.

  Two candidate fixes, needs a decision before spec:
  1. **Coerce defensively in the gate** — treat an uncoercible `tier` (or `visibility`) as
     not-readable and log at warning level. Fail closed per candidate, which is the standard
     posture for an access-control predicate, and the loops keep running. Cost: silently
     tolerates corruption that currently surfaces loudly.
  2. **Guard at the loop** — leave the gate strict and have each call site skip a candidate
     whose gate evaluation raises. Keeps the gate's contract sharp but repeats the guard at
     three-plus call sites, which is the duplication `_scope.py` exists to prevent.

  Option 1 is the smaller and more consistent change; option 2 preserves the loud signal. Either
  way the fix belongs in or beside `_scope.py`, inside the declared mutation-testing Scope, and
  wants a test per malformed shape.

  Found while investigating the mutation-survivor issue's claim that the gate had no
  absent/malformed metadata coverage — the absent cases turned out to be covered, the malformed
  ones not.

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

- **B-4 — OKF import of foreign bundles.** Ingest an external OKF bundle into an Arkeology scope:
  the `migrating-to-arkeology` skill accepts an OKF bundle as an input source, and/or an
  `import_okf` tool that reads each concept, stores its content, and embeds it. Map OKF free-form
  `type` onto Arkeology's enum with a fallback for unmapped types (OKF consumers must not reject
  unknown types). In scope per the first-class OKF commitment (D6).
  Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D6).

## Operational tuning

- **B-7 — Unify per-tool concurrency bounds under one configurable mechanism.** `write_artifacts.py`
  is the only tool whose bounded-concurrency fan-out is caller-configurable (`artifact_concurrency`,
  default 3, clamped to `[1, 15]`). The Phase 12 T63 codebase-hygiene pass converted four more tools'
  sequential per-artifact loops to the same bounded-concurrency pattern
  (`purge.py`, `freshness.py`, `link_metadata.py`, `reconcile.py`) but each hardcodes its own fixed
  bound (`5`, matching `SECTION_CONCURRENCY`'s default) with no caller or operator override —
  reviewed and accepted as non-blocking for T63 itself, but the inconsistency is worth resolving.
  A sixth, pre-existing instance: `list.py`'s `_fetch_link_fields` fans out an **unbounded**
  `asyncio.gather` (no semaphore at all) over every distinct candidate artifact_id, and T58's
  `propose_commit_links.py` fix (`docs/specs/p12-t58-commit-refs-cap-references-removal.md`)
  deliberately mirrored that exact pattern — so the same unbounded fan-out now exists in two tools,
  predating T63 and out of its scope. Include both in the unification.
  Propose a single, simple mechanism instead of five independent bounds — e.g. one shared setting/
  constant, or extending `artifact_concurrency`-style per-call override to all five tools — design-first:
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

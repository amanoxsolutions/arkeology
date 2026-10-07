---
type: Plan
id: plan
title: Plan Arkeology
description: Full phase history and current open phase for Arkeology development, tracking all completed and in-progress tasks from foundation through OKF schema alignment.
tags: []
okf_version: "0.2"
generated:
  by: "axians-pm/unknown"
  at: 2026-05-29T10:46:28Z
revised:
  by: "axians-pm/claude-opus-5.5"
  at: 2026-10-07T12:05:41Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Plan: Arkeology

_Project: arkeology_ · _Generated: 2026-05-29_ · _Last updated: 2026-10-07_ · _Status: **Phases 1–14 complete · Phase 15 open · latest tag v0.7.0**_

## How we work

This project runs as a **single open phase**, not a pre-planned roadmap. Completed phases stay below as a full history (every feature marked ✅); the current phase shows its tasks in detail; and anything not yet started — issues, deferred work, and scoped-but-unbuilt features — lives in [`backlog.md`](backlog.md), pulled into the current phase when we decide to tackle it. There are no pre-planned future phases beyond the current one, and a phase ends when we judge it done.

- **Requirements** (FR/NFR/AC/Constraints) live in [`requirements.md`](requirements.md) and product vision lives in [`vision.md`](vision.md) — this plan references requirement IDs, it does not redefine them.
- **Per-task implementation detail** lives in [`../specs/`](../specs/) as `p<phase>-t<task>-<slug>.md` (e.g. task 3 of Phase 10 → `p10-t3`).
- **Status legend:** ⬜ pending · 🔄 in progress · 🔍 in review · ✅ done · 🔴 blocked
- **Delivery model:** each **Phase** is a coherent slice of value delivered as a set of tasks. A phase ends when we judge it done.

**Current state:** Phase 15 — OKF v0.2 Adoption is open (T76–T91). Phases 1–14 are complete, and the latest tag is v0.7.0.

---

## Notes

- **TDD throughout** — tests written before implementation on every task (NFR-07)
- **Layered architecture from day one** — AWS client interfaces established in Phase 1; all subsequent tasks build on them, never bypassing them (NFR-04)
- **Integration tests must clean up after themselves** — once `delete_artifact` is implemented (T12), all integration test teardown fixtures must call `delete_artifact` to remove every artifact written during the test run; existing integration tests for T7–T9 must be updated at the same time as T12 is delivered

---

## Phase 1 — Foundation: runnable server with startup validation

Goal: a server skeleton that starts, validates all configuration, and fails clearly on any misconfiguration, with no tools yet.

1. ✅ **Bootstrap Python project** — project must be installable and testable from source (NFR-08, NFR-09).

2. ✅ **FastMCP server skeleton** — stdio transport, structured logging, graceful shutdown; no tools registered yet (NFR-05).

3. ✅ **AWS client layer** — S3, S3 Vectors, and Bedrock each behind a typed interface, with HTTPS enforced and credential failures re-raised as structured typed errors (NFR-04, NFR-10, FR-12, D2).

4. ✅ **Configuration model** — every required and optional environment variable parsed and validated at process start.

5. ✅ **Startup validation sequence** — credentials, `WRITE_PREFIX` read/write, each `READ_PREFIXES` entry read, vector index existence, embedding model ↔ index dimension match; any failure is a hard stop with a distinct actionable error (FR-07, NFR-03).

---

## Phase 2 — Core value loop: write, search, read

Goal: the minimum viable loop — an agent writes an artifact and immediately finds it via semantic search.

6. ✅ **Artifact model and key generation** — the metadata schema and deterministic tier 2 (date-anchored) and tier 3 artifact keys (FR-09, FR-08).

7. ✅ **Write artifact tool** — content stored in S3 and one embedding vector per `##` section (document-level fallback), with orphan-section cleanup on rewrite, tier 2 immutability, tier 3 in-place overwrite, and idempotent same-key writes (FR-01, FR-13, FR-15, NFR-06).

8. ✅ **Search artifacts tool** — semantic search over own scope plus shared tier 3 foreign scopes through a bounded re-fetch loop, grouping section vectors per artifact and returning metadata and description only (FR-03, NFR-02).

9. ✅ **Read artifact tool** — S3 GetObject by identifier; cross-scope gate enforced (FR-02, FR-10).

---

## Phase 3 — Complete tool surface: list, archive, delete, health, reliability

Goal: an operationally complete server — agents list, archive, and delete artifacts, admins diagnose health, and partial write failures are never silent.

10. ✅ **List artifacts tool** — metadata-only listing with filters (type, feature tags, team, project, tier, status); no semantic ranking; cross-scope gate enforced (FR-04).

11. ✅ **Archive artifact tool** — update `status` in S3 Vectors metadata to inactive; scoped to `WRITE_PREFIX` only; no content modification (FR-05, FR-14).

12. ✅ **Delete artifact tool** — confirmed own-scope hard delete, vectors first then the S3 object, warning but proceeding when the artifact is a synthesis source, with a partial delete recoverable via reconciliation (FR-21, FR-13, FR-14, AC-19).

13. ✅ **Purge archived tool** — confirmed bulk hard delete of all inactive own-scope artifacts, cascading to any synthesis whose every source is purged (FR-22, AC-20).

14. ✅ **Health check tool** — independent per-component status: S3, S3 Vectors, Bedrock, `WRITE_PREFIX`, each `READ_PREFIXES` entry (FR-06).

15. ✅ **Partial write failure log** — an S3-success/vector-failure write is recorded in a local failure log before the error surfaces, and a Bedrock throttle is retried once with back-off (FR-16, NFR-11).

16. ✅ **Synthesise artifacts tool** — semantic search returning the bundled full content of the top-k source artifacts, for the agent to synthesise in-context and write back as a tier 3 `synthesis` (FR-19).

---

## Phase 4 — Self-documentation and adoption *(T18–T20 can start in parallel with Phase 3)*

Goal: any agent discovers the schema at runtime, and a new team adopts the server from the README and AGENTS.md snippet alone.

17. ✅ **Run full integration test suite** — the T7–T16 integration tests run against live AWS, resolving open question Q1 (upsert behaviour) and closing the Phase 3 retrospective (NFR-07).

18. ✅ **MCP Resources** — expose artifact schema, tier model, visibility and cross-scope model, type catalogue, and query strategy guidance as MCP Resources; always in sync with running server version (FR-18).

19. ✅ **Setup documentation and AGENTS.md snippet** — README quick start, configuration reference, minimum IAM policy, AWS provisioning steps (including the index settings that are immutable after creation), an `mcp-servers.json` example, and a recommended AGENTS.md usage snippet (NFR-12).

20. ✅ **Migration skill** — the `migrating-to-arkeology` skill with agent-only and manifest-plus-script paths, a PEP 723 `migrate.py` bulk-write script with dry-run mode, and the `ARKEOLOGY_IMPORT.yaml` manifest schema (FR-23, NFR-12).

---

## Phase 5 — Could-have: reconciliation and synthesis freshness

21. ✅ **Reconciliation tool** — failure log replay + full S3 vs vector index orphan scan (including partial-delete orphans); re-index missing entries; remove resolved failure log entries; return structured summary (FR-17).

22. ✅ **Synthesis freshness check tool** — a report flagging syntheses whose sources were updated more recently (stale) or archived (orphaned) (FR-20).

---

## Phase 6 — Production Hardening (Review Fix Cycle)

Goal: resolve all 76 findings (12 critical, 27 major, 37 minor) from the full project code review, with no new functionality.

23. ✅ **Implement all 20 review-fix specs** — the Phase 6 hardening fixes, spanning credential-error handling, vector score semantics, the shared search helper, test infrastructure, the ABC→Protocol and `filter`→`filter_expr` migrations, and the Apache 2.0 licence.

24. ✅ **V1 integration suite re-run** — full integration test suite re-run against live AWS after Phase 6 hardening; all tests pass; V1 declared clean.

---

## Phase 7 — Test infrastructure: moto migration

Goal: replace the hand-rolled S3 and S3 Vectors fakes with moto-backed real clients, fixing the score-range inconsistency between unit tests and production.

25. ✅ **Migrate unit tests from hand-rolled fakes to moto** — `FakeS3Client`/`FakeVectorsClient` replaced by moto-backed real clients plus a cosine-similarity `query_vectors` extension, with score assertions corrected to the production `[−1, 1]` range (FR-mock-conv).

---

## Phase 8 — Write Performance

Goal: remove the dominant latency bottlenecks in `write_artifact` and `migrate.py` with no new tools or breaking changes (specs `docs/specs/p8-t26-*.md` through `docs/specs/p8-t29-*.md`).

26. ✅ **P1 — Concurrent embedding + batched put_vectors** — section embeds run concurrently, bounded by a new `SECTION_CONCURRENCY` setting, and each artifact's vectors are written in one batched call (NFR-13, NFR-14).

27. ✅ **P2 — Retry and throttle fix** — the duplicate Bedrock throttle retry removed from the write path and jitter added to the client's retry back-off (NFR-11).

28. ✅ **P3 — Configurable section caps** — `EMBED_MAX_SECTIONS` and `EMBED_MIN_SECTION_LENGTH` bound which sections are embedded, falling back to a document-level embed when none remain (FR-01, NFR-13).

29. ✅ **L1+L2 — Migration skill parallel writes** — the migration skill split into three size-banded paths (sequential, manifest + script, parallel sub-agents) and `migrate.py` gained bounded concurrent writes via `MIGRATE_CONCURRENCY` (FR-23, NFR-15).

---

## Phase 9 — Improvements and Fixes

Goal: quality-of-life improvements and documentation polish before declaring v1, plus the v0.3.0 artifact commit-references feature.

30. ✅ **Z1 — `write_artifacts` + `migrate_artifacts` bulk tools** — the two bulk-write MCP tools.

31. ✅ **Setting-up-arkeology skill** — a six-step workflow that collects parameters, pre-flight checks the externally provisioned AWS resources, writes the MCP client config with operator permission, smoke-tests via `health_check`, and records permanent Arkeology exclusions in AGENTS.md (FR-24, FR-44, NFR-12, AC-28, AC-29, AC-40, AC-42, AC-49).

32. ✅ **Reconcile Phase 3 — dangling vector pruning** — an always-on third `reconcile_index` phase that deletes vectors whose backing S3 object no longer exists, reported in three new additive response fields.

33. ✅ **Skill distribution via native plugin mechanisms** — `setting-up-arkeology` and `migrating-to-arkeology` distributed to engineers' AI tools through native plugin mechanisms, with no server code.

34. ✅ **`sync-arkeology-plugin` — generic tool-aware skill update** — a skill that detects the AI coding tool it runs in and applies that tool's update action.

---

## Phase 10 — Artifact Commit References + OKF Schema Alignment + MCP Data Resources

Goal: link artifacts to git commits (T35–T40), rename `feature_tags` to `tags` for OKF alignment (T41), and expose MCP data resources for browsing artifacts (T42).

35. ✅ **Filter range operators ($gte / $lte)** — inclusive string-comparison operators added to the in-process filter evaluator (FR-30).

36. ✅ **`commit_refs` and `last_edited_ulid` metadata fields** — both fields added to the artifact model, stored in S3 and vector metadata, and surfaced by `write_artifact`, `list_artifacts` (with a `commit_refs` filter) and `read_artifact`, with legacy artifacts returning `None` (FR-28, FR-29).

37. ✅ **`propose_commit_links` tool** — read-only discovery of own-scope artifacts with no `commit_refs`, optionally bounded by a `since_ulid` cursor (FR-31).

38. ✅ **`link_commit` tool + AGENTS.md post-commit protocol** — merged a commit SHA into confirmed own-scope artifacts' `commit_refs` without re-embedding, plus a post-commit protocol snippet in the setup skill; later superseded by `link_metadata` (T49) (FR-32).

39. ✅ **Caller-controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`** — the `ARTIFACT_CONCURRENCY` setting replaced by a per-call parameter that is clamped with a warning rather than rejected, with the migration skill batching by it (FR-23, FR-25, FR-26, NFR-14, NFR-15).

40. ✅ **Migration skill `commit_refs` backfill options** — a skill-only change offering three post-write choices: no backfill (default), rely on the migration-time `last_edited_ulid`, or backfill from git history via `link_commit` (D12).

41. ✅ **Rename `feature_tags` → `tags`** — a pure identifier rename across the model, tool parameters, both metadata stores, tests, docs, and skills, preserving the dual encoding with no data migration (D2, `brainstorming-2026-06-15-okf-alignment.md`).

42. ✅ **MCP data resources** — `arkeology://artifact/{id}` and `arkeology://artifacts` resources for human-facing artifact browsing, the former gated exactly like `read_artifact` (FR-46, AC-51, AC-52).

---

## Phase 11 — Visual Reading Interface (MCP Apps)

Goal: an interactive artifact browser, `arkeology_studio`, rendered inline in MCP App hosts with faceted filtering, semantic search, and markdown and mermaid rendering, needing no new AWS infrastructure and routing every call through the existing scope gate.

**Execution order:** T43 (server-side infrastructure) was the prerequisite for T44 (browser UI).

43. ✅ **Server-side MCP App infrastructure and `arkeology_studio` tool** — the `arkeology_studio` tool, with a plain-text fallback for hosts without the UI extension, and the CSP-declared `ui://arkeology-studio/index.html` resource serving the packaged HTML (FR-47, FR-48; ADR-010).

44. ✅ **Browser UI (HTML/JS)** — the self-contained `arkeology-studio.html` browser with filter controls, artifact listing, a markdown and mermaid document viewer, and semantic search (FR-47, FR-48, FR-49).

---

## Phase 12 — Artifact Cross-Referencing + Annotation-Backed Link Storage

Goal: a first-class `references` field, S3 object annotations as the durable store of `commit_refs`/`references` so they survive `reconcile_index`, `link_commit` generalised into `link_metadata`, and an own-scope `referenced_by` warning on delete and archive (FR-51–FR-58, revising FR-32, FR-17, FR-28, FR-09; design decisions D1–D15 in `docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md`).

This phase superseded Phase 10's vector-only `commit_refs` storage with annotation-backed storage, revising specs `p10-t36`, `p10-t38`, `p10-t40`, `p2-t9`, and `p5-t21` (ADR-011).

45. ✅ **S3 object annotation client support + moto self-mock extension** — annotation put/get/list/delete on the S3 client interface and implementation, with a moto self-mock for tests (FR-54).

46. ✅ **`references` first-class field on the `Artifact` model + write / read / list surfacing** — a `references` field accepted at write and returned by write, read, and list, with a `list_artifacts` filter; its vector-metadata copy and that filter were later removed by T58 and T59 (FR-51).

47. ✅ **Annotation dual-write in the write path + overwrite preservation** — the write path stores `commit_refs`/`references` in S3 object annotations durable-first and carries them forward across an overwriting write (FR-54, FR-55).

48. ✅ **`reconcile_index` rebuilds `commit_refs` + `references` from annotations** — re-indexing restores both link fields from the object's annotations (FR-17, FR-54; OQ2).

49. ✅ **`link_metadata` tool — generalizes and supersedes `link_commit`** — an idempotent, own-scope merge of supplied `commit_refs`/`references` without re-embedding, retiring `link_commit` while keeping `propose_commit_links` (FR-53, FR-31; supersedes FR-32).

50. ✅ **Unified own-scope `referenced_by` warning on delete + archive** — delete and archive warn, without blocking, about other own-scope artifacts citing the target in `source_artifacts` or `references`; the `references` half was later dropped by T60 (FR-56, FR-21).

51. ✅ **Migration frontmatter reference rewriting + `arkeology://` content rewrite** — migration resolves frontmatter `references:` paths through a manifest-wide path→identifier map into `references`, rewriting resolved targets in stored content to `arkeology://artifact/{id}` (FR-52).

52. ✅ **`setting-up-arkeology` annotation availability + IAM check; runtime graceful handling; README + AGENTS.md** — an annotation availability and IAM probe in the setup skill, the required IAM actions documented, runtime graceful handling of unavailable annotations, and `arkeology://` referencing guidance in the AGENTS.md snippet; the no-startup-gate stance (D15) was later reversed by T73 (FR-57, NFR-12; D9, D15).

53. ✅ **Reference-backfill cleanup skill** — an optional skill that proposes `references` backfills from a content scan in a dry-run report and applies only confirmed ones via `link_metadata` (FR-58; OQ1-cleanup).

54. ✅ **Search age transparency** — every `search_artifacts` result carries `last_edited_ulid` and a derived ISO 8601 `last_edited_at`, with no ranking change (recency-weighted ranking deferred to backlog B-6).

55. ✅ **Write-path metadata size + charset validation** — writes fail fast with a structured error when metadata exceeds the S3 or vector budgets, control characters are neutralised, `title` length is bounded, and non-ASCII titles are preserved consistently (FR-59, AC-67).

56. ✅ **Deterministic, server-side content reference rewrite (frontmatter + body)** — `migrate_artifacts` itself rewrites every occurrence of an already-resolved frontmatter reference path, in frontmatter and body link targets, to `arkeology://artifact/{id}`, reversing ADR-012's skill-only rewrite for this bounded case (FR-52; ADR-012).

57. ✅ **Guard coverage in `link_metadata.py` and `reconcile.py`** — both paths run the metadata-budget check before their vector write, as the write path already did (ADR-2026-08-13 D1; also closes I-4).

58. ✅ **Split-store decision: `references` removed from S3 Vectors metadata, `commit_refs` capped at 20** — annotations became the sole store of `references`, and the vector copy of `commit_refs` keeps only the 20 most recent entries while annotations keep the full list (ADR-2026-08-13 D2; also closes I-2).

59. ✅ **Remove `references=` filter param from `list_artifacts`; `commit_refs=` unchanged** — a breaking removal, since `references` is no longer vector-filterable after T58 (ADR-2026-08-13 D6; OQ6).

60. ✅ **Narrow the delete/archive reverse-lookup warning to `source_artifacts`; document the `references` gap** — the `referenced_by` warning scans only `source_artifacts`, with the lost `references` coverage documented rather than worked around (ADR-2026-08-13 D6; OQ6).

61. ✅ **Migration self-heal: `skipped_unindexed` classification** — migration reports a candidate that exists in S3 but is unindexed as `skipped_unindexed` and points it at `reconcile_index` (ADR-2026-08-13 D3; OQ3).

62. ✅ **Bounded `reconcile_index` failure-log retry** — a failure-log entry stops auto-retrying after three failed replays and is reported once in a new `stuck_failures` field (ADR-2026-08-13 D4; OQ4; also closes H-2).

63. ✅ **Codebase-hygiene pass: shared scope-check/cross-scope/fetch helpers + bounded concurrency** — the shared `is_own_scope`, `is_cross_scope_readable`, and `fetch_vectors_by_metadata` helpers, plus bounded concurrency for the remaining sequential per-artifact loops (I-3, F-1, F-3, H-1).

64. ✅ **I-6 — Validate `file_extension` starts with `.` in `migrate_artifacts.py`'s skip-existing pre-check** — rejected with the same validation error `write.py` uses.

65. ✅ **J-2 — `check_synthesis_freshness(confirm=True)`'s `all_fresh` must also require `delete_failed` empty** — a malformed synthesis whose S3 delete failed no longer lets `all_fresh` report true.

66. ✅ **C-1 — Distinguish `VectorDistanceMissingError` (index corruption) from ordinary transient errors in `run_search_loop`** — index corruption gets a distinct log line and a response-level flag, without aborting the search or dropping partial results.

67. ✅ **J-1 — `write_artifact`'s orphan-vector cleanup: retry inline, fall back to a `reconcile_index` repair mechanism** — orphan-vector deletion retries inline and, once exhausted, logs a new failure-log entry kind that `reconcile_index` repairs under T62's bounded-retry rules.

68. ✅ **Cleanup-hygiene batch 2: reuse/DRY findings F-2, F-4, F-5, F-6, G-1, G-3 + H-3 concurrency** *(no dedicated spec)* — seven small shared helpers and fixes, each closing one duplication or latency finding.

69. ✅ **Convention-class cleanup: C-2, C-3, D-1, E-1, E-2, I-1** *(no dedicated spec)* — the six remaining convention-class findings from the 2026-08-13 full-codebase review, none a broken behaviour.

---

## Phase 13 — Artifact Type Vocabulary: `prd` → `vision` + `requirements`

Goal: replace the `prd` artifact type with `vision` and `requirements`, mirroring the planning-artifact convention this project itself follows.

70. ✅ **Rename `prd` type to `vision` + `requirements`** — the two new types replaced `prd` across the type vocabulary, resources, skills, Studio, and docs, recorded as a breaking change in the changelog.

---

## Phase 14 — Consistency Review Remediation

Goal: close the findings of the 2026-09-05 whole-repository consistency review, the 2026-09-06 diff review, and the Minor-severity batch of the 2026-09-06 full-codebase review, whose Major findings were closed without task numbers.

71. ✅ **Reject a literal comma inside a `tags` or `source_artifacts` element** — such a write now returns `validation_error` instead of silently diverging S3 and vector metadata.

72. ✅ **Resolve a failure-log entry whose artifact no longer exists, instead of replaying it forever** *(scope of record: the `arkeology.tools.reconcile` contract and the `Revision — 2026-09-05` section of `p12-t62-bounded-reconcile-retry.md`)* — such an entry is pruned and reported once in `reconciled` under a new `failure_log_obsolete` source.

73. ✅ **Make S3 object annotations the sole source of truth for link fields, gated at startup** — replaced the dual-store read, which cost a full vector-index scan per artifact, with annotation-only reads and a startup gate on annotation availability (C-08, FR-57; reverses ADR-011 decision 5).

74. ✅ **Fix the 2026-09-06 diff-review findings** *(no dedicated spec)* — closed the review of commits `35b04a8..88cc6e5`, correcting the affected contracts and requirements to the sole-source-of-truth model and adding AC-68 to pin the annotation restore rule (FR-17, FR-51, FR-54, FR-56, C-07, AC-57, AC-59, AC-60, AC-61, AC-68).

75. ✅ **Minor-hygiene batch: startup/health robustness, sanitized error echoes, stale-comment cleanup, and shared-helper reuse** *(no dedicated spec)* — a structured startup error for unmapped `get_object` failures, per-invocation health probe keys, two stale comments corrected, shared error-helper reuse, and four cross-module private names made public; the MN-9 sanitized error echo was later reverted, so every surface again reports the underlying exception text (MN-1, MN-8, MN-9, MN-10, MN-14, MN-16, MN-20).

## Phase 15 — OKF v0.2 Adoption

Goal: make Arkeology a full OKF v0.2 consumer and store — lifecycle keys that no longer collide,
first-class provenance, structured `sources`/`relationships`, producer-supplied identifiers, an
open type list, and an in-force default view — as one breaking release, with a store-migration
skill for deployments that already hold artifacts. Decisions:
[`adr-2026-09-25-okf-v02-adoption.md`](../architecture-decisions/adr-2026-09-25-okf-v02-adoption.md),
from [`brainstorming-2026-09-17-okf-v02-adoption.md`](../brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md).
Requirements: FR-01, FR-04, FR-05, FR-08–FR-10, FR-14, FR-15, FR-17–FR-23, FR-46, FR-48,
FR-51–FR-56, FR-58, FR-59, FR-67–FR-74, C-01, C-07, C-08.

**How each task runs (TDD).** Every task below changes behaviour, so each gets its own spec in
`docs/specs/p15-t<n>-<slug>.md` before any code. Per task: spec → contract amendments in
`docs/contracts/` → tests written and **confirmed failing** (red) → implementation until the unit
suite, ruff, mypy and `npm test` are green. A task is ✅ only when all of that holds. No aliases
for removed names (D42): each rename task also proves the old name is rejected with a
`validation_error` naming its replacement (AC-80).

**Integration tests move with the code.** CI does not run `tests/integration/`, so a task that
changes a tool's signature or behaviour also updates, in the same task, every integration test
that change breaks — the rule Phase 2 applied to T7–T9 when T12 landed. A task is ✅ only once
those tests are updated; the full integration suite passing against real AWS gates the release
(T91).

**Ordering.** Tasks are listed in dependency order and each names what blocks it. T76 must land
before T81 — renaming `status` → `archived` before OKF `status` is introduced keeps one key from
meaning two things. Tasks marked *parallel* touch disjoint code and may run concurrently.

76. ⬜ **Archive marker `status` → `archived: bool`** — delete `ArtifactStatus`; store `archived` in
    S3 object metadata and filterable vector metadata where `status` is today; every tool
    parameter, response field and filter expression, Studio's facet, and the `status: all`
    sentinel convention move to the boolean (`false` default, `true`, omitted for all).
    `reconcile_index` reports and rebuilds, from S3 object metadata, any vector whose `archived`
    is missing or not a boolean (D50). Done: archive, list, search, synthesise, purge, delete, studio and resources use `archived`
    only; AC-08, AC-20, AC-52, AC-54 pass; the old `status` parameter is rejected (AC-80).
    (FR-04, FR-05, FR-09, FR-14, FR-17, FR-22, FR-46, FR-48; D21, D50)

77. ⬜ **Open type list** *(parallel with 76)* — accept any `type`, stored and matched verbatim;
    known types become a recommended list in the schema resource; legacy code comparisons
    (`type == "synthesis"` in `find_referrers` and freshness) move to OKF display names; Studio
    gets a default style for unknown types; a generated id still slugifies the type, so existing
    ids are unchanged. Done: AC-77 passes; `ARTIFACT_TYPES` is no longer a validator.
    (FR-09, FR-18, FR-48; D37)

78. ⬜ **Split writing into `create_artifact` / `update_artifact`; drop `overwrite`** *(parallel
    with 76, 77)* — `create_artifact` succeeds only if the key does not exist (atomic, S3
    `IfNoneMatch: *`) and returns the id; `update_artifact` takes the `artifact_id`, succeeds only
    if the key exists (`not_found` otherwise), and fully replaces content and metadata — S3 objects
    are immutable, so there is no partial patch. The key never changes on update, so retitling
    keeps the id; `tier`, `team`, `project` and `type` cannot change on update. The update writes
    with S3 `If-Match` on the ETag it read, so an update racing a delete returns `not_found` and
    never recreates it; an optional caller `if_match` (the `last_edited_ulid` it read) fails the
    update with `conflict` if the artifact changed since. Same split for the
    bulk tools: `write_artifacts` → `create_artifacts` plus a new `update_artifacts`;
    `migrate_artifacts` stays create-only. Case-only duplicate ids are accepted. Done: AC-04,
    AC-05, AC-82–AC-86 pass; `write_artifact`, `write_artifacts` and `overwrite` are rejected
    (AC-80). (FR-01, FR-08, FR-13–FR-15, FR-25, FR-75, FR-76, C-05; D51)

79. ⬜ **Provenance: `generated` / `revised`; drop `date`, `author_role`, `timestamp`** — `generated:
    {by, at}` required and written once, carried forward on every overwrite; `revised` absent
    until the first overwriting content write; `at` values are ISO 8601 UTC with `Z` and compared
    as parsed datetimes; a generated tier-2 id anchors on the UTC day of `generated.at` (ADR
    default; the spec confirms it); link
    backfills, archive, lifecycle changes, verifications and reconciliation never move `revised`.
    Done: AC-04, AC-64, AC-72 pass; `date`/`author_role` are rejected (AC-80).
    Blocked by 76, 78. (FR-01, FR-08, FR-09, FR-15, FR-17, FR-59, FR-69; D9, D19, D32, D35)

80. ⬜ **Revision-history annotation + shared compare-and-swap append helper** — one `{by, at}`
    entry appended per content write in its own annotation, uncapped; carried across overwrites;
    returned by `read_artifact`, omitted from listings unless asked. The append helper is built
    once here and reused by 83. Done: AC-75 passes. Blocked by 79. (FR-54, FR-72; D26, D30, D31, D34)

81. ⬜ **OKF lifecycle `status` + in-force default view** *(parallel with 80)* — ingest
    `draft | stable | deprecated` into S3 object metadata and filterable vector metadata; search,
    list and synthesis preparation default to in-force (`status != deprecated AND archived ==
    false`), with options for full lineage and for excluding drafts; `supersedes` never excludes.
    Done: AC-69, AC-70 pass. Blocked by 76. (FR-04, FR-46, FR-67; D22–D25)

82. ⬜ **Change lifecycle status without re-embedding** — reuse `archive_artifact`'s re-PUT path
    (carrying metadata and all three annotations forward); the tool surface (own tool vs
    generalised archive) is decided in the spec. Done: AC-71 passes. Blocked by 80, 81.
    (FR-14, FR-68)

83. ⬜ **`verified` annotation, `add_artifact_verification`, "unverified since revised" on read** —
    `verified` in its own annotation; the new tool appends `{by, at}` via 80's helper with no
    re-PUT, re-embed or `revised` change; `read_artifact` returns the list and computes the
    advisory signal. Listings and search stay out of scope (backlog B-14). Done: AC-73, AC-74 pass.
    Blocked by 80. (FR-14, FR-70, FR-71; D41, D44, D45, D46)

84. ⬜ **`sources` + `relationships` structured annotation; `link_metadata` → `add_artifact_links`** —
    one structured annotation replaces the comma-joined `references` annotation and the
    `source_artifacts` field; the `source_artifacts` vector projection is deleted (declared slot
    stays unused — no re-index); `commit_refs` unchanged; overwrite replaces both fields with
    exactly what the call supplies; a source resolving into Arkeology without `last_modified`
    gets the source's current `revised.at` (or `generated.at`); `find_referrers` becomes a
    `type` prefilter plus one annotation read per own-scope synthesis, and a failed read raises.
    Done: AC-56–AC-61, AC-68 pass; `references`, `source_artifacts` and `link_metadata` are
    rejected (AC-80). Blocked by 79. (FR-19, FR-21, FR-51, FR-53–FR-56, C-01, C-07, C-08; D17–D20, D29, D40, D46)

85. ⬜ **Cross-scope gate for `sources` and `relationships`, with the `{withheld: n}` marker** —
    Arkeology-pointing sources pass the existing gate in `_scope.py`; unreadable entries are
    removed and one in-list `{withheld: n}` marker is emitted on **every** capability returning
    link fields or content to a foreign-scope reader — in the structured field and in the
    returned content's frontmatter alike (D49), never modifying the stored object. Done: AC-78
    passes on read, list, synthesis and the data resources; mutation run over the declared Scope shows no new non-equivalent
    survivor. Blocked by 84. (FR-10; D38, D47, D48, D49)

86. ⬜ **Per-source freshness** *(parallel with 85)* — `check_synthesis_freshness` compares each
    Arkeology source's current `revised.at` (or `generated.at`) with its captured
    `last_modified` as parsed datetimes, and reports stale, archived and missing sources; a
    revised synthesis no longer hides a source change; a source whose timestamp does not parse
    is reported "unchecked: unreadable timestamp" and the rest are still checked (D50). Done:
    AC-18 passes; the integration freshness test — already failing, because it still makes a
    source stale by date — is rewritten for per-source freshness. Blocked by 84.
    (FR-20; D19, D20)

87. ⬜ **Producer-supplied `id` becomes the artifact id** *(parallel with 84–86)* — used verbatim
    and case-preserved, no hash suffix; validated (charset, alphanumeric ends, no `/`, no `..`,
    ≤128 chars) and never repaired; generated ids unchanged when absent. Done: AC-76 passes;
    AGENTS.md's deterministic-keys rule and Working Conventions carry the ADR amendment.
    Blocked by 79. (FR-08, FR-15, FR-73; D28, D32, D33)

88. ⬜ **Migration skill + `references.py` + source-backfill skill for the new frontmatter** — honour
    `id:`; check id uniqueness across the manifest before any write; prefer `generated.at` as the
    first-authorship time; resolve `sources[].resource` paths by reading the target file's own
    `id:`; carry `relationships` over unchanged; keep `sources[].id` as a label only; retarget
    `backfilling-references` to sources, recording `last_modified`; update
    `test_skill_artifact_id_drift.py`. Done: AC-58, AC-63, AC-81 pass. Blocked by 84, 87.
    (FR-23, FR-52, FR-58; D28, D40, D43)

89. ⬜ **Schema resource rewrite** — the schema MCP resource explains every field in OKF terms so an
    agent interprets it correctly: `archived`, `status`, the in-force view, `generated`,
    `revised`, `verified` and the advisory signal, `sources` (incl. `last_modified`, the
    footnote-label `id`, the `withheld` marker), `relationships`, supplied ids, the open type
    list. Done: the resource content is reviewed against the ADR field by field, and its tests
    pin each field's presence. Blocked by 76–88. (FR-18)

90. ⬜ **Store-migration skill + scripts** — brings an existing deployment to the new shape in S3
    object metadata, vector metadata and annotations: `status` → `archived`, legacy types → OKF
    display names, `date`/`author_role`/`timestamp` → provenance, comma-joined link annotations →
    the structured annotation, `source_artifacts` removed from vectors; dry-run report first,
    changes only on operator confirmation, no re-embedding, idempotent. The `generated.at` it
    writes for an existing artifact must fall on the UTC day of the old `date`, so a later
    overwrite of a tier-2 artifact regenerates the key already stored. At the end of a run it
    verifies that every vector carries a boolean `archived` and reports any it missed (D50).
    `reconcile_index` gains no migration code. Done: AC-79 passes against a moto store seeded in the pre-Phase-15 shape;
    a second run reports nothing to change. Blocked by 76–87. (FR-74; D42)

91. ⬜ **Documentation, CHANGELOG, release notes** *(Tech Writer)* — README, SERVER-REFERENCE, the
    setting-up and migration skills' agent snippets, AGENTS.md (Repository Structure, Working
    Conventions on `ARTIFACT_TYPES`, comma-joined lists, deterministic keys; mutation Scope if
    85 moved gate code), and a `[Unreleased]` **Breaking** CHANGELOG entry listing every removed
    name with its replacement and pointing at the store-migration skill. Blocked by 89, 90 and
    a full integration-suite run against real AWS passing.

## Risks and Open Questions

- **Spec count.** Sixteen tasks means sixteen specs. Some tasks share most of their
  surface (79 + 80, 84 + 85); merging their specs is an option the operator has not decided.
- **OKF rulings pending (#16, #22, #28, #32).** Decided now and adapted later (D39). A ruling
  against the in-list `withheld` marker or the per-edge trust blocks changes response shapes
  only; storage does not move.
- **Validator conflict.** A redacted document fails a strict OKF v0.2 validator (`resource` is
  REQUIRED per `sources` entry, §5.1). Accepted; #32 asks for the amendment.
- **Annotation round trips on read.** `read_artifact` gains two annotation GETs (revision history,
  `verified`). Measured cost is expected to be small (D34) but has not been measured end to end.
- **Store migration on a live corpus.** Task 90 is the first tool that rewrites every artifact in
  place. Its dry-run and idempotency are the safety net; a partial run must be resumable.

---

## References

- [`docs/planning-artifacts/vision.md`](./vision.md)
- [`docs/planning-artifacts/requirements.md`](./requirements.md)
- [`docs/brainstorming/brainstorming-artifact-store.md`](../brainstorming/brainstorming-2026-05-27-artifact-store.md)
- [`docs/brainstorming/research-artifact-store.md`](../brainstorming/research-artifact-store.md)
- [`docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md`](../brainstorming/brainstorming-2026-05-30-delete-artifact.md)
- [`docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md`](../brainstorming/brainstorming-2026-05-30-existing-project-migration.md)
- [`docs/brainstorming/brainstorming-write-performance-2026-06-01.md`](../brainstorming/brainstorming-2026-06-01-write-performance.md)
- [`docs/specs/p8-t26-concurrent-embedding.md`](../specs/p8-t26-concurrent-embedding.md)
- [`docs/specs/p8-t27-retry-throttle-fix.md`](../specs/p8-t27-retry-throttle-fix.md)
- [`docs/specs/p8-t28-section-caps.md`](../specs/p8-t28-section-caps.md)
- [`docs/specs/p8-t29-migrate-skill.md`](../specs/p8-t29-migrate-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md`](../brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`](../brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md)
- [`docs/specs/p9-t31a-setting-up-arkeology-skill.md`](../specs/p9-t31a-setting-up-arkeology-skill.md)
- [`docs/specs/p9-t31b-migration-skill-exclusion-gate.md`](../specs/p9-t31b-migration-skill-exclusion-gate.md)
- [`docs/specs/p9-t31c-readme-reduction.md`](../specs/p9-t31c-readme-reduction.md)
- [`docs/brainstorming/brainstorming-reconcile-dangling-vectors-2026-06-03.md`](../brainstorming/brainstorming-2026-06-03-reconcile-dangling-vectors.md)
- [`docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md`](../specs/p9-t32-reconcile-phase3-dangling-vectors.md)
- [`docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md`](../brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md)
- [`docs/specs/p10-t35-filter-range-operators.md`](../specs/p10-t35-filter-range-operators.md)
- [`docs/specs/p10-t36-commit-refs-metadata-fields.md`](../specs/p10-t36-commit-refs-metadata-fields.md)
- [`docs/specs/p10-t37-propose-commit-links.md`](../specs/p10-t37-propose-commit-links.md)
- [`docs/specs/p10-t38-link-commit.md`](../specs/p10-t38-link-commit.md)
- [`docs/specs/p10-t39-caller-controlled-artifact-concurrency.md`](../specs/p10-t39-caller-controlled-artifact-concurrency.md)
- [`docs/brainstorming/brainstorming-2026-06-10-migrate-artifacts-concurrency.md`](../brainstorming/brainstorming-2026-06-10-migrate-artifacts-concurrency.md)
- [`docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md`](../brainstorming/brainstorming-2026-06-08-skill-distribution.md)
- [`docs/specs/p9-t33a-opencode-js-plugin.md`](../specs/p9-t33a-opencode-js-plugin.md)
- [`docs/specs/p9-t33b-claude-code-plugin.md`](../specs/p9-t33b-claude-code-plugin.md)
- [`docs/specs/p9-t33c-install-script.md`](../specs/p9-t33c-install-script.md)
- [`docs/specs/p9-t33d-copilot-adapter.md`](../specs/p9-t33d-copilot-adapter.md)
- [`docs/specs/p9-t33e-readme-quick-install.md`](../specs/p9-t33e-readme-quick-install.md)
- [`docs/specs/p10-t40-migration-skill-commit-refs-backfill.md`](../specs/p10-t40-migration-skill-commit-refs-backfill.md)
- [`docs/specs/p10-t41-rename-feature-tags-to-tags.md`](../specs/p10-t41-rename-feature-tags-to-tags.md)
- [`docs/brainstorming/brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md)
- [`docs/specs/p10-t42-mcp-data-resources.md`](../specs/p10-t42-mcp-data-resources.md)
- [`docs/brainstorming/brainstorming-2026-06-14-visual-reading-interface.md`](../brainstorming/brainstorming-2026-06-14-visual-reading-interface.md)
- [`docs/brainstorming/brainstorming-2026-06-24-mcp-apps-visual-interface.md`](../brainstorming/brainstorming-2026-06-24-mcp-apps-visual-interface.md)
- [`docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md`](../architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md)
- [`docs/specs/p11-t43-mcp-app-infrastructure.md`](../specs/p11-t43-mcp-app-infrastructure.md)
- [`docs/specs/p11-t44-browser-ui.md`](../specs/p11-t44-browser-ui.md)
- [`docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md`](../brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md)

---
type: plan
title: Plan Arkeology
description: Full phase history and current open phase for Arkeology development, tracking all completed and in-progress tasks from foundation through OKF schema alignment.
tags: []
timestamp: 2026-06-18T00:00:00Z
okf_version: "0.1"
---

# Plan: Arkeology

_Project: arkeology_ _Generated: 2026-05-29_ · _Last updated: 2026-08-21_ _Status: **V1 — Phases 1–9 complete (unit + integration suite passing against live AWS; ruff + mypy clean; Apache 2.0 licensed; production-hardened; moto migration complete; write performance hardened; bulk write + migration tools; setting-up-arkeology + sync-arkeology-plugin skills; skill distribution via native plugin mechanisms) · Phase 10 complete (artifact commit references + caller-controlled concurrency + OKF schema alignment + MCP data resources; v0.4.0) · Phase 11 complete (MCP App visual reading interface; v0.5.0) · Phase 12 complete (artifact cross-referencing + annotation-backed link storage) — tasks T45–T69 all implemented, unit-tested, and merged to `main`, including the T57–T62 vector metadata budget hardening wave (ADR-2026-08-13, Accepted) and the T63–T69 further review-remediation batches · Phase 13 complete — T70 (`prd` type → `vision` + `requirements`) implemented, unit-tested (1281 passed), ruff/mypy/npm-test clean; unreleased — latest tag is v0.5.0 (Phase 11)**_

## How we work

This project runs as a **single open phase**, not a pre-planned roadmap. Completed phases stay below as a full history (every feature marked ✅); the current phase shows its tasks in detail; and anything not yet started — issues, deferred work, and scoped-but-unbuilt features — lives in [`backlog.md`](backlog.md), pulled into the current phase when we decide to tackle it. There are no pre-planned future phases beyond the current one, and a phase ends when we judge it done.

- **Requirements** (FR/NFR/AC/Constraints) live in [`requirements.md`](requirements.md) and product vision lives in [`vision.md`](vision.md) — this plan references requirement IDs, it does not redefine them.
- **Per-task implementation detail** lives in [`../specs/`](../specs/) as `p<phase>-t<task>-<slug>.md` (e.g. task 3 of Phase 10 → `p10-t3`).
- **Status legend:** ⬜ pending · 🔄 in progress · 🔍 in review · ✅ done · 🔴 blocked
- **Delivery model:** each **Phase** is a coherent slice of value delivered as a set of tasks. A phase ends when we judge it done.

**Current state:** Phase 14 — Consistency Review Remediation is open, closing the findings of the 2026-09-05 whole-repository consistency review; T71–T74 are done. Prior phases below remain as delivered. Phase 12 — Artifact Cross-Referencing + Annotation-Backed Link Storage: all planned tasks **T45–T69** implemented, unit-tested (suite green), and merged to `main` (the `phase-12-cross-referencing` branch is merged; work is trunk-based on `main` per AGENTS.md); skills consolidated under `plugins/arkeology/skills/`; specs, ADR-011/ADR-012, and user docs aligned. **T57–T62** (added 2026-08-13) delivered the post-implementation remediation for a real vector-metadata-budget-overflow incident (guard coverage, `commit_refs`/`references` split-store fix, migration self-heal, bounded reconcile retry — see `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`, Accepted). Two closely-related review findings were folded directly into those specs rather than getting their own task numbers: I-4 (control-character validation gap) into T57's spec, and I-2 (`propose_commit_links.py` first-vector-only bug) into T58's spec — both touched the exact same file/function T57/T58 already opened. H-2 was folded into T62's spec (same file, already reopened by T62). Four other findings (F-1, F-3, H-1, I-3) were batched into follow-up task **T63**, and a further six batches of review-2026-08-13 remediation — **T64–T69** (I-6, J-2, C-1, J-1, cleanup-hygiene batch 2, and convention-class cleanup) — landed 2026-08-19/20, closing out every open finding from that review. No task in the phase remains open. Not yet released: latest tag is v0.5.0 (Phase 11 — Visual Reading Interface); `CHANGELOG.md`'s `[Unreleased]` section carries the accumulated Phase 12 changes pending a version cut.

---

## Notes

- **TDD throughout** — tests written before implementation on every task (NFR-07)
- **Layered architecture from day one** — AWS client interfaces established in Phase 1; all subsequent tasks build on them, never bypassing them (NFR-04)
- **Credential error wrapping is a Phase 1 concern** — all credential-related errors are caught and re-raised as structured MCP error responses at the AWS client layer (FR-12, D2); individual tool tasks inherit this automatically and do not need to re-implement it
- **T18–T20 (Phase 4) can start in parallel with Phase 3** — MCP Resources and migration skill do not depend on Phase 3 being complete; T17 (integration test phase gate) should complete before T19 (setup docs) to ensure documented behaviour is empirically verified
- **Integration tests must clean up after themselves** — once `delete_artifact` is implemented (T12), all integration test teardown fixtures must call `delete_artifact` to remove every artifact written during the test run; existing integration tests for T7–T9 must be updated at the same time as T12 is delivered

---

## Phase 1 — Foundation: runnable server with startup validation

Goal: the server starts, validates all configuration, and fails clearly on any misconfiguration. No tools yet — just the skeleton everything else builds on.

1. ✅ **Bootstrap Python project** — project must be installable and testable from source (NFR-08, NFR-09).

2. ✅ **FastMCP server skeleton** — stdio transport, structured logging, graceful shutdown; no tools registered yet (NFR-05).

3. ✅ **AWS client layer** — S3, S3 Vectors, and Bedrock each behind a clean typed interface; HTTPS enforced; all boto3 calls catch credential-related exceptions and re-raise as structured typed errors (NFR-04, NFR-10, FR-12, D2).

4. ✅ **Configuration model** — all env vars parsed and validated at process start: `AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `WRITE_PREFIX`, `READ_PREFIXES`, `BEDROCK_EMBEDDING_MODEL`, `AWS_PROFILE` (optional), `SEARCH_FETCH_TOP_K` (optional, default 25), `SEARCH_MAX_ITERATIONS` (optional, default 3), `SEARCH_DEFAULT_TOP_K` (optional, default 5).

5. ✅ **Startup validation sequence** — credentials, `WRITE_PREFIX` read/write, each `READ_PREFIXES` entry read, vector index existence, embedding model ↔ index dimension match; any failure is a hard stop with a distinct actionable error (FR-07, NFR-03).

---

## Phase 2 — Core value loop: write, search, read

Goal: an agent writes an artifact and immediately finds it via semantic search. This is the minimum viable loop — the reason the server exists.

6. ✅ **Artifact model and key generation** — metadata schema (FR-09), deterministic tier 2 slug (`type-date-title_slug`) and tier 3 slug (`type-title_slug`) (FR-08).

7. ✅ **Write artifact tool** — S3 PutObject → parse all `##` sections → one Bedrock embed per section (fallback: single embed from title+description+type+features if no sections) → one `S3 Vectors PutVector` per section with key `{artifact_key}#{section_name_slug}` and `artifact_id` in filterable metadata (fallback key = artifact_key); re-write: upsert existing section keys + query by `artifact_id` to delete orphaned section keys for removed sections; tier 2 immutability (FR-13); tier 3 overwrite in place (FR-15); idempotent same-key writes (NFR-06); returns identifier (FR-01).

8. ✅ **Search artifacts tool** — one Bedrock embed of query; re-fetch loop: single combined `S3 Vectors QueryVectors` call per iteration using `$or` filter covering own scope (unrestricted) and foreign scopes (tier 3 + shared only); group section vectors by `artifact_id`; repeat until `top_k` artifacts collected or `SEARCH_MAX_ITERATIONS` reached; metadata + description only in response, no content (NFR-02) (FR-03).

9. ✅ **Read artifact tool** — S3 GetObject by identifier; cross-scope gate enforced (FR-02, FR-10)

---

## Phase 3 — Complete tool surface: list, archive, delete, health, reliability

Goal: the server is operationally complete. Agents can list, archive, and delete artifacts; admins can diagnose health. Partial write failures are never silent.

10. ✅ **List artifacts tool** — metadata-only listing with filters (type, feature tags, team, project, tier, status); no semantic ranking; cross-scope gate enforced (FR-04)

11. ✅ **Archive artifact tool** — update `status` in S3 Vectors metadata to inactive; scoped to `WRITE_PREFIX` only; no content modification (FR-05, FR-14)

12. ✅ **Delete artifact tool** — hard-delete by `artifact_id` with `confirm=True` required; delete vectors first then S3 object; warn-and-proceed if artifact is a synthesis source; scoped to `WRITE_PREFIX` only; partial delete (vectors gone, S3 delete failed) recoverable via reconciliation (FR-21, FR-13, FR-14, AC-19).

13. ✅ **Purge archived tool** — bulk hard-delete of all `status=inactive` artifacts in own scope with `confirm=True` required; cascade-delete any synthesis whose every `source_artifact` is in the purge set; returns summary of purged identifiers (FR-22, AC-20).

14. ✅ **Health check tool** — independent per-component status: S3, S3 Vectors, Bedrock, `WRITE_PREFIX`, each `READ_PREFIXES` entry (FR-06).

15. ✅ **Partial write failure log** — on S3 success + S3 Vectors failure: write structured entry to local tier 1 failure log before surfacing error; error includes artifact identifier; Bedrock throttle triggers one retry with back-off before error (FR-16, NFR-11).

16. ✅ **Synthesise artifacts tool** — semantic search + batch `read_artifact` for top-k results; returns bundled full content (identifier, metadata, description, content) per source artifact; agent performs synthesis in-context; agent writes back via `write_artifact` with `type=synthesis`, `tier=3`, `source_artifacts=[...]` (FR-19).

---

## Phase 4 — Self-documentation and adoption *(T18–T20 can start in parallel with Phase 3)*

Goal: any agent can discover the schema at runtime; a new team can adopt the server following only the README and AGENTS.md snippet.

17. ✅ **Run full integration test suite** *(top priority — phase gate for T19 setup docs)* — execute all integration tests for T7–T16 against live AWS credentials; resolve remaining open question Q1 (upsert behaviour); confirm T7/T8 empirical integration checkpoints; update Learnings; close Phase 3 retrospective (NFR-07).

18. ✅ **MCP Resources** — expose artifact schema, tier model, visibility and cross-scope model, type catalogue, and query strategy guidance as MCP Resources; always in sync with running server version (FR-18).

19. ✅ **Setup documentation and AGENTS.md snippet** — README quick start, full configuration reference with all env vars, minimum IAM policy, AWS provisioning steps (including S3 Vectors index creation with `description` and `source_artifacts` non-filterable slots, and explicit warning that index dimension, distance metric, and non-filterable keys are immutable after creation — a new index must be created on model or dimension change), `mcp-servers.json` example; recommended AGENTS.md snippet covering when to write/search, artifact types, description quality guidance, tier selection, query strategy (start narrow, broaden if needed), when to synthesise and how (NFR-12).

20. ✅ **Migration skill** — `skills/migrating-to-arkeology/SKILL.md` with structured workflow covering both paths (agent-only < 30 files; manifest + script ≥ 30 files); discovery, classification table, metadata enrichment guidance, post-migration AGENTS.md update step; `skills/migrating-to-arkeology/scripts/migrate.py` with PEP 723 inline deps — Bedrock description generation, `git log` date recovery, bulk `write_artifact` calls, `--dry-run` mode (JSON preview), structured JSON stdout, idempotent on re-run; `skills/migrating-to-arkeology/schema.yaml` documenting ARKEOLOGY_IMPORT.yaml manifest format; README table of skills directory paths for Claude Code, Codex, Copilot, and OpenCode (FR-23, NFR-12).

---

## Phase 5 — Could-have: reconciliation and synthesis freshness

21. ✅ **Reconciliation tool** — failure log replay + full S3 vs vector index orphan scan (including partial-delete orphans); re-index missing entries; remove resolved failure log entries; return structured summary (FR-17).

22. ✅ **Synthesis freshness check tool** — scan all `synthesis` type artifacts; compare synthesis `date` against `date` of each listed `source_artifact`; flag stale (source updated more recently) and orphaned (source archived) entries; return structured report (FR-20).

---

## Phase 6 — Production Hardening (Review Fix Cycle)

Goal: resolve all 76 findings from the full project code review (12 critical, 27 major, 37 minor). No new functionality — correctness, security, and maintainability only.

23. ✅ **Implement all 20 review-fix specs** — credential error hardening, vector score semantics, health probe filter, README IAM fixes, exception chaining, S3/Bedrock hardening, health CredentialError distinction, archive idempotency, list scope filter, shared search helper, test infrastructure consolidation, CredentialError test coverage, integration test isolation, project config fixes, minor foundation/client/tool/test/doc improvements, ABC→Protocol migration, `filter`→`filter_expr` rename, Apache 2.0 licence, repo URL.

24. ✅ **V1 integration suite re-run** — full integration test suite re-run against live AWS after Phase 6 hardening; all tests pass; V1 declared clean.

---

## Phase 7 — Test infrastructure: moto migration

Goal: replace hand-rolled in-memory fakes for S3 and S3 Vectors with moto-backed real client implementations. Fixes the score range inconsistency between unit and production and aligns with the project's testing convention.

25. ✅ **Migrate unit tests from hand-rolled fakes to moto** — delete `FakeS3Client` and `FakeVectorsClient`; replace with moto-backed `S3ClientImpl` / `VectorsClientImpl` throughout the unit test suite; patch `S3VectorsBackend.query_vectors` with a cosine similarity extension in `conftest.py`; fix score range from `[0, 2]` (fake) to `[−1, 1]` (cosine similarity, matching production) in all score assertions (FR-mock-conv).

---

## Phase 8 — Write Performance

Goal: eliminate the dominant latency bottlenecks in `write_artifact` and `migrate.py`. No new tools, no breaking changes — pure performance, correctness, and usability improvements. Specs: `docs/specs/p8-t26-*.md` through `docs/specs/p8-t29-*.md`.

26. ✅ **P1 — Concurrent embedding + batched put_vectors** *(highest impact)* — replace the serial section `for` loop in `write_artifact` with `asyncio.to_thread` + `asyncio.gather` bounded by `asyncio.Semaphore(SECTION_CONCURRENCY)`; collapse all per-section `put_vector` calls into one `vectors.put_vectors_batch` call per artifact; add `SECTION_CONCURRENCY` config var (default 5); add `put_vectors_batch` to `VectorsClientInterface` and `VectorsClientImpl` (chunk at 500) (NFR-13, NFR-14).

27. ✅ **P2 — Retry and throttle fix** *(correctness fix)* — remove the duplicate `ThrottlingException` catch-and-retry blocks from `write.py` (redundant with `bedrock.py`'s internal retry; adds up to 5 s per throttled section); add `random.uniform(0, 1)` jitter to the `bedrock.py` retry sleep to prevent thundering-herd when concurrent embeds throttle simultaneously (NFR-11).

28. ✅ **P3 — Configurable section caps** *(defensive bound)* — add `EMBED_MAX_SECTIONS` (default 20) and `EMBED_MIN_SECTION_LENGTH` (default 50 chars) config vars; apply as filters in `write.py` immediately after `parse_sections`; fall back to document-level embed if no sections remain; log dropped sections at DEBUG (FR-01, NFR-13).

29. ✅ **L1+L2 — Migration skill parallel writes** *(skill + script)* — restructure SKILL.md into three mutually exclusive bands (1–4 files → Path A sequential; 5–9 files → Path B manifest+script; ≥10 files → Path C parallel sub-agents via `task` tool, batches of 4–5); lower Path B threshold from 30 → 5 files; add `asyncio.gather` + `asyncio.Semaphore(MIGRATE_CONCURRENCY)` to `migrate.py` for concurrent writes; read `MIGRATE_CONCURRENCY` from env (default 3); wrap `main()` with `asyncio.run` (FR-23, NFR-15).

---

## Phase 9 — Improvements and Fixes

Goal: quality-of-life improvements and documentation polish before declaring v1, plus the v0.3.0 artifact commit-references feature.

30. ✅ **Z1 — `write_artifacts` + `migrate_artifacts` bulk tools** *(priority 1 — unblocks correct migration performance)* — add two new MCP tools.

31. ✅ **Setting-up-arkeology skill** — `skills/setting-up-arkeology/SKILL.md` with 6-step structured workflow that assumes all required AWS resources are already provisioned externally: (1) parameter collection upfront — region, existing S3 bucket name, existing S3 Vectors bucket and index names, embedding model, AWS profile, IDE choice, team/project names, optional cross-scope read prefixes; (2) pre-flight checks — AWS CLI availability, active credentials (`aws sts get-caller-identity`), `uv` installed, S3 bucket reachable (`head-bucket`), Vectors index reachable (`describe-index`), Bedrock model accessible (`invoke-model`); (3) clone and Python setup; (4) MCP client config — write the Arkeology server entry including all required env vars directly into the correct configuration file for the chosen MCP client (see multi-client table below); show entry and ask explicit permission before writing; merge into existing file without touching other entries; display entry for manual addition if operator declines; no `.env` file is written at any step; (5) smoke test via `health_check` — all components must return `"status": "ok"` before proceeding; (6) permanent exclusion configuration — two-part step: (A) ADR strategy (git-only vs arkeology-only): if git-only, auto-detect ADR folder from common directory names; confirm with operator or ask for path if not found; add confirmed path to `local_only_paths` and `adr` to `local_only_types`; (B) ask for any additional folders or files that should never go into Arkeology; for each path, infer artifact type from the migration skill's path-pattern table and confirm with operator. Write `<!-- arkeology:config -->` block to AGENTS.md; write narrative snippet from `references/agents-snippet.md`. Re-running updates config block in place. No IAM policy generation at any step — the README provides a static reference policy with YOUR-* placeholders that operators use as a template. (FR-24, FR-44, NFR-12, AC-28, AC-29, AC-40, AC-42, AC-49)

32. ✅ **Reconcile Phase 3 — dangling vector pruning** *(priority 2)* — extend `reconcile_index` with a third phase that detects and deletes vector index entries whose backing S3 object no longer exists. Dangling vectors arise when an S3 object is deleted externally (outside Arkeology) while its vector index entries remain; they surface in search and list results with valid-seeming metadata but cause `read_artifact` to return a not-found error. Phase 3 reuses data already collected in Phase 2 at zero additional API cost: `indexed_artifact_ids − set(own_keys)` identifies all dangling artifact IDs; their vector keys are already grouped from the existing `indexed_keys_raw` listing and are deleted. Phase 3 always runs automatically — no new parameters, consistent with Phases 1+2 which also auto-repair without confirmation. Response schema gains three additive fields: `dangling_artifacts_found` (int), `dangling_vectors_pruned` (int), `dangling_artifacts` (list[str]). Existing callers that ignore unknown keys are unaffected.

33. ✅ **Skill distribution via native plugin mechanisms** — wire `setting-up-arkeology` and `migrating-to-arkeology` into engineers' AI tools using the same plugin pattern as the shared engineering plugin project. No new server code — purely repo-level files and a bash script. Independent of all other Phase 9 tasks; can be worked at any point.

34. ✅ **`sync-arkeology-plugin` — generic tool-aware skill update** — add `skills/sync-arkeology-plugin/SKILL.md` (~35 lines). The skill detects which AI coding tool it is running in and takes the appropriate update action for each.

---

### Phase 10 — Artifact Commit References + OKF Schema Alignment + MCP Data Resources

Goal: close the traceability gap between artifacts and git commits (T35–T40); align the `feature_tags` field name with OKF vocabulary as a pure rename (T41); expose MCP data resources for direct artifact browsing from host tools (T42). All tasks complete.

35. ✅ **Filter range operators ($gte / $lte)** *(prerequisite — filter.py only; no tool changes)* — add `$gte` and `$lte` inclusive string-comparison operators to `filter.py`; update module docstring (FR-30).

36. ✅ **`commit_refs` and `last_edited_ulid` metadata fields** *(core data model)* — add `commit_refs: list[str]` to `Artifact`; generate `last_edited_ulid` via `python-ulid` on every `write_artifact` call; store both fields in S3 object metadata and vector metadata following the `tags` encoding pattern (comma-joined string in S3, `list[str]` in vectors, key omitted when empty in vectors); include `last_edited_ulid` in `write_artifact` response; expose both fields in `list_artifacts` (with `commit_refs` filter parameter) and `read_artifact` responses; legacy artifacts (missing fields) return `None` — no error (FR-28, FR-29).

37. ✅ **`propose_commit_links` tool** *(read-only discovery)* — scan own-scope artifacts in the vector index optionally bounded by `last_edited_ulid >= since_ulid`; deduplicate by `artifact_id`; filter client-side for artifacts with absent or empty `commit_refs`; return candidate list with human-readable timestamps; no writes (FR-31).

38. ✅ **`link_commit` tool + AGENTS.md post-commit protocol** *(write, no re-embed)* — for each confirmed `artifact_id`: `list_vectors_by_metadata` → `get_vectors` → merge `commit_sha` into `commit_refs` (append + deduplicate) → `put_vectors_batch` with same float32 embeddings and updated metadata; scope-gate rejects foreign-scope IDs (counted in `skipped`); generate `next_since_ulid` after all artifacts processed; return `{linked, skipped, commit_sha, next_since_ulid}`; add AGENTS.md post-commit protocol snippet to setting-up-arkeology skill (FR-32).

39. ✅ **Caller-controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`** — remove `ARTIFACT_CONCURRENCY` from `Settings` (field, validator, and property); add `artifact_concurrency: int = 3` optional parameter to `write_artifacts` and `migrate_artifacts`; out-of-range values are never rejected — above 15 capped to 15, below 1 substituted with default 3, both with a top-level `warning` field in the response; thread `artifact_concurrency` from `migrate_artifacts` through to `_write_artifacts_inner` for the `dry_run=False` path; update migration skill: (1) recommend `min(file_count, 15)` with quota context and confirm with operator, (2) batch 3.B3 and 3.B5 calls by `artifact_concurrency` (batch_size = artifact_concurrency) so the operator receives progress updates after each batch; update all unit tests that previously set `ARTIFACT_CONCURRENCY` via `monkeypatch.setenv` to pass the parameter directly; remove config-level tests for the deleted env var (FR-23, FR-25, FR-26, NFR-14, NFR-15).

40. ✅ **Migration skill `commit_refs` backfill options** *(skill-only change; no server code)* — update the `migrating-to-arkeology` skill to offer the operator three backfill choices after artifacts are written: (1) **do not backfill** (default — `commit_refs` left empty, migration finishes immediately), (2) **set migration timestamp** (`commit_refs` left empty; `last_edited_ulid` already set to migration time by `write_artifact` — no extra step needed; document this for operator clarity), (3) **backfill from git history** (for each migrated file run `git log -1 --format=%H -- <filepath>` to obtain the last-touching commit SHA, then call `link_commit` in batches); warn upfront that option 3 is O(n) git calls and can be slow for large projects (D12).

41. ✅ **Rename `feature_tags` → `tags`** *(pure identifier rename; OKF schema alignment)* — rename the `feature_tags` metadata field to `tags` across the entire codebase: `Artifact` model, all MCP tool public parameters (`write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts`), S3 object metadata key, vector metadata key, filter clause keys, all tool implementations, tests, `resources.py`, `AGENTS.md`, `SERVER-REFERENCE.md`, and setting-up-arkeology + migrating-to-arkeology skills; preserve the deliberate S3-comma-joined-string vs vector-`list[str]` dual-encoding under the new key name; no data migration (no live data) (D2 — brainstorming-2026-06-15-okf-alignment.md)

42. ✅ **MCP data resources** — expose `arkeology://artifact/{id}` URI template resource returning the full markdown content of the identified artifact and `arkeology://artifacts` listing resource returning a markdown-formatted index of active own-scope artifacts; both carry `audience: ["user"]` annotations signalling human-facing content; `arkeology://artifact/{id}` applies the same scope, tier, and visibility gate as `read_artifact`; both registered alongside existing schema resources via `register_resources()` (FR-46, AC-51, AC-52).

---

## Phase 11 — Visual Reading Interface (MCP Apps)

Goal: a developer calling `arkeology_studio` in any MCP App-supporting host (Claude Desktop, claude.ai, VS Code Copilot) sees an interactive artifact browser rendered inline — faceted filtering, semantic search, full markdown and mermaid rendering — with zero new AWS infrastructure. All Arkeology tool calls from within the browser pass through the existing scope gate unchanged.

**Execution order:** T43 is the prerequisite (server-side infrastructure, `arkeology_studio` tool registration, and HTML placeholder must exist before T44 can be developed and loaded). T44 depends on T43.

43. ✅ **Server-side MCP App infrastructure and `arkeology_studio` tool** *(prerequisite — establishes the entry point and resource serving before any UI work)* — add `fastmcp[apps]` (a pip packaging extra, installed as a base dependency — not optional for the server, see ADR-010 revision) to `pyproject.toml`; create `src/arkeology/tools/studio.py`: `arkeology_studio` tool decorated with `AppConfig(resource_uri="ui://arkeology-studio/index.html")`, initial call returns active artifact listing data, branches on `ctx.client_supports_extension(UI_EXTENSION_ID)` — graceful degradation path returns a plain-text `list_artifacts` equivalent when extension not supported; register `ui://arkeology-studio/index.html` resource in `resources.py` with `ResourceCSP` declaring CDN origins (`unpkg.com`, `cdn.jsdelivr.net`), reads HTML from `src/arkeology/static/arkeology-studio.html`; create `src/arkeology/static/arkeology-studio.html` placeholder; declare `src/arkeology/static/` as package data in `pyproject.toml`; register tool in `server.py` via `register_tools()`; update AGENTS.md repository structure table (FR-47, FR-48).

44. ✅ **Browser UI (HTML/JS)** *(depends on T43)* — build `src/arkeology/static/arkeology-studio.html`: a self-contained HTML/JS browser application with all dependencies loaded from declared CDNs; left panel providing filter controls (type, tier, status) and an artifact listing populated on open and refreshed by `list_artifacts` on filter change; right panel document viewer triggered by artifact selection that fetches via `read_artifact` and renders markdown and mermaid diagrams; semantic search box that calls `search_artifacts` and replaces the listing with ranked results, clearing restores the filter view; update `SERVER-REFERENCE.md` with `arkeology_studio` tool entry; update AGENTS.md to mention `arkeology_studio` as the reading entry point (FR-47, FR-48, FR-49).

---

### Phase 12 — Artifact Cross-Referencing + Annotation-Backed Link Storage

Goal: give artifacts a first-class `references` field, move the durable copy of the mutable link fields (`commit_refs`, `references`) from vector-metadata-only to **S3 object annotations** so they survive `reconcile_index`, generalize `link_commit` into a single `link_metadata` primitive, and add an own-scope `referenced_by` warning on delete/archive. Requirements: FR-51–FR-58, plus revisions to FR-32, FR-17, FR-28, FR-09. Design source: `docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md` (decisions D1–D15).

**This track supersedes several Phase 10 commit-refs decisions.** The vector-only `commit_refs` storage (Phase 10 T38 "Known limitation") and the "commit references lost after reconcile" requirements.md limitation are replaced by annotation-backed dual-write. The Phase 10 specs `p10-t36`, `p10-t38`, and `p10-t40`, plus the read (`p2-t9`) and reconcile (`p5-t21`) specs touched by the annotation change, are revised as part of this phase — **assigned to an Architect** (see execution note). A one-time relink sweep for legacy vector-only `commit_refs` was considered and dropped — no live deployment has such data to sweep (see ADR-011).

45. ✅ **S3 object annotation client support + moto self-mock extension** *(prerequisite — client layer + test infrastructure)* — add put/get/list/delete object-annotation operations to the S3 client interface (`typing.Protocol`) and the concrete boto3 implementation; add a moto conftest extension self-mocking the annotation APIs, mirroring the existing `query_vectors` cosine patch (moto has no native annotation support). No tool changes. (FR-54)

46. ✅ **`references` first-class field on the `Artifact` model + write / read / list surfacing** *(core data model)* — add `references: list[str]` to `Artifact`; dual-store durably on the S3 object (annotation, per T47) and as `list[str]` in vector metadata; accept `references` at write time; return it in `write_artifact`, `read_artifact`, and `list_artifacts` responses; add a `references` list-membership filter to `list_artifacts` (AND semantics); legacy artifacts return `[]`. (FR-51)

47. ✅ **Annotation dual-write in the write path + overwrite preservation** — write `commit_refs` and `references` to S3 object annotations (durable-side first, vectors second — recoverable-state ordering); on an overwriting tier-3 write, read forward the existing `commit_refs`/`references` and re-apply them to both stores, because `PutObject` clears annotations. Content body is never re-embedded by this path. (FR-54, FR-55)

48. ✅ **`reconcile_index` rebuilds `commit_refs` + `references` from annotations** — when re-indexing an artifact, restore both link fields into vector metadata by reading the object's durable annotations (`ListObjectAnnotations`/`GetObjectAnnotation`) instead of standard object metadata. Resolves OQ2. (FR-17, FR-54)

49. ✅ **`link_metadata` tool — generalizes and supersedes `link_commit`** — fetch existing vectors + embeddings → merge and deduplicate the supplied `commit_refs`/`references` → dual-write (durable annotations first, vectors second) with the same embeddings; no Bedrock call; own-scope only (foreign identifiers skipped and counted); idempotent on re-run; returns counts and the write-time cursor. Rename/retire `link_commit`; keep `propose_commit_links` (FR-31). (FR-53, supersedes FR-32)

50. ✅ **Unified own-scope `referenced_by` warning on delete + archive** *(independent of annotation work)* — before delete or archive, reverse-lookup other own-scope artifacts referencing the target across both `source_artifacts` and `references` using server-side `$eq` list-membership filtering; warn-but-don't-block (delete: stronger, permanent; archive: informational, reversible); strictly own-scope — never reveal foreign-scope identifiers. Generalizes the existing synthesis-source delete warning (FR-21). (FR-56)

51. ✅ **Migration frontmatter reference rewriting + `arkeology://` content rewrite** *(migration path)* — build a single authoritative path→identifier map from the full migration manifest before any writes (forward-reference safe); resolve frontmatter `references:` path entries to artifact identifiers to populate `references` (T46); rewrite resolved references in stored content to `arkeology://artifact/{id}`; best-effort bounded path normalization; leave `http(s)://` URLs and unresolved/excluded targets untouched; in-body markdown links out of scope. (FR-52)

52. ✅ **`setting-up-arkeology` annotation availability + IAM check; runtime graceful handling; README + AGENTS.md** *(code + skill + snippet done; README/SERVER-REFERENCE IAM actions completed in the tech-writer docs pass)* — add a one-time annotation availability + IAM-permission probe to the `setting-up-arkeology` skill (aws-cli ≥ 2.35.14 guard or boto3 fallback via `uv run`); document the four required IAM actions and the regions/bucket types where annotations are unavailable in the README reference policy; handle annotation-unavailable / AccessDenied gracefully at runtime in `link_metadata` and the write path (post-setup drift); add the `arkeology://` referencing and "reference healing" guidance to the AGENTS.md snippet (D9). NOT a hard startup gate (D15). (FR-57, NFR-12)

53. ✅ **Reference-backfill cleanup skill** *(skill-only; optional, decoupled)* — ship an optional, skippable-by-default skill that content-scans artifacts against the migration path→identifier map, presents a dry-run batch report of proposed `references` backfills for operator review, and applies confirmed backfills via `link_metadata`; never rewrites stored content; never mutates metadata without confirmation. Resolves OQ1-cleanup. (FR-58)

54. ✅ **Search age transparency** *(review fix; independent of annotation work)* — surface the last-edited timestamp on every `search_artifacts` result so agents can judge and discount stale artifacts. Add the raw `last_edited_ulid` (already stored on every vector — no re-index) and a derived ISO 8601 `last_edited_at` to each result entry, reusing the existing ULID→ISO derivation used by `propose_commit_links` / `resources.py`. **No ranking change** — recency-weighted *ranking* is deferred to backlog B-6 (design-first, ADR before spec).

55. ✅ **Write-path metadata size + charset validation** *(review fix; write-path robustness)* — before any storage write, validate that the artifact's metadata fits the S3 object-metadata and vector-metadata size budgets and fail fast with a structured error, so an oversize artifact never produces a deterministic partial write (S3 ok, vector fails) that `reconcile_index` replays forever; neutralise control characters that corrupt metadata (e.g. a newline raising a raw urllib3 `ValueError`); bound `title` length in the `Artifact` model; and preserve non-ASCII titles consistently so `read_artifact` and `search_artifacts` never disagree. The size-budget check must account for `references` and `commit_refs`. (FR-59, AC-67)

56. ✅ **Deterministic, server-side content reference rewrite (frontmatter + body)** *(migration path; extends T51)* — extend the migration content rewrite so an already-resolved frontmatter `references:` path is rewritten to `arkeology://artifact/{id}` everywhere it occurs in stored content — both the frontmatter block and markdown link targets in the body — executed as deterministic server-side code inside `migrate_artifacts` (reversing, for this bounded case only, ADR-012's prior "skill orchestrates, no server-side rewrite" call). The agent still resolves frontmatter `references:` entries in-context (unchanged `references.py` algorithm, T51) but now threads a `resolved_references_map` into the descriptor instead of hand-editing content. Does not reopen in-body link *discovery* — undeclared body-only links stay untouched (ADR-012 D1 preserved). (FR-52)

57. ✅ **Guard coverage in `link_metadata.py` and `reconcile.py`** *(prerequisite — closes the missing-check gap)* — call `check_metadata_budgets` immediately before each path's vector write: inside `_apply_link_metadata_with_cas`'s per-attempt loop (after the merged field values are computed, before the annotation write — durable-first ordering is unaffected), and inside `reconcile.py`'s `_reindex_artifact` (before its `put_vector` call). Mirrors `write.py`'s existing placement; `s3_metadata` passed empty for both, since neither path touches S3 user-defined metadata. (ADR D1)

58. ✅ **Split-store decision: `references` removed from S3 Vectors metadata, `commit_refs` capped at 20** *(core fix — the incident's product question)* — `write.py`, `link_metadata.py`, and `reconcile.py` stop writing `references` to S3 Vectors metadata entirely; the S3 object annotation copy becomes its sole durable store and sole read surface (read path collapses to single-store for this field). `commit_refs` stays in S3 Vectors metadata, filterable, capped at the most-recently-appended **20 entries** (real-AWS-calibrated: AWS accepts up to 36 entries for this payload shape, rejects 37 — 20 leaves deliberate margin; full measured evidence in the ADR); the complete, uncapped list remains durable in annotations regardless. Explicit non-completeness-guarantee wording added to `commit_refs`'s vector-metadata copy per the ADR's amendment. (ADR D2)

59. ✅ **Remove `references=` filter param from `list_artifacts`; `commit_refs=` unchanged** *(breaking API change, documented before shipped)* — `references` is no longer vector-filterable once T58 lands, so the `references=` server-side filter parameter is removed outright from `list_artifacts` rather than silently returning empty results. `search_artifacts` has never had a `references` parameter (confirmed by direct inspection of `search.py`/`server.py` — plan.md's earlier wording naming it alongside `list_artifacts` was inaccurate) so it needs no change. `commit_refs=` filtering in `list.py`'s `_list_artifacts_inner` is unaffected and requires no code change. (ADR D6 / brainstorming OQ6)

60. ✅ **Narrow the delete/archive reverse-lookup warning to `source_artifacts`; document the `references` gap** *(accepted capability loss, not silently absorbed)* — the `referenced_by` warning (T50) keeps scanning `source_artifacts` exactly as today; the `references`-half of the scan is dropped with no fallback (an unbounded full-corpus annotation scan was explicitly rejected as a substitute — see ADR). The gap is documented in the tool's response/docstring, not silently absorbed. (ADR D6 / brainstorming OQ6)

61. ✅ **Migration self-heal: `skipped_unindexed` classification** *(closes the permanent-un-retryable gap)* — `migrate_artifacts`' Step 5 skip-existing check adds one bounded, per-candidate `vectors.list_vectors_by_metadata` existence query (per-candidate, not a bulk pre-scan — confirmed OQ3); an S3-exists-but-not-indexed candidate is reported under a new `skipped_unindexed` category (not folded into `skipped_existing`) and pointed at `reconcile_index` for remediation. (ADR D3)

62. ✅ **Bounded `reconcile_index` failure-log retry** *(independent — closes the infinite-replay risk)* — `reconcile_index`'s failure-log replay adds a per-entry `reconcile_attempts` counter, incremented on each failed replay; once it crosses the existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`, reused rather than made independently configurable — confirmed OQ4), the entry stops being auto-retried and is reported once, loudly, in a new `stuck_failures` response field, instead of being replayed identically forever. (ADR D4)

63. ✅ **Codebase-hygiene pass: shared scope-check/cross-scope/fetch helpers + bounded concurrency** *(review findings I-3, F-1, F-3, H-1 — batched into one task rather than four separate ones, scheduled right after T57–T62 rather than folded into those specs, since most of their call sites live outside T57–T62's scope)* — extract `is_own_scope(artifact_id, scope) -> bool` (I-3), `is_cross_scope_readable(meta, artifact_id, own_scope, read_prefixes) -> bool` (F-1), and `fetch_vectors_by_metadata(vectors, filter_expr, *, include_data=False)` (F-3) as shared helpers used consistently across all their call sites (`delete.py`, `read.py`, `list.py`, `archive.py`, `link_metadata.py`, `purge.py`, `freshness.py`, `reconcile.py`, `_reference_filter.py`, `write.py`, `propose_commit_links.py`); apply `write_artifacts.py`'s bounded-concurrency pattern to the remaining sequential per-artifact loops (H-1: `purge.py`, `freshness.py`, `migrate_artifacts.py`'s Step 5, plus whatever's left of `reconcile.py`/`link_metadata.py`'s loops after T57/T61/T62/H-2 land).

64. ✅ **I-6 — Validate `file_extension` starts with `.` in `migrate_artifacts.py`'s skip-existing pre-check** — mirror `write.py`'s existing check (reject with the same validation error shape `write.py` uses, before any `head_object` probe is issued) so the two paths enforce the identical invariant instead of the pre-check silently probing a key `write_artifacts`/`write.py` would refuse to construct.

65. ✅ **J-2 — `check_synthesis_freshness(confirm=True)`'s `all_fresh` must also require `delete_failed` empty** — `all_fresh` currently only inspects `malformed_reported`, never the separately-tracked `delete_failed` list, so a malformed synthesis whose S3 `delete_object` call fails (vector deletion succeeded) is silently omitted from both `malformed` and the `all_fresh` calculation, even though it's still present in S3.

66. ✅ **C-1 — Distinguish `VectorDistanceMissingError` (index corruption) from ordinary transient errors in `run_search_loop`** *(operator decision: option (b2) "soft signal")* — `_search_helper.py`'s `run_search_loop` currently catches `VectorDistanceMissingError` via the same blanket `except Exception:` used for ordinary network blips, reporting it identically. Add a distinct log line (so it's grep/alertable, matching the exception's own docstring intent — "must never be treated as perfect similarity — hard error") and a response-level flag/field so a caller of `search_artifacts`/`synthesise_artifacts` can see the index has a corruption signal, without aborting the call or losing whatever partial results were already collected.

67. ✅ **J-1 — `write_artifact`'s orphan-vector cleanup: retry inline, fall back to a `reconcile_index` repair mechanism** *(operator decision: inline retry (option b) first; if retries are exhausted, extend `reconcile_index` with a real repair path (option c))* — `write.py`'s Step 8 orphan-vector cleanup claims `reconcile_index` "can collect any leftover orphan vectors later," but that promise doesn't hold today: the failure isn't logged, and even if it were, none of `reconcile_index`'s three existing repair mechanisms (failure-log replay, orphan scan, dangling-vector prune) are built to detect "an artifact has some correct vectors and some stale extra ones mixed together" — a full re-index rebuilds the current sections but never deletes ones that no longer belong. Fix: (b) wrap Step 8's `delete_vectors` call in a bounded inline retry with backoff, matching the existing Bedrock-throttle-retry pattern, so a transient failure self-heals immediately; (c) if retries are exhausted, log a distinct failure-log entry (a new kind, alongside T62's `reconcile_attempts`-bearing "needs re-index" kind) recording the orphan keys still needing deletion, and extend `reconcile_index` to recognise and repair that kind — participating in T62's existing `reconcile_attempts`/`stuck_failures` bounding rather than a separate mechanism.

68. ✅ **Cleanup-hygiene batch 2: reuse/DRY findings F-2, F-4, F-5, F-6, G-1, G-3 + H-3 concurrency** *(pure hygiene, zero behaviour change, same treatment as T63 — no dedicated spec file; this entry is the scope of record, per AGENTS.md's working convention)* — extract seven small shared helpers/fixes, each closing one confirmed duplication or latency finding.

69. ✅ **Convention-class cleanup: C-2, C-3, D-1, E-1, E-2, I-1** *(pure hygiene/consistency fixes, no new tool/parameter/response contract — no dedicated spec file; this entry, with each review finding's own write-up, is the scope of record, per AGENTS.md's working convention)* — the six remaining open findings from the 2026-08-13 full-codebase review, all convention-class (no currently-broken behaviour).

---

## Phase 13 — Artifact Type Vocabulary: `prd` → `vision` + `requirements`

Goal: replace the `prd` artifact type with two new types, `vision` and `requirements`, mirroring the amanox planning-artifact convention this project itself now follows (`vision.md` + `requirements.md` in place of a single `prd.md`; see this project's own `docs/planning-artifacts/` migration). No new spec file — the change is scoped as follow-up amendments to the existing `p7-t25b-extend-artifact-types.md` (type vocabulary and `resources.py`/README/Step 7 removal-guidance changes) and `p7-t25c-migration-skill-two-pass-classification.md` (Pass 1 filename-stem table change) specs, per AGENTS.md's working convention that a change applying an already-established pattern more consistently doesn't need a dedicated spec. Testing approach: **TDD** (NFR-07).

70. ✅ **Rename `prd` type to `vision` + `requirements`** — remove `"prd"` from `ARTIFACT_TYPES` in `artifact.py`; add `"vision"` and `"requirements"` (16 types total, up from 15). `resources.py`: replace the `prd` description entry with two new description entries (`vision`, `requirements`); update the tier 3 "Use for" line to drop `prd` and add `vision`, `requirements`. Migration skill (`skills/migrating-to-arkeology/SKILL.md`): split the Pass 1 filename-stem row — `vision` → `type=vision`, tier 3; `prd`/`product-requirements`/`requirements` (legacy single-document convention) → `type=requirements`, tier 3 (its content is predominantly requirements-shaped, and "requirements" is literally part of the name); update the Step 7 removal-guidance row accordingly; update `schema.yaml`'s inline `ARTIFACT_TYPES` comment. `setting-up-arkeology/SKILL.md` and `references/agents-snippet.md`: update tier 3 type lists and the AGENTS.md type-table entry. `src/arkeology/static/arkeology-studio.html`: replace the `prd` type-filter option, colour variable, and label with `vision` and `requirements` entries. `README.md` and `SERVER-REFERENCE.md`: update type tables/lists. `CHANGELOG.md`: add a `[Unreleased]` **Breaking** entry — callers writing or filtering on `type="prd"` must switch to `type="vision"` or `type="requirements"`.

---

## Phase 14 — Consistency Review Remediation

Goal: close the findings from the whole-repository consistency review of 2026-09-05 (ADRs, specs and
contracts against the source). Most are documentation-authority corrections rather than behaviour
changes; the code-level ones are defect fixes against preconditions the contracts already state. No
new spec files — each task entry below, together with the contract it corrects, is the scope of
record, per AGENTS.md's working convention that a fix enforcing an already-documented contract
clause does not need a dedicated spec. Testing approach: **TDD** (NFR-07).

71. ✅ **Reject a literal comma inside a `tags` or `source_artifacts` element** — `Artifact.validate_tags`
    and `validate_source_artifacts` in `artifact.py` enforced only `_require_no_control_chars`, while
    `validate_commit_refs`/`validate_references` also enforce `_require_no_comma`. The
    `s3.artifact` contract's Storage Shape section already requires that no element of a comma-joined
    field contain a comma, because the payload format has no escaping. Without the guard a tag `"a,b"`
    reached S3 object metadata as the raw string `a,b` and vector metadata as `["a,b"]`, so
    `read_artifact` (S3-sourced, split by `coerce_list_field`) reported `["a", "b"]` while
    `list_artifacts`/`search_artifacts` (vector-sourced) reported `["a,b"]` for the same artifact, and a
    `tags=["a"]` filter missed it. Fix: add the `_require_no_comma` call to both validators. `Artifact`
    is constructed only in `write.py`, and `write_artifacts` and `migrate_artifacts` both delegate
    through it, so the model validator is the single choke point for every write path — no per-caller
    guard. Caller-visible: such a write now returns `validation_error` rather than silently diverging
    the stores. Artifacts written before the guard converge on the split form at the next
    `reconcile_index`, which rebuilds vector metadata from the S3 side through the same coercion.

72. ✅ **Resolve a failure-log entry whose artifact no longer exists, instead of replaying it forever** —
    `reconcile.py`'s `_process_failure_log_entry` caught `KeyError` from `head_object` and returned a bare
    `failed` result with no `reconcile_attempts`. Since the end-of-run rewrite retains every entry that
    was not resolved, and only counter-bearing paths reach `stuck_failures`, an entry whose artifact had
    been deleted was replayed and re-reported on every run forever, with `failure_log_entries_after`
    never dropping — the "self-perpetuating failure-log replay" outcome T62 existed to prevent. T62's
    bounded-retry rule never reached this branch because it sits ahead of the replay attempt rather than
    inside it. Fix: that branch resolves the entry, pruning it from the log and reporting it once in
    `reconciled` under a new `failure_log_obsolete` source; it is not routed through the attempt counter,
    since a deleted artifact presents no cause for an operator to fix. The `CredentialError` and generic
    exception branches are unchanged. Scope of record: the Invariants and Postconditions of
    `docs/contracts/modules/arkeology.tools.reconcile.md`, plus the `Revision — 2026-09-05` section added
    to `docs/specs/p12-t62-bounded-reconcile-retry.md` recording which of its acceptance criteria is
    superseded and in what respect.

73. ✅ **Refuse to start when a read prefix sits at or beneath the write prefix** — `Settings` normalised
    each prefix but never compared them, so `WRITE_PREFIX=team` with `READ_PREFIXES=team/proj` made
    `is_own_scope` answer `True` for the other deployment's artifacts: they passed every own-scope-only
    gate (`archive_artifact`, `delete_artifact`, `purge_archived`, `link_metadata`) and Phase 2 of
    `reconcile_index` re-indexed them under the local scope. Fix: a `model_validator(mode="after")` on
    `Settings` rejecting a read prefix equal to or nested under the write prefix, running after both
    fields are normalised so slash-hidden forms are caught; duplicate read prefixes are de-duplicated
    rather than rejected. The constraint is deliberately one-directional — a write prefix *beneath* a
    read prefix, nesting among read prefixes, and sibling prefixes sharing a textual prefix all stay
    valid, each pinned by a test. `adr-2026-05-29-tier-based-access-control.md` records why: the foreign
    clause matches `scope` by exact equality while `is_own_scope` matches the key hierarchically, so only
    the one direction is unsafe. Caller-visible: a previously-accepted configuration now refuses to start.


## Risks and Open Questions

- **~~S3 Vectors `PutVector` upsert behaviour~~** — **CLOSED (2026-05-31, T17 confirmed)**: `PutVectors` silently overwrites an existing key (upsert confirmed). 44 integration tests passed green; tier 3 overwrite logic is correct as written; no code change required.

---

## References

- [`docs/planning-artifacts/vision.md`](./vision.md)
- [`docs/planning-artifacts/requirements.md`](./requirements.md)
- [`docs/brainstorming/brainstorming-artifact-store.md`](../brainstorming/brainstorming-artifact-store.md)
- [`docs/brainstorming/research-artifact-store.md`](../brainstorming/research-artifact-store.md)
- [`docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md`](../brainstorming/brainstorming-delete-artifact-2026-05-30.md)
- [`docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md`](../brainstorming/brainstorming-existing-project-migration-2026-05-30.md)
- [`docs/brainstorming/brainstorming-write-performance-2026-06-01.md`](../brainstorming/brainstorming-write-performance-2026-06-01.md)
- [`docs/specs/p8-t26-concurrent-embedding.md`](../specs/p8-t26-concurrent-embedding.md)
- [`docs/specs/p8-t27-retry-throttle-fix.md`](../specs/p8-t27-retry-throttle-fix.md)
- [`docs/specs/p8-t28-section-caps.md`](../specs/p8-t28-section-caps.md)
- [`docs/specs/p8-t29-migrate-skill.md`](../specs/p8-t29-migrate-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md`](../brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`](../brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md)
- [`docs/specs/p9-t31a-setting-up-arkeology-skill.md`](../specs/p9-t31a-setting-up-arkeology-skill.md)
- [`docs/specs/p9-t31b-migration-skill-exclusion-gate.md`](../specs/p9-t31b-migration-skill-exclusion-gate.md)
- [`docs/specs/p9-t31c-readme-reduction.md`](../specs/p9-t31c-readme-reduction.md)
- [`docs/brainstorming/brainstorming-reconcile-dangling-vectors-2026-06-03.md`](../brainstorming/brainstorming-reconcile-dangling-vectors-2026-06-03.md)
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

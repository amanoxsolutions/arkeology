---
type: plan
title: Plan Arkeology
description: Full phase history and current open phase for Arkeology development, tracking all completed and in-progress tasks from foundation through OKF schema alignment.
tags: []
timestamp: 2026-06-18T00:00:00Z
okf_version: "0.1"
---

# Plan: Arkeology

_Project: arkeology_
_Generated: 2026-05-29_ · _Last updated: 2026-08-12_
_Status: **V1 — Phases 1–9 complete (unit + integration suite passing against live AWS; ruff + mypy clean; Apache 2.0 licensed; production-hardened; moto migration complete; write performance hardened; bulk write + migration tools; setting-up-arkeology + sync-arkeology-plugin skills; skill distribution via native plugin mechanisms) · Phase 10 complete (artifact commit references + caller-controlled concurrency + OKF schema alignment + MCP data resources; v0.4.0) · Phase 11 complete (MCP App visual reading interface; v0.5.0) · Phase 12 (artifact cross-referencing + annotation-backed link storage) — tasks T45–T56 implemented and merged to `main`; T57–T62 (vector metadata budget hardening, guard coverage, migration self-heal — ADR-2026-08-13, Accepted) added and pending implementation; phase stays open while remediation work lands, and unreleased**_

## How we work

This project runs as a **single open phase**, not a pre-planned roadmap. Completed phases stay below as a full history (every feature marked ✅); the current phase shows its tasks in detail; and anything not yet started — issues, deferred work, and scoped-but-unbuilt features — lives in [`backlog.md`](backlog.md), pulled into the current phase when we decide to tackle it. There are no pre-planned future phases beyond the current one, and a phase ends when we judge it done.

- **Requirements** (FR/NFR) live in [`prd.md`](prd.md) — this plan references them by ID, it does not redefine them.
- **Per-task implementation detail** lives in [`../specs/`](../specs/) as `p<phase>-t<task>-<slug>.md` (e.g. task 3 of Phase 10 → `p10-t3`).
- **Status legend:** ⬜ pending · 🔄 in progress · 🔍 in review · ✅ done · 🔴 blocked
- **Delivery model:** each **Phase** is a coherent slice of value delivered as a set of tasks. A phase ends when we judge it done.

**Current state:** Phase 12 — Artifact Cross-Referencing + Annotation-Backed Link Storage: planned tasks **T45–T56** implemented, unit-tested (suite green), and merged to `main` (the `phase-12-cross-referencing` branch is merged; work is trunk-based on `main` per AGENTS.md); skills consolidated under `plugins/arkeology/skills/`; specs, ADR-011/ADR-012, and user docs aligned. **T57–T62** added 2026-08-13 as post-implementation remediation for a real vector-metadata-budget-overflow incident (guard coverage, `commit_refs`/`references` split-store fix, migration self-heal, bounded reconcile retry — see `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`, Accepted) and are pending Architect spec-writing before dispatch. Phase remains **open**: post-implementation remediation work is still in flight — the studio app and a documentation-hygiene pass are outstanding. Not yet released: latest tag is v0.5.0 (Phase 11 — Visual Reading Interface).

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

1. ✅ **Bootstrap Python project** — project must be installable and testable from source (NFR-08, NFR-09)
   - Approach: `uv init`, `pyproject.toml`, ruff, mypy, pytest, pre-commit hooks, `.gitignore` including tier 1 artifacts path
   - Done when: `uv run pytest` passes on an empty test suite; `uv run arkeology` starts without error

2. ✅ **FastMCP server skeleton** — stdio transport, structured logging, graceful shutdown; no tools registered yet (NFR-05)
   - Done when: server starts, logs its startup message, and exits cleanly

3. ✅ **AWS client layer** — S3, S3 Vectors, and Bedrock each behind a clean typed interface; HTTPS enforced; all boto3 calls catch credential-related exceptions and re-raise as structured typed errors (NFR-04, NFR-10, FR-12, D2)
   - Approach: one interface + one concrete implementation + one in-memory fake per service; fakes used in all unit tests
   - Done when: each interface has full test coverage via its fake; concrete implementations connect to real AWS in integration tests; a simulated credential failure at any client call produces a structured typed error, never a raw exception

4. ✅ **Configuration model** — all env vars parsed and validated at process start: `AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `WRITE_PREFIX`, `READ_PREFIXES`, `BEDROCK_EMBEDDING_MODEL`, `AWS_PROFILE` (optional), `SEARCH_FETCH_TOP_K` (optional, default 25), `SEARCH_MAX_ITERATIONS` (optional, default 3), `SEARCH_DEFAULT_TOP_K` (optional, default 5)
   - Done when: missing required vars raise a clear named error; optional vars parse to typed values with documented defaults; all vars present in configuration reference

5. ✅ **Startup validation sequence** — credentials, `WRITE_PREFIX` read/write, each `READ_PREFIXES` entry read, vector index existence, embedding model ↔ index dimension match; any failure is a hard stop with a distinct actionable error (FR-07, NFR-03)
   - Done when: each of the 5 failure conditions produces a distinct, actionable error message with a clear remediation hint; tests cover every failure path

---

## Phase 2 — Core value loop: write, search, read

Goal: an agent writes an artifact and immediately finds it via semantic search. This is the minimum viable loop — the reason the server exists.

6. ✅ **Artifact model and key generation** — metadata schema (FR-09), deterministic tier 2 slug (`type-date-title_slug`) and tier 3 slug (`type-title_slug`) (FR-08)
   - Done when: hash function is pure and tested; same inputs always produce the same key; different inputs produce different keys; edge cases (empty feature tags, same-day vs cross-day) tested

7. ✅ **Write artifact tool** — S3 PutObject → parse all `##` sections → one Bedrock embed per section (fallback: single embed from title+description+type+features if no sections) → one `S3 Vectors PutVector` per section with key `{artifact_key}#{section_name_slug}` and `artifact_id` in filterable metadata (fallback key = artifact_key); re-write: upsert existing section keys + query by `artifact_id` to delete orphaned section keys for removed sections; tier 2 immutability (FR-13); tier 3 overwrite in place (FR-15); idempotent same-key writes (NFR-06); returns identifier (FR-01)
   - Done when: write → read → search round-trip tested end-to-end; section vectors carry correct `artifact_id`; same-day tier 2 write is idempotent; tier 3 same-type+title overwrites and cleans orphaned section vectors; fallback (no `##` sections) produces single document-level vector; credential errors return structured responses; no raw exceptions reach the caller
   - Integration test checkpoints: PutVector upsert behaviour — docs provide strong evidence (unique key semantics, no `ConflictException` in error list, "write/update/delete" language in overview, no separate UpdateVector API); empirical confirmation in T17; `#` key character — confirmed valid by docs (key is `String` 1–1024, no char pattern restriction; official tutorial uses spaces in keys); empirical confirmation in T17

8. ✅ **Search artifacts tool** — one Bedrock embed of query; re-fetch loop: single combined `S3 Vectors QueryVectors` call per iteration using `$or` filter covering own scope (unrestricted) and foreign scopes (tier 3 + shared only); group section vectors by `artifact_id`; repeat until `top_k` artifacts collected or `SEARCH_MAX_ITERATIONS` reached; metadata + description only in response, no content (NFR-02) (FR-03)
   - Done when: results contain no full content; cross-scope filter enforced and tested; re-fetch loop exits correctly when index is exhausted; `SEARCH_MAX_ITERATIONS` cap respected; zero results distinguished from service error; filter combinations return correct subsets
   - Integration test checkpoint: S3 Vectors `$nin` operator on `artifact_id` — confirmed supported by AWS documentation ([Metadata filtering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html)); non-empty array required (omit clause on first iteration); empirical confirmation in T17

9. ✅ **Read artifact tool** — S3 GetObject by identifier; cross-scope gate enforced (FR-02, FR-10)
   - Done when: known artifact returns full content; tier 2 artifact from foreign scope is rejected with a clear error; tier 3 shared artifact from foreign scope is accessible

---

## Phase 3 — Complete tool surface: list, archive, delete, health, reliability

Goal: the server is operationally complete. Agents can list, archive, and delete artifacts; admins can diagnose health. Partial write failures are never silent.

10. ✅ **List artifacts tool** — metadata-only listing with filters (type, feature tags, team, project, tier, status); no semantic ranking; cross-scope gate enforced (FR-04)
    - Done when: filter combinations return correct subsets; archived artifacts excluded by default; active-only filter can be overridden; cross-scope gate tested

11. ✅ **Archive artifact tool** — update `status` in S3 Vectors metadata to inactive; scoped to `WRITE_PREFIX` only; no content modification (FR-05, FR-14)
    - Done when: archived artifact absent from default search and list; archiving a foreign-scope artifact returns a clear rejection; no other metadata or content is modified

12. ✅ **Delete artifact tool** — hard-delete by `artifact_id` with `confirm=True` required; delete vectors first then S3 object; warn-and-proceed if artifact is a synthesis source; scoped to `WRITE_PREFIX` only; partial delete (vectors gone, S3 delete failed) recoverable via reconciliation (FR-21, FR-13, FR-14, AC-19)
    - Done when: deleted artifact not retrievable by ID; deleted artifact absent from search and list results; foreign-scope delete returns clear rejection; synthesis warning returned when applicable; credential errors return structured responses
    - **Also deliver**: update all existing integration tests (T7–T9) to use `delete_artifact` in teardown so test data is cleaned up on every run

13. ✅ **Purge archived tool** — bulk hard-delete of all `status=inactive` artifacts in own scope with `confirm=True` required; cascade-delete any synthesis whose every `source_artifact` is in the purge set; returns summary of purged identifiers (FR-22, AC-20)
    - Done when: all inactive artifacts absent after purge; cascade-deleted synthesis identifiers reported; empty purge set returns a clear no-op response; foreign-scope artifacts never touched

14. ✅ **Health check tool** — independent per-component status: S3, S3 Vectors, Bedrock, `WRITE_PREFIX`, each `READ_PREFIXES` entry (FR-06)
    - Done when: each component reports independently; a single misconfigured component is identifiable without log access; all-healthy case tested alongside each individual failure case

15. ✅ **Partial write failure log** — on S3 success + S3 Vectors failure: write structured entry to local tier 1 failure log before surfacing error; error includes artifact identifier; Bedrock throttle triggers one retry with back-off before error (FR-16, NFR-11)
    - Done when: simulated S3 Vectors failure produces a machine-readable failure log entry and a structured error with the identifier; Bedrock throttle triggers exactly one retry; failure log path is gitignored

16. ✅ **Synthesise artifacts tool** — semantic search + batch `read_artifact` for top-k results; returns bundled full content (identifier, metadata, description, content) per source artifact; agent performs synthesis in-context; agent writes back via `write_artifact` with `type=synthesis`, `tier=3`, `source_artifacts=[...]` (FR-19)
    - Done when: single tool call returns full content from multiple matching artifacts; result includes all required fields; content is bounded by the `top_k` ceiling (100); cross-scope gate applied (same as `search_artifacts`); credential errors return structured responses

---

## Phase 4 — Self-documentation and adoption *(T18–T20 can start in parallel with Phase 3)*

Goal: any agent can discover the schema at runtime; a new team can adopt the server following only the README and AGENTS.md snippet.

17. ✅ **Run full integration test suite** *(top priority — phase gate for T19 setup docs)* — execute all integration tests for T7–T16 against live AWS credentials; resolve remaining open question Q1 (upsert behaviour); confirm T7/T8 empirical integration checkpoints; update Learnings; close Phase 3 retrospective (NFR-07)
    - Done when: `uv run pytest tests/integration/ -q` passes green; upsert behaviour result recorded in Learnings — if upsert confirmed, no code change needed; if NOT upsert, tier 3 overwrite logic updated to explicit delete-then-re-put section vector pattern, unit and integration tests updated, and suite re-run green; `#` key separator and `$nin` operator confirmed empirically; open question Q1 closed in this plan; Phase 3 retrospective flag removed

18. ✅ **MCP Resources** — expose artifact schema, tier model, visibility and cross-scope model, type catalogue, and query strategy guidance as MCP Resources; always in sync with running server version (FR-18)
    - Done when: a connected agent can query resources and receive accurate, current field definitions, valid values, tier semantics, and query strategy guidance; resources update automatically when schema changes

19. ✅ **Setup documentation and AGENTS.md snippet** — README quick start, full configuration reference with all env vars, minimum IAM policy, AWS provisioning steps (including S3 Vectors index creation with `description` and `source_artifacts` non-filterable slots, and explicit warning that index dimension, distance metric, and non-filterable keys are immutable after creation — a new index must be created on model or dimension change), `mcp-servers.json` example; recommended AGENTS.md snippet covering when to write/search, artifact types, description quality guidance, tier selection, query strategy (start narrow, broaden if needed), when to synthesise and how (NFR-12)
    - Done when: a new team member can provision AWS resources, configure the server, and connect an agent following only the README and AGENTS.md snippet — no prior knowledge of the codebase required

20. ✅ **Migration skill** — `skills/migrating-to-arkeology/SKILL.md` with structured workflow covering both paths (agent-only < 30 files; manifest + script ≥ 30 files); discovery, classification table, metadata enrichment guidance, post-migration AGENTS.md update step; `skills/migrating-to-arkeology/scripts/migrate.py` with PEP 723 inline deps — Bedrock description generation, `git log` date recovery, bulk `write_artifact` calls, `--dry-run` mode (JSON preview), structured JSON stdout, idempotent on re-run; `skills/migrating-to-arkeology/schema.yaml` documenting ARKEOLOGY_IMPORT.yaml manifest format; README table of skills directory paths for Claude Code, Codex, Copilot, and OpenCode (FR-23, NFR-12)
    - Done when: `SKILL.md` covers both workflow paths end-to-end including post-migration AGENTS.md update; `migrate.py --help` documents all flags; `migrate.py --dry-run` with a valid manifest outputs JSON preview without any writes; full manifest run imports all listed artifacts and makes them immediately searchable; re-running the same manifest produces no duplicates; date fallback (no git history) is handled gracefully and logged to stderr
    - **Note**: `migrate.py` calls AWS APIs directly via boto3 (PEP 723 dep) using the same env vars as the server (`ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `AWS_REGION`, `BEDROCK_EMBEDDING_MODEL`) — it does not import from `arkeology` to avoid a source dependency from the skill bundle into the server package

---

## Phase 5 — Could-have: reconciliation and synthesis freshness

21. ✅ **Reconciliation tool** — failure log replay + full S3 vs vector index orphan scan (including partial-delete orphans); re-index missing entries; remove resolved failure log entries; return structured summary (FR-17)
    - Done when: an orphaned S3 object (present in S3, absent from vector index) is detected and re-indexed; partial-delete orphans are handled identically to write-failure orphans; failure log entries are resolved and cleared; summary identifies each recovered artifact by identifier and title

22. ✅ **Synthesis freshness check tool** — scan all `synthesis` type artifacts; compare synthesis `date` against `date` of each listed `source_artifact`; flag stale (source updated more recently) and orphaned (source archived) entries; return structured report (FR-20)
    - Done when: a synthesis artifact with a source artifact updated after the synthesis date is flagged correctly; an archived source artifact is flagged correctly; all-fresh case returns an empty report; no S3 content fetch required (metadata-only operation)

---

## Phase 6 — Production Hardening (Review Fix Cycle)

Goal: resolve all 76 findings from the full project code review (12 critical, 27 major, 37 minor). No new functionality — correctness, security, and maintainability only.

23. ✅ **Implement all 20 review-fix specs** — credential error hardening, vector score semantics, health probe filter, README IAM fixes, exception chaining, S3/Bedrock hardening, health CredentialError distinction, archive idempotency, list scope filter, shared search helper, test infrastructure consolidation, CredentialError test coverage, integration test isolation, project config fixes, minor foundation/client/tool/test/doc improvements, ABC→Protocol migration, `filter`→`filter_expr` rename, Apache 2.0 licence, repo URL
    - Done when: all 486 unit tests passing; ruff + mypy clean; all 20 specs implemented; full post-implementation review passed clean (0 critical, 0 major, 0 minor)
    - Spec files: `docs/specs/review-fix-01-*.md` through `docs/specs/review-fix-20-*.md`

24. ✅ **V1 integration suite re-run** — full integration test suite re-run against live AWS after Phase 6 hardening; all tests pass; V1 declared clean
    - Done when: `uv run pytest tests/integration/ -q` passes green post-hardening — confirmed 2026-06-01

---

## Phase 7 — Test infrastructure: moto migration

Goal: replace hand-rolled in-memory fakes for S3 and S3 Vectors with moto-backed real client implementations. Fixes the score range inconsistency between unit and production and aligns with the project's testing convention.

25. ✅ **Migrate unit tests from hand-rolled fakes to moto** — delete `FakeS3Client` and `FakeVectorsClient`; replace with moto-backed `S3ClientImpl` / `VectorsClientImpl` throughout the unit test suite; patch `S3VectorsBackend.query_vectors` with a cosine similarity extension in `conftest.py`; fix score range from `[0, 2]` (fake) to `[−1, 1]` (cosine similarity, matching production) in all score assertions (FR-mock-conv)
    - Done when: 451 unit tests passing; `FakeS3Client`, `FakeVectorsClient` deleted; `test_fake_s3.py`, `test_fake_vectors.py` deleted; `test_moto_query_vectors_extension.py` added with 6 targeted tests; ruff + mypy clean; AGENTS.md Testing Conventions accurate

---

## Phase 8 — Write Performance

Goal: eliminate the dominant latency bottlenecks in `write_artifact` and `migrate.py`. No new
tools, no breaking changes — pure performance, correctness, and usability improvements.
Specs: `docs/specs/p8-t26-*.md` through `docs/specs/p8-t29-*.md`.

**Execution order:** T26 first (establishes concurrent embed foundation all others benefit from);
T27 and T28 can proceed in parallel after T26 merges; T29 is independent and can start at any
point.

26. ✅ **P1 — Concurrent embedding + batched put_vectors** *(highest impact)* — replace the serial section `for` loop in `write_artifact` with `asyncio.to_thread` + `asyncio.gather` bounded by `asyncio.Semaphore(SECTION_CONCURRENCY)`; collapse all per-section `put_vector` calls into one `vectors.put_vectors_batch` call per artifact; add `SECTION_CONCURRENCY` config var (default 5); add `put_vectors_batch` to `VectorsClientInterface` and `VectorsClientImpl` (chunk at 500) (NFR-13, NFR-14)
    - Done when: 8-section write makes 8 concurrent embed calls and 1 batch put call (verified by unit test spy); `SECTION_CONCURRENCY=0` rejected at startup; all existing write tests pass; ruff + mypy clean
    - Spec: `docs/specs/p8-t26-concurrent-embedding.md`

27. ✅ **P2 — Retry and throttle fix** *(correctness fix)* — remove the duplicate `ThrottlingException` catch-and-retry blocks from `write.py` (redundant with `bedrock.py`'s internal retry; adds up to 5 s per throttled section); add `random.uniform(0, 1)` jitter to the `bedrock.py` retry sleep to prevent thundering-herd when concurrent embeds throttle simultaneously (NFR-11)
    - Done when: a `ThrottlingException` exhausting both `bedrock.py` retries results in exactly 2 `embed` calls total (no third attempt from `write.py`); `asyncio.sleep` is never called from `write.py` on a throttle event; jitter is applied (verified by patching `random.uniform`); ruff + mypy clean
    - Spec: `docs/specs/p8-t27-retry-throttle-fix.md`

28. ✅ **P3 — Configurable section caps** *(defensive bound)* — add `EMBED_MAX_SECTIONS` (default 20) and `EMBED_MIN_SECTION_LENGTH` (default 50 chars) config vars; apply as filters in `write.py` immediately after `parse_sections`; fall back to document-level embed if no sections remain; log dropped sections at DEBUG (FR-01, NFR-13)
    - Done when: a section with a 30-char body is not embedded when `EMBED_MIN_SECTION_LENGTH=50`; a 25-section document indexes only 20 vectors when `EMBED_MAX_SECTIONS=20`; full content is still returned by `read_artifact`; `EMBED_MAX_SECTIONS=0` rejected at startup; ruff + mypy clean
    - Spec: `docs/specs/p8-t28-section-caps.md`

29. ✅ **L1+L2 — Migration skill parallel writes** *(skill + script)* — restructure SKILL.md into three mutually exclusive bands (1–4 files → Path A sequential; 5–9 files → Path B manifest+script; ≥10 files → Path C parallel sub-agents via `task` tool, batches of 4–5); lower Path B threshold from 30 → 5 files; add `asyncio.gather` + `asyncio.Semaphore(MIGRATE_CONCURRENCY)` to `migrate.py` for concurrent writes; read `MIGRATE_CONCURRENCY` from env (default 3); wrap `main()` with `asyncio.run` (FR-23, NFR-15)
    - Done when: SKILL.md Step 5 clearly describes the two-phase enrichment + parallel-write path for ≥ 10 files with a sub-agent fallback; Path B gate reads "< 5 files" and "≥ 5 files"; `migrate.py --dry-run` on a 5-entry manifest outputs correct JSON preview; `migrate.py` on a 9-entry manifest processes entries concurrently (not strictly ordered in log); `MIGRATE_CONCURRENCY=0` exits with a clear error
    - Spec: `docs/specs/p8-t29-migrate-skill.md`
    - **Open question:** Do sub-agents spawned by the `task` tool inherit Arkeology MCP connections? Test empirically during implementation; the SKILL.md fallback path (sub-agent returns metadata → main agent writes) must be in place regardless.

---

## Phase 9 — Improvements and Fixes

Goal: quality-of-life improvements and documentation polish before declaring v1, plus the v0.3.0 artifact commit-references feature.

30. ✅ **Z1 — `write_artifacts` + `migrate_artifacts` bulk tools** *(priority 1 — unblocks correct migration performance)* — add two new MCP tools:
    - **`write_artifacts`** (FR-25): accepts a list of artifact descriptors (same fields as `write_artifact`; `description` required); processes all concurrently via `asyncio.gather` + `asyncio.Semaphore(ARTIFACT_CONCURRENCY)`, default 3; section-level concurrency (P1, `SECTION_CONCURRENCY`) applied within each artifact; partial failures recorded per-artifact in response list without aborting the batch; add `ARTIFACT_CONCURRENCY` config var (int, default 3, ≥ 1).
    - **`migrate_artifacts`** (FR-26): accepts a list of artifact descriptors with `description` optional; for each descriptor missing a description, generates one concurrently via Bedrock Nova Lite (bounded by semaphore, reusing `ARTIFACT_CONCURRENCY` — no separate `DESCRIPTION_CONCURRENCY` needed); generated descriptions clipped to 280 chars (`dry_run=False` = silent clip + DEBUG log; `dry_run=True` = return clipped in enriched list for agent review; same rule applies to agent-provided descriptions that already exceed 280 chars); `dry_run=True` returns enriched descriptor list without writing; `dry_run=False` generates descriptions then delegates to `write_artifacts`; add `BEDROCK_TEXT_MODEL` config var (string, default `amazon.nova-lite-v1:0`); add 6th startup health check validating Nova Lite accessibility when `BEDROCK_TEXT_MODEL` is configured.
    - **P4 — `EMBED_MAX_SECTION_LENGTH`** (FR-01): add `EMBED_MAX_SECTION_LENGTH` config var (int, default 24,000 chars; 0 = disabled); sections exceeding the limit are truncated before the embedding call (not skipped); truncation applies to embedding input only — S3 content is never modified; log at DEBUG; default 24,000 chars targets ≈ 6,000–8,000 tokens depending on content type (code ~3 chars/token ≈ 8,000 tokens; prose ~4 chars/token ≈ 6,000 tokens) — comfortably under Titan's 8,192-token hard limit across content types.
    - **migrate.py eliminated**: delete `skills/migrating-to-arkeology/scripts/migrate.py` and the `scripts/` directory entirely; all Bedrock and write logic lives in the server.
    - **SKILL.md simplified**: remove all sub-agent/task-tool references; two paths — agent-only (< 5 files: agent classifies + generates descriptions in-context + calls `write_artifacts` once) and manifest + `migrate_artifacts` (≥ 5 files: agent classifies into ARKEOLOGY_IMPORT.yaml with git dates → calls `migrate_artifacts(dry_run=True)` to preview → reviews → calls `migrate_artifacts(dry_run=False)` to write); ARKEOLOGY_IMPORT.yaml as progress tracker enabling partial-failure retry; ≤ 500 lines; cross-IDE compatible (no IDE-specific tool references).
    - Update plan.md, PRD, and brainstorming docs.
    - Done when: `write_artifacts` on a 10-entry list processes entries concurrently (verified by log order); any failed entry appears in the response with an error field while successful entries report `written=True`; `ARTIFACT_CONCURRENCY=0` exits with a clear error at startup; `migrate_artifacts` with `dry_run=True` returns enriched descriptors with generated descriptions and writes nothing; descriptions in the enriched list are clipped to 280 chars; `migrate_artifacts` with `dry_run=False` writes all artifacts and makes them immediately searchable; `BEDROCK_TEXT_MODEL` startup check fires when configured; a section body exceeding `EMBED_MAX_SECTION_LENGTH` is truncated before embedding but the full body is returned unchanged by `read_artifact`; `EMBED_MAX_SECTION_LENGTH=0` disables truncation; `skills/migrating-to-arkeology/scripts/` directory absent; SKILL.md ≤ 500 lines and references no IDE-specific tool; full round-trip: agent classifies → `migrate_artifacts(dry_run=True)` → `migrate_artifacts(dry_run=False)` → `list_artifacts` confirms all entries
    - Spec: `docs/specs/p9-t30-write-artifacts.md` (status: **approved + complete** — 547 unit tests passing; SKILL.md 354 lines; scripts/ deleted; ruff + mypy clean; integration tests pending live AWS run)
    - **New config vars**: `ARTIFACT_CONCURRENCY` (int, default 3, ≥ 1); `BEDROCK_TEXT_MODEL` (string, default `None` — operator opt-in); `EMBED_MAX_SECTION_LENGTH` (int, default 24,000, ≥ 0; 0 = disabled); combined `ARTIFACT_CONCURRENCY × SECTION_CONCURRENCY ≤ 15` rule of thumb (safe Bedrock quota ceiling)
    - **Supersedes**: L1+L2 spec (`p8-t29-migrate-skill.md`) — both made redundant by server-side parallelism; spec marked `status: superseded`

31. ✅ **Setting-up-arkeology skill** — `skills/setting-up-arkeology/SKILL.md` with 6-step structured
    workflow that assumes all required AWS resources are already provisioned externally:
    (1) parameter collection upfront — region, existing S3 bucket name, existing S3 Vectors
    bucket and index names, embedding model, AWS profile, IDE choice, team/project names,
    optional cross-scope read prefixes; (2) pre-flight checks — AWS CLI availability, active
    credentials (`aws sts get-caller-identity`), `uv` installed, S3 bucket reachable
    (`head-bucket`), Vectors index reachable (`describe-index`), Bedrock model accessible
    (`invoke-model`); (3) clone and Python setup; (4) MCP client config — write the
    Arkeology server entry including all required env vars directly into the correct
    configuration file for the chosen MCP client (see multi-client table below); show entry
    and ask explicit permission before writing; merge into existing file without touching
    other entries; display entry for manual addition if operator declines; no `.env` file is
    written at any step; (5) smoke test via `health_check` — all components must return
    `"status": "ok"` before proceeding; (6) permanent exclusion configuration —
    two-part step: (A) ADR strategy (git-only vs arkeology-only): if git-only, auto-detect
    ADR folder from common directory names; confirm with operator or ask for path if not
    found; add confirmed path to `local_only_paths` and `adr` to `local_only_types`; (B) ask
    for any additional folders or files that should never go into Arkeology; for each path,
    infer artifact type from the migration skill's path-pattern table and confirm with
    operator. Write `<!-- arkeology:config -->` block to AGENTS.md; write narrative snippet
    from `references/agents-snippet.md`. Re-running updates config block in place. No IAM
    policy generation at any step — the README provides a static reference policy with
    YOUR-* placeholders that operators use as a template. (FR-24, FR-44, NFR-12, AC-28,
    AC-29, AC-40, AC-42, AC-49)
    - **Multi-client per-project config (FR-44, AC-49)**: the skill supports all four
      MCP clients — Claude Code, opencode, GitHub Copilot CLI, and OpenAI Codex. For
      clients that support a project-scoped config file (Claude Code `.mcp.json`/`.mcp.jsonc`,
      opencode `opencode.json`, Codex `.codex/config.toml`), the skill writes
      the Arkeology entry into that project-level file. GitHub Copilot CLI uses `.mcp.json`
      at the workspace root (shared with Claude Code, supported since v0.0.401), so all four
      clients receive a project-scoped entry. Config files are
      always edited (JSON/JSONC: parse → insert → write; TOML: append section), never
      replaced or overwritten. opencode uses `environment` as the env-vars key (not `env`);
      all other clients use `env`. For Codex, note the "trusted projects only" requirement
      for project-scoped config. opencode's merge is additive at the server-name level —
      project config adds new server names without disturbing global entries (empirically
      confirmed). The skill checks for `opencode.json`; creates `opencode.json` (no dot
      prefix — officially documented name) if neither exists.
    - **Also delivers**: update `skills/migrating-to-arkeology/SKILL.md` — remove Step 2c ADR
      strategy gate entirely; add pre-flight check at top of Step 2: if no `arkeology:config`
      block found in AGENTS.md → hard stop ("run `setting-up-arkeology` first"); if block found →
      read `local_only_paths` (excluded at scan time) and `local_only_types` (excluded after
      classification). (FR-23, AC-41)
    - Done when: `SKILL.md` covers all 6 steps including Step 4 multi-client table with all
      four clients; the four client configs are shown with their correct format (JSON, JSONC,
      TOML), correct env key (`environment` for opencode, `env` for all others), and correct
      file path (project-level for all four clients, including Copilot CLI via `.mcp.json`
      shared with Claude Code); the safe-edit requirement is explicit
      in Step 4 (parse-insert-write for JSON/JSONC; append-section for TOML); `opencode.json`
      (no dot prefix) is used when creating new opencode project configs; `references/agents-snippet.md`
      contains the complete AGENTS.md snippet; `SKILL.md` ≤ 500 lines; README shrinks
      to ~255 lines with no `YOUR-*` placeholder blocks remaining; a new operator following
      the skill reaches a server confirmed healthy by `health_check` returning all-ok; the
      `arkeology:config` block written to AGENTS.md is valid YAML inside the HTML comment
      with all four keys; re-running the skill replaces the block in place; migration skill
      Step 2c is absent; migration skill halts on missing config block; migration skill scan
      respects `local_only_paths` and classification respects `local_only_types`
    - Specs: `docs/specs/p9-t31a-setting-up-arkeology-skill.md` (requires revision — add
      multi-client per-project config per FR-44, AC-49, and
      `docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`),
      `docs/specs/p9-t31b-migration-skill-exclusion-gate.md`,
      `docs/specs/p9-t31c-readme-reduction.md`

32. ✅ **Reconcile Phase 3 — dangling vector pruning** *(priority 2)* — extend `reconcile_index` with a third phase that detects and deletes vector index entries whose backing S3 object no longer exists. Dangling vectors arise when an S3 object is deleted externally (outside Arkeology) while its vector index entries remain; they surface in search and list results with valid-seeming metadata but cause `read_artifact` to return a not-found error. Phase 3 reuses data already collected in Phase 2 at zero additional API cost: `indexed_artifact_ids − set(own_keys)` identifies all dangling artifact IDs; their vector keys are already grouped from the existing `indexed_keys_raw` listing and are deleted. Phase 3 always runs automatically — no new parameters, consistent with Phases 1+2 which also auto-repair without confirmation. Response schema gains three additive fields: `dangling_artifacts_found` (int), `dangling_vectors_pruned` (int), `dangling_artifacts` (list[str]). Existing callers that ignore unknown keys are unaffected.
    - Done when: an artifact whose S3 object was deleted externally while its vector entries remain is detected by Phase 3 and its vector entries are removed; `dangling_artifacts_found` and `dangling_vectors_pruned` report correct counts; `dangling_artifacts` lists affected IDs; clean state (no dangling vectors) reports all zeros in the new fields; own-scope gate enforced — foreign-scope vector entries never pruned; credential error during vector deletion returns structured error; Phase 2 orphan scan and Phase 3 dangling prune both execute within a single `reconcile_index` call
    - Spec: `docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md` (status: complete)

33. ✅ **Skill distribution via native plugin mechanisms** — wire `setting-up-arkeology` and `migrating-to-arkeology` into engineers' AI tools using the same plugin pattern as the shared engineering plugin project. No new server code — purely repo-level files and a bash script. Independent of all other Phase 9 tasks; can be worked at any point.
    - **OpenCode JS plugin (FR-33)**: `package.json` at repo root (`name: arkeology`, `type: module`, `main: .opencode/plugins/arkeology.js`); `.opencode/plugins/arkeology.js` ESM module (~50 lines) using the `config` hook to push `skills/` into `config.skills.paths`; path resolved relative to plugin file via `import.meta.url` so it works from Bun's cache regardless of clone location; errors in the hook logged to stderr, never thrown.
    - **Claude Code plugin (FR-34, FR-35, FR-36)**: `.claude-plugin/marketplace.json` registering the repo as a private marketplace source; `plugins/arkeology/.claude-plugin/plugin.json` (name: `arkeology`, giving the `arkeology:` slash command namespace); `plugins/arkeology/skills/setting-up-arkeology` and `plugins/arkeology/skills/migrating-to-arkeology` as symlinks to `../../../skills/<name>`; `plugins/arkeology/skills/plugin-sync/SKILL.md` (~22 lines, Claude Code-specific: runs `git -C ~/.claude/plugins/arkeology pull` + `/reload-plugins`; notes server requires a separate update); no agents directory.
    - **Install script (FR-37, FR-38, FR-39, FR-40, FR-42)**: `install.sh` at repo root; detects `claude`, `opencode`, `copilot` on PATH; OpenCode section prints the `git+ssh://` plugin snippet (does not patch `opencode.jsonc` directly); Claude Code section runs `claude plugin marketplace add` + `claude plugin install arkeology@arkeology` and merges `Bash(git -C * pull)` pre-approval into `~/.claude/settings.json`; no `@`-import to `~/.claude/CLAUDE.md` (Arkeology AGENTS.md is server-specific context, not global engineering conventions); no agent symlinks loop (Arkeology has no agents); idempotent; bash only / WSL Ubuntu on Windows; always prints session-refresh instructions.
    - **Copilot adapter (FR-41)**: inside `install.sh`; detects `copilot` on PATH as the Copilot-specific signal (not `gh`); checks `gh` and `gh skill` as prerequisites; loops over `skills/*/` calling `gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`; stops immediately on any failure, prints error and docs link; no fallback path.
    - **README quick-install section (FR-43)**: adds a "Quick install" section before the full server setup instructions; documents the one-line OpenCode plugin snippet (SSH primary, HTTPS alternative) and the two-command Claude Code install; brief note that `arkeology:` coexists with other plugin namespaces without collision.
    - Done when: adding the plugin line to `opencode.jsonc` and restarting OpenCode makes `setting-up-arkeology` and `migrating-to-arkeology` discoverable via the `skill` tool (AC-43); `claude plugin install arkeology@arkeology` makes `/arkeology:setting-up-arkeology`, `/arkeology:migrating-to-arkeology`, `/arkeology:plugin-sync` available as slash commands (AC-44); `./install.sh` on a machine with all three tools wires each and prints session-refresh instructions (AC-45); running the script twice produces no duplicate entries or errors (AC-46); `/arkeology:plugin-sync` pulls and reloads without permission prompts (AC-47); partial-tool install skips absent tools cleanly (AC-48); `plugin-sync` skill absent from shared `skills/` directory; no Python source changes; ruff + mypy clean
    - Brainstorming: `docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md`
    - Spec: `docs/specs/p9-t33a-opencode-js-plugin.md`, `docs/specs/p9-t33b-claude-code-plugin.md`, `docs/specs/p9-t33c-install-script.md`, `docs/specs/p9-t33d-copilot-adapter.md`, `docs/specs/p9-t33e-readme-quick-install.md` (status: complete)

34. ✅ **`sync-arkeology-plugin` — generic tool-aware skill update** — add `skills/sync-arkeology-plugin/SKILL.md` (~35 lines). The skill detects which AI coding tool it is running in and takes the appropriate update action for each:
    - **OpenCode**: clear `~/.cache/opencode/packages/arkeology@git+*` then instruct restart — Bun fetches the latest HEAD on next launch.
    - **Claude Code**: perform `git -C ~/.claude/plugins/arkeology pull` then `/reload-plugins` (replaces `plugin-sync` — same steps, one canonical cross-tool command; `plugin-sync` is removed as part of this task).
    - **Copilot**: instruct the engineer to re-run `./install.sh` from the Arkeology repo (which calls `gh skill install --force` for all skills).
    - **Unknown / undetected**: explain all three paths and ask the engineer to identify their tool.
    The skill is distributed through all existing channels: OpenCode auto-discovers it (plugin pushes all of `skills/`); Claude Code requires a new symlink under `plugins/arkeology/skills/sync-arkeology-plugin → ../../../skills/sync-arkeology-plugin` and removal of the existing `plugin-sync` symlink and SKILL.md; Copilot receives it via `gh skill install --force` on the next `install.sh` run (FR-41 loop already covers all `skills/*/` entries). No Python source changes.
    - Done when: `skills/sync-arkeology-plugin/SKILL.md` exists; the Claude Code plugin symlink is in place and `plugin-sync` is removed; an engineer on any supported tool invokes the skill and receives the correct action for their tool; unknown tool falls back to the explanation path; ruff + mypy unaffected
    - Spec: `docs/specs/p9-t34-sync-arkeology-plugin.md`

---

### Phase 10 — Artifact Commit References + OKF Schema Alignment + MCP Data Resources

Goal: close the traceability gap between artifacts and git commits (T35–T40); align the
`feature_tags` field name with OKF vocabulary as a pure rename (T41); expose MCP data resources
for direct artifact browsing from host tools (T42). All tasks complete.

**Execution order:** T35 is an independent prerequisite (filter.py only); T36 depends on
T35 and must complete before T37 and T38; T37 and T38 can be worked in parallel once T36
merges. T39 and T40 are independent of T35–T38 and of each other and can be worked at any point. This track is
independent of T31, T32, T33, and T34 — no shared files.

35. ✅ **Filter range operators ($gte / $lte)** *(prerequisite — filter.py only; no tool changes)* — add `$gte` and `$lte` inclusive string-comparison operators to `filter.py`; update module docstring (FR-30)
    - Done when: `matches_filter(meta, {"field": {"$gte": v}})` returns `True` iff `meta["field"] >= v`; `$lte` symmetric; absent field → `False`; combined `$and` interval works; `$gt` / `$lt` (strict) raise `ValueError`; all existing operator tests pass; ruff + mypy clean
    - Spec: `docs/specs/p10-t35-filter-range-operators.md`

36. ✅ **`commit_refs` and `last_edited_ulid` metadata fields** *(core data model)* — add `commit_refs: list[str]` to `Artifact`; generate `last_edited_ulid` via `python-ulid` on every `write_artifact` call; store both fields in S3 object metadata and vector metadata following the `tags` encoding pattern (comma-joined string in S3, `list[str]` in vectors, key omitted when empty in vectors); include `last_edited_ulid` in `write_artifact` response; expose both fields in `list_artifacts` (with `commit_refs` filter parameter) and `read_artifact` responses; legacy artifacts (missing fields) return `None` — no error (FR-28, FR-29)
    - Done when: `write_artifact` response includes `last_edited_ulid`; `read_artifact` and `list_artifacts` return both fields; `commit_refs` filter in `list_artifacts` returns correct subset; empty `commit_refs` stores `""` in S3 and omits key from vector metadata; legacy artifacts return `None` for `last_edited_ulid` and `[]` for `commit_refs`; ruff + mypy clean
    - Spec: `docs/specs/p10-t36-commit-refs-metadata-fields.md`
    - **New dependency**: `python-ulid` added to `pyproject.toml`

37. ✅ **`propose_commit_links` tool** *(read-only discovery)* — scan own-scope artifacts in the vector index optionally bounded by `last_edited_ulid >= since_ulid`; deduplicate by `artifact_id`; filter client-side for artifacts with absent or empty `commit_refs`; return candidate list with human-readable timestamps; no writes (FR-31)
    - Done when: tool called with `since_ulid` returns only own-scope artifacts written at or after that timestamp with no `commit_refs`; called without `since_ulid` returns all unlinked own-scope artifacts; foreign-scope artifacts never included; empty result returns `{"proposed": [], "commit_sha": "..."}` not an error; credential errors return structured responses; ruff + mypy clean
    - Spec: `docs/specs/p10-t37-propose-commit-links.md`

38. ✅ **`link_commit` tool + AGENTS.md post-commit protocol** *(write, no re-embed)* — for each confirmed `artifact_id`: `list_vectors_by_metadata` → `get_vectors` → merge `commit_sha` into `commit_refs` (append + deduplicate) → `put_vectors_batch` with same float32 embeddings and updated metadata; scope-gate rejects foreign-scope IDs (counted in `skipped`); generate `next_since_ulid` after all artifacts processed; return `{linked, skipped, commit_sha, next_since_ulid}`; add AGENTS.md post-commit protocol snippet to setting-up-arkeology skill (FR-32)
    - Done when: `link_commit` appends SHA to all section vectors without Bedrock call; existing SHA not duplicated; foreign-scope IDs skipped and counted; `next_since_ulid` returned; two successive calls produce monotonically non-decreasing cursors; Bedrock `embed` never called (verified by spy); credential errors return structured responses; AGENTS.md snippet includes session-start ULID capture, post-commit proposal, confirmation, linking, and cursor-advance steps; known reconcile limitation documented in module docstring; ruff + mypy clean
    - Spec: `docs/specs/p10-t38-link-commit.md`
    - **Known limitation (V1)**: commit references are stored in vector metadata only; `reconcile_index` will drop them on any reconcile run — documented in spec and module docstring; S3 `copy_object` update deferred to a future milestone

39. ✅ **Caller-controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`** — remove `ARTIFACT_CONCURRENCY` from `Settings` (field, validator, and property); add `artifact_concurrency: int = 3` optional parameter to `write_artifacts` and `migrate_artifacts`; out-of-range values are never rejected — above 15 capped to 15, below 1 substituted with default 3, both with a top-level `warning` field in the response; thread `artifact_concurrency` from `migrate_artifacts` through to `_write_artifacts_inner` for the `dry_run=False` path; update migration skill: (1) recommend `min(file_count, 15)` with quota context and confirm with operator, (2) batch 3.B3 and 3.B5 calls by `artifact_concurrency` (batch_size = artifact_concurrency) so the operator receives progress updates after each batch; update all unit tests that previously set `ARTIFACT_CONCURRENCY` via `monkeypatch.setenv` to pass the parameter directly; remove config-level tests for the deleted env var (FR-23, FR-25, FR-26, NFR-14, NFR-15)
    - Done when: `write_artifacts(artifact_concurrency=10, ...)` processes at most 10 artifacts concurrently (verified by semaphore spy); `write_artifacts(artifact_concurrency=20, ...)` caps to 15, writes all artifacts successfully, and returns `{"results": [...], "warning": "..."}` with a non-empty warning; `write_artifacts(artifact_concurrency=0, ...)` substitutes 3, writes all artifacts, and returns a warning; `migrate_artifacts(dry_run=True, artifact_concurrency=20, ...)` caps and warns; `migrate_artifacts(dry_run=False, artifact_concurrency=3, ...)` passes 3 to `write_artifacts`; `ARTIFACT_CONCURRENCY` env var has no effect; migration skill asks operator for `artifact_concurrency`, batches 3.B3 calls by that value and reports progress after each batch, does the same for 3.B5; all existing unit tests pass; ruff + mypy clean
    - Brainstorming: `docs/brainstorming/brainstorming-2026-06-10-migrate-artifacts-concurrency.md`
    - Spec: `docs/specs/p10-t39-caller-controlled-artifact-concurrency.md` *(spec ready)*

40. ✅ **Migration skill `commit_refs` backfill options** *(skill-only change; no server code)* — update the `migrating-to-arkeology` skill to offer the operator three backfill choices after artifacts are written: (1) **do not backfill** (default — `commit_refs` left empty, migration finishes immediately), (2) **set migration timestamp** (`commit_refs` left empty; `last_edited_ulid` already set to migration time by `write_artifact` — no extra step needed; document this for operator clarity), (3) **backfill from git history** (for each migrated file run `git log -1 --format=%H -- <filepath>` to obtain the last-touching commit SHA, then call `link_commit` in batches); warn upfront that option 3 is O(n) git calls and can be slow for large projects (D12)
    - Done when: skill presents all three options with the default clearly marked; option 1 requires no additional tool calls after migration; option 2 explains that `last_edited_ulid` is already set to migration time with no extra action; option 3 drives `git log -1` per file and `link_commit` in batches, with an upfront slow-operation warning; the no-`since_ulid` edge case (all unlinked artifacts surfacing in future `propose_commit_links` calls) is noted; skill text is clear, concise, and consistent with the existing migration skill style
    - Spec: `docs/specs/p10-t40-migration-skill-commit-refs-backfill.md`
    - Brainstorming: `docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md` (D12, Resolved Questions)

41. ✅ **Rename `feature_tags` → `tags`** *(pure identifier rename; OKF schema alignment)* — rename the `feature_tags` metadata field to `tags` across the entire codebase: `Artifact` model, all MCP tool public parameters (`write_artifact`, `search_artifacts`, `list_artifacts`, `synthesise_artifacts`), S3 object metadata key, vector metadata key, filter clause keys, all tool implementations, tests, `resources.py`, `AGENTS.md`, `SERVER-REFERENCE.md`, and setting-up-arkeology + migrating-to-arkeology skills; preserve the deliberate S3-comma-joined-string vs vector-`list[str]` dual-encoding under the new key name; no data migration (no live data) (D2 — brainstorming-2026-06-15-okf-alignment.md)
    - Done when: no occurrence of `feature_tags` remains in `src/`, `tests/`, `AGENTS.md`, `SERVER-REFERENCE.md`, or `skills/`; all unit tests pass; `ruff check`, `ruff format --check`, and `mypy src/` are clean; dual-encoding tests (`test_vector_metadata_tags_is_list`, `test_s3_metadata_tags_…`) verify the S3 string vs vector list split is preserved under the new key name
    - Spec: `docs/specs/p10-t41-rename-feature-tags-to-tags.md`
    - Brainstorming: `docs/brainstorming/brainstorming-2026-06-15-okf-alignment.md` (D2)

42. ✅ **MCP data resources** — expose `arkeology://artifact/{id}` URI template resource returning the full markdown content of the identified artifact and `arkeology://artifacts` listing resource returning a markdown-formatted index of active own-scope artifacts; both carry `audience: ["user"]` annotations signalling human-facing content; `arkeology://artifact/{id}` applies the same scope, tier, and visibility gate as `read_artifact`; both registered alongside existing schema resources via `register_resources()` (FR-46, AC-51, AC-52)
    - Done when: `arkeology://artifact/{id}` returns full markdown content for valid own-scope artifacts with `mimeType: "text/markdown"`; foreign-scope tier 2 artifacts rejected; `arkeology://artifacts` returns a markdown listing equivalent to `list_artifacts` with default parameters; both resources available to any connected MCP client without additional configuration; ruff + mypy clean
    - Spec: `docs/specs/p10-t42-mcp-data-resources.md`

---

## Phase 11 — Visual Reading Interface (MCP Apps)

Goal: a developer calling `arkeology_studio` in any MCP App-supporting host (Claude Desktop, claude.ai, VS Code Copilot) sees an interactive artifact browser rendered inline — faceted filtering, semantic search, full markdown and mermaid rendering — with zero new AWS infrastructure. All Arkeology tool calls from within the browser pass through the existing scope gate unchanged.

**Execution order:** T43 is the prerequisite (server-side infrastructure, `arkeology_studio` tool registration, and HTML placeholder must exist before T44 can be developed and loaded). T44 depends on T43.

43. ✅ **Server-side MCP App infrastructure and `arkeology_studio` tool** *(prerequisite — establishes the entry point and resource serving before any UI work)* — add `fastmcp[apps]` (a pip packaging extra, installed as a base dependency — not optional for the server, see ADR-010 revision) to `pyproject.toml`; create `src/arkeology/tools/studio.py`: `arkeology_studio` tool decorated with `AppConfig(resource_uri="ui://arkeology-studio/index.html")`, initial call returns active artifact listing data, branches on `ctx.client_supports_extension(UI_EXTENSION_ID)` — graceful degradation path returns a plain-text `list_artifacts` equivalent when extension not supported; register `ui://arkeology-studio/index.html` resource in `resources.py` with `ResourceCSP` declaring CDN origins (`unpkg.com`, `cdn.jsdelivr.net`), reads HTML from `src/arkeology/static/arkeology-studio.html`; create `src/arkeology/static/arkeology-studio.html` placeholder; declare `src/arkeology/static/` as package data in `pyproject.toml`; register tool in `server.py` via `register_tools()`; update AGENTS.md repository structure table (FR-47, FR-48)
    - **Red (tests written before implementation):** test `arkeology_studio` returns plain-text listing when `ctx.client_supports_extension(UI_EXTENSION_ID)` is `False`; test `arkeology_studio` returns structured tool result when extension is supported (mock `ctx`); test `ui://arkeology-studio/index.html` resource returns non-empty string content
    - **Green:** all three tests pass; `fastmcp[apps]` installed; tool registered and callable; resource serves the HTML placeholder; `uv run ruff check`, `ruff format --check`, `mypy src/` clean
    - Spec: `docs/specs/p11-t43-mcp-app-infrastructure.md`

44. ✅ **Browser UI (HTML/JS)** *(depends on T43)* — build `src/arkeology/static/arkeology-studio.html`: a self-contained HTML/JS browser application with all dependencies loaded from declared CDNs; left panel providing filter controls (type, tier, status) and an artifact listing populated on open and refreshed by `list_artifacts` on filter change; right panel document viewer triggered by artifact selection that fetches via `read_artifact` and renders markdown and mermaid diagrams; semantic search box that calls `search_artifacts` and replaces the listing with ranked results, clearing restores the filter view; update `SERVER-REFERENCE.md` with `arkeology_studio` tool entry; update AGENTS.md to mention `arkeology_studio` as the reading entry point (FR-47, FR-48, FR-49)
    - Done when: `arkeology_studio` called in Claude Desktop renders the browser UI with a populated artifact list; selecting an artifact renders its full markdown content and mermaid diagrams correctly; semantic search returns ranked results that replace the listing; clearing the search query restores the faceted-filter listing; `uv run arkeology` starts without error (startup validation passes); `uv run ruff check`, `ruff format --check`, `mypy src/` clean
    - Spec: `docs/specs/p11-t44-browser-ui.md`

---

### Phase 12 — Artifact Cross-Referencing + Annotation-Backed Link Storage

Goal: give artifacts a first-class `references` field, move the durable copy of the mutable link
fields (`commit_refs`, `references`) from vector-metadata-only to **S3 object annotations** so
they survive `reconcile_index`, generalize `link_commit` into a single `link_metadata` primitive,
and add an own-scope `referenced_by` warning on delete/archive. Requirements: FR-51–FR-58, plus
revisions to FR-32, FR-17, FR-28, FR-09. Design source: `docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md`
(decisions D1–D15).

**This track supersedes several Phase 10 commit-refs decisions.** The vector-only `commit_refs`
storage (Phase 10 T38 "Known limitation") and the "commit references lost after reconcile" PRD
limitation are replaced by annotation-backed dual-write. The Phase 10 specs `p10-t36`, `p10-t38`,
and `p10-t40`, plus the read (`p2-t9`) and reconcile (`p5-t21`) specs touched by the annotation
change, are revised as part of this phase — **assigned to an Architect** (see execution note). A
one-time relink sweep for legacy vector-only `commit_refs` was considered and dropped — no live
deployment has such data to sweep (see ADR-011).

**Execution order:** T45 is the hard prerequisite (annotation client + test infra) — nothing
durable can be built or tested without it. T46 (`references` field) is the other early
prerequisite. Once both merge: T47, T49, T52 can proceed; T48 (reconcile) needs annotations
being written (T47/T49); T50 depends on T46 only and is independent of all annotation work
(parallelisable); T51 depends on T46; T53 depends on T49 + T51. **T54** (search age transparency) is an independent review fix folded into this
phase — it depends on nothing and is parallelisable with all cross-referencing work. **T55** (metadata validation) is a write-path robustness fix that must land before or with T46/T47, which enlarge the validated metadata payload. Testing
approach: **TDD** (NFR-07) — tests written and failing before implementation on every task with
testable logic.

45. ✅ **S3 object annotation client support + moto self-mock extension** *(prerequisite — client layer + test infrastructure)* — add put/get/list/delete object-annotation operations to the S3 client interface (`typing.Protocol`) and the concrete boto3 implementation; add a moto conftest extension self-mocking the annotation APIs, mirroring the existing `query_vectors` cosine patch (moto has no native annotation support). No tool changes. (FR-54)
    - Why: annotations are the durable store for all link data in this phase; every downstream task depends on being able to read/write and unit-test them.
    - Done when: **(Red)** client-method and moto-extension tests are written and failing before implementation; **(Green)** an annotation put→get→list→delete round-trip passes through the moto extension in unit tests and against a real bucket in an integration test; the extension returns results consistent with the real S3 Vectors annotation API; ruff + mypy clean
    - Spec: `docs/specs/p12-t45-s3-annotation-client.md`

46. ✅ **`references` first-class field on the `Artifact` model + write / read / list surfacing** *(core data model)* — add `references: list[str]` to `Artifact`; dual-store durably on the S3 object (annotation, per T47) and as `list[str]` in vector metadata; accept `references` at write time; return it in `write_artifact`, `read_artifact`, and `list_artifacts` responses; add a `references` list-membership filter to `list_artifacts` (AND semantics); legacy artifacts return `[]`. (FR-51)
    - Done when: **(Red)** field, encoding, and filter tests written and failing first; **(Green)** round-trip write→read→list returns supplied `references`; the `references` filter returns the correct subset; absent field returns `[]` (no error); the deliberate S3-vs-vector dual-encoding is preserved under the new field; ruff + mypy clean
    - Depends on: T45 (annotation storage). Spec: `docs/specs/p12-t46-references-field.md`

47. ✅ **Annotation dual-write in the write path + overwrite preservation** — write `commit_refs` and `references` to S3 object annotations (durable-side first, vectors second — recoverable-state ordering); on an overwriting tier-3 write, read forward the existing `commit_refs`/`references` and re-apply them to both stores, because `PutObject` clears annotations. Content body is never re-embedded by this path. (FR-54, FR-55)
    - Done when: **(Red)** tests for durable-first ordering and tier-3 overwrite preservation written and failing first; **(Green)** a write persists both fields to annotations and vector metadata; a tier-3 same-type+title overwrite preserves prior `commit_refs`/`references` in both stores even though the underlying `PutObject` cleared annotations; no Bedrock re-embed is triggered by the annotation write; ruff + mypy clean
    - Depends on: T45, T46. Spec: `docs/specs/p12-t47-annotation-dual-write.md`

48. ✅ **`reconcile_index` rebuilds `commit_refs` + `references` from annotations** — when re-indexing an artifact, restore both link fields into vector metadata by reading the object's durable annotations (`ListObjectAnnotations`/`GetObjectAnnotation`) instead of standard object metadata. Resolves OQ2. (FR-17, FR-54)
    - Done when: **(Red)** a test proving reconcile currently drops the fields is written and failing first; **(Green)** an artifact whose vectors are rebuilt by reconcile retains its `commit_refs` and `references` sourced from annotations; clean-state reconcile is unaffected; own-scope gate preserved; ruff + mypy clean
    - Depends on: T45, and annotations being written (T47/T49). Spec: `docs/specs/p12-t48-reconcile-from-annotations.md`

49. ✅ **`link_metadata` tool — generalizes and supersedes `link_commit`** — fetch existing vectors + embeddings → merge and deduplicate the supplied `commit_refs`/`references` → dual-write (durable annotations first, vectors second) with the same embeddings; no Bedrock call; own-scope only (foreign identifiers skipped and counted); idempotent on re-run; returns counts and the write-time cursor. Rename/retire `link_commit`; keep `propose_commit_links` (FR-31). (FR-53, supersedes FR-32)
    - Done when: **(Red)** dual-write, no-re-embed (Bedrock spy), merge-dedup, and scope-gate tests written and failing first; **(Green)** `link_metadata` backfills either field to both stores, makes zero embedding calls, does not disturb `last_edited_ulid`, skips + counts foreign-scope IDs, and is idempotent; ruff + mypy clean
    - Depends on: T45, T46, T47. Spec: `docs/specs/p12-t49-link-metadata.md`

50. ✅ **Unified own-scope `referenced_by` warning on delete + archive** *(independent of annotation work)* — before delete or archive, reverse-lookup other own-scope artifacts referencing the target across both `source_artifacts` and `references` using server-side `$eq` list-membership filtering; warn-but-don't-block (delete: stronger, permanent; archive: informational, reversible); strictly own-scope — never reveal foreign-scope identifiers. Generalizes the existing synthesis-source delete warning (FR-21). (FR-56)
    - Done when: **(Red)** warning tests for both delete and archive, covering `source_artifacts` and `references`, plus an own-scope-only assertion, written and failing first; **(Green)** delete/archive of a referenced artifact returns the referencing identifiers and still performs the operation; a foreign-scope referrer is never revealed; server-side filtering used (not fetch-all-then-filter); ruff + mypy clean
    - Depends on: T46 only (references in vector metadata). Parallelisable with T47–T49. Spec: `docs/specs/p12-t50-referenced-by-warning.md`

51. ✅ **Migration frontmatter reference rewriting + `arkeology://` content rewrite** *(migration path)* — build a single authoritative path→identifier map from the full migration manifest before any writes (forward-reference safe); resolve frontmatter `references:` path entries to artifact identifiers to populate `references` (T46); rewrite resolved references in stored content to `arkeology://artifact/{id}`; best-effort bounded path normalization; leave `http(s)://` URLs and unresolved/excluded targets untouched; in-body markdown links out of scope. (FR-52)
    - Done when: **(Red)** resolution-map, forward-reference, normalization-ceiling, and untouched-URL tests written and failing first; **(Green)** a same-batch forward reference resolves; the migrated artifact's `references` is populated and content rewritten to `arkeology://artifact/{id}`; URLs and unresolved/excluded targets are left verbatim; no tier-2 content is retroactively patched; ruff + mypy clean
    - Depends on: T46. Spec: `docs/specs/p12-t51-migration-reference-rewrite.md`

52. ✅ **`setting-up-arkeology` annotation availability + IAM check; runtime graceful handling; README + AGENTS.md** *(code + skill + snippet done; README/SERVER-REFERENCE IAM actions completed in the tech-writer docs pass)* — add a one-time annotation availability + IAM-permission probe to the `setting-up-arkeology` skill (aws-cli ≥ 2.35.14 guard or boto3 fallback via `uv run`); document the four required IAM actions and the regions/bucket types where annotations are unavailable in the README reference policy; handle annotation-unavailable / AccessDenied gracefully at runtime in `link_metadata` and the write path (post-setup drift); add the `arkeology://` referencing and "reference healing" guidance to the AGENTS.md snippet (D9). NOT a hard startup gate (D15). (FR-57, NFR-12)
    - Done when: **(Red)** runtime graceful-handling tests (annotation unavailable / AccessDenied → structured error, core store still works) written and failing first; **(Green)** those errors surface structured, actionable responses and never a raw exception; the skill probe reports availability + the four IAM actions; README documents actions + unavailable regions/bucket types; AGENTS.md snippet carries the reference guidance; server still boots when annotations are unavailable; ruff + mypy clean
    - Depends on: T45. Spec: `docs/specs/p12-t52-annotation-availability-graceful.md`

53. ✅ **Reference-backfill cleanup skill** *(skill-only; optional, decoupled)* — ship an optional, skippable-by-default skill that content-scans artifacts against the migration path→identifier map, presents a dry-run batch report of proposed `references` backfills for operator review, and applies confirmed backfills via `link_metadata`; never rewrites stored content; never mutates metadata without confirmation. Resolves OQ1-cleanup. (FR-58)
    - Done when: the skill presents a dry-run batch report before any write; confirmed backfills route through `link_metadata`; declining leaves all artifacts unchanged; no stored content is rewritten; skill text is consistent with existing skill style; ruff + mypy unaffected (skill-only)
    - Depends on: T49 (`link_metadata`), T51 (path→id map). Spec: `docs/specs/p12-t53-reference-backfill-skill.md`

54. ✅ **Search age transparency** *(review fix; independent of annotation work)* — surface the last-edited timestamp on every `search_artifacts` result so agents can judge and discount stale artifacts. Add the raw `last_edited_ulid` (already stored on every vector — no re-index) and a derived ISO 8601 `last_edited_at` to each result entry, reusing the existing ULID→ISO derivation used by `propose_commit_links` / `resources.py`. **No ranking change** — recency-weighted *ranking* is deferred to backlog B-6 (design-first, ADR before spec).
    - Done when: **(Red)** tests written and failing first — a searched artifact returns correct `last_edited_ulid` + `last_edited_at`; missing/malformed ULID degrades to `null` without error; result ordering is unchanged with vs without the new fields; **(Green)** `search_artifacts` results carry both fields; existing unit suite + ruff + format + mypy clean.
    - Depends on: nothing (parallelisable with all annotation tasks). Spec: `docs/specs/p12-t54-search-age-transparency.md`

55. ✅ **Write-path metadata size + charset validation** *(review fix; write-path robustness)* — before any storage write, validate that the artifact's metadata fits the S3 object-metadata and vector-metadata size budgets and fail fast with a structured error, so an oversize artifact never produces a deterministic partial write (S3 ok, vector fails) that `reconcile_index` replays forever; neutralise control characters that corrupt metadata (e.g. a newline raising a raw urllib3 `ValueError`); bound `title` length in the `Artifact` model; and preserve non-ASCII titles consistently so `read_artifact` and `search_artifacts` never disagree. The size-budget check must account for `references` and `commit_refs`. (FR-59, AC-67)
    - Why: T46/T47 add `references` to the metadata payload, increasing pressure on the same vector-metadata size budget — the guard must exist before the references field goes live. Moving `commit_refs`/`references` durable copies to annotations relieves only the S3-user-metadata side, not the vector side.
    - Done when: **(Red)** tests written and failing first — an oversize-metadata write is rejected before any S3 or vector write (no partial write, no failure-log replay loop); a control char in a metadata value returns a structured error rather than a raw exception; a non-ASCII title round-trips identically through `read_artifact` and `search_artifacts`; an over-long title is rejected with a clear error; **(Green)** all pass; existing suite + ruff + format + mypy clean.
    - Depends on: nothing to start, but **must land before/with T46 + T47 going live** (it validates the enlarged payload). Spec: `docs/specs/p12-t55-metadata-validation.md`

56. ✅ **Deterministic, server-side content reference rewrite (frontmatter + body)** *(migration path; extends T51)* — extend the migration content rewrite so an already-resolved frontmatter `references:` path is rewritten to `arkeology://artifact/{id}` everywhere it occurs in stored content — both the frontmatter block and markdown link targets in the body — executed as deterministic server-side code inside `migrate_artifacts` (reversing, for this bounded case only, ADR-012's prior "skill orchestrates, no server-side rewrite" call). The agent still resolves frontmatter `references:` entries in-context (unchanged `references.py` algorithm, T51) but now threads a `resolved_references_map` into the descriptor instead of hand-editing content. Does not reopen in-body link *discovery* — undeclared body-only links stay untouched (ADR-012 D1 preserved). (FR-52)
    - Why: the current agent-in-context frontmatter rewrite is not deterministic (LLM find/replace, no local scripts) and never touches body occurrences of the same already-resolved path — a common documentation pattern where a frontmatter reference is echoed as an inline markdown link in the body. Moving the rewrite server-side removes that fragility and unifies both occurrence sites into one tested code path.
    - Done when: **(Red)** `rewrite_content_references` pure-helper tests (frontmatter quote-style preservation, body markdown-link rewrite, anchor handling, substring-collision safety, fenced-code-block skip, URL passthrough, idempotency, empty-map no-op) written and failing first; **(Green)** `migrate_artifacts` applies the rewrite to any descriptor carrying `resolved_references_map` before the write, in both `dry_run` modes, with the key never leaking into any response, metadata, or the `Artifact` model; the `migrating-to-arkeology` skill passes the map instead of hand-rewriting content; ruff + mypy clean.
    - Depends on: T51 (path→id map, `references.py` resolution algorithm). Spec: `docs/specs/p12-t56-deterministic-content-reference-rewrite.md`

**T57–T62 — Vector metadata budget hardening, guard coverage, and migration self-heal** (added
2026-08-13, post-implementation remediation). A real 57-file migration surfaced a permanent partial
write: an artifact's `commit_refs`/`references` metadata passed this project's local pre-write size
approximation but was rejected by AWS's real `PutVectors` accounting, and two of the three
metadata-writing paths (`link_metadata.py`, `reconcile.py`) skip the size guard entirely, while
`migrate_artifacts` could not detect or repair the resulting stuck artifact. Design source:
`docs/brainstorming/brainstorming-2026-08-13-artifact-metadata-budget-overflow.md` (D1–D4, D6,
D7) and `docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`
(Accepted). **Execution order:** T57 (guard coverage) is the hard prerequisite — it must land before
T58 enlarges any payload the guard is meant to catch. T58 (the split-store decision itself) then
gates T59 and T60, both of which depend on `references` actually being removed from vector metadata.
T61 (migration self-heal) depends on T57 only (it routes through the now-guarded reconcile path), not
on T58–T60. T62 (bounded reconcile retry) is independent of all the others per the ADR's own D4
framing. Testing approach: **TDD** (NFR-07), matching T45–T56.

57. ⬜ **Guard coverage in `link_metadata.py` and `reconcile.py`** *(prerequisite — closes the missing-check gap)* — call `check_metadata_budgets` immediately before each path's vector write: inside `_apply_link_metadata_with_cas`'s per-attempt loop (after the merged field values are computed, before the annotation write — durable-first ordering is unaffected), and inside `reconcile.py`'s `_reindex_artifact` (before its `put_vector` call). Mirrors `write.py`'s existing placement; `s3_metadata` passed empty for both, since neither path touches S3 user-defined metadata. (ADR D1)
    - Why: `check_metadata_budgets` is currently called only from `write.py`, so `link_metadata` and `reconcile` can each durably write vector metadata that a fresh `write_artifact` call would reject outright — the exact gap that let the original incident's stuck artifact go undetected by its own repair tool.
    - Done when: **(Red)** a test proving `link_metadata`/`reconcile` currently accept an oversize payload that `write_artifact` would reject is written and failing first; **(Green)** both paths reject an oversize payload with the same `validation_error` behaviour as `write.py`, before any vector write and before any failure-log append; ruff + mypy clean.
    - Depends on: nothing new (the guard function itself already exists in `artifact.py`). Spec: `docs/specs/p12-t57-guard-coverage.md` (to be written by Architect before dispatch)

58. ⬜ **Split-store decision: `references` removed from S3 Vectors metadata, `commit_refs` capped at 20** *(core fix — the incident's product question)* — `write.py`, `link_metadata.py`, and `reconcile.py` stop writing `references` to S3 Vectors metadata entirely; the S3 object annotation copy becomes its sole durable store and sole read surface (read path collapses to single-store for this field). `commit_refs` stays in S3 Vectors metadata, filterable, capped at the most-recently-appended **20 entries** (real-AWS-calibrated: AWS accepts up to 36 entries for this payload shape, rejects 37 — 20 leaves deliberate margin; full measured evidence in the ADR); the complete, uncapped list remains durable in annotations regardless. Explicit non-completeness-guarantee wording added to `commit_refs`'s vector-metadata copy per the ADR's amendment. (ADR D2)
    - Why: closes the metadata-budget-overflow failure mode at its root — `references` never needed vector-side filterability (confirmed nice-to-have, not load-bearing); `commit_refs` does (`list.py:141-143` already filters on it), so it needs a real, calibrated cap instead of an unbounded, never-verified copy.
    - Done when: **(Red)** tests written failing first — `references` never appears in vector metadata after a write/link/reconcile through any of the three paths; a `commit_refs` list of 21+ entries writes successfully with only the most-recently-appended 20 promoted into the filterable vector-metadata copy, full list still readable via annotations; existing tests asserting the old (uncapped, dual-field) vector-metadata shape updated to the new contract; **(Green)** all three paths implement the split; ruff + mypy clean.
    - Depends on: T57. Spec: `docs/specs/p12-t58-commit-refs-cap-references-removal.md` (to be written by Architect before dispatch)

59. ⬜ **Remove `references=` filter param from `list_artifacts`/`search_artifacts`; `commit_refs=` unchanged** *(breaking API change, documented before shipped)* — `references` is no longer vector-filterable once T58 lands, so the `references=` server-side filter parameter is removed outright rather than silently returning empty results. `commit_refs=` filtering (`list.py:141-143`) is unaffected and requires no code change. (ADR D6 / brainstorming OQ6)
    - Why: OQ6 resolved `commit_refs=` as staying exactly as shipped (it remains filterable), so only `references=` becomes non-functional and must be removed cleanly rather than left to fail silently.
    - Done when: **(Red)** a test asserting `references=` is rejected/removed (not silently ignored, not silently empty) written failing first; **(Green)** `list_artifacts`/`search_artifacts` reject or drop the `references=` parameter with a clear, documented signature change; existing `commit_refs=` filter tests continue to pass unchanged; ruff + mypy clean.
    - Depends on: T58. Spec: `docs/specs/p12-t59-remove-references-filter-param.md` (to be written by Architect before dispatch)

60. ⬜ **Narrow the delete/archive reverse-lookup warning to `source_artifacts`; document the `references` gap** *(accepted capability loss, not silently absorbed)* — the `referenced_by` warning (T50) keeps scanning `source_artifacts` exactly as today; the `references`-half of the scan is dropped with no fallback (an unbounded full-corpus annotation scan was explicitly rejected as a substitute — see ADR). The gap is documented in the tool's response/docstring, not silently absorbed. (ADR D6 / brainstorming OQ6)
    - Why: the `references`-half of this warning depended on `references` being vector-filterable; once T58 removes that, continuing to scan it would require an unbounded scan this project's own design principles reject.
    - Done when: **(Red)** a test asserting the warning still fires correctly for `source_artifacts`-based referrers and no longer attempts a `references` scan, written failing first; **(Green)** `delete_artifact`/`archive_artifact` match that behaviour; a response/docstring note documents the `references` gap explicitly; ruff + mypy clean.
    - Depends on: T58. Spec: `docs/specs/p12-t60-narrow-reverse-lookup-warning.md` (to be written by Architect before dispatch)

61. ⬜ **Migration self-heal: `skipped_unindexed` classification** *(closes the permanent-un-retryable gap)* — `migrate_artifacts`' Step 5 skip-existing check adds one bounded, per-candidate `vectors.list_vectors_by_metadata` existence query (per-candidate, not a bulk pre-scan — confirmed OQ3); an S3-exists-but-not-indexed candidate is reported under a new `skipped_unindexed` category (not folded into `skipped_existing`) and pointed at `reconcile_index` for remediation. (ADR D3)
    - Why: today's skip-existing check verifies S3 existence only, so a partial write (S3 durable, vector rejected) is permanently un-retryable through the normal migration path and silently reported as already-done — the exact state the original incident produced.
    - Done when: **(Red)** a test simulating an S3-exists/vector-absent candidate, asserting today's silent `skipped_existing` misclassification, written failing first; **(Green)** `migrate_artifacts` distinguishes `skipped_unindexed` from `skipped_existing` via the per-candidate existence check; the migration report surfaces the new category with a pointer to `reconcile_index`; fully-migrated candidates are unaffected; ruff + mypy clean.
    - Depends on: T57 (self-heal must route through a guarded reconcile path). Spec: `docs/specs/p12-t61-migration-self-heal.md` (to be written by Architect before dispatch)

62. ⬜ **Bounded `reconcile_index` failure-log retry** *(independent — closes the infinite-replay risk)* — `reconcile_index`'s failure-log replay adds a per-entry `reconcile_attempts` counter, incremented on each failed replay; once it crosses the existing `CAS_MAX_ATTEMPTS = 3` precedent (`annotations.py`, reused rather than made independently configurable — confirmed OQ4), the entry stops being auto-retried and is reported once, loudly, in a new `stuck_failures` response field, instead of being replayed identically forever. (ADR D4)
    - Why: today a genuinely unfixable failure-log entry is retried identically and silently on every `reconcile_index` run forever — precisely the "self-perpetuating failure-log replay" failure mode `p12-t55` named as something that must never happen.
    - Done when: **(Red)** a test simulating a failure-log entry that fails identically 3+ times, asserting today's infinite-retry behaviour, written failing first; **(Green)** `reconcile_index` increments `reconcile_attempts` per failed replay, stops auto-retrying and reports via `stuck_failures` once the threshold is crossed; entries that eventually succeed are still pruned as today; ruff + mypy clean.
    - Depends on: nothing new (independent of T57–T61 per the ADR's own D4 framing). Spec: `docs/specs/p12-t62-bounded-reconcile-retry.md` (to be written by Architect before dispatch)

**Phase 12 spec revisions (Architect):** revise `p12-t46-references-field.md`, `p12-t47-annotation-dual-write.md`, `p12-t48-reconcile-from-annotations.md`, and `p12-t55-metadata-validation.md` where T58's split-store decision (`references` removed, `commit_refs` capped at 20) changes their described contract; write the new specs for T57–T62 above, sourced from `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`. These are spec-consistency updates plus new-task specs, not new behaviour beyond what that ADR and this plan entry describe. (`adr-2026-07-03-annotation-backed-link-storage.md` and `adr-2026-07-03-artifact-cross-referencing.md` — the two prior ADRs affected — already carry `## Revision — 2026-08-13` backward-links, done ahead of T57–T62 implementation; no further action needed on those two.)

---

## Risks and Open Questions

- **~~S3 Vectors `PutVector` upsert behaviour~~** — **CLOSED (2026-05-31, T17 confirmed)**: `PutVectors` silently overwrites an existing key (upsert confirmed). 44 integration tests passed green; tier 3 overwrite logic is correct as written; no code change required.

---

## References

- [`docs/planning-artifacts/prd.md`](./prd.md)
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

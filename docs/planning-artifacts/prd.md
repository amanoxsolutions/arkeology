# Product Requirements Document — cairn-mcp

## Description

Product requirements for cairn-mcp, a Python MCP server that gives AI agents persistent and searchable artifact memory backed by AWS S3, S3 Vectors, and Amazon Bedrock.

---

## Executive Summary

AI coding agents produce knowledge at significant moments throughout a session — code review findings, architectural decisions, implementation notes, specs, session summaries. Unless proactively stored, this knowledge is discarded when the context window closes. In such a case, the next session, or the next engineer, starts from zero.

But storage alone is only half the problem. As a project grows — months of agent sessions producing hundreds or thousands of artifacts — a second challenge emerges: **finding the right artifact at the right moment**. No agent can be asked to scan thousands of files to find the one that matters. Structured storage without semantic search simply moves the problem.

AI-assisted engineering produces knowledge at three levels:

| Tier | What it is | Where it lives today |
|---|---|---|
| **Code** | The deliverable — functions, tests, infrastructure | Git — durable, searchable, shared |
| **Working artifacts** | Code reviews, session summaries, implementation notes, specs | Scattered — in the repo, in proprietary tool memory, or lost when the session ends |
| **Canonical knowledge** | ADRs, architecture decisions, org-wide patterns | Wikis or documentation folders |

The code tier is solved. The working artifact tier is the gap.

cairn-mcp is a Python MCP server that gives AI agents **persistent and searchable artifact memory**, backed entirely by AWS — S3 for durable content storage, S3 Vectors for semantic search, and Amazon Bedrock for embeddings. Agents connect via MCP to write, search, list, and recall structured artifacts across sessions and across team boundaries.

---

## Problem Statement

On small projects with short lifespans, ad-hoc approaches work: commit notes to the repo, store summaries in a `docs/` folder, rely on a tool's built-in memory. Some AI coding platforms provide session memory out of the box. But these approaches hit two hard limits as projects grow.

**Problem 1 — Durable, portable storage.** Artifacts end up scattered: in the repo (adding noise to git history and polluting the codebase), in proprietary tool memory (locked to one platform, invisible to other engineers and tools), or simply discarded when the context window closes. No ad-hoc approach is simultaneously durable, portable, and shared across engineers, tools, and sessions. Some teams have found creative workarounds — the Streamlit engineering team, for example, repurposed their GitHub wiki as a scratch space, describing it as *"a hack, honestly. But it works surprisingly well."* It does. But it is GitHub-specific, has no semantic search, and does not scale across projects or teams.

**Problem 2 — Semantic retrieval.** Even when artifacts are stored, finding the right one is unsolved. As a project grows, months of agent sessions produce hundreds or thousands of artifacts. No agent can be asked to scan all of them to find the one that matters for the current task. Without semantic search and metadata filtering, an agent starting a session on the `auth` module has no practical way to surface the implementation notes from six months ago — even if those notes exist and are perfectly relevant.

cairn-mcp addresses both problems in AWS environments: structured durable storage and immediate semantic search. Artifacts are written mid-session and immediately searchable — by semantic similarity, by metadata filter, or by direct identifier. Canonical knowledge can be flagged as shareable, making it discoverable by agents on other projects or teams.

---

## Vision

Each deployment of cairn-mcp is a self-contained, independent persistent memory store for one team or project. Agents write artifacts at significant moments — end of session, after a code review, after an architecture decision. Future agents and engineers search and retrieve those artifacts to resume where prior work left off, without re-discovering what is already known.

When a shared S3 bucket is deliberately configured across teams, tier 3 permanent knowledge — ADRs, canonical patterns, architecture decisions — becomes discoverable across project and team boundaries. A platform team's VPC peering decision surfaces for a microservices team agent that subscribed to the platform team's prefix. Tier 2 working documents stay strictly project-local.

The server is deployment-agnostic: it is given resource names and trusts the credentials it receives. Deployment topology — one shared org-wide bucket, one bucket per team, one per project — is entirely the operator's choice.

---

## Deployment Prerequisites

Before the server can start, the following must be provisioned externally:

- An S3 bucket accessible with the configured credentials
- An S3 Vectors index created with a vector dimension matching the configured embedding model, and with two non-filterable metadata key slots declared at creation time: `description` (tweet-length summary, required on all artifacts) and `source_artifacts` (list of source artifact identifiers, required on `synthesis` type artifacts only)
- Amazon Bedrock enabled in the target AWS region with access to the configured embedding model
- IAM credentials with read/write permissions to the S3 bucket and S3 Vectors index, and `bedrock:InvokeModel` permission for the embedding model

**Regional constraint:** S3 Vectors is not available in all AWS regions. The operator is responsible for selecting a supported region. The server does not validate regional availability at startup.

**Cross-scope constraint:** cross-scope semantic search requires all participating deployments to share the same S3 Vectors index, embedding model, and vector dimension. Each team may have its own S3 prefix or bucket for content storage, but the vector index must be shared. Deployments using separate vector indexes per team cannot perform cross-scope semantic search.

**Optional configuration:**

- The number of section vectors requested from the vector index per search iteration is configurable (default: 25, ceiling: 100).
- The maximum number of search iterations per query before returning available results is configurable (default: 3).
- The default number of artifacts returned per query when the caller does not specify is configurable (default: 5).

---

## Scope

### Core features

- MCP server with 11 tools and MCP Resources: write artifact, read artifact, search artifacts, list artifacts, archive artifact, delete artifact, purge archived, health check, reconcile index, synthesise artifacts, check synthesis freshness; plus schema discovery resources (artifact metadata schema, tier model, visibility model, type catalogue, query strategy guidance)
- AWS S3 + S3 Vectors + Bedrock (Titan Text Embeddings v2) backend
- Artifact metadata schema: type, team, project, tier, date, status, title, visibility, description (≤280 chars), optional feature tags and author role
- Cross-scope read with tier 3 + shared visibility gate
- Startup validation sequence: credentials → storage scope access → embedding model compatibility
- stdio transport (primary); architecture open to additional transports without rework
- All standard AWS credential environments (local profiles, IAM roles, CI/CD pipelines)
- Layered architecture: storage, vector search, embedding, and server transport each behind clean interfaces
- Tier 2 artifacts are append-only and immutable by design — a code review, session summary, or implementation note is a historical record; archiving is the only permitted state change
- Tier 3 artifacts are living documents — a plan or ADR is updated in place as decisions evolve
- Automatic section-level embedding: every `##` section in an artifact is indexed as an independent vector; artifacts with no `##` sections fall back to a single document-level vector from title + description + type + features; no embedding configuration required
- Recommended AGENTS.md snippet shipped with the repository documentation covering when to write, artifact types, description quality guidance, and tier selection
- Migration skill (`skills/migration/`) following the agentskills.io standard, shipped with the repository: structured agent-driven workflow to migrate existing project documentation into cairn-mcp; covers discovery, classification, metadata enrichment (Bedrock-generated descriptions, git date recovery), and post-migration guidance (AGENTS.md update, tier 2 file removal instructions); bundles `scripts/migrate.py` (PEP 723 inline deps, bulk operations, `--dry-run` support, concurrent writes via `MIGRATE_CONCURRENCY`) and a `schema.yaml` for the `CAIRN_IMPORT.yaml` manifest format; two paths: agent-only for very small projects (< 5 files, sequential) and manifest + script for 5+ files; for ≥ 10 files the agent-only path uses a two-phase approach (enrich all files first, then write in parallel batches of 4–5 via sub-agents)

### Future considerations

- Additional transport implementations (e.g. HTTP/SSE) for shared or automated deployments
- Offline-first local cache with deferred synchronisation
- Programmatic AWS resource provisioning
- Multi-agent concurrent write conflict resolution
- TTL-based automatic artifact expiry by type
- Full visibility cross-scope enforcement
- Milestone-triggered memory summarisation hook

---

## Users

| User | Description |
|---|---|
| **Developer agent** | An AI coding agent running interactively on a developer's machine — the primary user |
| **CI/CD pipeline agent** | An automated AI agent (e.g. code reviewer) running in a pipeline — secondary user |
| **Admin / DevOps** | The person who provisions AWS resources and configures the server |

---

## User Stories

### Writing artifacts

- As a developer agent completing a code review, I want to write the findings as an artifact so they persist beyond this session and are retrievable by future agents.
- As a developer agent making an architecture decision, I want to write an ADR as a tier 3 shared artifact so other teams' agents can discover it.
- As a CI/CD pipeline agent completing an automated code review, I want to write findings as an artifact using IAM role credentials so findings are stored even in non-interactive environments.

### Searching and reading

- As a developer agent starting a new session on a feature, I want to search for prior artifacts related to that feature so I can resume where the last session left off.
- As a developer agent, I want to know about a prior bug fix — its implementation, reason, and context — so I do not accidentally undo it without understanding why it was made.
- As a developer agent, after finding relevant artifacts via search, I want to read the full content of the specific artifacts I selected based on their description and relevance score.
- As a developer agent, I want to list all active artifacts for my project to browse what exists without issuing a semantic query.
- As a CI/CD pipeline agent completing an automated code review, I want to know about prior architecture and implementation decisions so I do not investigate or challenge already decided, valid implementations.

### Cross-team knowledge sharing

- As a microservices team agent, I want to discover other teams' (e.g. platform, networking, security) ADRs and architecture decisions that I need to take into account when designing my architecture.

### Migrating existing projects

- As an existing project operator adopting cairn-mcp, I want to migrate accumulated documentation from my repo into cairn-mcp so that future agents can search and retrieve existing knowledge immediately without starting from zero.
- As an existing project operator, I want a structured workflow that classifies my existing docs by artifact type and tier, generates quality descriptions for search, and recovers original creation dates from git history — so migrated artifacts are as useful as freshly written ones.
- As an existing project operator, I want to preview what the migration will import before committing any writes, so I can review and correct the manifest without risk.
- As an existing project operator, I want the migration to finish by updating my project AGENTS.md with cairn-mcp usage guidance, so future agents write to cairn-mcp going forward without any additional configuration step.

### Maintenance

- As a developer agent, I want to archive an artifact that is no longer relevant so it stops appearing in search and list results.

### Operations

- As an admin, I want the server to validate all configuration at startup and fail with a clear, actionable error if anything is misconfigured, so I catch problems before an agent session begins.
- As an admin, I want a health check capability that reports the status of each component independently so I can diagnose issues without reading logs.

---

## Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| FR-01 | **Must** | The server provides an artifact writing capability. The agent provides: full content, a human-readable title, a tweet-length description (≤280 characters), artifact type, optional feature tags, team, project, storage tier (project-local or permanent/shared), visibility (shared or hidden), and optionally the producing role. The server stores the artifact durably, indexes it for semantic search immediately, and returns a unique artifact identifier. Every `##` (H2) section in the artifact markdown is indexed as an independent vector; each section vector embeds: title + type + feature tags + section content. If the artifact contains no `##` sections, one document-level vector is generated from title + description field + type + feature tags. Section embedding calls are issued concurrently (bounded by `SECTION_CONCURRENCY`, default 5) and all resulting section vectors are written in a single batched S3 Vectors call per artifact. Sections shorter than a configurable minimum body length (`EMBED_MIN_SECTION_LENGTH`, default 50 characters) are skipped as semantic noise; the total indexed section count per artifact is bounded by a configurable maximum (`EMBED_MAX_SECTIONS`, default 20). Full artifact content is always stored in S3 regardless of which sections are indexed. Cost impact at Titan Text Embeddings v2 pricing remains negligible. |
| FR-02 | **Must** | The server provides a capability to retrieve the full content of a known artifact by its identifier. For artifacts outside the deployment's own storage scope, access is restricted to permanent shared artifacts only. |
| FR-03 | **Must** | The server provides a semantic search capability. The agent provides a natural language query and optional metadata filters (type, feature tags, team, project, tier). The server returns a ranked list of matching artifacts with their metadata and description — no full content. Results from outside the deployment's own scope are restricted to permanent shared artifacts. The search uses a re-fetch loop: the server queries S3 Vectors for `SEARCH_FETCH_TOP_K` section vectors, groups results by artifact, excludes already-seen artifact identifiers in each subsequent call, and repeats until the requested number of artifacts is reached or `SEARCH_MAX_ITERATIONS` is exhausted — returning whatever results are available at that point. Maximum artifacts per query: 100. |
| FR-04 | **Should** | The server provides a metadata-only artifact listing capability. The agent can filter by type, feature tags, team, project, tier, and status. No semantic ranking is performed. Results from outside the deployment's own scope are restricted to permanent shared artifacts. |
| FR-05 | **Should** | The server provides an artifact archiving capability. Archiving marks an artifact as inactive, excluding it from search and listing results by default. Archiving is scoped to the deployment's own storage — artifacts from foreign scopes cannot be archived. |
| FR-06 | **Should** | The server provides a health check capability that reports the connectivity and accessibility status of each configured component independently, enabling diagnosis without log access. |
| FR-07 | **Must** | At startup, the server validates all configuration before accepting any tool calls: credential validity, read and write accessibility of the deployment's own storage scope, read accessibility of each subscribed foreign scope, existence of the vector index, and compatibility between the configured embedding model and the vector index. If the vector index does not exist, this is treated as a hard startup failure with a clear error identifying the missing resource. Any failure produces a clear, actionable error message and prevents the server from starting. |
| FR-08 | **Must** | Artifact identifiers are generated deterministically from the artifact's own attributes — no random component. Tier 2 project-local artifacts: same type, date, and title written multiple times on the same calendar day produces the same identifier and overwrites silently; a different day produces a new identifier and a new artifact. Tier 3 project documentation artifacts: same type and title always produces the same identifier and overwrites regardless of date — living documents are updated in place. |
| FR-09 | **Must** | Each stored artifact carries the following metadata, used for filtering, display, and access control. **Required** — type, team, project, tier, date (last write), status, title, visibility, description (≤280 characters). **Optional** — feature tags (list), author role, source artifacts (list of artifact identifiers, set only on `synthesis` type artifacts). Visibility is enforced server-side and is not exposed as an agent-facing filter parameter. |
| FR-10 | **Must** | Cross-boundary access is enforced server-side. Within the deployment's own storage scope, all artifacts are accessible regardless of tier or visibility. Across subscribed foreign scopes, only tier 3 shared artifacts are accessible. This is a soft control enforced at the server layer; it does not substitute for infrastructure-level access controls. This distinction must be documented in the server README. |
| FR-11 | **Must** | The server supports all standard AWS credential environments — local developer profiles, IAM roles, CI/CD pipelines, and any other environment where AWS credentials are available. Named profiles are optional and developer-facing; the platform credential chain is the primary mechanism. |
| FR-12 | **Must** | Credential errors occurring at any point during a session are surfaced as structured, human-readable error responses with re-authentication instructions. Raw exceptions are never returned to the agent. |
| FR-13 | **Must** | Tier 2 project-local artifacts are immutable once written (content cannot be edited after the initial write). Content is frozen as a permanent, point-in-time record. No content editing capability is provided. Tier 2 artifacts may be archived (FR-05) or deleted (FR-21); these are lifecycle operations and are not constrained by the content immutability principle. |
| FR-14 | **Must** | Archiving or deleting a tier 2 artifact are the only post-write operations permitted (content immutability — see FR-13). Archiving marks the artifact inactive and excludes it from search and listing results by default. Deleting removes it permanently from storage and the vector index. No attribute — content, tier, visibility, title, or feature tags — can be modified after the initial write. |
| FR-15 | **Must** | Tier 3 project documentation artifacts are living documents. Writing an artifact with the same type and title as an existing tier 3 artifact always overwrites it in place, updating content, refreshing the semantic index, and updating all metadata including the write date. |
| FR-16 | **Should** | When a write operation partially fails — S3 content storage succeeds but vector index write fails — the server writes a structured entry to a local tier 1 failure log before surfacing a structured error to the agent. The entry records the artifact identifier, title, type, tier, and the nature of the failure. The error response to the agent includes the artifact identifier and indicates that a failure log entry was written. The failure log is a tier 1 artifact: local, ephemeral, and gitignored. |
| FR-17 | **Could** | The server provides a reconciliation capability. When triggered, it performs two steps: (1) if a failure log exists, it re-indexes each artifact listed and removes resolved entries from the log; (2) regardless of whether a failure log exists, it scans the deployment's own S3 prefix against the vector index and re-indexes any orphaned objects found — artifacts present in S3 with no corresponding vector index entry, including those left by a partially-failed delete operation (vectors removed, S3 delete failed). The tool returns a structured summary of what was found and what was reconciled. |
| FR-18 | **Should** | The server exposes MCP Resources providing always-current schema information accessible to any connected agent at runtime: the artifact metadata schema with all required and optional fields, valid values, and constraints; the tier model explaining tier 2 vs tier 3 semantics, immutability rules, and key generation behaviour; the visibility and cross-scope access model; an artifact type catalogue with usage guidance; and query strategy guidance covering how to compose effective queries — starting with type and feature tag filters to narrow scope before relying on pure semantic similarity, and broadening only when narrow queries return insufficient results. These resources require no companion skill and are available to any MCP-compatible agent. |
| FR-19 | **Should** | The server provides a synthesis preparation capability. The agent provides a natural language query, optional metadata filters (type, feature tags, team, project), and a maximum number of source artifacts (default 10, ceiling 100). The server performs a semantic search using the query and filters, fetches the full content of the top-ranked results, and returns each result with its identifier, metadata, description, and full content in a single response. The agent uses the returned content to perform a synthesis in-context, then writes the result back as a tier 3 shared artifact of type `synthesis` using the write capability — including the list of source artifact identifiers in the `source_artifacts` metadata field. The server retrieves and assembles source content; the synthesis is performed by the agent. |
| FR-20 | **Could** | The server provides a synthesis freshness check capability. When triggered, it scans all `synthesis` type artifacts in the deployment's own storage scope and, for each, compares the synthesis artifact's `date` against the `date` of each identifier listed in its `source_artifacts` field. The tool returns a structured report identifying: synthesis artifacts with source artifacts updated more recently than the synthesis (potentially stale); and synthesis artifacts referencing source artifacts that have been archived (potentially superseded content). This capability addresses knowledge quality rather than index consistency and complements the reconciliation capability (FR-17). |
| FR-21 | **Should** | The server provides a hard-delete capability for individual artifacts. The agent provides an artifact identifier and an explicit confirmation parameter (`confirm=True`). The server removes the artifact content from S3 and all its section vectors from the vector index. Deletion is scoped to the deployment's own storage prefix; foreign-scope artifacts cannot be deleted. Ordering: vectors are deleted first, then the S3 object — if vectors succeed but the S3 delete fails, the orphaned S3 object is recoverable via the reconciliation capability (FR-17); if vector deletion fails, the artifact is fully intact and an error is returned. If the artifact being deleted is referenced as a `source_artifact` in one or more active synthesis artifacts, the server returns a warning listing the affected synthesis identifiers but proceeds with deletion. |
| FR-22 | **Could** | The server provides a bulk hard-delete capability for archived artifacts. When triggered with explicit confirmation (`confirm=True`), the server deletes all artifacts in the deployment's own storage prefix that have `status=inactive`, along with all their section vectors. Before executing, the server checks whether any active synthesis artifact has all of its `source_artifacts` in the purge set; if so, that synthesis is cascade-deleted and reported in the response summary. The response includes the count and identifiers of all purged artifacts. Foreign-scope artifacts are never purged. |
| FR-24 | **Should** | The cairn-mcp repository ships an installation skill following the agentskills.io standard. The skill provides a structured agent-driven workflow for first-time server setup covering: collecting all operator-specific values upfront (AWS region, resource names, access identity, MCP client preference, team and project names, optional cross-scope read configuration) before any action is taken; pre-flight verification that required tooling and credentials are available; provisioning all required AWS resources in the correct dependency order; generating access policies with actual resource identifiers substituted throughout — no placeholder values in any emitted output; issuing a hard stop before creating any resource whose configuration is irreversible after creation, presenting the resolved values and requiring explicit operator confirmation; actively verifying embedding model access via a live call after the operator enables it in the provider console; writing server configuration and MCP client configuration directly for the chosen client; running the server's health check at the conclusion to confirm all components report healthy status; and appending the recommended AGENTS.md usage snippet with the operator's declared ADR strategy. Existing AWS resources from a prior partial installation are detected and reported rather than silently re-created. |
| FR-23 | **Must** | The cairn-mcp repository ships a migration skill (`skills/migration/`) following the agentskills.io standard (https://agentskills.io/home). The skill provides a structured agent-driven workflow for migrating existing repo documentation into cairn-mcp and is intended for one-time use at adoption time. **Discovery**: the agent scans standard documentation directories (e.g. `docs/adr/`, `docs/specs/`, `docs/brainstorming/`, `docs/notes/`, `docs/planning-artifacts/`) and excludes non-artifact files (`README.md`, `AGENTS.md`, `CHANGELOG.md`, non-markdown files, auto-generated docs). **Classification**: the skill provides a directory-convention mapping table (e.g. `docs/adr/` → `adr` tier 3, `docs/specs/` → `spec` tier 3, `docs/brainstorming/` → `session-summary` tier 2) plus the agent's judgment for ambiguous files. **Metadata enrichment**: title extracted from H1 heading (fallback: filename); description generated by the agent in-context for ambiguous or high-value tier 3 files, or by `scripts/migrate.py` via Bedrock for bulk clear-cut files; date recovered from git log (first commit for tier 2, last commit for tier 3), with frontmatter `date:` field and filename-embedded date as overrides and current date as fallback; `team` and `project` provided once by the operator and applied uniformly. **Two workflow paths**: agent-only (< 5 files — agent sweeps, classifies, generates descriptions, calls `write_artifact` for each sequentially) and manifest + script (≥ 5 files — agent produces a `CAIRN_IMPORT.yaml` manifest, operator reviews, then `scripts/migrate.py` executes concurrent bulk writes). For the agent-only path with ≥ 10 files, the agent uses a two-phase approach: complete all enrichment (read, describe, date-recover) for every file first, then split into batches of 4–5 and spawn sub-agents via the `task` tool to write in parallel, collecting results before verification. **Post-migration**: the skill instructs the operator which tier 2 files may be removed from the repo; the skill's final step appends the cairn-mcp usage snippet to the project `AGENTS.md` so future agents write to cairn-mcp by default. The skill bundles `scripts/migrate.py` (PEP 723 inline deps, run with `uv run scripts/migrate.py`): supports `--dry-run` for a JSON preview of what would be imported without writing; writes artifacts concurrently bounded by `MIGRATE_CONCURRENCY` (default 3); outputs structured JSON to stdout; logs diagnostics to stderr; idempotent on re-run. A `schema.yaml` documents the `CAIRN_IMPORT.yaml` manifest format. Installation is manual copy; the README documents the skills directory path for each supported IDE (Claude Code, Codex, Copilot, OpenCode). |

---

## Non-Functional Requirements

| ID | Priority | Requirement |
|---|---|---|
| NFR-01 | **Must** | **Write-then-read consistency** — an artifact written by the server must be searchable and retrievable without requiring any background synchronisation job. There is no imposed delay between writing an artifact and it being available for search in the same session. |
| NFR-02 | **Must** | **Bounded response payloads** — semantic search results must never include full artifact content. Responses carry metadata and description only. Full content is fetched explicitly and on demand. |
| NFR-03 | **Must** | **Hard startup failure** — any misconfiguration surfaces as a clear, actionable error before the server accepts any tool call. The server never starts in a degraded or partially functional state. |
| NFR-04 | **Should** | **Layered architecture** — storage, vector search, embedding, and server transport must each sit behind a clean interface. Any layer must be replaceable without modifying the others. |
| NFR-05 | **Could** | **Transport extensibility** — the primary transport is stdio for interactive local use. The server must be structured so that additional transports can be added as a configuration choice, without architectural rework. |
| NFR-06 | **Must** | **Idempotent writes** — writing the same logical artifact multiple times produces exactly one stored artifact and one index entry. No duplicates, no orphaned index entries. |
| NFR-07 | **Must** | **Test-driven development** — all business logic must be covered by tests written before implementation. AWS service interactions must be covered by integration tests. |
| NFR-08 | **Must** | **Runtime simplicity** — the server must run in a standard Python environment without requiring containerisation, orchestration, or custom infrastructure beyond the configured AWS resources and credentials. |
| NFR-09 | **Must** | **Distribution** — the server must be installable and runnable directly from the repository source using standard Python tooling. Distribution via a public or private package registry is a future consideration and not a current requirement. |
| NFR-10 | **Must** | **Encryption in transit** — all communication between the server and AWS services must use HTTPS. Encryption at rest for S3 and S3 Vectors storage is the responsibility of the admin provisioning those resources and is out of scope for the server. |
| NFR-11 | **Should** | **Partial failure handling** — the server must never silently discard a write operation. If the embedding call is throttled by Bedrock, the server retries once with back-off and jitter before surfacing a structured error to the agent. Jitter distributes retry attempts when multiple concurrent embedding calls throttle simultaneously, preventing a thundering-herd re-trigger. If the vector index write fails after S3 content storage succeeds, the server writes to the local failure log and surfaces a structured error including the artifact identifier. AWS service unavailability mid-session (beyond transient errors) is surfaced as a structured error per tool call — no degraded mode, no silent swallowing of failures. |
| NFR-12 | **Must** | **Setup documentation** — the server repository must include setup documentation and an installation skill. The installation skill (FR-24) is the primary interactive onboarding vehicle: it guides the operator through AWS resource provisioning, access policy configuration, server setup, MCP client connection, health verification, and AGENTS.md configuration in a single structured workflow. The repository README retains a server configuration reference covering all configurable options and their defaults, and the server launch instructions. A recommended AGENTS.md snippet covering when to write artifacts, artifact types and when to use each, how to write a high-quality description, tier 2 vs tier 3 selection guidance, query strategy guidance (start with type and feature tag filters before issuing pure semantic queries; broaden only when narrow queries return insufficient results), when to use the synthesis capability and how to write the result back, and a pointer to the server's MCP Resources for runtime schema precision — is shipped with the installation skill and applied as the final step of the installation workflow. All documentation must be kept current with any change to the deployment prerequisites or artifact schema. |
| NFR-13 | **Should** | **Write latency** — for a typical structured artifact with ≤20 `##` sections and no Bedrock throttling, `write_artifact` must complete in under 2 seconds wall-clock time. This is achieved by embedding all sections concurrently (bounded by `SECTION_CONCURRENCY`) and issuing a single batched S3 Vectors call per artifact. Writing must not impose a perceivable blocking delay on an interactive agent session. |
| NFR-14 | **Should** | **Bedrock quota safety** — concurrent Bedrock embedding calls from `write_artifact` must be bounded by a configurable semaphore (`SECTION_CONCURRENCY`, default 5). At the default of 5 concurrent calls from a single session the server operates well within the Titan Text Embeddings v2 on-demand quota (6,000 RPM, 300,000 TPM in eu-central-1). Teams running multiple concurrent sessions should keep `SECTION_CONCURRENCY × concurrent_sessions ≤ 15` for comfortable headroom; configuration documentation must state this guideline explicitly. |
| NFR-15 | **Should** | **Migration throughput** — a bulk migration of 10 documents using `migrate.py` with the default `MIGRATE_CONCURRENCY=3` must complete in under 2 minutes under normal Bedrock response times. The migration skill's two-phase parallel-agent path for ≥ 10 files must reduce end-to-end wall-clock time (LLM enrichment + writing) to under 2 minutes for a 10-document migration. |

---

## Product Value Failure

This section identifies the conditions under which cairn-mcp could work correctly as software and still fail to deliver value.

**Who would not use it**
- Teams not using AWS — accepted constraint
- Small teams or short-lived projects where storing artifacts in the repository is sufficient — accepted constraint
- Teams whose agents do not support the MCP protocol — hard technical exclusion
- Solo developers on short projects where AWS setup overhead exceeds the value
- Teams in regulated environments where storing code artifacts outside the repository requires compliance review
- Teams already using a dedicated knowledge management pipeline
- Highly automated pipelines generating artifacts at high volume — the server is not designed for that scale
- Teams not using highly structured agents and skills with explicit artifact writing instructions — cairn-mcp is designed for disciplined agent workflows where skills define when to write, what type to assign, and how to write the description; without that structure, the store fills with inconsistent artifacts and search quality degrades regardless of the embedding model
- Open source projects with public contributors — granting public read/write access to an S3 bucket is not a viable security posture; the server assumes a closed, credentialed environment

**What would make it useless**
- Poor search quality: wrong embedding model, content truncated before embedding, a better model unavailable because the vector index dimension is locked — if the right artifact does not surface, agents re-discover instead of recall and the system stops being used
- Write API too complex or write latency too high in an interactive session — agents skip writing; an empty store is useless regardless of search quality
- No signal distinguishing "nothing exists" from "something exists but was not retrieved" — agents lose trust in zero-result responses
- Cross-scope discovery silently broken by misconfigured prefixes — a key differentiator fails without any error

**Assumptions that if wrong make this effort pointless**
- Agents consistently write artifacts at significant moments — if the write discipline is not established through skills and workflows, the store stays empty
- Context window limits remain a binding constraint — if future models hold an entire project's history in context natively, the core problem disappears
- Prior session knowledge is more useful than misleading — on fast-moving projects, stale artifacts can confidently point agents in the wrong direction
- Semantic search is the right retrieval mechanism — if agents mostly know what they are looking for by type and metadata, a simpler system would suffice

**What failure feels like**
- The agent retrieves an artifact, trusts it, and acts on superseded or wrong information — no error, no signal, just quietly wrong
- The agent asks questions that were already answered and documented — the developer answers again; the problem the server was meant to solve is still present
- Writing feels like a ritual: artifacts go in, nothing useful comes back; teams stop writing
- The store grows over months but the agent stays blind — confidence in the system collapses

---

## Known Limitations

**Concurrent writes** — when two agents write an artifact with the same identifier simultaneously, the outcome is last-writer-wins at both S3 and S3 Vectors. No conflict detection, locking, or merge is performed. In practice this requires two agents to write the same artifact type, title, and tier at the same moment — unlikely in normal use but possible in large automated pipelines. This is an accepted constraint and a candidate for a future resolution.

---

## Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-01 | Writing an artifact with valid inputs succeeds and returns a unique identifier. The artifact is immediately retrievable by that identifier. |
| AC-02 | A written artifact appears in semantic search results in the same session, without any intermediate step. |
| AC-03 | Semantic search results contain metadata and description only — no full content. |
| AC-04 | Writing the same tier 2 project-local artifact (same type, date, and title) twice on the same day produces exactly one stored artifact and one index entry. |
| AC-05 | Writing a tier 3 project documentation artifact (same type and title) on two different days produces exactly one stored artifact — the second write overwrites the first. |
| AC-06 | A tier 2 project-local artifact from a foreign scope is not returned by search, listing, or direct retrieval — even if its visibility is set to shared. |
| AC-07 | A tier 3 shared artifact from a foreign scope is returned by search and listing, and its full content is retrievable. |
| AC-08 | Archiving an artifact excludes it from search and listing results when using the default active filter. |
| AC-09 | The server refuses to start when credentials are invalid, surfacing a clear error before any tool call is accepted. |
| AC-10 | The server refuses to start when the deployment's own storage scope is unreachable, surfacing a clear error identifying the inaccessible scope. |
| AC-11 | The server refuses to start when the configured embedding model is incompatible with the existing vector index, surfacing a clear error with remediation instructions. |
| AC-12 | A credential expiry mid-session produces a structured, human-readable error response — not a raw exception. |
| AC-13 | The health check returns an independent status for each configured component, with any misconfigured component clearly identified. |
| AC-14 | The server is installable and runnable from the repository source using standard Python tooling with no additional infrastructure beyond AWS credentials and the configured AWS resources. |
| AC-15 | A write that fails after S3 content storage but before vector index completion produces a structured error containing the artifact identifier, and a corresponding entry appears in the local failure log. |
| AC-16 | Triggering reconciliation when orphaned S3 objects exist (artifacts in S3 with no vector index entry) re-indexes them and returns a summary listing each recovered artifact. |
| AC-17 | The synthesise_artifacts tool called with a query returns full content from the top matching artifacts in a single response, including identifier, metadata, description, and full content for each source artifact. |
| AC-18 | The synthesis freshness check identifies synthesis artifacts whose source artifacts have a more recent write date than the synthesis itself, and lists the affected source artifact identifiers in the returned report. |
| AC-19 | Deleting an artifact by identifier removes it from S3 and the vector index; it is no longer retrievable by identifier and no longer appears in search or listing results. Attempting to delete a foreign-scope artifact returns a clear rejection. |
| AC-20 | Purging archived artifacts removes all inactive artifacts from S3 and the vector index within own scope; none are retrievable by identifier and none appear in any listing. Any synthesis artifact whose every source artifact was in the purge set is also deleted and identified in the response summary. |
| AC-21 | Following the migration skill workflow on a project with existing documentation files results in all identified artifacts written to cairn-mcp and immediately searchable. The project AGENTS.md is updated with the cairn-mcp usage snippet at the conclusion of the workflow. |
| AC-22 | Running `uv run scripts/migrate.py --dry-run` with a valid CAIRN_IMPORT.yaml outputs a structured JSON preview of all artifacts that would be imported — including resolved dates, generated descriptions, and resolved artifact identifiers — without making any changes to S3, S3 Vectors, or the project repo. |
| AC-23 | Running `uv run scripts/migrate.py` with a valid CAIRN_IMPORT.yaml writes all listed artifacts to cairn-mcp and makes them immediately searchable. Re-running the same manifest produces no duplicate artifacts and no errors. |
| AC-24 | `write_artifact` on a structured artifact with 8 `##` sections makes exactly 8 Bedrock embedding calls (concurrently, not serially) and exactly 1 S3 Vectors batch call. The `sections_indexed` count in the response equals the number of sections that passed both the minimum-length filter and the section cap. |
| AC-25 | Running `migrate.py` with `MIGRATE_CONCURRENCY=3` and a 9-entry manifest processes multiple artifacts simultaneously — entries are not written in strict sequential order, and the total wall-clock time is less than the sum of individual per-artifact write times. |
| AC-26 | A `##` section whose body is shorter than `EMBED_MIN_SECTION_LENGTH` is not present in the vector index after a write. The `sections_indexed` count excludes it. The full artifact content (including the short section) is still returned in full by `read_artifact`. |
| AC-27 | An artifact with more `##` sections than `EMBED_MAX_SECTIONS` has exactly `EMBED_MAX_SECTIONS` section vectors in the index. Full content remains in S3 and is returned in full by `read_artifact`. |
| AC-28 | Following the installing-cairn skill workflow on a fresh environment results in all required AWS resources provisioned, server configuration written, MCP client configured for the chosen client, the server's health check returning healthy status for all components, and the project AGENTS.md updated with the cairn-mcp usage snippet and the operator's declared ADR strategy. |
| AC-29 | The installation skill generates access policy documents with all operator-specific resource identifiers substituted — no placeholder text remains in any emitted output. |

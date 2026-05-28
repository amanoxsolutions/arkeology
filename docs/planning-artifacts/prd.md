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

## Scope

### Core features

- MCP server with 7 tools: write artifact, read artifact, search artifacts, list artifacts, archive artifact, health check, reconcile index
- AWS S3 + S3 Vectors + Bedrock (Titan Text Embeddings v2) backend
- Artifact metadata schema: type, team, project, tier, date, status, title, visibility, description (≤280 chars), optional feature tags and author role
- Cross-scope read with tier 3 + shared visibility gate
- Startup validation sequence: credentials → storage scope access → embedding model compatibility
- stdio transport (primary); architecture open to additional transports without rework
- All standard AWS credential environments (local profiles, IAM roles, CI/CD pipelines)
- Layered architecture: storage, vector search, embedding, and server transport each behind clean interfaces
- Tier 2 artifacts are append-only and immutable by design — a code review, session summary, or implementation note is a historical record; archiving is the only permitted state change
- Tier 3 artifacts are living documents — a plan or ADR is updated in place as decisions evolve

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

### Maintenance

- As a developer agent, I want to archive an artifact that is no longer relevant so it stops appearing in search and list results.

### Operations

- As an admin, I want the server to validate all configuration at startup and fail with a clear, actionable error if anything is misconfigured, so I catch problems before an agent session begins.
- As an admin, I want a health check capability that reports the status of each component independently so I can diagnose issues without reading logs.

---

## Functional Requirements

| ID | Requirement |
|---|---|
| FR-01 | The server provides an artifact writing capability. The agent provides: full content, a human-readable title, a tweet-length description (≤280 characters), artifact type, optional feature tags, team, project, storage tier (project-local or permanent/shared), visibility (shared or confidential), and optionally the producing role. The server stores the artifact durably, indexes it for semantic search immediately, and returns a unique artifact identifier. |
| FR-02 | The server provides a capability to retrieve the full content of a known artifact by its identifier. For artifacts outside the deployment's own storage scope, access is restricted to permanent shared artifacts only. |
| FR-03 | The server provides a semantic search capability. The agent provides a natural language query and optional metadata filters (type, feature tags, team, project, tier). The server returns a ranked list of matching artifacts with their metadata and description — no full content. Results from outside the deployment's own scope are restricted to permanent shared artifacts. Maximum results per query: 100. |
| FR-04 | The server provides a metadata-only artifact listing capability. The agent can filter by type, feature tags, team, project, tier, and status. No semantic ranking is performed. Results from outside the deployment's own scope are restricted to permanent shared artifacts. |
| FR-05 | The server provides an artifact archiving capability. Archiving marks an artifact as inactive, excluding it from search and listing results by default. Archiving is scoped to the deployment's own storage — artifacts from foreign scopes cannot be archived. |
| FR-06 | The server provides a health check capability that reports the connectivity and accessibility status of each configured component independently, enabling diagnosis without log access. |
| FR-07 | At startup, the server validates all configuration before accepting any tool calls: credential validity, read and write accessibility of the deployment's own storage scope, read accessibility of each subscribed foreign scope, and compatibility between the configured embedding model and the vector index. Any failure produces a clear, actionable error message and prevents the server from starting. |
| FR-08 | Artifact identifiers are generated deterministically from the artifact's own attributes — no random component. Tier 2 project-local artifacts: same type, date, and title written multiple times on the same calendar day produces the same identifier and overwrites silently; a different day produces a new identifier and a new artifact. Tier 3 project documentation artifacts: same type and title always produces the same identifier and overwrites regardless of date — living documents are updated in place. |
| FR-09 | Each stored artifact carries the following metadata, used for filtering, display, and access control. **Required** — type, team, project, tier, date (last write), status, title, visibility, description (≤280 characters). **Optional** — feature tags (list), author role. Visibility is enforced server-side and is not exposed as an agent-facing filter parameter. |
| FR-10 | Cross-boundary access is enforced server-side. Within the deployment's own storage scope, all artifacts are accessible regardless of tier or visibility. Across subscribed foreign scopes, only tier 3 shared artifacts are accessible. This is a soft control enforced at the server layer; it does not substitute for infrastructure-level access controls. This distinction must be documented in the server README. |
| FR-11 | The server supports all standard AWS credential environments — local developer profiles, IAM roles, CI/CD pipelines, and any other environment where AWS credentials are available. Named profiles are optional and developer-facing; the platform credential chain is the primary mechanism. |
| FR-12 | Credential errors occurring at any point during a session are surfaced as structured, human-readable error responses with re-authentication instructions. Raw exceptions are never returned to the agent. |
| FR-13 | Tier 2 project-local artifacts are immutable once written. Content is frozen as a permanent, point-in-time record. No content editing capability is provided. |
| FR-14 | Archiving an artifact is the only modification permitted on an existing tier 2 project-local artifact. It marks the artifact as inactive and excludes it from search and listing results by default. No other attribute — content, tier, visibility, title, or feature tags — can be modified after the initial write. |
| FR-15 | Tier 3 project documentation artifacts are living documents. Writing an artifact with the same type and title as an existing tier 3 artifact always overwrites it in place, updating content, refreshing the semantic index, and updating all metadata including the write date. |
| FR-16 | When a write operation partially fails — S3 content storage succeeds but vector index write fails — the server writes a structured entry to a local tier 1 failure log before surfacing a structured error to the agent. The entry records the artifact identifier, title, type, tier, and the nature of the failure. The error response to the agent includes the artifact identifier and indicates that a failure log entry was written. The failure log is a tier 1 artifact: local, ephemeral, and gitignored. |
| FR-17 | The server provides a reconciliation capability. When triggered, it performs two steps: (1) if a failure log exists, it re-indexes each artifact listed and removes resolved entries from the log; (2) regardless of whether a failure log exists, it scans the deployment's own S3 prefix against the vector index and re-indexes any orphaned objects found — artifacts present in S3 with no corresponding vector index entry. The tool returns a structured summary of what was found and what was reconciled. |

---

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Write-then-read consistency** — an artifact written by the server must be searchable and retrievable without requiring any background synchronisation job. There is no imposed delay between writing an artifact and it being available for search in the same session. |
| NFR-02 | **Bounded response payloads** — semantic search results must never include full artifact content. Responses carry metadata and description only. Full content is fetched explicitly and on demand. |
| NFR-03 | **Hard startup failure** — any misconfiguration surfaces as a clear, actionable error before the server accepts any tool call. The server never starts in a degraded or partially functional state. |
| NFR-04 | **Layered architecture** — storage, vector search, embedding, and server transport must each sit behind a clean interface. Any layer must be replaceable without modifying the others. |
| NFR-05 | **Transport extensibility** — the primary transport is stdio for interactive local use. The server must be structured so that additional transports can be added as a configuration choice, without architectural rework. |
| NFR-06 | **Idempotent writes** — writing the same logical artifact multiple times produces exactly one stored artifact and one index entry. No duplicates, no orphaned index entries. |
| NFR-07 | **Test-driven development** — all business logic must be covered by tests written before implementation. AWS service interactions must be covered by integration tests. |
| NFR-08 | **Runtime simplicity** — the server must run in a standard Python environment without requiring containerisation, orchestration, or custom infrastructure beyond the configured AWS resources and credentials. |
| NFR-09 | **Distribution** — the server must be installable and runnable directly from the repository source using standard Python tooling. Distribution via a public or private package registry is a future consideration and not a current requirement. |
| NFR-10 | **Encryption in transit** — all communication between the server and AWS services must use HTTPS. Encryption at rest for S3 and S3 Vectors storage is the responsibility of the admin provisioning those resources and is out of scope for the server. |
| NFR-11 | **Partial failure handling** — the server must never silently discard a write operation. If the embedding call is throttled by Bedrock, the server retries once with back-off before surfacing a structured error to the agent. If the vector index write fails after S3 content storage succeeds, the server writes to the local failure log and surfaces a structured error including the artifact identifier. AWS service unavailability mid-session (beyond transient errors) is surfaced as a structured error per tool call — no degraded mode, no silent swallowing of failures. |

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

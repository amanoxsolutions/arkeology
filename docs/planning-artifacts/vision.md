---
type: vision
title: "Arkeology — Persistent Artifact Memory"
description: Vision for Arkeology, a Python MCP server that gives AI agents persistent and searchable artifact memory backed by AWS S3, S3 Vectors, and Amazon Bedrock.
tags: []
timestamp: 2026-08-21T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "pm"
  date: "2026-08-21"
revised:
  by: "pm"
  date: "2026-09-24"
---

# Arkeology — Persistent Artifact Memory

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

Arkeology is a Python MCP server that gives AI agents **persistent and searchable artifact memory**, backed entirely by AWS — S3 for durable content storage, S3 Vectors for semantic search, and Amazon Bedrock for embeddings. Agents connect via MCP to write, search, list, and recall structured artifacts across sessions and across team boundaries.

## Problem Statement

On small projects with short lifespans, ad-hoc approaches work: commit notes to the repo, store summaries in a `docs/` folder, rely on a tool's built-in memory. Some AI coding platforms provide session memory out of the box. But these approaches hit two hard limits as projects grow.

**Problem 1 — Durable, portable storage.** Artifacts end up scattered: in the repo (adding noise to git history and polluting the codebase), in proprietary tool memory (locked to one platform, invisible to other engineers and tools), or simply discarded when the context window closes. No ad-hoc approach is simultaneously durable, portable, and shared across engineers, tools, and sessions. Some teams have found creative workarounds — the Streamlit engineering team, for example, repurposed their GitHub wiki as a scratch space, describing it as *"a hack, honestly. But it works surprisingly well."* It does. But it is GitHub-specific, has no semantic search, and does not scale across projects or teams.

**Problem 2 — Semantic retrieval.** Even when artifacts are stored, finding the right one is unsolved. As a project grows, months of agent sessions produce hundreds or thousands of artifacts. No agent can be asked to scan all of them to find the one that matters for the current task. Without semantic search and metadata filtering, an agent starting a session on the `auth` module has no practical way to surface the implementation notes from six months ago — even if those notes exist and are perfectly relevant.

Arkeology addresses both problems in AWS environments: structured durable storage and immediate semantic search. Artifacts are written mid-session and immediately searchable — by semantic similarity, by metadata filter, or by direct identifier. Canonical knowledge can be flagged as shareable, making it discoverable by agents on other projects or teams.

## Product Boundaries

Arkeology is not built for every team or every project. The following are permanent exclusions, not near-term deferrals:

- Teams not using AWS — accepted constraint; the server is built entirely on AWS services (S3, S3 Vectors, Bedrock)
- Small teams or short-lived projects where storing artifacts in the repository is sufficient — accepted constraint
- Teams whose agents do not support the MCP protocol — hard technical exclusion
- Solo developers on short projects where AWS setup overhead exceeds the value
- Teams in regulated environments where storing code artifacts outside the repository requires compliance review
- Teams already using a dedicated knowledge management pipeline
- Highly automated pipelines generating artifacts at high volume — the server is not designed for that scale
- Teams not using highly structured agents and skills with explicit artifact writing instructions — Arkeology is designed for disciplined agent workflows where skills define when to write, what type to assign, and how to write the description; without that structure, the store fills with inconsistent artifacts and search quality degrades regardless of the embedding model
- Open source projects with public contributors — granting public read/write access to an S3 bucket is not a viable security posture; the server assumes a closed, credentialed environment

## Differentiator

Each deployment of Arkeology is a self-contained, independent persistent memory store for one team or project. Agents write artifacts at significant moments — end of session, after a code review, after an architecture decision. Future agents and engineers search and retrieve those artifacts to resume where prior work left off, without re-discovering what is already known.

When a shared S3 bucket is deliberately configured across teams, tier 3 permanent knowledge — ADRs, canonical patterns, architecture decisions — becomes discoverable across project and team boundaries. A platform team's VPC peering decision surfaces for a microservices team agent that subscribed to the platform team's prefix. Tier 2 working documents are never served across scope boundaries (see the Cross-Scope Trust Constraint in `requirements.md`'s Constraints table for what this does and does not protect).

Artifacts follow the Open Knowledge Format, so a document keeps in Arkeology the identifier, provenance, sources, relationships, and lifecycle status it carries in the repository. An agent moves between the Git corpus and Arkeology using the same names, with no translation step.

The server is deployment-agnostic: it is given resource names and trusts the credentials it receives. Deployment topology — one shared org-wide bucket, one bucket per team, one per project — is entirely the operator's choice.

## Users

| User | Description |
|---|---|
| **Developer agent** | An AI coding agent running interactively on a developer's machine — the primary user |
| **CI/CD pipeline agent** | An automated AI agent (e.g. code reviewer) running in a pipeline — secondary user |
| **Admin / DevOps** | The person who provisions AWS resources and configures the server |

## User Journeys

### Writing artifacts

- As a developer agent completing a code review, I want to write the findings as an artifact so they persist beyond this session and are retrievable by future agents.
- As a developer agent making an architecture decision, I want to write an ADR as a tier 3 shared artifact so other teams' agents can discover it.
- As a CI/CD pipeline agent completing an automated code review, I want to write findings as an artifact using IAM role credentials so findings are stored even in non-interactive environments.

### Searching and reading

- As a developer agent starting a new session on a feature, I want to search for prior artifacts related to that feature so I can resume where the last session left off.
- As a developer agent, I want to know about a prior bug fix — its implementation, reason, and context — so I do not accidentally undo it without understanding why it was made.
- As a developer agent, after finding relevant artifacts via search, I want to read the full content of the specific artifacts I selected based on their description and relevance score.
- As a developer using an MCP-aware host tool (MCP Inspector, Claude Desktop), I want to browse and open Arkeology artifacts directly in the host's resource panel so I can read artifact content without issuing a tool call.
- As a developer, I want to call a visual browser tool in my MCP host and see an interactive artifact browser rendered inline — with faceted filtering, semantic search, and full markdown and diagram rendering — so I can browse, search, and read artifacts visually without issuing multiple tool calls.
- As a developer agent, I want to list all active artifacts for my project to browse what exists without issuing a semantic query.
- As a CI/CD pipeline agent completing an automated code review, I want to know about prior architecture and implementation decisions so I do not investigate or challenge already decided, valid implementations.

### Cross-team knowledge sharing

- As a microservices team agent, I want to discover other teams' (e.g. platform, networking, security) ADRs and architecture decisions that I need to take into account when designing my architecture.

### Migrating existing projects

- As an existing project operator adopting Arkeology, I want to migrate accumulated documentation from my repo into Arkeology so that future agents can search and retrieve existing knowledge immediately without starting from zero.
- As an existing project operator, I want a structured workflow that classifies my existing docs by artifact type and tier, generates quality descriptions for search, and recovers original creation dates from git history — so migrated artifacts are as useful as freshly written ones.
- As an existing project operator, I want to preview what the migration will import before committing any writes, so I can review and correct the manifest without risk.
- As an existing project operator, I want the migration to finish by updating my project AGENTS.md with Arkeology usage guidance, so future agents write to Arkeology going forward without any additional configuration step.

### Maintenance

- As a developer agent, I want to archive an artifact that is no longer relevant so it stops appearing in search and list results.

### Operations

- As an admin, I want the server to validate all configuration at startup and fail with a clear, actionable error if anything is misconfigured, so I catch problems before an agent session begins.
- As an admin, I want a health check capability that reports the status of each component independently so I can diagnose issues without reading logs.

## Product-Value-Failure Pre-Mortem

This section identifies the conditions under which Arkeology could work correctly as software and still fail to deliver value.

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
- The agent retrieves an artifact, trusts it, and acts on superseded or wrong information — no error, no signal, just quietly wrong. *Mitigated by* the default in-force view, which leaves out documents their own writer has deprecated, and by per-source freshness, which flags a document whose sources changed after it was written
- The agent asks questions that were already answered and documented — the developer answers again; the problem the server was meant to solve is still present
- Writing feels like a ritual: artifacts go in, nothing useful comes back; teams stop writing
- The store grows over months but the agent stays blind — confidence in the system collapses

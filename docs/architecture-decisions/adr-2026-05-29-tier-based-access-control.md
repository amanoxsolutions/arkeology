---
type: adr
title: Tier-Based Cross-Scope Access Control Model
description: Records the model that controls which artifacts from foreign scopes are readable by a given Arkeology deployment, governed by tier and visibility attributes and enforced server-side.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: "analyst"
  date: "2026-07-02"
---

# Tier-Based Cross-Scope Access Control Model

## Description

Arkeology is designed to be deployed once per team or project, with each deployment writing
to its own S3 prefix. This decision records the model that controls which artifacts from
foreign scopes are readable by a given deployment, and how that model is enforced.

## Status

Accepted

## Context

A key product requirement is cross-team knowledge sharing (FR-10): platform team ADRs and
architecture decisions must be discoverable by microservices team agents, without those agents
being able to read or overwrite the platform team's working documents (session summaries,
code reviews, implementation notes).

The access model must answer two questions:

1. **Which artifacts from foreign scopes are visible?** — Teams need to share canonical,
   stable knowledge; they do not need to share in-progress working documents.
2. **How is access enforced?** — IAM policies control S3 bucket access at the infrastructure
   level. Server-side enforcement is a higher-level semantic gate, not a security boundary.

Two attributes on every artifact govern cross-scope visibility:

- **Tier**: `2` (project-local, session-scoped, append-only) or `3` (permanent, living
  document, updated in place). Tier 2 includes code reviews, session summaries, and
  implementation notes. Tier 3 includes ADRs, plans, PRDs, and synthesis artifacts.
- **Visibility**: `shared` (discoverable across scopes) or `hidden` (own scope only).

The cross-scope read configuration is set by the operator via `READ_PREFIXES` — a
comma-separated list of S3 prefixes the server is allowed to read from. Startup check 3
validates that each prefix is accessible.

A subtle but critical implementation detail: the scope check must use
`artifact_id.startswith(scope + "/")`, never bare `startswith(scope)`. A bare prefix check
allows a scope of `"team-a"` to incorrectly match keys under `"team-abc/"`.

## Decision

Access across scope boundaries is governed by two rules, enforced server-side in every read,
search, list, and synthesise tool:

- **Own scope** (`WRITE_PREFIX`): all artifacts are accessible regardless of tier or
  visibility.
- **Foreign scope** (`READ_PREFIXES`): only tier 3 + `visibility=shared` artifacts are
  accessible. Tier 2 artifacts and tier 3 hidden artifacts from foreign scopes are silently
  excluded from results and rejected on direct read.

Write, archive, delete, and purge operations are always restricted to the own scope.

This is a **soft control** enforced at the server layer, and its reach differs by storage
side (revised 2026-07-02 — see the Revision note below):

- **S3 content can be hard-bounded**: IAM supports prefix-scoped object permissions, so a
  team can be denied `s3:GetObject` on foreign prefixes — foreign tier 2 *content* is
  infrastructure-protectable.
- **The shared vector index cannot**: the IAM condition keys applicable to
  `s3vectors:QueryVectors`/`GetVectors`/`ListVectors` (`aws:ResourceTag`,
  `s3vectors:VectorBucketTag`) evaluate at the index/bucket resource level only — no
  condition key references vector keys, vector metadata, or the request's filter
  expression. Any principal with query access to the shared index can read **all**
  participants' vector metadata (titles, descriptions, tags, tier, status) and embeddings —
  including tier 2 and hidden artifacts — with plain AWS API calls; no modified server is
  required.

Sharing a vector index therefore implies **mutual trust between all participating teams at
the metadata, description, and embedding level**. The tier/visibility gate is a policy
convention honoured by unmodified servers, not an access control. The server README
documents this distinction.

Cross-scope semantic search requires all participating deployments to share the same S3
Vectors index, embedding model, and vector dimension. Deployments using separate indexes
cannot perform cross-scope semantic search (documented in deployment prerequisites).

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — Tier + visibility gate | Simple two-attribute model; maps naturally to the tier 2/3 semantic split; no per-artifact ACL to manage | Soft control only — does not replace IAM; visibility is binary (shared/hidden), not fine-grained |
| Full isolation (no cross-scope) | Simplest implementation; no access control logic in tools | Loses the cross-team knowledge sharing use case — a core product differentiator |
| Per-artifact ACL (allowlist of scopes) | Fine-grained control | Significant complexity: ACL storage, evaluation, and management surface for agents; far exceeds the use case requirements |
| IAM only (no server-side gate) | Single enforcement point | IAM policies cannot encode the tier 2 / tier 3 semantic distinction; every artifact in a readable bucket would be accessible |

## Consequences

- Every read, search, list, and synthesise tool contains a scope gate. The gate is tested for
  both the own-scope (unrestricted) and foreign-scope (tier 3 + shared only) cases.
- The scope check `artifact_id.startswith(scope + "/")` is non-negotiable — bare
  `startswith(scope)` is a documented high-friction area in `AGENTS.md` and must never be
  used.
- Cross-scope semantic search is implemented as a single combined `QueryVectors` call using a
  `$or` filter that covers own scope (unrestricted) and each foreign scope (tier 3 + shared).
  This avoids N separate query calls per iteration.
- `WRITE_PREFIX` must not be empty — an empty prefix causes `startswith("" + "/")` to always
  return `True`, silently bypassing the gate for all artifacts. A startup validator enforces
  this.
- Visibility is enforced server-side and is intentionally not exposed as a filter parameter
  to agents — the gate is not bypassable through the MCP API.
- The delete synthesis reference check in `delete_artifact` is scoped to own scope only —
  foreign-scope synthesis identifiers must never appear in delete warnings (confirmed as a
  known bug in Phase 3 and fixed in Phase 6).

## Revision — 2026-07-02

The original Decision text claimed "operators who want a hard boundary must configure IAM
to restrict cross-bucket or cross-prefix access accordingly." No IAM configuration can
provide a tier-aware boundary *within* a shared vector index — verified against the
[Service Authorization Reference for Amazon S3 Vectors](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazons3vectors.html):
all condition keys applicable to the query/read actions evaluate at the index/bucket
resource level (resource tags), never at the vector or metadata level. The Decision text
above now records the content/index asymmetry and the mutual-trust assumption. The tier +
visibility gate itself is unchanged and remains correctly implemented.

Hard-boundary directions, if ever required (candidates for a future ADR; anchored in
requirements.md FR-65, "full cross-scope enforcement of the visibility gate"):

1. **Per-team vector indexes + tier 3 replication** — each team owns a private index; tier 3
   `shared` vectors are additionally written to a shared discovery index. Dual writes and a
   reconcile story, but index-level resource tags then give a true IAM boundary between
   teams.
2. **Metadata redaction for non-shared artifacts** — keep `description` (and optionally
   `title`) out of the shared index for tier 2 / hidden artifacts, shrinking the exposure to
   embeddings only.
3. **Hosted deployment** — a shared server process holds the AWS credentials and clients
   authenticate to it; the gate then runs on the trusted side of the boundary. Requires the
   HTTP transport listed as a future consideration (NFR-05).

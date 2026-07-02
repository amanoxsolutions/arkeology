---
type: plan
title: Backlog
description: All work waiting to be started for cairn-mcp — deferred improvements, issues, and not-yet-built features organised by topic with stable IDs.
tags: []
timestamp: 2026-06-16T00:00:00Z
okf_version: "0.1"
---

# Backlog

The single home for all work **waiting to be started** — issues, deferred improvements, and not-yet-built features. Tasks are pulled from here into the current open phase in [`plan.md`](plan.md) when we decide to tackle them; there is no pre-planned schedule.

Organised by topic. Each item keeps a stable ID so brainstorming docs, specs, and reviews can reference it:
- **`B-…`** — deferred backlog items (features, improvements, or design-first items that require brainstorming before they can be specced).

Items that were promoted to a phase are **not** listed here — see the phase history in [`plan.md`](plan.md).

---

## Retrieval quality

- **B-1 — Retrieval-quality benchmark harness.** Reusable harness measuring recall/precision of
  cairn semantic search vs OKF-style `index.md` progressive-disclosure navigation over a fixed
  corpus at N≈10/100/1000 artifacts; repeatable as corpus and embedding model evolve. Substantiates
  the "semantic memory beats progressive-disclosure wiki at scale" positioning claim.
  Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (OQ1).

## Cross-scope security

- **B-5 — Hard cross-scope security boundary.** Today the tier/visibility gate is a soft
  control: S3 Vectors authorization is all-or-nothing per index, so every team sharing the
  vector index can technically read all teams' vector metadata (titles, descriptions, tags)
  and embeddings, including tier 2 — cross-scope deployment is a mutual-trust topology
  (documented 2026-07-02 in ADR-007 revision, PRD Known Limitations, and the
  SERVER-REFERENCE Cross-Scope Security Model). Two candidate solutions, design-first
  (brainstorming + ADR before spec):
  1. **Hosted MCP server** — deploy cairn-mcp as a shared service (requires the HTTP
     transport, NFR-05): the server holds the AWS credentials, clients authenticate to it,
     and the tier/visibility gate runs on the trusted side of the boundary. Turns the
     existing gate into a real access control without index topology changes.
  2. **Split vector index** — each team owns a private vector index; tier 3 `shared`
     vectors are additionally replicated into a shared discovery index. Index-level IAM
     (resource tags / separate ARNs) then provides a true hard boundary. Costs: dual
     writes on tier 3 shared artifacts, a cross-index reconcile story, and a search path
     that queries two indexes.
  Source: [`adr-2026-05-29-tier-based-access-control.md`](../architecture-decisions/adr-2026-05-29-tier-based-access-control.md)
  (Revision 2026-07-02); full-project review CA-1 (2026-07-02).

## OKF interoperability

- **B-2 — OKF export adapter (+ governance).** `cairn export --okf <scope>` emitting an OKF bundle
  (git repo + `index.md` + `log.md` + cross-links) on a **best-effort** basis: preserve each
  document's existing agent-authored frontmatter, fill gaps from cairn's stored metadata (`tags`;
  OKF `timestamp` ← `last_edited_ulid`; cairn `date` → custom key; add `resource`), and append
  cairn's extra tags. cairn
  does **not** transform non-OKF content into OKF (the authoring agent's job) and makes no internal
  schema change; vector index stays OKF-agnostic. Must reuse the scope/tier/visibility gate at export
  time, exclude/partition `hidden`/cross-scope artifacts, and stamp the bundle as ungoverned
  downstream. Open detail: precedence when existing frontmatter and cairn metadata disagree (default:
  existing frontmatter authoritative, cairn fills gaps only). Also resolves the visual-reading-interface
  export path. Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D1, D2a, D4).

- **B-4 — OKF import of foreign bundles.** Ingest an external OKF bundle into a cairn scope: the
  `migrating-to-cairn` skill accepts an OKF bundle as an input source, and/or an `import_okf` tool that
  reads each concept, stores its content, and embeds it. Map OKF free-form `type` onto cairn's enum with
  a fallback for unmapped types (OKF consumers must not reject unknown types). In scope per the
  first-class OKF commitment (D6). Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D6).

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

## Schema

- **B-3 — Rename `feature_tags` → `tags`.** Cross-cutting field rename aligning the one cairn metadata
  field where OKF alignment is clean (same concept, no semantic loss). Touches the Artifact model,
  `write.py` (S3 object metadata **and** vector metadata keys), `filter.py`, `list.py` faceting, tests,
  AGENTS.md, and the install/migrate skills; must preserve the deliberate S3 comma-joined-string vs
  vector `list[str]` dual-encoding. No data migration (no live data). Independent of the exporter —
  can proceed anytime. Source: [`brainstorming-2026-06-15-okf-alignment.md`](../brainstorming/brainstorming-2026-06-15-okf-alignment.md) (D2).

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

---
type: adr
title: Section-Level Embedding at H2 Boundaries
description: Records the choice to embed each H2 section of an artifact as an independent vector rather than embedding the full artifact as a single document vector.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: developer
  date: "2026-07-05"
---

# Section-Level Embedding at H2 Boundaries

## Description

When an artifact is written, cairn-mcp must produce one or more embedding vectors to make it
searchable. This decision records the choice to embed each `##` (H2) section of the artifact
as an independent vector, rather than embedding the full artifact as a single document vector.

## Status

Accepted

## Context

Artifacts in cairn-mcp can be long, structured Markdown documents — code reviews, session
summaries, implementation notes, ADRs — each potentially covering multiple distinct concepts.
A code review may discuss authentication in one section and database indexing in another. A
session summary may cover a bug fix in one section and a performance optimisation in another.

If the entire artifact is embedded as a single document vector, a query for "database indexing
strategy" must compete against the centroid of all topics in every artifact. Semantically
specific queries surface documents that only partially match, and the ranking degrades as
artifacts grow longer and more heterogeneous.

The alternative is sub-document chunking: embed smaller units so that a query can match the
relevant part of a long artifact without being diluted by unrelated sections. Markdown `##`
headings provide a natural, author-defined boundary for this chunking — they are meaningful
structural divisions, not arbitrary byte offsets.

Three sub-document strategies were evaluated:

- **H2 section boundaries** — use `##` headings as chunk boundaries; each section becomes
  one vector. Boundaries are author-defined and semantically meaningful.
- **Sliding window** — fixed-size overlapping text windows. No awareness of document structure.
- **Sentence-level** — one vector per sentence. Maximum granularity; maximum index size.

The search path must then group section-level results back into artifacts: the re-fetch loop
in `_search_helper.py` queries for section vectors, groups hits by `artifact_id`, and repeats
until the requested number of *artifacts* is reached.

## Decision

We embed each `##` (H2) section of the artifact as an independent vector. Section bodies are
embedded with context: `title + type + tags + section_content`. The section vector key
is `{s3_key}#{section_slug}` (matching ADR-005's key format — see the Revision note below).
The `artifact_id` is stored as filterable metadata on every section vector so the re-fetch
loop can group and deduplicate.

If the artifact contains no `##` sections, a single document-level vector is generated from
`title + description + type + tags` (the "fallback" path).

Three configurable guards bound the embedding cost per artifact:

| Config var | Default | Effect |
|---|---|---|
| `EMBED_MIN_SECTION_LENGTH` | 50 chars | Sections shorter than this are skipped — semantic noise |
| `EMBED_MAX_SECTIONS` | 20 | At most 20 sections are embedded per artifact |
| `EMBED_MAX_SECTION_LENGTH` | 24,000 chars | Section body is truncated before the embedding call only; the full body is always stored in S3 and returned by `read_artifact` |

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — H2 section boundaries | Author-defined semantic boundaries; one vector per meaningful topic; moderate index growth; natural fallback for flat documents | More vectors per artifact; re-fetch loop must group by `artifact_id`; cross-section concepts may be missed |
| Single document-level vector | Minimal index size; simplest search path | Long, heterogeneous documents produce diluted embeddings; specific queries score poorly against multi-topic artifacts |
| Sliding window chunking | No dependency on document structure; works for any text | Arbitrary boundaries split meaningful units; overlap creates near-duplicate vectors; higher index size |
| Sentence-level embedding | Maximum semantic granularity | Very large index; grouping logic more complex; sentence-level vectors are too narrow for artifact-scale concepts |

## Consequences

- Index size scales with artifact section count, not artifact count alone. The
  `EMBED_MAX_SECTIONS=20` cap bounds the worst case to 20 vectors per artifact.
- The search re-fetch loop (in `_search_helper.py`) must always group section vectors by
  `artifact_id` to deduplicate. A single artifact can contribute multiple hits per query
  iteration; only the highest-scoring section determines the artifact's rank.
- Updating a tier 3 artifact (living document) may add, remove, or rename sections. The write
  path detects orphaned section vectors by querying the index for all vectors with
  `artifact_id` equal to the artifact being written, then deleting any whose key is not in the
  new section set. The `PutVectors` upsert semantics handle unchanged sections (confirmed
  empirically in T17, 2026-05-31).
- Section bodies exceeding `EMBED_MAX_SECTION_LENGTH` are truncated before the Bedrock call
  only. The full body is always stored in S3 and returned unchanged by `read_artifact`.
  Truncation is logged at DEBUG and is never visible to the agent.
- Cost at Titan Text Embeddings v2 pricing (on-demand) is negligible even at the 20-section
  ceiling — documented in NFR-14.

> **Revised (2026-07-05, Phase 12 review M-3).** The three guards in this decision, and the
> embedding-text construction described above, are implemented in a single shared module
> (`tools/_section_pipeline.py`) called from both `write_artifact` and `reconcile_index` —
> not duplicated per tool. This was tightened after a review finding that `reconcile_index`
> re-embedded sections directly, bypassing the min-length filter, the `EMBED_MAX_SECTIONS`
> cap, and `EMBED_MAX_SECTION_LENGTH` truncation entirely; a section truncated at write time
> was resubmitted full-length on every reconcile replay and failed Titan's input limit
> forever. Both tools now apply identical filtering/capping/truncation by construction.

> **Revised (2026-07-05, Phase 12 review M-14).** The Decision section above previously stated
> the section vector key as `{artifact_id}#{section_slug}`. This was incorrect — the shipped
> code (`write.py`, `reconcile.py::_reindex_artifact`) and ADR-005 both use `{s3_key}#{section_slug}`,
> where `s3_key` is the full S3 object key (`{WRITE_PREFIX}/{artifact_id}{file_extension}`), not
> the bare `artifact_id`. The Decision text above is corrected to match. This is purely a
> documentation fix — no behavioural change; the `artifact_id`-as-filterable-metadata mechanism
> described in the same paragraph is unaffected and remains accurate.

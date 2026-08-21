---
type: brainstorming
title: Retrieval Architecture and Synthesis Layer
description: Explores whether PageIndex ideas can improve retrieval quality for structured artifacts and what a synthesis/wiki layer above Arkeology would concretely look like.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-29"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Retrieval Architecture and Synthesis Layer

## Description

Two questions left open after the external source review (PageIndex + Karpathy llm-wiki). First: can PageIndex ideas improve retrieval quality for structured artifacts, even though the core PageIndex architecture does not apply directly? Second: what would a synthesis/wiki layer above Arkeology actually look like — concretely, for this project? Brainstormed 2026-05-29, after vision.md, requirements.md, and plan.md were finalised.

---

## Part 1 — PageIndex ideas for structured artifacts

### Context: what the claim was and why it was wrong

The previous analysis said: "For our target scale (teams, cross-project, thousands of artifacts), vector search + metadata filtering outperforms tree-based reasoning in latency and infrastructure cost."

That claim was architectural reasoning dressed up as a data point. There is no benchmark comparing the two approaches on structured markdown artifacts. The honest basis for preferring vector search over PageIndex's tree traversal is:

1. **PageIndex solves a problem we don't have.** PageIndex was designed for documents where vector similarity systematically fails — long, unstructured content where meaning requires multi-step reasoning across sections. Our artifacts are short (typically 300–2000 words), explicitly structured by agent skills using consistent markdown templates, and written to be semantically dense. The precondition for PageIndex's advantage (similarity ≠ relevance) is weak for well-structured short documents.

2. **Architectural reasoning about speed, not data.** ANN (approximate nearest neighbour) search is a single embedding call + index query. PageIndex's tree traversal requires at least 2–3 LLM calls (tree navigation + section extraction). Directionally, vector search is faster in wall-clock time for any individual query. But this is not measured — it is inferred from architecture.

3. **No claim can be made about cost.** LLM reasoning calls vs. embedding calls + ANN query have very different cost profiles depending on model choice, query volume, and index size. No comparison is possible without benchmarks.

**The right framing:** vector search is the better fit for our use case because of the *structural match* to our problem, not because of benchmarked performance. PageIndex is a poor fit because its core motivation does not apply to us.

---

### Transferable ideas from PageIndex

Even though the full PageIndex architecture does not apply, the underlying insight — *structure matters for retrieval* — has concrete applications for Arkeology.

#### Idea P1 — Section-level indexing

**Current approach (D12):** one embedding per artifact, generated from configured H2 section content.

**PageIndex-inspired extension:** index each section separately, not just the artifact as a whole. A 1500-word implementation note has a `## Problem`, `## Solution`, `## Trade-offs`, and `## References` section. Each carries different semantic content. A query about "trade-offs of the chosen approach" would match the `## Trade-offs` section directly; the document-level embedding dilutes this signal.

**Mechanics:**
- At write time: extract each configured section and generate one embedding per section
- Each section vector stores the artifact's full metadata + a `section` field indicating which heading it came from
- At search time: query returns section-level results; two results from the same artifact are grouped before returning to the caller
- The caller sees: "found in section `## Trade-offs` of artifact `impl-note/a3f8b2c1.md`"

**Trade-offs:**
| | Pro | Con |
|---|---|---|
| Retrieval precision | Higher — matches at the section that is actually relevant | More vectors per artifact in the index |
| S3 Vectors cost | — | Proportionally more PutVector calls at write time |
| Result presentation | Richer — caller knows which section is relevant | More complex result grouping logic |
| Index size | — | 3–5x more vectors per artifact depending on section count |

**Verdict:** worth evaluating in a Phase 2 retrospective once the core write/search loop is running. Not a V1 requirement — the base document-level embedding already outperforms naive full-text search. Section-level indexing is a precision improvement for later.

---

#### Idea P2 — Multi-level scope narrowing before vector search

**Current approach:** query across `WRITE_PREFIX` and each `READ_PREFIXES` entry with a flat metadata filter.

**PageIndex-inspired extension:** treat metadata filtering as a tree traversal step before vector search — not as a simultaneous filter.

Concretely: a query for "authentication decisions" across a large shared corpus could first narrow by:
1. `type: adr` (tree node: canonical decisions)
2. `features: auth` (tree node: authentication)
3. Only then run vector search within the narrowed set

This is actually already possible with Arkeology's metadata filtering — the question is whether the agent should be instructed to issue narrow queries before broad ones, rather than always issuing a broad semantic query with loose filters.

**Implication for AGENTS.md snippet:** the recommended snippet should include guidance on query strategy: start narrow (type + feature + team), broaden if results are insufficient, not the reverse. This is a skill concern, not a server concern — but PageIndex makes it explicit.

---

#### Idea P3 — Corpus-level index artifact (index.md stored in Arkeology)

**PageIndex insight:** before searching individual documents, an index of the corpus is queried first to identify where to look.

**Arkeology adaptation:** a tier 3 shared artifact of `type: index` that an agent (or the synthesis tool) maintains — a high-level catalogue of what knowledge exists in the store, grouped by theme or domain. This is not the S3 Vectors index (which is the retrieval infrastructure); this is a *semantic map* of the artifact corpus, readable by any connected agent.

**Contents of an index artifact:**
- Thematic clusters: "authentication", "infrastructure", "data model", "security"
- For each cluster: what types of artifacts exist, rough date range, key decisions captured
- Pointers to tier 3 canonical documents per cluster

**Value:** agents starting a new session can read the index artifact first (one artifact read) to orient themselves before issuing semantic queries. This is the low-cost equivalent of PageIndex's tree-root query.

**Maintenance challenge:** who updates the index? Options:
- Agent updates it at session end (write discipline required)
- Synthesis tool regenerates it periodically
- Manual update by the team

**Verdict:** interesting, but fragile without a maintenance mechanism. Becomes viable when the synthesis tool exists (Part 2 below). Low priority for V1.

---

## Part 2 — The synthesis/wiki layer: what would it actually look like?

### The core question

Arkeology stores raw point-in-time artifacts. A Karpathy-style wiki synthesises them. Two agents working on authentication six months apart each write a code review. The code reviews are individually correct, individually useful, individually stored. But:

- If the second agent had access to a *synthesised* understanding of everything known about authentication in this codebase — patterns, decisions, past bugs, past reviews — it would start from a richer baseline than either individual artifact provides.
- That synthesis does not exist today. Nobody maintains it. It accretes implicitly, in human heads, if at all.

The synthesis layer is the answer to: *"What would a new engineer's onboarding document look like, if it were automatically maintained by the agents doing the work?"*

---

### Cluster A — Where does the synthesis live?

| Option | Description | Pro | Con |
|---|---|---|---|
| A1 — Tier 3 artifact in Arkeology | Synthesis pages stored as `type: wiki-page` or `type: synthesis`, overwritten in place (tier 3 semantics) | No new infrastructure; existing `write_artifact` handles it | No git history of synthesis evolution unless explicitly versioned |
| A2 — Separate wiki git repo | Markdown files in a git repo, LLM-maintained, Arkeology artifacts as source | Full git history; human-readable without MCP client | Two systems to maintain; not accessible via MCP without a second server |
| A3 — Both: wiki repo + mirrored tier 3 artifacts | Git repo is source of truth; artifacts are copies written to Arkeology for MCP discoverability | Best of both worlds | Sync complexity; divergence risk |
| A4 — Tier 3 artifacts only, with dedicated `synthesis` type | A new first-class artifact type, visually distinct in listings | Clean; no new infrastructure | Requires schema change if added post-V1 |

**Strongest option: A1 with a dedicated type.** Synthesis pages are tier 3 shared artifacts with `type: synthesis`. They are living documents — overwritten when updated. They participate in semantic search like any other artifact. Agents discover them naturally without any change to the retrieval tools. The only prerequisite: add `synthesis` to the type catalogue now (even if no synthesis tool exists yet) so the schema is ready.

---

### Cluster B — What triggers synthesis?

| Trigger | Description | Pro | Con |
|---|---|---|---|
| B1 — On-demand: agent calls synthesis tool | Explicit agent invocation: "synthesise all artifacts about auth" | Predictable cost; agent controls when | Relies on agent remembering to synthesise; synthesis pages stay stale between invocations |
| B2 — Event-based: after N new artifacts on a topic | After 3 new code reviews tagged `auth` are written, synthesis for `auth` is flagged as stale | Automatic; keeps synthesis current | Requires a staleness tracking mechanism; hard to implement without hooks |
| B3 — Periodic: weekly or monthly | A scheduled job (outside Arkeology) calls the synthesis tool on a cadence | Simple; predictable | Synthesis may be outdated between runs; scheduled job is external infrastructure |
| B4 — Milestone-triggered | At project milestones (sprint end, release), synthesis is run | Aligned with natural review points | Requires milestone detection (hooks, F3.4) |
| B5 — Lint-triggered: synthesis "lint" detects stale pages | A lint tool scans synthesis pages against their source artifacts; flags pages with new sources since last synthesis | Principled; Karpathy's explicit recommendation | Most complex to implement |

**For V1: B1 (on-demand).** The synthesis tool is triggered explicitly by the agent. No staleness tracking, no scheduling, no event hooks required. Teams can call it at natural review moments (end of sprint, before major refactor). More sophisticated triggers are Phase N+1.

---

### Cluster C — What is the synthesis granularity?

| Granularity | Description | Example |
|---|---|---|
| C1 — Per feature/topic | One synthesis page per topic cluster (auth, payments, infrastructure) | `synthesis/auth-architecture.md` |
| C2 — Per type | One synthesis per artifact type — "all code reviews summarised", "all ADRs synthesised" | `synthesis/code-review-patterns.md` |
| C3 — Per team/project | One synthesis per team — "what platform team has decided and documented" | `synthesis/platform-team-knowledge.md` |
| C4 — Temporal: per release or sprint | Synthesis covering a time window | `synthesis/2026-Q1-decisions.md` |
| C5 — Per query: on-demand synthesis of search results | Agent issues a query; instead of returning raw results, the server synthesises them in real time | "Synthesise the 5 most relevant auth artifacts" |

**Most useful: C1 (per topic) for living synthesis pages, C5 (per query) for in-session use.**

C1 produces durable knowledge assets that compound over time — exactly what Karpathy describes. C5 is a lighter-weight capability where the agent issues a search + synthesise call as a single operation, getting a compiled answer rather than a list of artifacts.

---

### Cluster D — What does the synthesis tool look like?

**Option D1 — Standalone `synthesise_artifacts` MCP tool (8th tool)**

```
synthesise_artifacts(
    query: str,              # Topic to synthesise: "authentication architecture"
    artifact_type: str = "", # Optional: focus on one type
    features: list[str] = [],# Optional: restrict to features
    top_k: int = 10,         # How many artifacts to source from
    title: str,              # Title of the synthesis page to produce/update
    write_back: bool = True  # Whether to store the synthesis as a tier 3 artifact
) → synthesis: str           # The synthesis content
```

Steps:
1. `search_artifacts(query, top_k=top_k, filters...)` → ranked artifact metadata + descriptions
2. `read_artifact(id)` for the top N results → full content
3. LLM synthesis prompt: given these artifacts, produce a synthesis page with sections: Summary, Key Decisions, Recurring Patterns, Open Questions, Source Artifacts
4. If `write_back=True`: `write_artifact(content=synthesis, type="synthesis", tier="3", visibility="shared", title=title, ...)`
5. Returns synthesis content

**Trade-offs:**
- The MCP tool approach makes synthesis a first-class server capability, not a skill convention
- The LLM call for synthesis is done by the connected agent (it receives the artifacts and performs the synthesis), not by the server — the server orchestrates, the LLM synthesises
- This is actually how FastMCP works: the tool prepares inputs and the agent (LLM) does the reasoning

**Option D2 — Synthesis as a skill, not a server tool**

An agent skill that:
1. Issues multiple `search_artifacts` and `read_artifact` calls using existing tools
2. Synthesises in-context using the LLM
3. Calls `write_artifact` with the result as a `synthesis` type tier 3 artifact

**Trade-offs:**
- No new server tools required
- The skill is a set of instructions; no server code changes
- Less discoverable by agents without the skill loaded
- The synthesis logic lives in skill instructions, not in the server

**Verdict: D2 for V1.** A skill is enough to unlock the synthesis pattern. The synthesis tool (D1) is a V2 feature that makes synthesis first-class and discoverable via MCP Resources without loading a skill. Adding `synthesis` to the type catalogue from day one ensures the schema is ready for either path.

---

### Cluster E — What does Karpathy's "Lint" look like for Arkeology?

Karpathy's Lint scans the wiki for:
- Pages whose source artifacts have newer versions
- Contradictions between pages
- Orphaned pages (source artifacts were archived but page wasn't updated)
- Pages that reference each other incorrectly

**Arkeology equivalent:**

| Lint check | What it does | How to implement |
|---|---|---|
| Stale synthesis | `synthesis` tier 3 artifact has source artifacts newer than its own `date` field | Compare synthesis `date` against `date` of referenced source artifacts |
| Contradiction flag | Two `synthesis` or `adr` artifacts on the same topic make conflicting claims | Requires LLM reasoning — not a simple metadata check |
| Orphaned synthesis | `synthesis` artifact references source artifacts that are now archived | Check source artifact IDs in synthesis content against archive status |
| Coverage gap | Features with many tier 2 artifacts but no synthesis page | Count tier 2 artifacts per feature; flag features exceeding threshold with no `synthesis` counterpart |

**Implementation path:** most lint checks can be implemented as an extension of the reconciliation tool (FR-17, task 16). The reconciliation tool currently handles structural consistency (S3 vs vector index). A Phase N+1 extension adds knowledge quality checks. The two concerns are distinct and should be separate operations — do not conflate them in V1.

---

### Cluster F — What changes in Arkeology today to enable synthesis later?

Very little. The synthesis pattern builds on the existing architecture. The only schema change needed:

| Change | Why | When |
|---|---|---|
| Add `synthesis` to the type catalogue | Agents and synthesis skill need a canonical type name; avoids schema drift if different teams use different names | Before V1 ships (type catalogue is in MCP Resources and AGENTS.md snippet) |
| Add `source_artifacts` as an optional metadata field | A synthesis page should carry the IDs of the artifacts it was built from — enables staleness checking and lint | Optional in V1 schema; not filterable; stored as non-filterable metadata (uses one of the 10 non-filterable key slots) |

**Caution on `source_artifacts`:** S3 Vectors allows 10 non-filterable keys per index. We are already using 1 (`description`). Adding `source_artifacts` as a second non-filterable key uses another slot. A list of artifact IDs can be long — care needed to stay within the 40 KB total metadata limit.

---

### What the synthesis experience looks like for an agent

**Without synthesis (today's model):**

> Agent: "Search for anything about authentication"
> arkeology: returns 7 artifacts — 3 code reviews from different dates, 1 ADR, 1 implementation note, 1 session summary, 1 spec
> Agent: reads each one, forms its own understanding from 7 separate documents

**With synthesis (future model):**

> Agent: "Search for anything about authentication"
> arkeology: returns the same 7 artifacts PLUS 1 synthesis page: "Authentication Architecture — Synthesised 2026-04-01 from 7 sources"
> Agent: reads the synthesis first (ranked highest by relevance and tier), then reads individual artifacts only if it needs specifics
> Synthesis page includes: summary of all decisions made, recurring patterns, open questions, list of source artifacts

The synthesis page doesn't replace the individual artifacts — it accelerates understanding. The agent loads one page instead of seven to get the compiled view, then digs into specifics as needed.

---

### Summary: what is decided and what remains open

### Locked ✅

| Decision | Locked as | Detail |
|---|---|---|
| Vector search is the right choice — PageIndex solves a problem we don't have (vector similarity failing on long unstructured docs) | Informational | Section-level indexing addresses the structure concern directly |
| **Section-level indexing replaces EMBEDDING_SECTIONS**: every `##` section indexed as an independent vector; fallback (no sections) = one document-level vector from title+description+type+features | D12 | requirements.md: FR-01; plan: task 7 |
| Section vector key: `{artifact_key}#{section_name_slug}`; `artifact_id` in filterable metadata links section vectors to S3 object; section keys are internal, never exposed to callers | D12 | Plan: task 7 integration test checkpoints |
| `EMBEDDING_SECTIONS` env var eliminated — zero configuration needed | D12 | requirements.md: Constraints table, Scope; plan: task 4 |
| Write cost: N Bedrock calls per write (one per section) — known trade-off, negligible at Titan Text Embeddings v2 pricing | D12 | requirements.md: FR-01 |
| Re-fetch loop with exclusion filter: `artifact_id NOT IN seen_ids` on each iteration; fixed `SEARCH_FETCH_TOP_K` per call; bounded by `SEARCH_MAX_ITERATIONS` | D12 | requirements.md: FR-03; plan: task 8 |
| Three new server config params: `SEARCH_FETCH_TOP_K` (default 25), `SEARCH_MAX_ITERATIONS` (default 3), `SEARCH_DEFAULT_TOP_K` (default 5) | D12 | requirements.md: Constraints table; plan: task 4 |
| Synthesis lives as tier 3 artifacts with `type: synthesis` — no new infrastructure | D15 | requirements.md: FR-19, FR-20 |
| `synthesise_artifacts` is a V1 MCP tool (8th tool); server retrieves and assembles source content; agent synthesises | D16 | requirements.md: FR-19 |
| Synthesis granularity is unconstrained — both topic-based and type-based queries are valid | D17 | No server enforcement |
| Synthesis lint / freshness check is a V1 Could-have (FR-20); metadata-only, no LLM call | D18 | requirements.md: FR-20 |
| `synthesis` added to type catalogue before V1 ships | D15 | requirements.md: FR-09, D6 |
| `source_artifacts` as second non-filterable metadata field (declared at index creation) | D15/D16 | requirements.md: FR-09, Constraints table; D6 updated |
| P3 (corpus-level index artifact) superseded by `list_artifacts` + metadata — no standalone index needed | Closed | Metadata already is the index |
| Synthesis trigger: on-demand (B1) for V1; guidance in AGENTS.md snippet | D16 | NFR-12 updated |
| Query strategy guidance (start narrow, broaden if insufficient): in MCP Resources (FR-18) and AGENTS.md snippet (NFR-12) | P2 | requirements.md updated |

### Open (integration test checkpoints — not design questions)

| Question | Task | Fallback if unsupported |
|---|---|---|
| `#` valid in S3 Vectors vector keys? | Task 7 | Use `--` separator — no design change |
| `PutVector` is upsert on existing key? | Task 7 | Explicit delete-before-write on re-write |
| S3 Vectors `$nin` operator supported on `artifact_id`? | Task 8 | Fall back to over-fetching with scaling `top_k` per iteration |

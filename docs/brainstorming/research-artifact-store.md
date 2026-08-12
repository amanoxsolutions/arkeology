---
type: brainstorming
title: Research — Artifact Store (Arkeology)
description: Research notes compiled 2026-05-26 covering how the industry handles cross-session, cross-engineer agent memory and scratchpad sharing, synthesizing 13 primary and 2 secondary sources evaluated against the tier 2 artifact gap and tier 3 project documentation.
tags: []
timestamp: 2026-05-26T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-26"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Research — Artifact Store (Arkeology)

## Description

Research notes compiled 2026-05-26 for artifact store brainstorming; extended 2026-05-29 with two additional sources reviewed after the PRD was complete. Covers how the industry handles cross-session, cross-engineer agent memory and scratchpad sharing. Synthesizes 13 primary sources and 2 secondary sources. Evaluated against tier 2 (artifacts: sharing and indexing) and tier 3 (project documentation: SCRATCHPAD.md, PRD, ADRs) separately.

---

## Problem Summary

**The three-tier document lifecycle** is the correct model. The original four-tier proposal incorrectly separated "working notes" (SCRATCHPAD.md) into its own tier. SCRATCHPAD.md is a committed project document with a high-churn discipline — that is a content rule, not a structural tier. It belongs in tier 3 alongside PRD and ADRs.

| Tier | Name | Examples | Committed | Currently in framework? |
|------|------|----------|-----------|------------------------|
| 1 | Ephemeral | Scratch notes, dead-ends | No (gitignored) | Yes |
| 2 | **Artifacts** | Issue records, code review logs, implementation notes | **No (gitignored)** | **No — this is the gap** |
| 3 | Project documentation | PRD, ADRs, requirements, planning artifacts, SCRATCHPAD.md | Yes | Partially |

**The core problem is tier 2:** artifacts are gitignored, unindexed, and invisible across sessions and engineers. A developer agent producing `issues/YYYY-MM-DD-bug-fix.md` today creates knowledge that is unreachable to any future agent on the same project.

**SCRATCHPAD.md** is part of tier 3 — a committed project document with a high-churn, current-state discipline. Its conventions (≤100 lines, cleanup at milestones) are content rules for this specific document type, not a tier-defining property.

**The tier 2 solution is not yet locked.** Constraints: tool-agnostic, markdown-only, portable across VCS platforms, usable solo on day one. Candidates: naming convention, committed index file, agent-maintained summary, or a combination. A dedicated MCP server (`amanox-artifact-store-mcp`) has been identified as the long-term infrastructure answer — see `brainstorming-artifact-store.md`.

---

## Source Tracking

### Source 1 — Streamlit: The Repo Is the Harness
- **URL:** https://blog.streamlit.io/the-repo-is-the-harness-how-we-made-an-8-year-old-codebase-agent-native-75629a953354
- **Author:** Lukas Masuch, Streamlit
- **Date:** April 2026
- **Summary:** Streamlit's playbook for making an 8-year-old codebase agent-native. Describes a layered system: simplify the code for agents, add guardrails (linting, hooks), move context into the repo (AGENTS.md files, architecture docs, specs), package recurring work as skills/subagents, layer AI review, and automate. On scratchpad sharing: they repurposed the GitHub wiki git repo as a shared artifact store organized by PR number. Agents push documents there; reviewers see the full context; agents building new changes access prior implementation plans.
- **Key quote:** *"It is a hack, honestly. But it works surprisingly well as a lightweight, version-controlled scratch space that lives right next to the main repo."*
- **Useful for tier 2 (artifacts):**
  - The core concept: artifacts scoped by feature/PR and stored in a version-controlled location next to the main repo — agents working on new changes access prior implementation plans cross-session. This is exactly the problem tier 2 solves.
  - "Every PR review is a context audit. Repeated feedback is often just missing repository knowledge in disguise." — strong framing for why artifact sharing matters.
  - Artifact scoping by work unit (PR/feature/issue) rather than flat structure — prevents a single accumulation pile.
- **Useful for tier 3 (working notes):**
  - Spec-driven development: a well-written spec committed to the repo gives agents enough context for implementation. The spec is a form of committed working note, more structured than SCRATCHPAD.md but in the same tier.
- **Not useful:**
  - GitHub wiki as the storage mechanism — GitHub-specific, not portable across VCS platforms.

---

### Source 2 — Agentic Design Patterns: Shared Scratchpad Collaboration (SSC)
- **URL:** https://agentic-design.ai/patterns/multi-agent/shared-scratchpad-collaboration
- **Summary:** Describes SSC as a multi-agent pattern: multiple agents collaborate on a common workspace with shared visibility. Key design principles: clear schema, real-time visibility, version control, conflict resolution, audit trails, access control.
- **Useful for tier 2 (artifacts):**
  - "Maintain clear audit trails of all contributions" — artifacts are append-only historical records; this validates the pattern of never editing past artifact files.
  - "Version control and conflict resolution mechanisms" — git handles both for committed artifact files.
- **Useful for tier 3 (working notes):**
  - "Clear shared state schema with structured sections" — strong argument for defined sections in SCRATCHPAD.md rather than free-form.
- **Not useful:**
  - Real-time synchronization and concurrent orchestration — adds concurrency and conflict-resolution mechanics out of scope for the artifact store V1 solution.
  - Referenced academic links (arxiv 2404.12345, 2405.15789) appear to be placeholder/fabricated IDs — treat with skepticism.
  - Implementation framework links (LangGraph, CrewAI, AutoGen) — code-based orchestration systems, not relevant to our markdown-convention approach.

---

### Source 3 — arXiv 2508.11126: AI Agentic Programming — A Survey
- **URL:** https://arxiv.org/html/2508.11126v1
- **Authors:** Wang, Gong, Zhang, Wang — University of Leeds
- **Summary:** Comprehensive survey of AI agentic programming. Table 3 compares context management across agents: GitHub Copilot (no persistent memory, sliding window), Cursor (persistent memory, semantic search), SWE-agent (vector DB), Devika (SQLite + embeddings), OpenDevin (RAG over history). Section 5.5 identifies "scalable memory" as a key challenge. Section 6.2 outlines the opportunity: hierarchical memory models, memory summarization, context-aware retrieval, persistent cross-session memory.
- **Key quote:** *"Without hierarchical and queryable memory systems, agents risk repeating errors, forgetting past successes, or producing inconsistent results."*
- **Useful for tier 2 (artifacts):**
  - Cross-session persistent memory explicitly identified as a key challenge and opportunity — validates the tier 2 problem statement.
  - Table 3: agents with persistent memory (Cursor, SWE-agent) consistently outperform those without — persistent memory correlates with output quality.
  - Memory summarization as a technique for making accumulated knowledge navigable without reading everything — directly relevant to the indexing problem.
- **Useful for tier 3 (working notes):**
  - The hierarchical memory framing (short-term / mid-term / long-term) maps directly to our 4-tier model and validates separating working notes from permanent knowledge.
  - Memory summarization — condensing multi-turn sessions into structured representations — is what SCRATCHPAD.md cleanup does: compact, promote, discard noise.
- **Not useful:**
  - Vector DB, embedding-based retrieval, SQLite — not tool-agnostic.
  - Structure-guided attention (syntax trees, control flow graphs) — model architecture concern, not relevant.
  - Fine-tuning / RL approaches — same.

---

### Source 4 — Russ Poldrack (Substack): Workflows for Agentic Coding
- **URL:** https://russpoldrack.substack.com/p/workflows-for-agentic-coding-and
- **Author:** Russ Poldrack, neuroscientist/programmer
- **Date:** September 2025
- **Summary:** Practical agentic coding workflow. Files used: PRD.md, CLAUDE.md/AGENTS.md, PLANNING.md, TASKS.md, SCRATCHPAD.md. Workflow: read all files at session start, code until 50% context usage, update TASKS.md + SCRATCHPAD.md and commit, clear context, repeat. SCRATCHPAD.md is "a place for the model to keep notes on ongoing development work; when work is completed, clean it out from this file."
- **Key quote:** *"When the work is completed, clean it out from this file, so that the contents only reflect ongoing work."*
- **Useful for tier 2 (artifacts):**
  - Nothing directly. Poldrack's workflow is about within-session continuity and checkpoint-based compaction, not about accumulating and sharing structured artifact files.
- **Useful for tier 3 (working notes):**
  - SCRATCHPAD.md in the main repo (committed) — the most directly applicable real-world precedent.
  - The cleanup rule: scratchpad reflects current state only, never history. Completed items are removed.
  - The underlying process (compact + commit at checkpoints) is portable even if the slash commands (`/freshstart`, `/summ+commit`) are Claude Code-specific.
  - Context monitoring and proactive compaction at milestones.
- **Not useful:**
  - The slash commands themselves — Claude Code-specific, not portable.
  - Specific file locations (PRD.md at root) — our project uses a different structure.

---

### Source 5 — Fast Company: Why Shared Memory Is Agentic AI's Biggest Consumer Moment
- **URL:** https://www.fastcompany.com/91472483/why-shared-memory-is-agentic-ais-biggest-consumer-moment
- **Author:** Zander Cook, Lease End
- **Date:** January 2026
- **Summary:** Consumer-oriented piece arguing that shared memory — a synchronized context layer that doesn't reset between sessions or agents — is the key enabler for genuinely useful agentic AI.
- **Key quote:** *"Most AI-powered consumer experiences today are competent, even impressive, but fundamentally short-lived. Each interaction is a small island."*
- **Useful for tier 2 (artifacts):**
  - Validates the pain point: agents restart from zero each session, missing historical context built up in prior work. Useful for explaining the problem to stakeholders.
  - "Agentic AI magnifies this issue — if agents can't share memory, you get fragmentation at scale" — directly describes the tier 2 problem.
- **Useful for tier 3 (working notes):**
  - Nothing specific. The consumer UX framing does not translate to engineering workflow conventions.
- **Not useful:**
  - Consumer product framing, "AI Constellation" product, multi-agent handoff scenarios — not relevant to our engineering workflow context.

---

### Source 6 — Adnan Masood (Medium): Engineering Trustworthy LM Agents with Scratchpads and Verifiers
- **URL:** https://medium.com/@adnanmasood/engineering-trustworthy-lm-agents-with-scratchpads-and-verifiers-5c1084533be7
- **Note:** Member-only content — tl;dr only accessible.
- **Summary (from tl;dr):** Scratchpads as intermediate workspaces improve accuracy, auditability, and governance. Taxonomy axes: purpose, visibility, structure, time horizon, governance/logging.
- **Useful for tier 2 (artifacts):**
  - The **time horizon** axis: long-horizon scratchpad (across sessions) is explicitly distinguished from short-horizon (within a turn) and mid-horizon (within a session). Tier 2 artifacts are the long-horizon case.
  - Governance/logging — for teams, artifacts record who produced what and when; this supports the case for committing them.
- **Useful for tier 3 (working notes):**
  - Structured scratchpad schemas improve auditability and agent readability — supports defined sections in SCRATCHPAD.md.
- **Not useful:**
  - Full technical content inaccessible due to paywall — cannot validate beyond tl;dr.
  - Verifier pattern — more relevant to in-model reasoning correctness than file-based sharing.

---

### Secondary Source A — htdocs.dev: Claude Code Best Practices and Pro Tips
- **URL:** https://htdocs.dev/posts/claude-code-best-practices-and-pro-tips/
- **Author:** Stephane Busso
- **Date:** June 2025
- **Relevant section (tip #43):** *"Use scratch pads to plan work — Tell Claude to use a scratchpad file (e.g., SCRATCHPAD.md) to outline its plan, list files it will modify, or jot down thoughts before making changes."*
- **Useful for tier 2 (artifacts):**
  - Nothing. This source is entirely focused on within-session scratchpad usage, not on accumulating and sharing artifact files across sessions.
- **Useful for tier 3 (working notes):**
  - Confirms SCRATCHPAD.md as a recognized community convention.
  - Plan-before-act discipline: agent writes its plan to SCRATCHPAD.md before making changes — a workflow pattern worth encoding in the skill.
  - Proactive compaction at checkpoints (`/compact` vs `/clear`) — maps to the "clean at milestones" principle.
- **Not useful:**
  - Most tips are Claude Code-specific (slash commands, Puppeteer MCP, etc.).

---

### Secondary Source B — agents.md
- **URL:** https://agents.md/
- **Summary:** Open format for AGENTS.md, stewarded by the Agentic AI Foundation under Linux Foundation. Supported by 20+ tools. Monorepo support: nested AGENTS.md files per component, closest one takes precedence.
- **Useful for tier 2 (artifacts):**
  - Nothing directly. AGENTS.md is the permanent-knowledge layer; this source does not address artifact accumulation.
- **Useful for tier 3 (working notes):**
  - The proximity principle ("closest AGENTS.md wins") applies to SCRATCHPAD.md placement in monorepos — place it next to the AGENTS.md it supplements.
  - Confirms the gap: AGENTS.md is for "what to know always"; there is no equivalent standard for "what is actively in progress." That gap is tier 3.
- **Not useful:**
  - Nothing else specific to the artifact store.

---

### Source 7 — arXiv 2310.08560: MemGPT — Towards LLMs as Operating Systems
- **URL:** https://arxiv.org/abs/2310.08560
- **Authors:** Packer, Wooders, Lin, Fang, Patil, Stoica, Gonzalez — UC Berkeley
- **Date:** October 2023 (v2 February 2024)
- **Summary:** Proposes virtual context management for LLMs, drawing directly from OS hierarchical memory design. MemGPT manages three tiers: (1) in-context memory (the LLM's active context window — fast, limited), (2) external storage (disk-like persistent store — slower, unlimited), and (3) archival storage (cold store for long-term retention). The agent explicitly moves content between tiers using OS-like system calls (`send_to_archival`, `retrieve_from_archival`). Control flow uses interrupts: the LLM pauses, decides what to promote or evict, then resumes. Evaluated on two tasks: document analysis (files exceeding context window) and multi-session chat (agents that remember and evolve across sessions).
- **Key quote:** *"Just as virtual memory in operating systems creates the illusion of unlimited RAM by moving data between fast and slow storage, MemGPT creates the illusion of an unlimited context window by intelligently managing what information is active."*
- **Useful for tier 2 (artifacts):**
  - MemGPT's archival tier is the direct academic analogue of our tier 2. It is persistent, named, cross-session, and explicitly managed by the agent — not implicit in the context window. The core design insight: the agent must *actively decide* to persist information to the archival tier; it does not happen automatically. In our model this maps to: skills must explicitly instruct agents to write artifact files at the right moment (end of session, end of feature, at milestone).
  - The `retrieve_from_archival` pattern is the academic form of D4's open question: agents do not read all artifacts blindly — they issue targeted retrieval calls. For a markdown-based system this means either a committed index (to know what exists before retrieving) or a strong naming convention (to construct retrieval paths directly).
- **Useful for tier 3 (working notes):**
  - MemGPT's "in-context" tier (active scratch space) maps to our tier 1 (`.docs/` ephemeral notes). The "external storage" tier (fast but not in-context) maps to our tier 2 (artifacts — committed or MCP store). The tier 3 management discipline (compact at milestone, promote permanent decisions to tier 3 project docs) mirrors MemGPT's eviction and promotion protocol.
- **Not useful:**
  - The system-call interface and interrupt mechanism — these are implementation details for a software system. Our approach is convention-based, not programmatic.
  - Multi-session chat domain — the evaluation is on conversational agents, not coding workflow agents, so the benchmark results are not directly comparable.

---

### Source 8 — arXiv 2303.11366: Reflexion — Language Agents with Verbal Reinforcement Learning
- **URL:** https://arxiv.org/abs/2303.11366
- **Authors:** Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao
- **Date:** March 2023 (v4 October 2023)
- **Summary:** Proposes Reflexion: agents improve not by gradient updates but by generating verbal reflections on failures and storing them in an *episodic memory buffer*. After each trial, the agent writes a textual reflection summarising what went wrong and what to do differently. On the next trial, past reflections are prepended to the context. Evaluated on sequential decision-making, coding (HumanEval), and language reasoning — achieves 91% pass@1 on HumanEval vs. GPT-4's 80%. Ablations show that the episodic memory buffer (persistent cross-trial storage) is the dominant contributor to the improvement; without it, verbal reflection alone provides only marginal gains.
- **Key quote:** *"Reflexion agents verbally reflect on task feedback signals, then maintain their own reflective text in an episodic memory buffer to induce better decision-making in subsequent trials."*
- **Useful for tier 2 (artifacts):**
  - The episodic memory buffer is a direct instantiation of tier 2. It is: (a) plain text, (b) written by the agent, (c) persistent across sessions/trials, (d) read at the start of the next session, (e) append-only (prior reflections are not edited). This is the strongest academic precedent for our tier 2 model.
  - The ablation result — persistent buffer is the key contributor — is strong empirical evidence that *where* past knowledge is stored matters. Keeping reflections only in-context (tier 1) produces little benefit; committing them to a persistent store (tier 2) produces the full gain.
  - The append-only pattern validates the rule we identified from agentic-design.ai SSC: artifacts (reflections) are never edited; new knowledge is appended as a new entry.
- **Useful for tier 3 (working notes):**
  - Less direct. Within a single trial the agent uses a working scratchpad (chain-of-thought), but the Reflexion paper does not explicitly address the tier 3 (current-state working notes) problem.
- **Not useful:**
  - The verbal reinforcement framing — improving model behaviour via textual feedback — is not directly applicable to our workflow convention design.
  - The coding benchmark context (self-contained HumanEval functions) is far simpler than multi-session project work.

---

### Source 9 — arXiv 2308.00352: MetaGPT — Meta Programming for a Multi-Agent Collaborative Framework
- **URL:** https://arxiv.org/abs/2308.00352
- **Authors:** Hong, Zhuge, Chen, et al. (incl. Schmidhuber)
- **Date:** August 2023 (v7 November 2024)
- **Summary:** MetaGPT encodes Standardized Operating Procedures (SOPs) into multi-agent LLM workflows, simulating a software development team. Roles: Product Manager (writes PRD), Architect (writes system design), Engineer (writes code), QA (writes tests). Each role produces a structured artifact that the next role consumes. A *shared message pool* is the communication substrate: agents publish artifacts to the pool; other agents subscribe to relevant content. The SOP encoding reduces hallucination cascades by enforcing structured intermediate outputs before the next agent acts.
- **Key quote:** *"By obligating each agent to produce role-specific structured outputs before downstream agents proceed, MetaGPT prevents cascading hallucinations caused by naively chaining raw LLM responses."*
- **Useful for tier 2 (artifacts):**
  - MetaGPT's artifact pipeline (PRD → design → code → test) is the multi-agent analogue of our tier 2. Each artifact is: named by role and task, structured (defined sections), consumed by the next agent, and persisted in the shared message pool. This directly supports the naming-convention option for D4: artifacts named by producing role and work unit (`pm-prd-feature-auth.md`, `engineer-impl-notes-auth.md`) are self-describing and discoverable without an index.
  - The shared message pool concept maps to the committed repo as our shared pool. All agents (sessions) can read all artifacts; the naming convention is the subscription/query mechanism.
  - The SOP encoding principle — structured intermediate outputs enforced by convention — validates encoding artifact format requirements in skill instructions rather than tooling.
- **Useful for tier 3 (working notes):**
  - Less direct. MetaGPT agents do not maintain a per-session current-state working notes file; each role's artifact IS the handoff document. This suggests a potential design insight: if tier 2 artifacts are sufficiently structured, tier 3 (SCRATCHPAD.md) becomes less necessary between roles — but it remains useful for within-role continuity.
- **Not useful:**
  - The multi-agent orchestration infrastructure (role assignment, message routing, subscription mechanism) — MetaGPT implements these programmatically; our approach is convention-based.
  - The specific artifact formats MetaGPT uses (Python class diagrams, etc.) — implementation-specific.

---

### Source 10 — arXiv 2307.03172: Lost in the Middle — How Language Models Use Long Contexts
- **URL:** https://arxiv.org/abs/2307.03172
- **Authors:** Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni, Liang — Stanford / Meta AI
- **Date:** July 2023 (v3 November 2023), published in TACL
- **Summary:** Empirical study of how LLMs actually use long input contexts. Evaluates two tasks (multi-document QA, key-value retrieval) while varying the position of relevant information across the context. Key finding: performance is highest when relevant information appears at the beginning or end of the context, and degrades significantly when it appears in the middle — even for models explicitly trained on long contexts. The "lost in the middle" degradation is consistent across model families and context lengths.
- **Key quote:** *"Performance can degrade significantly when changing the position of relevant information… performance is often highest when relevant information occurs at the beginning or end of the input context, and significantly degrades when models must access relevant information in the middle of long contexts."*
- **Useful for tier 2 (artifacts):**
  - This is the empirical foundation for why we cannot rely on "just provide a large context window" as an alternative to structured artifact storage. Even with 128K+ context, an agent that loads all past artifacts into a single context will lose information buried in the middle. Selective retrieval (via naming convention or index) is not just a performance optimisation — it is necessary for correctness.
  - This finding directly informs D4: the tier 2 solution must enable *targeted* retrieval of specific artifacts (not bulk loading), so that what is loaded appears at the beginning or end of context where it will be used reliably.
- **Useful for tier 3 (working notes):**
  - Validates the ≤100 line size target for SCRATCHPAD.md (D4). A compact working notes file that fits in the first few hundred tokens of context will reliably be used by the agent. A long SCRATCHPAD.md risks having the middle sections ignored.
  - Supports the "current state only" cleanup discipline (D3): keeping SCRATCHPAD.md to the currently relevant content ensures it stays at the start of context, not buried.
- **Not useful:**
  - The specific evaluation tasks (QA benchmarks) are not directly comparable to coding workflow scenarios.
  - Model-specific degradation curves — not actionable for our convention design.

---

### Source 11 — arXiv 2409.05591: MemoRAG — Boosting Long Context Processing with Global Memory-Enhanced RAG
- **URL:** https://arxiv.org/abs/2409.05591
- **Authors:** Qian, Liu, Zhang, Mao, Lian, Dou, Huang
- **Date:** September 2024 (v3 April 2025), published at TheWebConf 2025
- **Summary:** Proposes MemoRAG, a dual-system RAG framework for long-context processing. System 1 (light, long-range): reads the full corpus and compresses it into a *global memory* (KV-compressed representation). When a query arrives, System 1 generates draft "clue" answers pointing to relevant locations. System 2 (expensive, expressive): retrieves the pointed-to content and generates the final answer. The global memory is trained with RLGF (Reinforcement Learning from Generation quality Feedback) to improve its clue generation over time. Outperforms standard RAG on both complex tasks (no explicit query anchor) and simple tasks (standard RAG conditions).
- **Key quote:** *"Conventional RAG requires explicitly stated queries and well-structured knowledge — conditions that do not hold in general long-context processing tasks. MemoRAG's global memory generates clues that guide retrieval even when the query is implicit or the knowledge is diffuse."*
- **Useful for tier 2 (artifacts):**
  - MemoRAG's global memory is the academic analogue of a committed index file for tier 2. The key insight: you do not retrieve from the artifact corpus directly — you first query the global memory (index) to get clues (locations), then retrieve the specific artifact. This is the strongest argument for a *committed index* as the D4 solution: an index file that agents query first to locate relevant artifacts, rather than either bulk-loading all artifacts or guessing artifact paths from a naming convention.
  - The "implicit query" problem MemoRAG solves is exactly the tier 2 problem: agents starting a new session often do not know what specific prior artifact they need — they know the topic or feature. A committed index that describes artifacts by topic/feature enables this implicit retrieval without a vector store.
  - MemoRAG's two-system split maps naturally: a committed `artifacts/index.md` (System 1 analogue, cheap to read) + the actual artifact files (System 2 analogue, read on demand).
- **Useful for tier 3 (working notes):**
  - Less direct. SCRATCHPAD.md is already small enough to be loaded in full; MemoRAG's architecture is designed for cases where the corpus is too large to load.
- **Not useful:**
  - The KV compression and RLGF training — these are model-level mechanisms. Our index is a manually maintained (or agent-maintained) markdown file, not a trained memory model.
  - The RAG retrieval pipeline itself — we are not building retrieval infrastructure.

---

### Source 12 — VectifyAI: PageIndex
- **URL:** https://github.com/VectifyAI/PageIndex
- **Author:** VectifyAI
- **Date:** 2025
- **Summary:** PageIndex is a vectorless, reasoning-based RAG system for long, complex, unstructured documents (financial filings, legal manuals, academic textbooks). Instead of chunking documents and embedding chunks, it builds a hierarchical tree index (table of contents) per document by analysing heading structure and summary content. Queries are answered by using an LLM to reason over this tree to identify relevant sections, then fetching only those sections for the final answer. Core claim: *similarity ≠ relevance* — for documents where meaning requires multi-step reasoning across structure, vector similarity search systematically misses.
- **Key insight:** Document structure matters for retrieval. For long documents where meaning is spread across sections that are individually weak signals, indexing by structure and reasoning over it outperforms pure vector similarity.
- **Useful for tier 2 (artifacts):**
  - Validates the EMBEDDING_SECTIONS decision (D12): structured artifacts with explicit H2 sections should not be embedded as a flat bag-of-words — section identity carries meaning and should be preserved in the retrieval signal.
  - Raises the idea of **section-level indexing**: rather than one embedding per artifact (our current approach), index each section separately, allowing queries to match at the section level and return "section X in artifact Y is relevant" rather than just "artifact Y is relevant". This is a richer retrieval signal, especially for long artifacts with heterogeneous sections.
  - Raises the idea of a **multi-level index** over the artifact corpus: a tree where the top level groups artifacts by type/team/project, and a leaf level groups by individual sections. Queries traverse the tree to narrow scope before issuing a vector similarity query on the narrowed set.
- **Useful for tier 3 (working notes):**
  - Nothing directly.
- **Not useful:**
  - The core PageIndex architecture (per-document tree index + LLM tree traversal at query time) is designed for documents where vector similarity fails — long, unstructured, reasoning-intensive content. Arkeology artifacts are short, structured, and agent-authored with explicit templates. The architecture is not directly applicable.
  - No performance benchmark data comparing tree-based reasoning to vector search on structured markdown artifacts — any claim about relative latency or cost would be architectural reasoning, not empirical evidence.

---

### Source 13 — Andrej Karpathy: llm-wiki
- **URL:** https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- **Author:** Andrej Karpathy
- **Date:** May 2025
- **Summary:** Describes a pattern for LLM-maintained persistent knowledge bases. Instead of RAG (re-deriving knowledge from raw sources at query time), an LLM incrementally builds and maintains a structured wiki: one markdown page per concept, cross-referenced, updated in place when new sources arrive. Three layers: (1) raw sources — immutable inputs (files, web pages, code, PDFs); (2) wiki — the LLM-maintained synthesis, one page per concept; (3) schema — AGENTS.md / CLAUDE.md with instructions for the LLM wiki maintainer. Operations: Ingest (read new sources and update affected pages), Query (answer questions using the wiki, not the raw sources), Lint (check for contradictions, stale claims, orphaned pages). At moderate scale (~100 sources, hundreds of pages), index.md + LLM reasoning is sufficient; larger scale calls for hybrid BM25/vector search tools.
- **Key quote:** *"The tedious part of maintaining a knowledge base is not the reading or the thinking — it's the bookkeeping. LLMs don't get bored."*
- **Key insight:** There is a qualitative difference between *storing* knowledge (Arkeology's current model) and *synthesising* it. Retrieval from a synthesised wiki returns compiled understanding; retrieval from a raw artifact store returns point-in-time records. Both have value at different abstraction levels.
- **Useful for tier 2 (artifacts):**
  - Raw artifact store (tier 2) maps directly to Karpathy's "raw sources" layer — immutable, point-in-time records. This validates Arkeology's append-only tier 2 model.
  - The wiki layer is a natural future layer above arkeology: LLM-maintained synthesis pages stored as tier 3 shared artifacts, using Arkeology's existing `write_artifact` (overwrite semantics) for tier 3 updates.
  - Raises the idea of a **synthesis tool** in arkeology: a new MCP tool that searches for artifacts on a topic, generates a synthesis page using the LLM, and writes it back as a tier 3 artifact — implementing Karpathy's Ingest operation directly as an MCP tool call.
  - Karpathy's "Lint" operation — scan the wiki for contradictions, stale claims, pages whose source artifacts have been superseded — is a more sophisticated version of the reconciliation tool (FR-17, task 16). Raises the question of whether reconciliation should extend beyond index repair to knowledge quality checks.
- **Useful for tier 3 (working notes):**
  - AGENTS.md as the schema layer (Karpathy's third layer) is exactly D13 — independently arrived at by two sources. Strong validation.
  - The "current state only" discipline for the wiki (Karpathy's pages reflect latest understanding, not historical accretion) mirrors the SCRATCHPAD.md cleanup rule: current state, not history.
- **Not useful:**
  - The local-file wiki model (markdown in a git repo, no backend) is designed for individuals or small teams on a single project. Arkeology is designed for teams, cross-project, cross-team — the shared AWS backend and semantic search at scale are requirements that the local wiki model does not address.
  - No benchmark comparison of wiki-based retrieval vs vector search at team scale.

---

> Revised to reflect the 4-tier model. Original D1–D9 were based on the incorrect 3-tier framing.

| # | Decision | Tier | Reasoning |
|---|---------|------|-----------|
| D1 | **Three-tier lifecycle** (ephemeral / artifacts / project documentation) | Both | Correct model after session discussion; four-tier was wrong because it elevated SCRATCHPAD.md's content discipline into a structural tier |
| D2 | **`SCRATCHPAD.md` as tier 3** — committed, in repo root, read at session start | Tier 3 | Poldrack, htdocs.dev all converge on this pattern; works with any tool; enforcement via rule in AGENTS.md added by `bootstrapping-repo-for-ai` at bootstrap |
| D3 | **Cleanup discipline** — SCRATCHPAD.md reflects current state only; completed items move to permanent docs or are discarded | Tier 3 | Poldrack's cleanup rule; keeps working notes signal-to-noise high |
| D4 | **SCRATCHPAD.md size target: ≤ 100 lines** | Tier 3 | Prevents SCRATCHPAD.md from becoming an unnavigable accumulation |
| D5 | **Structured sections in SCRATCHPAD.md** rather than free-form | Tier 3 | agentic-design.ai SSC pattern; improves agent readability and reliability |
| D6 | **Monorepo placement** — SCRATCHPAD.md at each component that warrants it, mirroring AGENTS.md proximity principle | Tier 3 | agents.md proximity rule |
| D7 | **Tier 2 artifacts are inputs for `resolving-drift`** — the artifact solution must account for `resolving-drift` readability from the start | Tier 2 | Tier 2 artifacts are ground-truth records of past work; `resolving-drift` reads them to detect contradictions with committed docs |
| D8 | **Tier 2 solution not yet locked** — candidates: naming convention, committed index, agent-maintained summary, or combination | Tier 2 | Core problem remains open; requires further brainstorming |

---

## Open Questions

1. **Tier 2 solution**: Naming convention, committed index file, agent-maintained summary, or a combination? The Streamlit scoped-by-work-unit pattern (items organised by PR/feature/issue) is the most promising structural idea but needs a tool-agnostic form.
   - *New evidence from Sources 7–11:* MemGPT supports targeted retrieval over named archival files (favours naming convention or index). Reflexion supports append-only flat logs (favours naming convention). MetaGPT supports role+task named artifacts in a shared pool (favours naming convention). MemoRAG most strongly supports a **committed index** as the primary retrieval layer (agents query the index first, then fetch specific artifacts). Lost in the Middle reinforces that bulk-loading all artifacts is unreliable — targeted retrieval is necessary regardless of mechanism.
2. **Tier 2 committed vs. gitignored**: Should artifacts be committed (solves sharing, adds repo noise) or remain gitignored with a committed index (solves discoverability on one machine but not cross-engineer sharing)?
   - *New evidence:* Reflexion's episodic memory buffer is committed (cross-trial persistence is its key benefit). MetaGPT's shared message pool is persistent and shared across agents. Both support committing artifacts.
3. **SCRATCHPAD.md canonical sections**: Proposal: `## Current Focus`, `## Active Decisions`, `## Blockers`, `## Next Steps`. Minimal; does not need to expand.

## Tier 2 Requirements

Seven requirements for a complete tier 2 solution. R1–R3 are infrastructure/storage decisions; R4–R7 are skill-convention decisions (no infrastructure needed — they are instructions baked into skills).

| # | Requirement | Category |
|---|---|---|
| R1 | Storage location — where artifacts live | Infrastructure or repo convention |
| R2 | Naming convention — how artifacts are named and organised | Convention (skill instruction) |
| R3 | Index / retrieval — how agents find and load relevant artifacts | Convention (committed index) or Infrastructure |
| R4 | Write protocol — when and what an agent writes | Convention (skill instruction) |
| R5 | Read protocol — when to retrieve and how to position in context | Convention (skill instruction) |
| R6 | Artifact schema — minimal structure to enable filtering | Convention (skill instruction) |
| R7 | Retention / cleanup policy — when artifacts become stale | Convention (skill instruction) |

---

### R1 — Storage location

| Solution | Notes | Constraint |
|---|---|---|
| Committed directory in repo (`artifacts/`) | Tool-agnostic, no extra infra, git handles versioning and sharing | Adds repo noise |
| Gitignored local directory + committed index | Keeps repo clean; index summarises what exists | Artifacts not shared across engineers or machines |
| Separate sidecar git repo | Clean separation from main repo; Streamlit wiki hack is a version of this | Extra setup friction; not portable as a default |
| Git notes (`refs/notes`) | No extra files; metadata attached to commits | Obscure, poorly supported by most UIs and agents |
| External object store (S3, Azure Blob, GCS) | Unlimited storage; can layer search/vector on top | Cloud-specific; breaks tool-agnostic constraint; not a general skill baseline |
| Issue tracker (GitHub Issues, Linear, Jira) | Artifacts as issue comments or attachments; search built in | Platform-specific; not portable; not markdown-file-based |
| RAG / vector database | Semantic search without naming conventions | Infrastructure overhead; explicitly ruled out for baseline (see Recommended Approach) |

---

### R2 — Naming convention

| Solution | Notes | Constraint |
|---|---|---|
| Flat date-type-slug: `artifacts/YYYY-MM-DD-<type>-<slug>.md` | Simple; scannable by listing; no sub-directories | All artifacts in one directory; harder to filter by feature at scale |
| Scoped by work unit: `artifacts/<feature-or-issue>/<type>.md` | Mirrors Streamlit's PR-scoped pattern; groups related artifacts | Requires knowing the work unit before writing |
| Scoped by type: `artifacts/<type>/YYYY-MM-DD-<slug>.md` | Easy to find all reviews, all impl-notes, etc. | Cross-type queries (everything for feature X) require index or search |
| Role-prefixed: `artifacts/<role>-<type>-<slug>.md` | Maps to MetaGPT's role+task pattern | Role concept may not exist in solo projects |
| No convention — rely entirely on index | Maximum flexibility; agent writes freeform names | Index must carry full discoverability burden; breaks without a maintained index |

> Note: naming conventions must be baked into skill instructions (write protocol, R4) to be enforceable. They are not yet defined in any existing skill.

---

### R3 — Index / retrieval mechanism

| Solution | Notes | Constraint |
|---|---|---|
| Committed index file (`artifacts/INDEX.md`) | Markdown table of all artifacts; agent reads index first, then fetches specific file; MemoRAG analogue | Must be kept up to date; agent or human must maintain it |
| Agent-maintained index | Agent updates `INDEX.md` at session end; no human overhead | Requires reliable agent discipline; risks drift if session ends abruptly |
| Directory listing as implicit index | Agent lists `artifacts/` directory and infers from file names | Only works with strong naming conventions; fragile at scale |
| Full-text grep / search | No index needed; agent scans file contents | Slow at scale; requires agent to know what terms to search for |
| Semantic / vector search (MCP tool) | Delegates to an external search MCP server; no index maintained manually | Requires MCP infrastructure; not tool-agnostic baseline |
| Per-feature sub-index | Each `artifacts/<feature>/` directory has its own `README.md` summary | Good for large projects; overkill for small ones |

---

### R4 — Write protocol

| Solution | Notes | Constraint |
|---|---|---|
| End-of-session write | Agent writes a session summary artifact at the end of every session | Every session produces a file even for trivial sessions; noise risk |
| Event-triggered write | Specific events (code review complete, bug closed, architecture decision) trigger artifact creation; each relevant skill instructs the write | Requires each skill to explicitly instruct when to write; not automatic |
| Milestone write | Agent writes artifact when SCRATCHPAD.md is cleaned (at milestone boundaries) | Ties artifact creation to SCRATCHPAD.md lifecycle; clean coupling |
| On-demand only | Agent writes when explicitly instructed by user or skill | No implicit artifact creation; relies on human discipline |
| Skill-coupled write | Each skill that produces significant output (`reviewing-code`, `troubleshooting`, `architecting`) includes an artifact write step in its workflow | Most targeted; ensures artifacts match skill output types | Requires updating each skill |

---

### R5 — Read protocol

| Solution | Notes | Constraint |
|---|---|---|
| Session-start index read | Agent reads `INDEX.md` at every session start; retrieves relevant artifacts before starting work | Adds a fixed overhead to every session start; index must be current |
| Query-on-demand | Agent queries index only when it encounters a topic that warrants looking up prior artifacts | Requires agent to recognise when a lookup is warranted; less reliable |
| Feature-scoped load | Load only artifacts under `artifacts/<current-feature>/` at session start | Only works with work-unit-scoped naming convention (R2 option 2) |
| Skill-instructed load | Each skill that benefits from prior context (`resolving-drift`, `reviewing-code`) explicitly instructs when to retrieve which artifact types | Most targeted; avoids loading irrelevant artifacts | Requires updating each skill |
| Full load | Load all artifacts into context | Violates "Lost in the Middle" finding; unreliable at any meaningful artifact volume |

> Positioning rule (from Lost in the Middle): retrieved artifacts must be placed at the beginning of context, before the current task description, not appended at the end.

---

### R6 — Artifact schema

| Solution | Notes | Constraint |
|---|---|---|
| No schema — freeform markdown | Zero overhead; any content | Index and `resolving-drift` must parse free text; filtering by type/feature requires grep |
| Minimal frontmatter: `date`, `type`, `feature` | Enables index generation and filtering with three fields; no tooling required | Agents must follow the frontmatter convention reliably |
| Extended frontmatter: adds `author-role`, `session-id`, `status` | Supports multi-agent attribution and status filtering (active / archived) | More fields = more for agents to fill correctly |
| Per-type templates | Each artifact type (code-review, impl-note, issue-record) has a fixed markdown template with required sections | Strongest structure; easiest for `resolving-drift` to parse | Requires defining and maintaining templates per type |
| Mandatory heading structure (no frontmatter) | Required sections (`## Summary`, `## Decisions`, `## References`) without YAML | Simpler than frontmatter; human-readable but harder to parse programmatically |

---

### R7 — Retention / cleanup policy

| Solution | Notes | Constraint |
|---|---|---|
| Keep forever — no deletion | Simplest; full audit trail; git history always available | Artifact volume grows unboundedly; index and retrieval degrade over time |
| TTL by artifact type | Code review logs expire after merge; impl notes expire after feature ships; ADRs never expire | Nuanced; matches real-world relevance lifecycle | Requires tracking merge/ship events |
| Milestone-triggered promotion | At milestone, promote relevant decisions to permanent docs (tier 3) and mark artifact as archived | Closes the tier 2 → tier 3 promotion loop cleanly | Requires milestone detection (ties to F3.4 hooks) |
| Status field in frontmatter | Mark as `status: archived` when stale; retrieval skips archived artifacts | Lightweight; no deletion; relies on R6 extended frontmatter | Requires agents to update status reliably |
| Manual cleanup by engineer | Engineer decides when to remove or archive | No automated overhead | Relies entirely on human discipline; inconsistent across teams |

---

## Links Tracked

| URL | Type | Status |
|-----|------|--------|
| https://blog.streamlit.io/the-repo-is-the-harness-how-we-made-an-8-year-old-codebase-agent-native-75629a953354 | Primary | ✅ Read |
| https://agentic-design.ai/patterns/multi-agent/shared-scratchpad-collaboration | Primary | ✅ Read |
| https://arxiv.org/html/2508.11126v1 | Primary | ✅ Read (scalable memory sections extracted) |
| https://russpoldrack.substack.com/p/workflows-for-agentic-coding-and | Primary | ✅ Read |
| https://www.fastcompany.com/91472483/why-shared-memory-is-agentic-ais-biggest-consumer-moment | Primary | ✅ Read |
| https://medium.com/@adnanmasood/engineering-trustworthy-lm-agents-with-scratchpads-and-verifiers-5c1084533be7 | Primary | ⚠️ Paywalled — tl;dr only |
| https://arxiv.org/abs/2310.08560 | Primary | ✅ Read (abstract + full paper structure) |
| https://arxiv.org/abs/2303.11366 | Primary | ✅ Read (abstract + full paper structure) |
| https://arxiv.org/abs/2308.00352 | Primary | ✅ Read (abstract + full paper structure) |
| https://arxiv.org/abs/2307.03172 | Primary | ✅ Read (abstract + full paper structure) |
| https://arxiv.org/abs/2409.05591 | Primary | ✅ Read (abstract + full paper structure) |
| https://htdocs.dev/posts/claude-code-best-practices-and-pro-tips/ | Secondary | ✅ Read |
| https://agents.md/ | Secondary | ✅ Read |
| https://github.com/VectifyAI/PageIndex | Primary | ✅ Read |
| https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | Primary | ✅ Read |
| https://arxiv.org/abs/2405.15789 | Referenced in agentic-design.ai | ⚠️ Likely placeholder arxiv ID — skipped |
| https://research.google/pubs/pub53421/ | Referenced in agentic-design.ai | Not fetched — generic multi-agent systems, not adding to artifact store design |
| https://poldrack.github.io/BetterCodeBetterScience/frontmatter.html | Referenced in Poldrack | Not fetched — the Substack article captured the key content |
| https://blog.langchain.com/langgraph-multi-agent-workflows/ | Listed in agentic-design.ai | Not fetched — LangGraph is code-based orchestration, not relevant to our markdown convention |
| https://langchain-ai.github.io/langgraph/concepts/low_level/#state | Listed in agentic-design.ai | Not fetched — same reason |
| https://docs.crewai.com/concepts/collaborative-process | Listed in agentic-design.ai | Not fetched — same reason |

---

## Promising Ideas for Further Investigation

Ideas that are worth tracking but out of scope for the artifact store V1 directly.

---

### 1. Semantic search over committed project history
**Source:** arXiv 2508.11126 (Cursor IDE, Table 3)
**Idea:** Embedding-based retrieval over committed files and history — agent queries "what decisions have we made about auth?" and gets semantically relevant docs back. Cursor IDE does this today for project history.
**Why not now:** Requires vector store or embedding service. Not tool-agnostic. Not markdown-only.
**Why investigate:** This is the long-term answer to the discoverability problem (Problem A in the artifact store research). As MCP server ecosystems mature, a skill that instructs agents to use a local semantic search MCP becomes possible without us owning the infrastructure. The `mcp_aws` and `mcp_iac` pattern in our AWS skills shows this model works.

---

### 2. Memory summarization hook
**Source:** arXiv 2508.11126 (Section 6.2); Poldrack workflow
**Idea:** A hook or slash command that an agent runs at milestone boundaries to: (a) summarize the session into SCRATCHPAD.md, (b) identify decisions ready for promotion to permanent docs, (c) flag items that need `resolving-drift`. Poldrack does this with `/summ+commit`. A tool-agnostic version would be a composite skill step or a hook trigger.
**Why not now:** Hooks don't exist yet in our catalogue (F3.4 is still pending brainstorming). The "memory summarization" step exists as a manual Workflow step in our SCRATCHPAD.md convention, but automation requires hooks.
**Why investigate:** This becomes the natural bridge between Arkeology (artifact store) and F3.4 (hooks library). A "summarize and promote" hook running at commit time would close the loop entirely.

---

### 3. Hierarchical memory with TTL (time-to-live) per tier
**Source:** arXiv 2508.11126 (Section 6.2, hierarchical memory model)
**Idea:** Short-term memory has a short TTL (current session → cleared at `/clear`); mid-term memory has a medium TTL (current milestone → cleared at milestone complete); long-term memory has no TTL (permanent docs). Our three-tier approach maps to this, but we don't encode the TTL discipline explicitly.
**Why not now:** Would require tooling or explicit workflow enforcement — neither exists yet.
**Why investigate:** Encoding TTL expectations in the SCRATCHPAD.md header ("clean at milestone") is a lightweight version we could implement now. A more rigorous TTL model becomes possible if hooks (F3.4) can automate milestone detection.

---

### 4. Shared memory for multi-agent workflows
**Source:** Agentic Design Patterns (SSC); Fast Company
**Idea:** When multiple agents work concurrently on the same project (different terminal sessions, or orchestrated sub-agents), they need a shared, conflict-resolved workspace. LangGraph shared state, CrewAI collaborative process, AutoGen GroupChat all address this. In our context: two engineers each running an agent session in different branches simultaneously — their scratchpads diverge.
**Why not now:** The conflict-resolution and concurrency mechanics (turn-based locking, branch-scoped scratchpads, merge strategies) add significant design complexity that is out of scope for the initial artifact store V1 solution. The baseline problem — a single committed SCRATCHPAD.md with no concurrent writers — must be solved first before adding concurrency handling.
**Why investigate:** SCRATCHPAD.md as a single committed file becomes a merge conflict hotspot when two engineers run agent sessions in parallel on different branches. The skills and agents we build will be used across teams and projects of unknown size and structure — concurrent agent sessions are a real scenario, not a distant edge case. Branch-scoped scratchpads or a lock convention will likely be needed as adoption grows. This connects to F3.4 hooks and the broader multi-agent collaboration problem.

---

### 5. SCRATCHPAD.md as structured YAML frontmatter + freeform body
**Source:** Design tension identified during this research
**Idea:** The top of SCRATCHPAD.md is machine-readable YAML frontmatter (current_focus, active_decisions as list, blockers, last_updated) and the body is human-readable freeform. Agents can parse the frontmatter programmatically; humans read the body. `resolving-drift` can query the frontmatter directly.
**Why not now:** Adds complexity. Our current skill format uses pure markdown. Would require defining a schema and maintaining it.
**Why investigate:** The YAML frontmatter pattern already works well in SKILL.md files and brainstorming-V3.md. Structured frontmatter in SCRATCHPAD.md would make it machine-queryable without a vector store — a lightweight middle ground between "free-form markdown" and "vector DB". Deserves a dedicated brainstorming session if Arkeology adoption reveals that agents struggle to extract structured state from free-form SCRATCHPAD.md.

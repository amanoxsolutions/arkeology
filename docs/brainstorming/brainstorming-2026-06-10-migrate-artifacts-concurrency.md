---
status: in-progress
references:
  - docs/brainstorming/brainstorming-2026-06-01-write-performance.md
authored:
  by: "pm"
  date: "2026-06-10"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
decisions_locked: []
decisions_pending:
  - D1: Should description concurrency be a per-call parameter on migrate_artifacts, a separate server env var, or derived from ARTIFACT_CONCURRENCY?
  - D2: Should the same parameter control write-phase concurrency or only the description-generation phase?
  - D3: What formula should the skill use to compute the concurrency value from file count?
  - D4: Should there be an upper cap, and if so, what value?
decisions_closed_not_applicable: []
---

# migrate_artifacts — Caller-Controlled Concurrency Parameter

## Description

`migrate_artifacts` generates missing artifact descriptions via Bedrock Nova Lite using
`asyncio.gather` bounded by `ARTIFACT_CONCURRENCY` (default 3). With 95 artifacts this
produces ~32 sequential rounds of 3 concurrent Nova Lite calls, making the dry-run phase
unacceptably slow. This session explores whether concurrency should be a per-call
parameter that the caller (the skill) computes from the file count at invocation time,
rather than a fixed server-side env var that requires a restart to change.

---

## Session 2026-06-10

### Problem Statement

Two issues motivate this session:

- **Issue A — no status updates**: `migrate_artifacts` fires all Nova Lite description
  calls inside a single `asyncio.gather` and returns nothing until all are done. With 95
  files the operator sees silence for minutes.

- **Issue B — concurrency too low**: `ARTIFACT_CONCURRENCY=3` was sized for the write
  path (each artifact write triggers concurrent section embeddings against Bedrock + S3
  Vectors). Nova Lite text generation calls are a different, lighter workload. The same
  cap is too conservative for bulk description generation.

**Why not just raise `ARTIFACT_CONCURRENCY`?** It is a server-side env var. Changing it
requires editing the MCP server config and restarting the MCP client. That is the wrong
friction point for a one-time bulk migration. It also conflates two workloads with
different cost profiles: embedding (CPU/network-light per section, many per artifact) vs.
text generation (heavier per call, one per artifact).

**The proposal**: add an optional `description_concurrency` (or similar) parameter to
`migrate_artifacts`. The skill computes the right value from `len(files)` and passes it.
No server restart, no env var, right-sized per run.

**Bedrock quota context (from write-performance brainstorm Session 3):**

| Quota | Value |
|---|---|
| Titan Text Embeddings V2 on-demand RPM | 6,000 (= 100 req/s) |
| Titan Text Embeddings V2 on-demand TPM | 300,000 (≈ 5,000 tok/s at 300 tok/section) |
| Nova Lite RPM / TPM | Not yet researched — open question |

The `SECTION_CONCURRENCY × ARTIFACT_CONCURRENCY ≤ 15` rule of thumb from Session 3
applies to embedding. Nova Lite quotas may differ and need separate analysis.

### Known Constraints

| Constraint | Source |
|---|---|
| `ARTIFACT_CONCURRENCY` default is 3; governs both write_artifacts and migrate_artifacts description phase | config.py |
| Description generation uses `asyncio.to_thread(bedrock.invoke_text_model, ...)` per descriptor | migrate_artifacts.py lines 130–135 |
| The semaphore in migrate_artifacts is created from `settings.artifact_concurrency` | migrate_artifacts.py line 121 |
| Raising the parameter does not affect the write phase (which delegates to write_artifacts with its own semaphore) | write_artifacts.py line 90 |
| Nova Lite quota is unknown — need to verify RPM/TPM limits before choosing an upper cap | Open |
| The skill currently passes all files in a single migrate_artifacts call with no batching | SKILL.md steps 3.B3, 3.B5 |
| Issue A (no status updates) is partially addressed by skill-level sequential batching regardless of this parameter | Prior discussion |

### Ideas Explored

<!-- To be filled in during the brainstorming session -->

### Clusters

<!-- To be filled in during the brainstorming session -->

### Selected Directions

<!-- To be filled in during the brainstorming session -->

### Challenges

<!-- To be filled in during the brainstorming session -->

### Open Questions

<!-- To be filled in during the brainstorming session -->

---
type: brainstorming
title: migrate_artifacts — Caller-Controlled Concurrency Parameter
description: Explores whether `migrate_artifacts` concurrency should be a per-call parameter rather than a fixed server-side env var, to enable the skill to set appropriate concurrency based on file count and avoid slow bulk description generation.
tags: []
timestamp: 2026-06-10T00:00:00Z
okf_version: "0.1"
status: complete
references:
  - docs/brainstorming/brainstorming-2026-06-01-write-performance.md
authored:
  by: "pm"
  date: "2026-06-10"
revised:
  by: "analyst"
  date: "2026-06-11"
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

## Decisions

### Locked

- "D1: Per-call parameter — artifact_concurrency is an optional parameter on migrate_artifacts and write_artifacts, not a server env var"
- "D2: Single parameter — one artifact_concurrency parameter per call; the two sequential migrate_artifacts calls (dry_run=True then dry_run=False) are the mechanism for phase-specific tuning"
- "D3: Skill proposes min(file_count, 15) with a brief explanation of the Titan quota context, then asks the operator to confirm or supply their own value before proceeding"
- "D4: Soft ceiling of 15 — values outside [1, 15] are never rejected; values > 15 are capped to 15, values < 1 are substituted with the default (3); in both cases a top-level warning field is added to the response and the work proceeds; at default SECTION_CONCURRENCY=5 the cap of 15 produces 75 concurrent Bedrock embedding calls, leaving 25% headroom under the 100 req/s Titan ceiling"
- "D8: Skill batches by artifact_concurrency (stdio workaround) — in 3.B3 and 3.B5 the skill splits the descriptor list into batches of artifact_concurrency and makes one migrate_artifacts call per batch; the operator receives a progress update after each batch; batch_size = artifact_concurrency so no separate parameter is needed; explicitly a stdio workaround — when Streamable HTTP + SSE is available the batching loop is replaced by a single call that receives per-item SSE events, and artifact_concurrency retains its server-side semaphore role independently"
- "D5: SECTION_CONCURRENCY stays as a server-level env var with default 5; it is server policy controlling the inner embedding loop, not a per-call tuning knob"
- "D6: ARTIFACT_CONCURRENCY env var removed entirely; artifact_concurrency becomes an optional parameter on write_artifacts and migrate_artifacts with a hardcoded default of 3"
- "D7: migrate_artifacts parameter renamed from concurrency to artifact_concurrency for consistency with write_artifacts"

### Pending

_None._

### Closed — Not Applicable

_None._

## Techniques Used

- assumption-surfacing
- constraint-removal

## Assumptions Challenged

- "Two parameters are needed because the description and write phases have different cost profiles — false: the phases run sequentially in separate calls, so one parameter per call is sufficient and the caller naturally sets a different value for each phase"
- "The write phase must keep the env var because it is called indirectly via write_artifacts — false: migrate_artifacts controls both calls and can thread a single parameter through to both phases"
- "The dynamic cap max(1, 15 // SECTION_CONCURRENCY) is the safest option — false: at the default SECTION_CONCURRENCY=5 it produces 3, identical to the current env var default, providing no improvement for the migration use case"
- "SECTION_CONCURRENCY should become a per-call parameter for symmetry with artifact_concurrency — false: section concurrency is an implementation detail of a single artifact write that callers have no meaningful reason to tune; it is server policy, not call-time tuning"
- "artifact_concurrency < 1 is a programming error that should return a validation error — false: there is no more reason to fail on a too-low value than on a too-high one; substitute the default (3) and warn, symmetrically with the > 15 cap"
- "batch size needs a separate parameter — false: batch_size = artifact_concurrency is sufficient; the skill already has the confirmed concurrency value and using it as the batch size gives free progress reporting with zero extra parameters"

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

**The initial proposal**: add an optional `description_concurrency` parameter to
`migrate_artifacts` for the Nova Lite phase only, leaving the write phase on the env var.
This was revised during Session 2026-06-11 — see below.

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
| write_artifacts also creates its own semaphore from `settings.artifact_concurrency` independently | write_artifacts.py line 90 |
| `SECTION_CONCURRENCY` has no upper bound in the validator — only `≥ 1` is enforced; the `SECTION_CONCURRENCY × ARTIFACT_CONCURRENCY ≤ 15` rule of thumb is advisory only, nothing in code enforces it | config.py lines 289–294 |
| Nova Lite quota is unknown — open question for future research | Open |
| The skill currently passes all files in a single migrate_artifacts call with no batching | SKILL.md steps 3.B3, 3.B5 |
| Issue A (no status updates) is partially addressed by skill-level sequential batching regardless of this parameter | Prior discussion |
| Migration is a standalone operation — the server is not serving concurrent requests during a bulk migration run | Operator context |

### Ideas Explored

**I1 — single `concurrency` parameter, both phases use it**
Add one optional `concurrency` parameter to `migrate_artifacts`. Both the description semaphore
and the value forwarded to `write_artifacts` use it. Env var is the fallback when omitted.

**I2 — two parameters: `description_concurrency` + `write_concurrency`**
One parameter per phase, both optional, both computed by the skill. Gives independent tuning
of the Nova Lite phase (no multiplier) vs the embedding phase (×SECTION_CONCURRENCY).

**I3 — parameter on `write_artifacts` itself, threaded through**
Add `artifact_concurrency` to `write_artifacts` as well, making it callable independently
with an explicit cap. `migrate_artifacts` threads through whatever it received.

**I4 — dynamic cap: `max(1, 15 // settings.section_concurrency)`**
The tool enforces a computed ceiling derived from the `SECTION_CONCURRENCY × N ≤ 15` advisory
rule. No fixed number — adapts to the server's embedding configuration.

**I5 — fixed hard cap of 10 in the tool**
Conservative ceiling. At default `SECTION_CONCURRENCY=5`: 50 concurrent embedding calls,
50% of Titan ceiling. Safe under concurrent load.

**I6 — fixed hard cap of 15 in the tool**
At default `SECTION_CONCURRENCY=5`: 75 concurrent embedding calls, 25% headroom under Titan
ceiling. Appropriate when migration is the sole workload.

**I7 — fixed hard cap of 20 in the tool**
At default `SECTION_CONCURRENCY=5`: 100 concurrent embedding calls, exactly at the Titan
ceiling. No headroom — rejected.

### Clusters

**Cluster A — parameter shape**
I1 (single parameter), I2 (two parameters), I3 (parameter on write_artifacts too).
These address how the caller expresses concurrency intent.

**Cluster B — tool-level safety ceiling**
I4 (dynamic), I5 (cap=10), I6 (cap=15), I7 (cap=20).
These address the maximum value the tool will accept regardless of what the caller passes.

### Selected Directions

**From Cluster A: I1 — single `concurrency` parameter**

The description phase (`dry_run=True`) and write phase (`dry_run=False`) are two separate
sequential calls to `migrate_artifacts`. The caller — skill or agent — already controls
which phase it is invoking via `dry_run`. It can therefore supply a different `concurrency`
value for each call. This makes two parameters on one call redundant: the sequential
structure of the two calls *is* the two-parameter solution, and it is cleaner because there
is no ambiguity about which value applies to which phase.

I3 is deferred: making `write_artifacts` itself accept a parameter is a valid but separate
concern. When called directly (not through `migrate_artifacts`), it falls back to the env
var. That is acceptable for now.

**From Cluster B: I6 — hard cap of 15**

Migration runs on a quiet server with no concurrent load. The 25% headroom under the Titan
ceiling (75 of 100 req/s at default `SECTION_CONCURRENCY=5`) is sufficient.

I4 (dynamic) was eliminated: at `SECTION_CONCURRENCY=5` (the common default), `max(1,
15 // 5) = 3` — identical to the current env var default. It provides no improvement for
the very use case that motivated this session.

I5 (cap=10) would be appropriate if the server were shared and concurrent load were
expected during migration. It was rejected because migration is confirmed to run on a
quiet server.

### Challenges

**Challenge: the single parameter applies to both phases but the phases have different cost
profiles — is 15 safe for both?**

- Description phase: 15 concurrent Nova Lite calls, no SECTION_CONCURRENCY multiplier.
  Nova Lite quotas are unresearched, but Nova Lite is a high-throughput model. 15 concurrent
  calls is conservative by any reasonable quota expectation.
- Write phase: 15 × SECTION_CONCURRENCY concurrent Bedrock embedding calls. At the
  default SECTION_CONCURRENCY=5 this is 75 calls — within the 100 req/s Titan ceiling
  with 25% headroom. At higher SECTION_CONCURRENCY values (e.g. 10), 15 × 10 = 150 would
  exceed the ceiling. This is an edge-case configuration; the operator is expected to pass
  a lower `concurrency` value in that case. The skill's explanation of the Titan quota
  context (D3) equips the operator to make that judgement.

**Challenge: what if the operator sets SECTION_CONCURRENCY above the default?**

The tool's hard cap of 15 does not account for non-default SECTION_CONCURRENCY values.
An operator with SECTION_CONCURRENCY=10 who passes concurrency=15 would fire 150
concurrent Bedrock embedding calls. This is outside the Titan quota. Mitigations:
1. The skill's explanation (D3) includes a note about the SECTION_CONCURRENCY multiplier.
2. Future work (I3 deferred): the tool could validate `concurrency ×
   settings.section_concurrency ≤ some_ceiling` and return an error rather than silently
   overloading Bedrock.

### Open Questions

**OQ1 — Nova Lite RPM/TPM quotas**
Still unresearched. The description-phase cap of 15 is believed safe but not verified.
Research needed before asserting a tighter or looser bound for that phase specifically.

**OQ2 — should the tool validate `concurrency × SECTION_CONCURRENCY` at call time?**
Currently deferred. If SECTION_CONCURRENCY is non-default and high, the caller can
inadvertently exceed the Titan quota even within the hard cap. A compound validation
would prevent silent overload at the cost of additional complexity.

## Session 2026-06-11

### Topic

Continued from Session 2026-06-10. Resolved all four open decisions. The key insight that
unlocked D2 was recognising that `migrate_artifacts` is already called twice sequentially
by the skill — once with `dry_run=True` for description generation, once with
`dry_run=False` for the write phase. This means two parameters on a single call are
unnecessary: the caller can supply a different `concurrency` value for each call. The
sequential structure is itself the per-phase tuning mechanism.

### Key Insight

The initial proposal introduced `description_concurrency` to avoid conflating two workloads
with different cost profiles, but simultaneously proposed leaving the write phase on the env
var — creating an inconsistency. Both phases are called from within `migrate_artifacts`, so
there was no principled reason to treat them differently. Once it was recognised that the
two calls are sequential and already separated by `dry_run`, the inconsistency resolved
itself: one parameter, used appropriately by the caller for whichever phase that call runs.

### Decisions Resolved (D1–D4)

| ID | Decision |
|---|---|
| D1 | Per-call parameter. `artifact_concurrency` is optional on `migrate_artifacts`; hardcoded default of 3. |
| D2 | Single parameter. Sequential calls handle phase-specific values; two parameters on one call are not needed. |
| D3 | Skill uses `min(file_count, 15)` as the proposal; presents Titan quota context; asks operator to confirm or override. |
| D4 | Hard cap of 15 in the tool. When the caller exceeds 15, the tool caps silently to 15 and adds a top-level `warning` field to the response — work proceeds, no writes lost. 75 concurrent embedding calls at default settings leaves 25% Titan headroom. |

### Extension — write_artifacts and env var removal (D5–D7)

The same session extended to whether `SECTION_CONCURRENCY` and `ARTIFACT_CONCURRENCY`
should also become per-call parameters on `write_artifacts`.

**SECTION_CONCURRENCY (D5 — stays as env var)**

`SECTION_CONCURRENCY` controls the inner embedding loop inside a single artifact write —
how many sections embed concurrently within one `_write_artifact_inner` call. This is an
implementation detail invisible to the caller; callers have no meaningful reason to tune it
per call. It is server policy (how aggressively the server uses Bedrock per write) and
belongs in the env var, not on the tool API. Default: 5.

**ARTIFACT_CONCURRENCY (D6 — removed as env var, D7 — parameter renamed)**

`ARTIFACT_CONCURRENCY` controls the outer loop — how many artifacts are processed
concurrently. This is the same concern as `migrate_artifacts`'s `artifact_concurrency`
parameter (D1). The argument is symmetric: callers of `write_artifacts` may also want to
right-size the outer loop per operation without a server restart.

The env var is removed entirely rather than kept as a default because the tool is not
deployed anywhere — there is no migration burden and no `.env` files to update. The
hardcoded default of 3 lives in the parameter signature.

The `migrate_artifacts` parameter name was updated from `concurrency` to
`artifact_concurrency` (D7) so both tools use the same name for the same concept.

**Affected call sites (confirmed via grep):**

| File | Line | Change |
|---|---|---|
| `migrate_artifacts.py` | 121 | semaphore reads parameter, not `settings.artifact_concurrency` |
| `write_artifacts.py` | 90 | semaphore reads parameter, not `settings.artifact_concurrency` |
| `config.py` | 179–188, 310–315, 418–420 | `ARTIFACT_CONCURRENCY` field, validator, and property removed |

`reconcile.py` does not use either variable — confirmed unaffected.

### Decisions Resolved (D5–D7)

| ID | Decision |
|---|---|
| D5 | `SECTION_CONCURRENCY` stays as server-level env var, default 5. It is server policy, not per-call tuning. |
| D6 | `ARTIFACT_CONCURRENCY` env var removed entirely. `artifact_concurrency` becomes an optional parameter on `write_artifacts` and `migrate_artifacts` with hardcoded default 3. |
| D7 | `migrate_artifacts` parameter renamed from `concurrency` to `artifact_concurrency` for consistency with `write_artifacts`. |

### Extension — out-of-range handling and skill batching (D4 revised, D8)

**D4 revised — symmetric out-of-range handling**

The initial D4 decision left `artifact_concurrency < 1` as a validation error while
capping `> 15`. This asymmetry was challenged: there is no more reason to fail on a
too-low value than on a too-high one. The tool substitutes the default (3) when the value
is below 1, matching the cap-and-warn behaviour for the upper bound. The tool never fails
on the concurrency parameter — it always clamps to `[1, 15]` with a warning and proceeds.

**D8 — skill batches by `artifact_concurrency` (Issue A resolved)**

Issue A (no status updates during long migrations) was flagged in the Known Constraints
table as "partially addressed by skill-level sequential batching". The approach: in steps
3.B3 and 3.B5 the skill splits the full descriptor list into batches of `artifact_concurrency`
and makes one `migrate_artifacts` call per batch, reporting progress to the operator after
each. For 95 files at `artifact_concurrency=15`: 7 calls, progress after each; at the
default of 3: 32 calls, very frequent updates.

`batch_size = artifact_concurrency` requires no additional parameter. The operator already
confirmed the concurrency value; using it as the batch size is self-documenting and means
the parameter now has two effects at the skill level: server-side semaphore bound per call,
and call granularity (how many artifacts per call = how often the operator gets feedback).

This is a skill-only change — the server's `migrate_artifacts` function processes whatever
list it receives, unchanged.

| ID | Decision |
|---|---|
| D4 (revised) | Out-of-range values are never rejected: > 15 capped to 15 + warning; < 1 substituted with default 3 + warning; work always proceeds. |
| D8 | Skill batches 3.B3 and 3.B5 by `artifact_concurrency` (batch_size = artifact_concurrency); progress after each batch; explicit stdio workaround — superseded by SSE when Streamable HTTP is adopted. |

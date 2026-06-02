# Write Performance — Reducing `write_artifact` Latency

## Description

`write_artifact` is unacceptably slow for bulk imports. A 10-document migration
(~30 KB total) took more than 10 minutes. This brainstorming session diagnoses
the root causes from first principles and explores every credible option for
reducing write latency, then identifies the most promising directions before
a design decision is taken.

---

## Session 2026-06-01

### Root cause diagnosis

Reading `src/cairn_mcp/tools/write.py` and the client implementations reveals
four compounding bottlenecks.

#### RC-1 — Sequential section embedding (dominant)

The section loop in `_write_artifact_inner` calls `bedrock.embed()` once per
section, **one at a time**, inside a `for` loop:

```python
for sec in sections:
    embedding = bedrock.embed(...)   # sync, blocking
    vectors.put_vector(...)           # sync, blocking
```

For a structured markdown document with 8 H2 sections, that is 8 sequential
Bedrock `InvokeModel` calls. At 200–400 ms per call, that is 1.6–3.2 s
**per document** in ideal conditions — roughly 16–32 s for 10 documents before
any throttling.

#### RC-2 — One S3 Vectors call per section (avoidable)

`vectors.put_vector(key, embedding, metadata)` wraps `put_vectors` with a
single-element list. The S3 Vectors API supports batching arbitrary numbers
of vectors in one call. For N sections, this wastes N−1 network round-trips
per artifact. At 100–200 ms per call, a 10-section document burns 1–2 extra
seconds purely in round-trips.

#### RC-3 — Blocking sleep in async context

`BedrockClientImpl.embed` uses `time.sleep(_RETRY_SLEEP_SECONDS)` (2 s) for
transient error retry. This is a **synchronous blocking sleep** executed inside
an async Python process. It freezes the entire event loop for the duration of
the sleep, preventing other coroutines from making progress. Any throttle event
adds a hard 2-second wall-clock pause to the loop.

#### RC-4 — Duplicate ThrottlingException retry path

`write.py` contains its own `ThrottlingException` catch-and-retry block around
`bedrock.embed()` with an additional `await asyncio.sleep(1)`. Because
`BedrockClientImpl.embed` **already** retries internally on `ThrottlingException`
(RC-3), a throttle that exhausts both attempts in `bedrock.py` is retried a
second time by `write.py`, adding another `asyncio.sleep(1)` + a full second
call cycle. This can cascade: one persistent throttle event can cost
2 s (bedrock.py) + 1 s (write.py wait) + 2 s (bedrock.py second call) = **5 s**
for a single section.

#### Compounding effect at migration scale

For 10 documents × 8 sections = 80 Bedrock calls, fully sequential:

| Scenario | Time estimate |
|---|---|
| No throttling, 300 ms/call | 80 × 300 ms = **24 s** |
| 20 % throttle rate, 5 s/throttle | 24 s + 16 × 5 s = **104 s** |
| 40 % throttle rate | 24 s + 32 × 5 s = **184 s** |
| 60 % throttle rate | 24 s + 48 × 5 s = **264 s** |

Adding ~2 s × 80 sequential put_vector calls = ~160 s. At 40 % throttle that is
already 184 + 160 = **344 s ≈ 6 minutes**. Add agent LLM inference time
(description generation, metadata decisions) for each document, and 10 minutes
is reachable and consistent.

---

### Option space

#### Theme A — Parallelism within a single `write_artifact` call

**A1 — Concurrent section embedding with `asyncio.gather` + `run_in_executor`**

Emit all section `bedrock.embed()` calls concurrently using
`asyncio.gather(*[loop.run_in_executor(None, embed, text) for text in texts])`.
The sync `embed` method runs in a thread pool; all sections of one artifact are
embedded in parallel. Wall-clock time per artifact drops from `N × embed_latency`
to `max(embed_latency_per_section)` — roughly one call's latency regardless
of section count.

Trade-offs:
- Bedrock TPS quota is per account. Concurrent calls from many sections increase
  instantaneous request rate and may trigger more throttling than serial calls.
  Mitigation: `asyncio.Semaphore(3)` caps concurrency without losing most of
  the benefit. Even with a semaphore of 3, 9 sections drop from 9 × 300 ms =
  2.7 s to ceil(9/3) × 300 ms = 900 ms.
- Requires `run_in_executor`; the sync `BedrockClientInterface.embed` signature
  need not change — wrapping happens at the call site in `write.py`.

**A2 — Make `BedrockClientImpl.embed` natively async**

Convert `embed` to `async def embed(...)` using an async HTTP client (e.g.
`aiobotocore`) or `asyncio.to_thread`. `asyncio.gather` can then call it
directly with `await`.

Trade-offs:
- Cleaner than `run_in_executor` at call sites. Native async throughout.
- `aiobotocore` is an additional dependency with its own release cadence.
  `asyncio.to_thread` (stdlib) is simpler and sufficient.
- `BedrockClientInterface` must change to `async def embed(...)`, requiring
  updates to `FakeBedrockClient` and all unit tests. Non-trivial but
  correct long-term.

**A3 — Batch all `put_vectors` per artifact**

Collect all (key, vector, metadata) tuples after embedding and call
`put_vectors` once per artifact with the full list, instead of one API call
per section. Drop the per-section `vectors.put_vector()` loop entirely.

Trade-offs:
- Zero interface change needed in the calling code — just accumulate a list and
  call a batch method. The client interface gains `put_vectors_batch(items)` or
  reuses `put_vector` with an overloaded signature.
- S3 Vectors `PutVectors` batch limit: not documented explicitly in the existing
  code; needs verification. Artifacts with > 100 sections (very unusual) may
  need chunking. In practice, 5–15 sections per artifact is the expected range.
- Cannot be done without all embeddings first — natural pair with A1 (embed all
  concurrently, then put all in one batch call).

**A1 + A3 combined** is the highest-impact, lowest-risk option: concurrent
embedding eliminates serial Bedrock latency; batched put_vectors eliminates
serial S3 Vectors calls. Together they reduce per-artifact vector write time
from `N × (embed + put)` to `max(embed per semaphore batch) + 1 put_vectors`.

---

#### Theme B — Fix retry/throttle handling

**B1 — Replace `time.sleep` with `asyncio.sleep` in `BedrockClientImpl.embed`**

`time.sleep` blocks the event loop. If `embed` becomes async (A2), this is
automatically fixed. If `embed` stays sync but runs in a thread pool (A1),
`time.sleep` in the thread is harmless (the thread blocks, not the loop).
Either way, `time.sleep` in the current sync-in-the-loop-without-executor
model is a hard blocker for any future concurrency.

**B2 — Remove the duplicate ThrottlingException retry in `write.py`**

The `ThrottlingException` catch block in `write.py` is redundant: `bedrock.py`
already retries internally. Remove it from `write.py`. The error will still
bubble up if both attempts in `bedrock.py` fail, and the top-level
`try/except Exception` will handle it cleanly. This eliminates the
"write.py waits 1 s + calls embed again → bedrock.py waits 2 s again" cascade.

**B3 — Exponential backoff with jitter**

Replace the fixed 2-second sleep in `bedrock.py` with exponential backoff
and jitter: `min(base × 2^attempt + random(0, 1), cap)`. This is the AWS
recommended pattern for sustained throttling. Reduces the chance that many
concurrent callers (future) all retry at the same moment.

---

#### Theme C — Granularity controls

**C1 — Configurable `MAX_SECTIONS_PER_ARTIFACT`**

A new env var (e.g. `EMBED_MAX_SECTIONS=20`) caps the number of sections
embedded per artifact. If a document has 40 H2 sections, only the first 20
are indexed. Simple bounded worst-case behavior.

Trade-offs:
- Operators must choose a value. Default of 20 is safe for nearly all
  structured artifacts; only unusually long brainstorming documents or
  large specs would exceed it.
- Sections beyond the cap are silently dropped from the vector index —
  they remain in S3 (full content is still returned by `read_artifact`)
  but are not searchable at the section level.
- Does not fix the fundamental sequential bottleneck; just bounds the damage.

**C2 — Minimum section body length**

Skip sections shorter than a configurable threshold (e.g. 50 characters).
Very short sections — "TBD", "See above", a single link — add noise to the
vector index without contributing search signal.

Trade-offs:
- Low risk: short sections have low semantic density; omitting them is
  unlikely to degrade retrieval quality.
- Simple to implement as a filter in `parse_sections` or at embed time.
- Does not help for documents with many substantial sections.

**C3 — Document-level fallback for section-heavy documents**

If `len(sections) > EMBED_MAX_SECTIONS`, fall back to the document-level
fallback strategy (one embed from title + description) rather than embedding
a capped subset. This avoids partial indexing bias (only first N sections)
at the cost of reduced retrieval precision for that artifact.

---

#### Theme D — New bulk write capability

**D1 — `write_artifacts` (plural) MCP tool**

A new MCP tool accepting a list of artifact descriptors. The server processes
all artifacts concurrently (asyncio.gather with a semaphore), then returns a
list of per-artifact results. Targeted at migration and batch import scenarios.

Trade-offs:
- The agent does one tool call for all documents — eliminates all agent
  LLM inference overhead between individual write calls (estimated 5–20 s
  per document for description generation and response processing).
- Error handling is more complex: partial successes must be reported per-artifact.
- Large payload: a batch of 10 × 3 KB documents = 30 KB in a single MCP call.
  This is well within MCP message limits.
- The migrate.py script in the migrating-to-cairn skill would be the primary
  caller — it already has all metadata resolved before calling the server.

**D2 — Async pipeline in `migrate.py` (skill-side, not server-side)**

The migrate.py script calls `write_artifact` via the MCP client. If the MCP
Python client supports async and the server handles concurrent requests, the
script can fire multiple calls with `asyncio.gather`. This keeps the server
interface unchanged while enabling client-side parallelism.

Trade-offs:
- Server-side, each write_artifact is independent and safe to parallelize.
- MCP stdio transport is typically sequential (one request at a time). This
  approach requires HTTP/SSE transport or a future async stdio MCP client
  capability. Likely not viable in the short term with the current stdio transport.

---

#### Theme E — Smaller embedding dimensions

**E1 — Default to 256 dimensions instead of 1024**

Titan Text Embeddings v2 supports 256, 512, and 1024. Reducing to 256 cuts
vector storage by 4× and reduces the response payload from Bedrock.

Trade-offs:
- The dominant latency cost is network round-trip (connect + send + receive),
  not payload size. At 256 vs 1024 floats, the response body difference is
  ~3 KB — negligible over the network. Latency improvement: minimal (< 10 %).
- Requires recreating the S3 Vectors index with dimension=256 — a destructive
  operation for existing deployments.
- Not worth it as a performance fix; the network RTT dominates.

---

### Selected directions (highest impact, cleanest architecture)

**P1 — Concurrent embedding + batched put_vectors [immediate win]**

Combine A1 + A3: embed all sections of one artifact concurrently using
`asyncio.gather` with `run_in_executor` and a semaphore (default 5), then
issue one batched `put_vectors` call per artifact. This is the most impactful
change and requires no interface evolution:

- `write.py` uses `asyncio.gather` with `loop.run_in_executor(None, embed, text)`
- All embeddings collected; then a new `put_vectors_batch` method on the client
  handles the batch put in one call
- `BedrockClientInterface` and `FakeBedrockClient` stay unchanged (sync embed)
- A new config var `EMBED_CONCURRENCY` (default 5) controls the semaphore

Estimated effect: for 8 sections, embed time drops from 8 × 300 ms = 2.4 s to
ceil(8/5) × 300 ms ≈ 600 ms (2 rounds with semaphore=5). Put_vectors drops from
8 × 150 ms = 1.2 s to 1 × 150 ms. Per-artifact time: ~750 ms vs 3.6 s — **~5×
faster per artifact**.

**P2 — Fix retry/throttle handling [correctness fix, medium win]**

Remove the duplicate ThrottlingException retry from `write.py` (B2). Replace
`time.sleep` in `bedrock.py` with `asyncio.sleep` via `run_in_executor` call
context, or accept that with `run_in_executor` the blocking sleep in the thread
is harmless (B1 becomes automatic). Add jitter to the retry sleep (B3) to avoid
thundering herd when multiple concurrent embeds throttle at the same time.

**P3 — Configurable section cap [defensive bound]**

Add `EMBED_MAX_SECTIONS` (default 20, C1) and minimum section body length
(50 chars, C2). These are one-line filters that bound worst-case behavior
for unusual documents without degrading the typical case.

---

### Challenges to the selected directions

**Challenge 1: Will concurrent embedding increase throttling frequency?**

With semaphore=5, at most 5 Bedrock calls are in-flight simultaneously.
For a single-user MCP session, the account-level TPS for Titan v2 is 50 TPS
on-demand (higher with provisioned throughput). 5 concurrent calls is well
below the per-account limit. If a team runs multiple agents simultaneously,
the effective TPS increases proportionally — mitigated by the semaphore and
the exponential backoff in B3.

**Challenge 2: `run_in_executor` thread pool sizing**

`asyncio.get_event_loop().run_in_executor(None, ...)` uses Python's default
`ThreadPoolExecutor` (min 5, max `os.cpu_count() * 5 + 4` threads). For an
MCP server that is typically single-tenant (one agent at a time), this is
more than adequate. No explicit pool sizing needed.

**Challenge 3: Batched `put_vectors` — S3 Vectors batch limit**

The S3 Vectors API `PutVectors` batch limit is not explicitly stated in the
existing code comments. The current `GetVectors` hard limit is documented at
100 vectors per call (brainstorming-artifact-store.md, D6). If `PutVectors`
shares the same limit, artifacts with > 100 sections must chunk the batch.
Given that C1 caps sections at 20, this is a non-issue in practice. The
implementation should chunk at 100 defensively.

**Challenge 4: Error handling for concurrent embeds**

If one section embedding fails mid-gather, the artifact cannot be fully
indexed. The failure behavior must be atomic from the caller's perspective:
all-or-nothing. If any embed fails, collect the error, do not call put_vectors,
and return `{"error": "partial_write", ...}` as today. The `asyncio.gather`
call should use `return_exceptions=True` to collect all results before deciding.

**Challenge 5: Existing tests**

Unit tests for `write.py` use `FakeBedrockClient`. If `write.py` switches to
`run_in_executor`, tests must provide an event loop (already present via
`pytest-asyncio`). The `FakeBedrockClient.embed` sync method is called from a
thread — no change needed. Existing test coverage exercises the section loop;
new tests should verify the concurrent path with a semaphore and the
batch put behavior.

---

### Open questions

| Question | Impact | Resolution path |
|---|---|---|
| Does S3 Vectors `PutVectors` have a documented batch size limit? | Medium — affects chunking logic | Check AWS docs / integration test |
| What is the Titan v2 TPS soft limit on on-demand access in `eu-central-1`? | Medium — informs semaphore default | AWS console → Service Quotas → Bedrock |
| Does `asyncio.to_thread` (Python 3.9+) avoid the need for explicit `run_in_executor`? | Low — implementation detail | Yes: `asyncio.to_thread(embed, text)` is equivalent and cleaner |

---

### Summary table

| Option | Impact | Risk | Effort | Recommended |
|---|---|---|---|---|
| A1+A3 concurrent embed + batch put | Very high | Low | Medium | ✅ P1 |
| B2 remove duplicate retry in write.py | Medium | Very low | Trivial | ✅ P2 |
| B1/B3 async sleep + jitter | Medium | Low | Low | ✅ P2 |
| C1 MAX_SECTIONS cap | Low (defensive) | Very low | Trivial | ✅ P3 |
| C2 min section length | Low | Very low | Trivial | ✅ P3 |
| A2 async Bedrock client | High (long-term) | Medium | High | V2 |
| D1 bulk write tool | High (migration) | Medium | High | V2 |
| E1 smaller dimensions | Negligible | High (destructive) | Low | ✗ |

---

## Session 2026-06-01 — Document-level parallelism

### The question

Can the migrating-to-cairn skill parallelize at the **document level** as well —
running several agents simultaneously, each getting a batch of documents to write?
Combined with P1 (section-level concurrent embedding), this gives two independent
axes of parallelism:

```
Documents  ────┬── Batch A → write_artifact → ──┬── concurrent section embeds
               ├── Batch B → write_artifact → ──┤── concurrent section embeds
               └── Batch C → write_artifact → ──┘── concurrent section embeds
```

---

### Hard constraint: stdio transport

The MCP stdio transport is a **one-client-one-server** channel. Each
cairn-mcp process is connected to exactly one client via stdin/stdout. It is
not a server that multiple clients can connect to simultaneously; it is a pipe.

This has a concrete implication for parallel agents:

| Scenario | What happens |
|---|---|
| Sub-agents share the parent's MCP connection | cairn-mcp tool calls are serialized through the parent's transport — LLM inference parallelizes but `write_artifact` calls do not |
| Each sub-agent spawns its own cairn-mcp process | Full parallelism for both LLM and `write_artifact`; each instance runs startup validation (~1–2 s overhead) |

In opencode, the `task` tool spawns sub-agents with the same MCP tool
definitions available. The exact multiplexing behavior (shared process vs.
independent process per agent) is an open question — but the architecture of
the two scenarios determines whether document-level parallelism is complete
or partial. Even partial (LLM inference only) is a meaningful win: description
generation for a 3 KB file takes several seconds of LLM inference, which is
parallelizable regardless of transport behavior.

**S3 concurrent write safety:** Multiple cairn-mcp instances writing to the
same S3 bucket simultaneously is safe. Each artifact gets a unique
deterministic key; `PutObject` is atomic per key; two agents writing different
documents never conflict. S3 Vectors `PutVector` behaves as an upsert —
concurrent writes to different vector keys are independent.

---

### Option space

#### Theme X — Agent-level batching in the skill

**X1 — Two-phase Path A: enrich first, write in parallel**

Split Path A into two distinct phases:

- **Phase 1 (sequential, fast):** The main agent reads all files and generates
  all metadata in-context — title, description, date (from git), type/tier,
  visibility. Produces a structured in-memory list of `ArtifactDescriptor`
  objects (one per file). No Bedrock calls, no S3 calls. Pure LLM inference.
  This is the bulk of the "thinking" work.

- **Phase 2 (parallel):** Split the descriptor list into batches of N
  (e.g. 3–5 per batch). Use the `task` tool to spawn one sub-agent per batch.
  Each sub-agent receives its batch descriptors and calls `write_artifact` for
  each entry. The main agent waits for all sub-agents, collects results, and
  continues to Step 6 (verification).

Sub-agents in Phase 2 have minimal context requirements — they only need the
descriptor data and `write_artifact` access. The expensive work (reading files,
LLM description generation) is already done.

Trade-offs:
- Clean separation of concerns: enrichment is serial (sequential reads, one
  in-context), writing is parallel (API-bound, safe to parallelize).
- Phase 1 adds no latency relative to today (it replaces the sequential
  read-then-write loop with a sequential read-only pass).
- Requires the sub-agents to have cairn-mcp `write_artifact` access — if
  not, they return descriptors to the main agent which writes them (partial
  win: only LLM inference parallelizes).
- Batch size tuning: too small (1 per agent) → high spawn overhead; too large
  → sub-agent context pressure. Sweet spot: 3–5 files per batch for a
  10-document migration.

**X2 — Sub-agents for enrichment only, main agent writes**

Sub-agents only perform the LLM-expensive step: read file → generate
description → return `{path, title, description, date, type, tier}`.
Main agent collects all results then calls `write_artifact` sequentially
(or with the future server-side bulk write tool).

Trade-offs:
- Works regardless of sub-agent MCP access — sub-agents never call cairn-mcp.
- Parallelizes description generation (currently ~3–5 s per file of LLM
  inference) but not the API calls.
- For 10 files: parallel enrichment ~5–10 s; sequential writes ~30–60 s.
  Net: reduces the enrichment tax to near-zero.

**X3 — Parallel agents + manifest coordination artifact**

Main agent generates the full `CAIRN_IMPORT.yaml` manifest (all metadata
resolved, all descriptions written) and saves it to disk. Then spawns N
sub-agents, each given a slice of the manifest path list. Sub-agents read
their slice from the manifest, read the file content, and call `write_artifact`.

Trade-offs:
- Manifest on disk is a clean coordination artifact — sub-agents are stateless
  readers, no shared mutable state.
- Works well if sub-agents have `write_artifact` access.
- Enables retry: failed entries stay in the manifest with an `error` field;
  re-running re-attempts only those.
- Blurs the Path A / Path B boundary — the manifest is currently a Path B
  concept. Could unify both paths.

---

#### Theme Y — Script-level concurrency (lower Path B threshold)

**Y1 — Lower the Path B threshold to 5 (or 1)**

Instead of Path A for < 30 files, use migrate.py for all migrations.
Add `asyncio.gather` to migrate.py for concurrent writes. The agent's sole
job is metadata enrichment (Steps 1–4), and migrate.py handles all I/O
concurrently. The threshold becomes irrelevant.

Trade-offs:
- migrate.py is deterministic Python — no agent orchestration complexity,
  no sub-agent MCP access concerns.
- `asyncio.gather` in a Python script is simpler to reason about and test
  than coordinated multi-agent workflows.
- Parallelism is at the write call level (document-level) AND at the section
  embedding level (P1) — the full two-layer stack.
- Requires migrate.py to call `write_artifact` via the MCP Python client
  with async support, or to call the cairn-mcp Python API directly.
- The agent's contribution reduces to: enrichment manifest → hand off to
  migrate.py. This is already how Path B works — just removes the 30-file
  gate.

**Y2 — migrate.py bypasses MCP, calls AWS directly**

migrate.py imports and calls `write_artifact` (the Python function, not the
MCP tool) directly — same logic, zero transport overhead.

Trade-offs:
- Eliminates MCP round-trip per artifact (saves ~50 ms × N).
- Exposes internal server API to migrate.py — creates a coupling between the
  script and server internals. Requires migrate.py to manage settings,
  clients, etc.
- Not recommended for the short term; violates the "single write path" principle.

---

#### Theme Z — Server-side bulk write (D1 revisited)

**Z1 — `write_artifacts` MCP tool (list of descriptors)**

A single MCP tool accepting a list of artifact descriptors. Internally uses
`asyncio.gather` + semaphore to process all artifacts concurrently, with
section-level concurrency (P1) within each artifact.

```
write_artifacts([
  {type, team, project, tier, title, description, content, ...},
  ...
])
→ [{artifact_id, sections_indexed}, ...]
```

The agent makes **one tool call** regardless of how many documents are in
the batch. No sub-agent orchestration. No transport multiplexing concerns.

Trade-offs:
- Maximum parallelism in one call: document-level AND section-level
  concurrency, all within a single server process with a single async
  event loop.
- The agent does all enrichment sequentially, then fires one tool call.
  Enrichment time is unchanged; write time collapses.
- Large payload: 10 × 3 KB = 30 KB in one MCP call — well within limits.
- Error handling: partial failures must be reported per-artifact in the
  response list.
- Requires significant server-side work (new tool, new test coverage,
  concurrency logic). Higher effort than skill changes.
- The migrating-to-cairn skill and migrate.py both benefit: migrate.py's
  asyncio loop is replaced by a single bulk call.

---

### Selected directions

**L1 — Two-phase Path A (X1) with task-tool sub-agents [skill change]**

Restructure Path A into enrichment phase (all files, main agent, sequential)
then write phase (batches, sub-agents, parallel). The skill instructs the
main agent to:
1. Complete Steps 1–4 for all files before any `write_artifact` call.
2. Split enriched descriptors into batches of 4–5.
3. Use the `task` tool to spawn one sub-agent per batch, passing the
   descriptor data in the prompt.
4. Each sub-agent calls `write_artifact` for its batch.
5. Main agent collects results, identifies any errors, then proceeds to
   Step 6.

This is the highest-impact change to the skill with the lowest server
change surface. Combined with P1, writes become ~5× faster per document
AND multiple documents are processed simultaneously.

**L2 — Lower Path B threshold to 5 files (Y1) [skill + migrate.py change]**

Add async `write_artifact` calls to migrate.py (via `asyncio.gather`). Update
the skill to use migrate.py for any migration ≥ 5 files. The agent always
does enrichment, the script always does writing. Simpler than multi-agent
orchestration; does not require sub-agent MCP access.

These two are **complementary, not competing**:
- L1 parallelizes LLM enrichment work across agents (biggest win for large imports).
- L2 parallelizes API write calls via Python asyncio (biggest win for the write step).
- Both together give the full two-layer stack without requiring a new server tool.
- Z1 (`write_artifacts` tool) becomes a V2 refinement that consolidates both.

---

### Challenges to the selected directions

**Challenge 1: Sub-agent MCP access (opencode task tool)**

If sub-agents spawned by the `task` tool do not receive cairn-mcp MCP
connections, X1 (sub-agents calling `write_artifact`) silently degrades to
sub-agents returning metadata → main agent writes sequentially. The skill must
detect this and have a fallback. Practical mitigation: the sub-agent prompt
includes explicit instructions to call `write_artifact` AND to return a
structured result list regardless, so the main agent can detect failures.
If the tool is absent from the sub-agent's tool list, the sub-agent should
return the enriched metadata — main agent writes sequentially (same as today).

**Challenge 2: Bedrock account TPS with 3 sub-agents × P1 concurrency**

3 sub-agents × P1 semaphore of 5 = up to 15 simultaneous Bedrock
`InvokeModel` calls. Titan v2 on-demand TPS limit is 50 (service quota,
adjustable). 15 concurrent calls is well within the limit for a single user.
For teams with multiple engineers running migrations simultaneously, the
combined request rate could approach the limit — mitigated by P2's
exponential backoff with jitter, which distributes retry bursts.

**Challenge 3: Sub-agent spawn overhead vs. benefit**

Spawning a sub-agent via the `task` tool takes time (LLM initialization,
context loading, tool schema fetch). Rough estimate: 5–15 s per spawn.
For 3 batches: 15–45 s spawning cost. This is justified only if the parallel
work saved exceeds the spawning cost. For 10 documents:

| Work type | Sequential today | With L1 (3 sub-agents) |
|---|---|---|
| LLM enrichment (10 × 5 s) | 50 s | ~20 s (parallel 3-4-3 split) |
| Bedrock embeds (P1, 3 agents × 3 docs × 8 sections) | Already P1 | Already P1 |
| Spawn overhead | 0 | ~30 s |
| Net | 50 s enrichment | ~50 s (break-even at 10 docs) |

At 10 documents, L1 is roughly break-even. It becomes clearly beneficial at
20+ documents. For small migrations (< 10 files), L1 may not be worth the
complexity — Path A as today (sequential enrichment + sequential writes)
is fine once P1 is in place.

**Revised recommendation:** gate the parallel-agent path on file count.
Use sequential Path A for < 10 files; use parallel batching for ≥ 10 files.

**Challenge 4: migrate.py async write calls (Y1)**

migrate.py currently calls `write_artifact` through the MCP Python client
(presumably via `asyncio` calls or subprocess). If it uses the FastMCP
Python client SDK, async `call_tool` is available and `asyncio.gather` works
directly. If it spawns a subprocess per tool call (common in simple MCP
clients), concurrent writes require concurrent subprocesses — less elegant
but still effective.

---

### Revised two-layer parallelism picture

With P1 (session 1) + L1 + L2 (session 2):

```
10 docs, 3 agents (batch 4 / 3 / 3), 8 sections/doc, semaphore=5:

Agent A: doc1(8 embeds → 1 put) + doc2(8→1) + doc3(8→1) + doc4(8→1)
         ≈ 4 × [ceil(8/5) × 300ms + 150ms] = 4 × [600+150] = 3.0 s

Agent B: doc5 + doc6 + doc7
         ≈ 3 × 750ms = 2.25 s

Agent C: doc8 + doc9 + doc10
         ≈ 3 × 750ms = 2.25 s

Wall-clock (agents run in parallel): max(3.0, 2.25, 2.25) = ~3.0 s write time
Plus enrichment (parallel 3 agents, ~5s each): ~5 s
Total: ~8 s vs ~10 minutes today — roughly 75× speedup
```

The estimate is optimistic (ignores spawn overhead, S3 head/put, error paths)
but the order-of-magnitude improvement is robust.

---

### Open questions

| Question | Impact | Resolution path |
|---|---|---|
| Do sub-agents spawned by `task` tool inherit cairn-mcp MCP connections? | High — determines whether X1 works at all | Test empirically; opencode docs or source |
| Does each sub-agent share or spawn its own cairn-mcp process? | High — determines whether writes are truly concurrent | Same test as above |
| Does FastMCP's Python client support async `call_tool` for use in migrate.py? | Medium — needed for Y1 | FastMCP client source / docs |
| What is the practical Bedrock TPS for Titan v2 in the target region? | Medium — informs semaphore defaults | AWS Service Quotas console |

---

### Summary table (both sessions)

| Option | Layer | Impact | Risk | Effort | Recommendation |
|---|---|---|---|---|---|
| P1 — concurrent embed + batch put | Section | Very high | Low | Medium | ✅ V1 |
| P2 — fix retry/throttle | Section | Medium | Very low | Low | ✅ V1 |
| P3 — section count + length caps | Section | Defensive | Very low | Trivial | ✅ V1 |
| L1 — two-phase Path A (task sub-agents) | Document | High (≥10 files) | Medium | Medium | ✅ V1 (gated ≥10) |
| L2 — lower Path B threshold + async migrate.py | Document | High | Low | Medium | ✅ V1 |
| Z1 — `write_artifacts` bulk tool | Both | Very high | Medium | High | V2 |
| A2 — async Bedrock client | Section | High (long-term) | Medium | High | V2 |

---

## Session 2026-06-01 — Service quota research

### Purpose

The open questions from Sessions 1 and 2 referenced two service quota unknowns
that affect semaphore sizing and chunking logic:

1. Does `PutVectors` have a published batch size limit?
2. What is the Titan Text Embeddings v2 on-demand TPS limit in the target region?

This section records the confirmed answers so they are not re-researched.

---

### S3 Vectors — confirmed limits

| Limit | Value | Source |
|---|---|---|
| `PutVectors` max vectors per call | **500** | AWS S3 Vectors docs |
| Throughput (whichever reached first) | **1,000 req/s/index** or **2,500 vectors/s/index** | AWS S3 Vectors docs |
| `GetVectors` / `QueryVectors` | "hundreds per second" (exact limit unpublished) | AWS S3 Vectors docs |
| `DeleteVectors` | 500 vectors/call (same cap as `PutVectors`) | AWS S3 Vectors docs |

**Implication for P1 (batch put):** At 5–15 sections per artifact, a single
`put_vectors` call per artifact is nowhere near the 500-vector cap or the
2,500-vectors/s throughput limit. Chunking logic (`chunk at 100`, noted in
Session 1 Challenge 3) is a defensive upper bound that can be set at 500 to
match the true API limit. For typical migration workloads (10 documents ×
15 sections = 150 vectors total across all write calls), these limits are
irrelevant.

---

### Bedrock Titan Text Embeddings v2 — confirmed limits

**Do we call `invoke_model`?** Yes. `BedrockClientImpl.embed` (line 73 of `bedrock.py`)
calls `self._client.invoke_model(modelId=..., body=...)` on the `bedrock-runtime` boto3
client. There is no separate "embed" API — embedding models are invoked through the same
`InvokeModel` API as text generation models.

**Does `invoke_model` consume tokens?** Yes. For Titan Text Embeddings v2 the response body
includes `inputTextTokenCount` (visible in `bedrock.py` line 80 comment). There are only
**input tokens** — embedding models do not produce output tokens in the text-generation
sense, but the input text is tokenised before embedding and those tokens count.

**Actual quota values (verified in Service Quotas console, eu-central-1):**

| Quota name | Value | Adjustable |
|---|---|---|
| On-demand model inference **requests per minute** for Amazon Titan Text Embeddings V2 | **6,000 RPM** | Not adjustable |
| On-demand model inference **tokens per minute** for Amazon Titan Text Embeddings V2 | **300,000 TPM** | Not adjustable |
| Model units per provisioned model for Amazon Titan Text Embeddings V2 | 0 (default) | Account level |
| Batch inference job size | 5 GB | Not adjustable |
| Records per batch inference job | 100,000 | Account level |

**Correction to earlier findings:**
- The previous session stated "no published on-demand quota exists" — that was **incorrect**.
  Both RPM and TPM quotas are published and visible in the console.
- The `bedrock-runtime` quota documentation states RPM quotas "are no longer enforced" —
  but the console still lists 6,000 RPM for Titan Text Embeddings V2. This contradiction
  likely means the RPM-no-longer-enforced policy applies to *text generation* models only,
  and embedding models retain RPM quotas. Whether throttling is RPM-triggered or
  TPM-triggered in practice remains unverified.

**Implication for concurrency defaults:**

At 6,000 RPM = **100 req/s** and 300,000 TPM = **5,000 tokens/s** (assuming ~300 tokens
per section):

| Scenario | Sustained req/s | Sustained tok/s | vs RPM limit | vs TPM limit |
|---|---|---|---|---|
| Serial today (300 ms/call) | ~3 req/s | ~1,000 tok/s | 3 % | 20 % |
| `EMBED_CONCURRENCY=5`, 1 agent | ~16 req/s | ~5,000 tok/s | 16 % | 100 % ⚠️ |
| `EMBED_CONCURRENCY=3`, 1 agent | ~10 req/s | ~3,000 tok/s | 10 % | 60 % |
| `EMBED_CONCURRENCY=5`, 3 agents | ~50 req/s | ~15,000 tok/s | 50 % | 300 % ⚠️⚠️ |

The TPM limit is the **binding constraint** at high concurrency. However, for a typical
migration (10 docs × 8 sections × 300 tokens = 24,000 tokens total), the job completes in
seconds and the *total* token count is only 8 % of the per-minute budget — burst, not
sustained load. Throttling at these scales would only occur if embeds completed faster than
~50 ms/call (unrealistic given network RTT).

**Concurrency combinations and quota headroom:**

Assuming ~300 tokens/section and ~300 ms round-trip latency per embed call.
The binding constraints are RPM (100 req/s) and TPM (~5,000 tok/s sustained).

| `SECTION_CONCURRENCY` | `MIGRATE_AGENT_CONCURRENCY` | Max concurrent calls | Sustained req/s | vs 100 req/s RPM | Token burst | vs ~5,000 tok/s TPM |
|---|---|---|---|---|---|---|
| 5 | 3 | 15 | ~50 req/s | 50 % ✅ | 4,500 tok | 90 % ✅ |
| 10 | 1 (single-agent) | 10 | ~33 req/s | 33 % ✅ | 3,000 tok | 60 % ✅ |
| 8 | 3 | 24 | ~80 req/s | 80 % ✅ | 7,200 tok | 144 % ⚠️ |
| 10 | 2 | 20 | ~67 req/s | 67 % ✅ | 6,000 tok | 120 % ⚠️ |
| 10 | 3 | 30 | ~100 req/s | 100 % ⚠️ | 9,000 tok | 180 % ⚠️ |

**Rule of thumb:** keep `SECTION_CONCURRENCY × MIGRATE_AGENT_CONCURRENCY ≤ 15` to
maintain comfortable margin below both limits. If you raise one knob, lower the other.

**Proposed defaults (user-configurable):**

| Parameter | Default | Rationale |
|---|---|---|
| `SECTION_CONCURRENCY` (server env var) | **5** | 50 % RPM, 90 % TPM burst at 3 agents — good margin; for single-agent use alone, operators can raise to 10 |
| `MIGRATE_AGENT_CONCURRENCY` (skill parameter) | **3** | Spawn overhead (~30 s for 3 agents) justified at ≥ 10 files; combined 5 × 3 = 15 concurrent calls stays within the ≤ 15 rule of thumb |

The **5 × 3 combination is the recommended default**: 50 % RPM headroom, 90 % TPM
burst, and a comfortable buffer for teams sharing an AWS account across concurrent
sessions. Operators with provisioned throughput or a dedicated account can raise
`SECTION_CONCURRENCY` to 10 while keeping `MIGRATE_AGENT_CONCURRENCY` at 2–3.

Reference URLs:
- **Bedrock runtime quotas (all models):** <https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html>
- **How tokens are counted (burndown rate):** <https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html>
- **Bedrock endpoints and quotas (region-specific table):** <https://docs.aws.amazon.com/general/latest/gr/bedrock.html>

---

### Resolved open questions

| Question (from Sessions 1 & 2) | Answer |
|---|---|
| Does S3 Vectors `PutVectors` have a documented batch size limit? | **Yes — 500 vectors/call** |
| What is the Titan v2 on-demand quota in `eu-west-1` (same values confirmed in `eu-central-1`)? | **6,000 RPM and 300,000 TPM — both published in Service Quotas console, both not adjustable** |
| Does `asyncio.to_thread` avoid `run_in_executor`? | **Yes — `asyncio.to_thread(fn, arg)` is equivalent and cleaner (Python 3.9+)** |
| Are `SECTION_CONCURRENCY` and `MIGRATE_AGENT_CONCURRENCY` the right knobs? | **Yes — user-controlled with defaults of 5 and 3 respectively (5 × 3 = 15 combined, the recommended safe ceiling)** |

### Remaining open question

| Question | Impact | Resolution path |
|---|---|---|
| Do sub-agents spawned by `task` tool inherit cairn-mcp MCP connections? | High — determines whether L1 write parallelism works or falls back to metadata-return | Test empirically during L1 implementation |
| Is the 6,000 RPM quota enforced for embedding models or only listed? | Medium — determines whether RPM or TPM is the actual throttle trigger | Verify empirically or via AWS support |

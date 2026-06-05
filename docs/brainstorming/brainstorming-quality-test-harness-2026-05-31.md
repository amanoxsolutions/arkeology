---
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Quality Test Harness for cairn-mcp

## Description

Beyond functional integration tests (do the tools work?), cairn-mcp needs a quality evaluation
harness that asks: *do the tools work well?* The harness simulates real multi-project usage —
migration, writing, searching, cross-scope discovery, synthesis — and evaluates whether the right
artifacts surface for the right queries, whether access gates hold, and whether synthesis behaves
coherently. A secondary goal is to enable empirical comparison of embedding models and vector
dimensions, so teams can choose the configuration that performs best for their content domain.

The user's vision: two simulated project repos, each with its own AGENTS.md and local context; a
supervisor agent running a testing-quality skill; developer agents operating inside each project;
and a structured evaluation pass covering retrieval precision, cross-scope gating, synthesis, and
orphaned-reference detection. Parametric: same test run against different embedding configs.
Potentially packaged as a cairn-mcp feature so adopting teams can benchmark their own corpus.

---

## Session 2026-05-31

---

### Theme 1 — What "quality" means for cairn-mcp

Quality in cairn-mcp is not a single metric. Five independent quality dimensions emerge:

| Dimension | Question |
|---|---|
| **Retrieval precision** | For a given query, do the *right* artifacts appear in the top-K results? |
| **Retrieval recall** | Are *all* expected artifacts surfaced, not just a subset? |
| **Cross-scope gating** | Are tier-2 artifacts and hidden artifacts reliably absent from foreign-scope results? |
| **Synthesis coherence** | Does the synthesise_artifacts output assemble the right sources, and does the resulting artifact make sense? |
| **Freshness/orphan detection** | Does the synthesis freshness check correctly identify stale or orphaned references after source mutations? |

Section-level indexing (D12) and description quality (FR-09) are not abstract principles — they
have directly measurable effects on retrieval quality. The harness must be able to test both in
isolation.

---

### Theme 2 — Harness architecture options

Four architectural options were considered, from fully agent-driven to fully scripted.

#### Option A — Fully agent-driven (supervisor + sub-agents, no scripts)

A supervisor agent reads a testing-quality skill, spawns developer sub-agents in each project
folder, observes their MCP tool calls and responses, and judges quality using LLM reasoning.
No Python test script involved.

| Pros | Cons |
|---|---|
| Tests exactly the workflow agents will actually use | Non-deterministic: different runs produce different results |
| Flexible: supervisor can recover from unexpected agent paths | Expensive: many LLM calls per test run |
| Exercises the full agent-to-MCP-to-AWS chain end-to-end | Slow: 10–30 minutes per full harness run |
| The testing-quality skill documents the workflow precisely | Hard to diff: "did quality improve?" is hard to quantify across runs |

#### Option B — Script-driven with LLM evaluation only at the judgment step

Python scripts write the fixture artifacts (using `write_artifact` directly), execute the test
operations (search, synthesise, etc.), capture raw results, and pass them to an LLM evaluator
that scores relevance. Agents are not involved in the write or search steps — only in evaluation.

| Pros | Cons |
|---|---|
| Reproducible: same fixture artifacts every run | Does not exercise agent behavior (agents not in the loop) |
| Fast: no LLM calls until evaluation | Evaluation still LLM-dependent and non-deterministic |
| Easy to add to CI with `pytest.mark.quality` | Does not validate the full agent workflow |
| Cheapest option for parametric runs | |

#### Option C — Hybrid: scripted fixtures + agent operations + scripted assertions (recommended)

Scripts create fixture project directories and pre-load artifacts (migration scenario). Agents
perform the test operations (search, synthesise) in their own project context as they naturally
would. Scripted assertions validate the structural results (cross-scope gating, synthesis source
lists, orphan detection). An LLM evaluator scores retrieval quality.

| Pros | Cons |
|---|---|
| Agents in the loop for operations (realistic) | More complex orchestration than Option B |
| Scripted assertions for deterministic gating checks | Agent behavior still variable |
| LLM scoring only for subjective quality (not correctness) | Slower than pure scripted |
| Structured report: metrics that can be compared across runs | |

#### Option D — Parametric benchmark CLI

A standalone `scripts/benchmark.py` (PEP 723 inline deps) that takes a config file listing
embedding models and vector dimensions, spins up a fresh index per configuration, runs the
test corpus against each, and produces a comparative JSON/Markdown report.

This option is orthogonal to A/B/C — it wraps whatever harness is chosen and runs it N times
across N configurations.

**Recommended architecture: Option C (hybrid) with Option D as the parametric wrapper.**

---

### Theme 3 — Fixture design

#### Two simulated projects

```
tests/quality/
  fixtures/
    project-alpha/          # "platform-team / infra-core"
      AGENTS.md             # context for developer agents in this scope
      docs/                 # pre-existing docs to be migrated
        adr/                # → tier 3, type: adr
        specs/              # → tier 3, type: spec
        brainstorming/      # → tier 2, type: session-summary
        notes/              # → tier 2, type: impl-note
                            # no .env file — runtime overrides main project .env
    project-beta/           # "platform-team / security-api"
      AGENTS.md
      docs/
        adr/
        specs/
                            # no .env file — runtime overrides main project .env
```

#### What the fixture docs must cover

The fixture corpus must be designed so that each quality dimension is testable with known ground truth:

| Scenario | What it tests | Ground truth |
|---|---|---|
| ADR in project-alpha on VPC peering | Cross-scope discovery from project-beta | Must appear in project-beta search, must NOT appear if visibility=hidden |
| Code review (tier 2) in project-alpha | Cross-scope isolation | Must NOT appear in project-beta search, ever |
| Two semantically similar specs in project-alpha | Retrieval precision | Query "authentication design" should return spec A (auth) not spec B (storage) |
| Spec with many `##` sections | Section-level recall | Query targeting one section should surface this artifact |
| Artifact with a minimal description | Description quality impact | Compare with an artifact with a rich description for the same query |
| Synthesis artifact citing 3 sources | Synthesis + orphan detection | Archive one source → freshness check flags it; delete one source → synthesis references it as orphaned |
| Two ADRs, one older than the synthesis | Freshness check | Synthesis pre-dates the ADR update → flagged as stale |

#### Ground truth format

Stored as `tests/quality/ground_truth.yaml`:

```yaml
queries:
  - id: q-vpc-peering
    query: "VPC peering architecture decisions"
    project_scope: project-beta   # which project runs this query
    expected_in_top_3:
      - artifact_slug: adr-vpc-peering     # project-alpha tier 3 shared → must appear
    expected_absent:
      - artifact_slug: review-vpc-impl     # project-alpha tier 2 → must be absent always
    expected_absent_if_hidden:
      - artifact_slug: adr-vpc-peering     # if visibility=hidden → also absent

  - id: q-auth-design
    query: "authentication token validation"
    project_scope: project-alpha
    expected_in_top_3:
      - artifact_slug: spec-auth-service
    expected_not_in_top_3:
      - artifact_slug: spec-storage-service   # semantically distant, should not rank
```

---

### Theme 4 — Evaluation methodology

#### Retrieval quality metrics

For each query in `ground_truth.yaml`:
- **Precision@K** (K=3, K=5): fraction of top-K results that are in the expected set
- **Recall@K**: fraction of expected artifacts that appear in top-K
- **MRR (Mean Reciprocal Rank)**: 1/rank of the first expected result — single-number summary
- **Hit@1**: did the top result match? — simple headline metric

These are deterministic: given the artifact corpus and embedding model, the same query always
produces the same ranked list (S3 Vectors is deterministic for a fixed corpus). No LLM needed
for these metrics.

#### Cross-scope gating: boolean assertions

These are not probabilistic. Either the artifact appears or it does not. Script checks, not LLM:
- tier-2 from foreign scope: always absent
- tier-3 hidden from foreign scope: always absent
- tier-3 shared from foreign scope: always present

#### Synthesis quality: LLM judge

After `synthesise_artifacts` returns and the agent writes the synthesis:
- The supervisor reads the synthesis artifact and the source artifacts
- Prompts an LLM judge: "Given these sources, does this synthesis accurately represent them?
  Score 1–5 and explain your reasoning."
- Scores are recorded per run

#### Description quality A/B

Two variants of the same artifact: one with a rich description, one with a weak description.
Compare Precision@3 for the same query. This directly validates the description quality guidance
in the recommended AGENTS.md snippet (NFR-12).

#### Section-level vs. document-level indexing A/B

Two writes of the same artifact: one with `##` sections, one flattened to a single body (no `##`).
Compare MRR for section-specific queries. This validates D12.

---

### Theme 5 — Agent orchestration

#### The testing-quality skill

A file at `.agents/skills/testing-quality/SKILL.md` (following the agentskills.io standard)
defines the supervisor workflow:

```
1. Setup: verify fixture projects exist; provision isolated AWS prefixes for this test run
2. Migration pass: run a developer agent in project-alpha with the migration skill to ingest
   project-alpha/docs/; verify all expected artifact IDs are in the store
3. Write pass: run developer agents in each project to write new artifacts (spec, ADR, code review)
   per the scenario list
4. Search evaluation: for each query in ground_truth.yaml, run search_artifacts from the correct
   project scope; record ranked results
5. Cross-scope checks: run list_artifacts and search_artifacts from project-beta for items
   that should / should not cross the boundary; record pass/fail
6. Synthesis pass: run synthesise_artifacts in project-alpha; agent writes back synthesis artifact
7. Orphan/freshness pass: archive one source artifact; run synthesis freshness check; verify flags
8. Scoring: evaluate Precision@K, Recall@K, MRR for retrieval; boolean pass/fail for gating;
   LLM judge for synthesis quality
9. Report: write structured JSON + Markdown report to tests/quality/results/YYYY-MM-DD/
10. Teardown: delete all artifacts written during this run
```

#### How agents operate in project scope

Each developer agent is launched with:
- Working directory = `tests/quality/fixtures/project-alpha/` or `project-beta/`
- MCP server config pointing to the main `.env` with runtime-injected scope overrides
  (`WRITE_PREFIX`, `READ_PREFIXES`) — unique per run (see C1)
- AGENTS.md in that directory providing project context

The supervisor agent does not write artifacts — it only reads results and evaluates.

#### Unique run prefixes

Each test run uses a short hex run ID to scope its prefixes:
```
project-alpha WRITE_PREFIX = quality/{run_id}/alpha
project-beta  WRITE_PREFIX = quality/{run_id}/beta
```
This ensures test runs do not interfere with each other or with production data. Teardown
deletes only artifacts under `quality/{run_id}/`. The run ID is generated by the quality runner
at startup (see C1 for the full env override approach).

---

### Theme 6 — Parametric embedding comparison

To compare embedding models and vector dimensions, a full quality run must be repeatable with
different configurations. The blocker is that S3 Vectors indexes have a fixed dimension set at
creation time.

#### Infrastructure approach

```
tests/quality/configs/
  default.yaml          # titan-embed-text-v2:0, 1024d (current default)
  titan-v1.yaml         # titan-embed-text-v1:0, 1536d
  titan-v2-256d.yaml    # titan-embed-text-v2:0, 256d (reduced dimension)
  cohere-en.yaml        # cohere.embed-english-v3 (if enabled)
```

Each config specifies:
```yaml
bedrock_embedding_model: "amazon.titan-embed-text-v2:0"
vector_dimension: 1024
vectors_index: "cairn-quality-1024d"   # pre-provisioned index for this dimension
```

Config files specify only the *deltas* from the main `.env` (see C1). The default config
specifies no overrides — it runs with whatever is in `.env`.

#### Run all configs, produce comparative report

```
uv run scripts/benchmark.py --configs tests/quality/configs/ --report-dir tests/quality/results/
```

Output:

```
┌──────────────────────────────────────────────┐
│ Quality benchmark — 2026-05-31               │
├─────────────────────┬─────────┬──────┬───────┤
│ Config              │ P@3     │ MRR  │ Cost  │
├─────────────────────┼─────────┼──────┼───────┤
│ titan-v2 1024d      │  0.87   │ 0.91 │ $0.02 │
│ titan-v1 1536d      │  0.79   │ 0.84 │ $0.03 │
│ titan-v2 256d       │  0.71   │ 0.76 │ $0.01 │
└─────────────────────┴─────────┴──────┴───────┘
```

#### Customer self-evaluation: a separate future track

A team adopting cairn-mcp who wants to find the best embedding configuration for their own
content domain is a different use case from this harness. They need to bring their own corpus,
define their own ground truth queries, and receive a recommendation for their deployment
configuration. That feature — possibly a `skills/evaluating-config/` skill or a standalone
script — shares some infrastructure with the parametric benchmark (config YAML files,
comparative report) but serves a different audience and answers a different question. It is
noted here as a future track and not conflated with the quality harness. See C7.

---

### Theme 7 — Reporting and CI integration

#### Report format

```
tests/quality/results/YYYY-MM-DD-{run_id}/
  report.md               # human-readable summary with tables
  report.json             # machine-readable for CI parsing and trend analysis
  queries/
    q-vpc-peering.json    # per-query results: ranked list, scores, ground truth match
    q-auth-design.json
  gating/
    cross-scope-checks.json   # all boolean assertions: pass/fail per scenario
  synthesis/
    synthesis-output.md       # the synthesis artifact produced
    synthesis-score.json      # LLM judge score + reasoning
```

#### CI integration

```bash
# Nightly quality run (not blocking — runs separately from unit/integration tests)
uv run pytest tests/quality/ -q -m 'quality' --timeout=600

# Or via the benchmark script directly (more control):
uv run scripts/benchmark.py --configs tests/quality/configs/default.yaml
```

The quality tests are expensive (real AWS calls, real LLM calls) and slow. They belong in a
nightly or pre-release gate, not the per-commit CI. `pytest.mark.quality` separates them from
`pytest.mark.integration`.

#### Trend analysis

Store reports in git (or as tier 3 artifacts in cairn-mcp itself — meta but appropriate).
Compare MRR across commits to detect embedding quality regressions when upgrading the model
or changing the indexing strategy.

---

### Theme 8 — What would it take to build this

Estimated effort, ordered by dependency:

| Layer | What to build | Effort estimate |
|---|---|---|
| **F1** Ground truth corpus | Write ~20–30 fixture markdown docs in 2 project dirs; curate `ground_truth.yaml` with ~8–10 queries | 1–2 days |
| **F2** Metrics script | `scripts/quality_runner.py`: load ground truth, call search_artifacts, compute P@K / MRR / Hit@1 | 1 day |
| **F3** Cross-scope assertion script | Deterministic pass/fail checks; no LLM needed | 0.5 days |
| **F4** Synthesis + freshness scenario | Script to set up synthesis scenario, run the tools, assert freshness check output | 0.5 days |
| **F5** LLM judge for synthesis | Prompt + call Bedrock/OpenAI to score synthesis quality 1–5 | 0.5 days |
| **F6** Testing-quality skill | `.agents/skills/testing-quality/SKILL.md` driving the agent workflow | 1 day |
| **F7** Report writer | Produce `report.md` + `report.json` from collected results | 0.5 days |
| **F8** Parametric benchmark | `scripts/benchmark.py` looping over config files, provisioning indexes | 1 day |
| **F9** CI integration | `pytest.mark.quality` gate, nightly schedule | 0.5 days |

**Total core harness (F1–F7):** ~5 days  
**Parametric comparison (F8):** +1 day  
**CI integration (F9):** +0.5 days  
**Packaging as a cairn-mcp MCP tool:** +2 days (future)

---

### Selected directions and trade-offs

#### Selected: Hybrid architecture (Option C)

Reasoning: purely scripted (Option B) doesn't validate agent behavior. Fully agent-driven
(Option A) is expensive, slow, and hard to compare across runs. The hybrid gives deterministic
assertions for correctness (gating) and quantitative metrics for quality (MRR), with agents
in the loop only for the operations that matter (search, synthesise).

#### Selected: YAML ground truth over LLM-judged ground truth

For retrieval metrics, the ground truth is human-curated and stored in YAML. This makes the
metrics deterministic and comparable across runs and model configurations. LLM judging is
reserved for synthesis quality, where "correct" is genuinely subjective.

#### Selected: Unique run prefixes for isolation

Each test run writes to its own prefix sub-namespace. This prevents cross-run pollution and
makes teardown safe (delete only own prefix). Critical for parametric runs that execute
concurrently or sequentially.

#### Selected: `pytest.mark.quality` separate from integration tests

Quality tests are expensive (minutes, real Bedrock calls, real S3 Vectors queries). They must
not block per-commit CI. The separation makes the gate explicit.

---

### Stress-tests (hidden assumptions and failure modes)

1. **"Ground truth is stable"** — it isn't. Embedding model updates, new fixture artifacts, and
   prompt changes can all shift relevance scores. The YAML ground truth needs a review process;
   otherwise metrics degrade silently as the corpus evolves.

2. **"S3 Vectors is deterministic for a fixed corpus"** — mostly true for pure cosine similarity,
   but metadata filter ordering and tie-breaking are not guaranteed. Tests should use top-3 or
   top-5 windows, not exact rank-1 assertions.

3. **"The fixture corpus is representative"** — 20–30 synthetic software project documents are
   the target domain for cairn-mcp. Specialized vocabularies (legal, medical, embedded systems)
   are explicitly not the target use case. Start with something; refine as real usage reveals
   retrieval gaps. See C4.

4. **"LLM judge for synthesis is reliable"** — LLM evaluation of LLM output has well-known
   biases (verbosity preference, positional bias). The synthesis judge must use a structured rubric
   and evaluate specific claims, not overall impressiveness.

5. **"Parametric runs are cheap"** — provisioning a new S3 Vectors index, running migration, then
   running 10 queries each with N embedding calls adds up fast. Each config run likely costs
   $0.50–$2.00 in Bedrock + S3 Vectors calls. Comparing 5 configs = $2.50–$10 per benchmark run.
   Document this clearly; don't make it part of nightly CI by default.

6. **"The testing-quality skill drives agents reliably"** — agent behavior is non-deterministic.
   The skill-driven agent path may take shortcuts (skip writing certain artifacts, hallucinate
   results). The scripted fallback path (Option B) should remain as a `--no-agents` flag in
   `benchmark.py` so the metric computation can run without agents when debugging.

7. **"Section-level indexing always beats document-level"** — D12's benefit depends on query
   specificity. For broad queries ("authentication"), document-level may rank just as well. The
   A/B test in the harness will reveal this and inform when section-level matters most.

8. **"The harness belongs in this repo"** — confirmed (see C6). Run-scoped prefixes
   (`quality/{run_id}/`) isolate test data from production data in the same bucket.

---

### Open questions — all resolved

1. ~~**Fixture authorship**~~ — **resolved**: all synthetic. See C8.

2. ~~**Supervisor agent vs. script**~~ — **resolved**: AI agent is the supervisor; Python
   helper scripts bundled in the skill handle objective metrics. See C9.

3. ~~**Cross-project READ_PREFIXES setup**~~ — **resolved**: see C1.

4. ~~**Embedding model availability**~~ — **resolved**: see C3.

5. ~~**Customer self-evaluation**~~ — **resolved**: separate future track. See C7.

---

### Corrections and refinements — 2026-05-31

#### C1 — Fixture projects do not carry their own `.env` files; purpose clarified

**Purpose of the quality harness:** this harness exists to evaluate and improve the cairn-mcp
tool itself using controlled, quality-specific simulated projects. It is not about testing a
team's production configuration. There is no "production" here — the `.env` at the repo root is
the project's test/development configuration, exactly the same file used by the integration test
suite. The quality harness reuses it for the same reason integration tests do: it is the
controlled test environment.

**What this means for the fixture projects:** the fixture project directories carry only
`AGENTS.md` and `docs/`. They do not carry `.env` files of any kind. The quality runner reuses
the repo's `.env` (same bucket, same index, same region, same embedding model as integration
tests) and overrides only the scope-related variables at runtime to isolate each simulated
project and each test run:

```python
# quality runner startup
from dotenv import dotenv_values
import uuid

base_env = dotenv_values(".env")   # same .env as integration tests
run_id   = uuid.uuid4().hex[:8]    # unique per run — prevents cross-run pollution

env_alpha = {**base_env,
             "WRITE_PREFIX":   f"quality/{run_id}/alpha",
             "READ_PREFIXES":  f"quality/{run_id}/beta"}

env_beta  = {**base_env,
             "WRITE_PREFIX":   f"quality/{run_id}/beta",
             "READ_PREFIXES":  ""}   # one-way by default; specific scenarios override this
```

For parametric runs, additionally override the embedding and index variables:
```python
env_256d = {**env_alpha,
            "BEDROCK_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0",
            "BEDROCK_DIMENSIONS":      "256",
            "VECTORS_INDEX":           "cairn-quality-256d"}   # separate index per dimension
```

Each config in `tests/quality/configs/` specifies only the *deltas* from the base `.env`:

```yaml
# tests/quality/configs/default.yaml  — no overrides; runs with whatever is in .env
label: "default"

# tests/quality/configs/titan-v2-256d.yaml
label: "titan-v2 256d"
overrides:
  BEDROCK_EMBEDDING_MODEL: "amazon.titan-embed-text-v2:0"
  BEDROCK_DIMENSIONS: "256"
  VECTORS_INDEX: "cairn-quality-256d"
```

Fixture directory structure:

```
tests/quality/
  fixtures/
    project-alpha/          # simulated project: "platform-team / infra-core"
      AGENTS.md             # project context for developer agents in this scope
      docs/
        adr/
        specs/
        brainstorming/
        notes/
    project-beta/           # simulated project: "platform-team / security-api"
      AGENTS.md
      docs/
        adr/
        specs/
  configs/
    default.yaml
    titan-v2-256d.yaml
    titan-v1-1536d.yaml
  ground_truth.yaml
  results/                  # gitignored
```

**Customer self-evaluation is a separate concern** — a future track, not part of this harness.
See C7.

---

#### C2 — Skill path: `testing-quality`, not `quality-testing`

All agent skill names follow the gerund-based convention (`testing-quality`, not
`quality-testing`). The skill lives at:

```
.agents/skills/testing-quality/SKILL.md
```

All references to `quality-testing` in the brainstorm above should be read as `testing-quality`.
The effort estimate row F6 is updated accordingly.

---

#### C3 — Embedding model availability: Amazon models need no opt-in

AWS documentation confirms: *"Access to all Amazon Bedrock foundation models is enabled by
default with the correct AWS Marketplace permissions."* Critically, Amazon-native models
(Titan family, including `amazon.titan-embed-text-v2:0` and `amazon.titan-embed-text-v1:0`)
are **not sold through AWS Marketplace and have no product IDs** — they are always available to
any IAM identity with `bedrock:InvokeModel` permission, with no subscription step and no
auto-enable timer.

Third-party models (Cohere, Anthropic) are sold through AWS Marketplace and auto-enable on first
invocation if the IAM role has `aws-marketplace:Subscribe`. The auto-enable can take up to
15 minutes the first time. For quality benchmark runs that include third-party models: either
verify the subscription is active before the run, or accept the first-run latency.

**Practical implication for parametric benchmark:** the default config (`titan-v2 1024d`) and
any reduced-dimension Titan variant (`titan-v2 256d`) require no special preparation. These
are the most useful parametric cases (same model, different dimension) and cost nothing to
enable. Third-party model comparisons are an optional addition — useful but not required for
the core benchmark.

---

#### C4 — Corpus representativeness: software project artifacts are sufficient

The fixture corpus covers software engineering artifacts: ADRs, implementation notes, code
reviews, session summaries, specs, brainstorming docs. This is exactly the cairn-mcp target
domain. Specialized domains (legal, medical, embedded systems) are explicitly not the target
use case. The `--no-agents` fallback flag ensures the corpus can be extended by anyone who
wants to test against a domain-specific corpus, but the default corpus is representative.

Start with something. Refine as real usage reveals retrieval gaps.

---

#### C5 — No existing agent supervisor runtime in this project

The project currently has no agent orchestration runtime. The quality harness must therefore
take one of two paths:

- **Path A (simpler, build first)**: the harness is a Python script (`scripts/quality_runner.py`)
  that calls the MCP server tools directly via `subprocess` + MCP stdio protocol (or via the
  MCP Python SDK client). No agent runtime needed. The `testing-quality` skill documents the
  intent and workflow; the script implements it deterministically. The "agent in the loop"
  is a future upgrade once an agent runtime exists.

- **Path B (future)**: a proper supervisor agent uses the `testing-quality` skill, spawns
  developer sub-agents in each project fixture folder, and evaluates results. This is the
  full vision — but it requires an agent runtime that does not yet exist in this repo.

**Decision for the build:** start with Path A (scripted). The `testing-quality` skill is still
authored and documents what the supervisor would do — it doubles as the specification for the
script. The skill can later drive an agent when the runtime is available.

---

#### C6 — Harness lives in this repo: confirmed

The quality harness, all fixture docs, config files, the benchmark script, and the
`testing-quality` skill all live in this repository alongside the server source. The harness
uses the same AWS resources as the integration test suite, scoped to dedicated `quality/`
prefixes per run. No separate account or separate repository is needed.

---

#### C7 — Customer self-evaluation is a separate future track

The quality harness is an internal tool development concern: controlled simulated projects,
known ground truth, software engineering artifacts, run by the cairn-mcp team to improve the
tool. It is not for customer adoption evaluation.

A customer wanting to evaluate cairn-mcp against their own data and content domain is a
different use case with different requirements:
- The corpus is the customer's own artifacts (not synthetic fixture docs)
- The ground truth must be established by the customer (what queries matter to them)
- The embedding model comparison is meaningful relative to their vocabulary
- The output is a recommendation for their deployment configuration, not a regression signal
  for the tool developers

This is a valid and valuable future feature — potentially a skill (`skills/evaluating-config/`)
or a standalone script delivered alongside the migration skill. It should not be conflated with
the quality harness. Both share some infrastructure (parametric runs, comparative reports) but
serve different audiences and answer different questions.

---

#### C8 — Fixture corpus: all synthetic, two simulated software teams

All fixture documents are purpose-built synthetic markdown files. Using the cairn-mcp project's
own real documentation was considered and rejected: real docs are richer but their retrieval
behaviour is harder to reason about (no controlled ground truth), and the test corpus would be
coupled to this repo's own evolving content.

Synthetic docs are strictly more useful here: each document can be crafted to exercise a
specific retrieval scenario precisely, and the ground truth in `ground_truth.yaml` is
deterministic from day one.

**Two simulated projects:**

| Project | Simulated team | Prefix |
|---|---|---|
| `project-net` | Network infrastructure team | `quality/{run_id}/net` |
| `project-svc` | Microservices development team | `quality/{run_id}/svc` |

The network team writes ADRs about VPC topology, peering decisions, subnet design, and
infrastructure standards — tier 3 shared artifacts intended to be discovered by the
microservices team. The microservices team writes implementation notes, code reviews, session
summaries, and specs about their services — tier 2 artifacts that stay local, plus their own
ADRs. The cross-scope scenario: the microservices team has `READ_PREFIXES` pointing at the
network team prefix; the network team does not read from the microservices prefix.

This pairing produces clean, testable ground truth:
- network ADRs → must appear in microservices search results
- microservices code reviews → must never appear in microservices search when queried from
  the network scope (one-way: network does not subscribe to microservices)
- network hidden artifacts → must never appear in microservices results regardless of tier

---

#### C9 — Supervisor is the AI agent; helper scripts are bundled in the skill

The question "is there an agent runtime in this project?" was the wrong question. The agent
runtime is the AI agent tool itself (opencode or any agent that supports the testing-quality
skill). No custom orchestration framework needs to be built into this repo.

**Division of responsibility:**

| Concern | Who handles it |
|---|---|
| Orchestrating the test scenario end-to-end | AI agent running the `testing-quality` skill |
| Spawning developer sub-agents in each project folder | AI agent (task/spawn mechanism) |
| Calling cairn-mcp MCP tools (write, search, synthesise…) | Developer sub-agents via MCP |
| Objective metric computation (P@K, MRR, Hit@1) | Python helper script (called by agent) |
| Boolean gating assertions | Python helper script (called by agent) |
| Report generation (JSON + Markdown) | Python helper script (called by agent) |
| Teardown (delete all quality/{run_id}/ artifacts) | Python helper script (called by agent) |
| Synthesis quality judgment | AI agent (LLM reasoning in-context) |

**Scripts are bundled inside the skill** following the agentskills.io convention
(https://agentskills.io/skill-creation/using-scripts). Each script lives at a relative path
from the skill root and is referenced in `SKILL.md`:

```
.agents/skills/testing-quality/
  SKILL.md
  scripts/
    setup_run.py          # generate run_id; emit env overrides for each project scope
    compute_metrics.py    # load ground_truth.yaml + search results; compute P@K, MRR, Hit@1
    assert_gating.py      # boolean cross-scope gating assertions
    write_report.py       # produce report.md + report.json from collected results
    teardown_run.py       # delete all artifacts under quality/{run_id}/
```

All scripts are PEP 723 self-contained (inline `# /// script` dependency block), run with
`uv run scripts/<name>.py`. Structured JSON to stdout; diagnostics to stderr. Each script
supports `--help` and destructive scripts support `--dry-run`.

The fixture docs and `ground_truth.yaml` live in `tests/quality/` (repo test fixtures, not
skill content). Scripts reference them by relative path from the repo root.

---
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-06-02"
revised:
  by: "analyst"
  date: "2026-06-07"
techniques_used:
  - inversion
  - perspective-shift
assumptions_challenged:
  - "ADR strategy is the only exclusion dimension needed (false — some teams are not ready to move any tier-3 docs)"
  - "Exclusions only matter at migration time (false — they are permanent runtime rules for every future agent session)"
  - "The migration skill can stand alone without checking for prior installation (false — it depends on decisions recorded by the installation skill)"
  - "Path exclusions should be applied after classification (false — scan-time exclusion is more efficient and clearer to the operator)"
decisions_locked:
  - D1: installing-cairn skill is the right approach — atomic skill, no bundled script, AGENTS.md snippet in references/
  - D2: adr_strategy key retained as a named field in the config block (git-only vs cairn-mcp-only)
  - D3: new local_only_paths key in the config block — a list of folders/files permanently excluded from cairn-mcp
  - D4: local_only_types derived from local_only_paths — installation skill infers type-level rules from path selections and confirms with operator
  - D5: structured <!-- cairn-mcp:config ... --> block (YAML inside HTML comment) written to AGENTS.md by installation skill — single source of truth for both migration and runtime exclusions
  - D6: config block presence is the installation sentinel — migration skill checks for it at pre-flight; absent = hard stop
  - D7: migration skill removes its ADR gate entirely — exclusions come from the config block
  - D8: when git-only ADR strategy chosen, installation skill auto-detects ADR folder; if not found, asks operator; then asks for additional folders/files
  - D9: local_only_paths exclusions applied at scan-time in migration skill (not post-classification)
  - D10: V1 path syntax — trailing / means entire directory tree; no trailing / means exact file; no glob syntax
  - D11: re-running installing-cairn updates the config block in place (no append, no history)
  - D12: AGENTS.md narrative snippet gains a standing never-write instruction referencing local_only_types and local_only_paths
  - D13: AWS provisioning (S3 bucket, S3 Vectors bucket/index, Bedrock model access) is OUT OF SCOPE for the installation skill — operator provisions these externally before running the skill
  - D14: the skill collects values for pre-existing resources only (bucket name, index name, AWS profile, etc.) — it never creates AWS resources
  - D15: pre-flight (Step 2) validates that the declared resources are reachable (s3api head-bucket, s3vectors describe-index) and that credentials are active — this replaces the provisioning responsibility
  - D16: README AWS Provisioning section (Steps 1–4 with all CLI commands) removed; replaced by an expanded Prerequisites section listing what must exist before running the skill
  - D17: provisioning IAM policy removed from README (no provisioning steps means no need for CreateIndex/DeleteIndex permissions); runtime IAM policy stays as a static reference with YOUR-* placeholders — the installation skill never generates or substitutes values into any IAM policy; operators use the README reference as a template for what to request from their AWS admin
  - D18: env vars passed via IDE MCP config file env/environment block — no .env file written at any step
  - D19: skill asks explicit permission before writing to any IDE config file; merges into existing file; displays entry for manual addition if operator declines
  - D20: step count is 6 (parameter collection, pre-flight + resource reachability validation, clone + setup, MCP client config with env vars + permission ask, health check, exclusion config → AGENTS.md); IAM policy generation is absent from all steps — the README provides a static reference policy with YOUR-* placeholders; the skill never generates, substitutes, or applies any IAM policy document
decisions_pending: []
decisions_closed_not_applicable:
  - Binary ADR gate as the sole exclusion mechanism — superseded by unified exclusion model (D2 + D3)
  - Post-classification path filtering in migration skill — superseded by scan-time exclusion (D9)
  - Append-on-rerun for config block — superseded by in-place update (D11)
---

# Installing-Cairn Skill

## Description

Should the cairn-mcp installation and provisioning workflow — currently ~400 lines in the
README (clone, Python setup, AWS provisioning, IAM policy, .env, MCP client config, AGENTS.md
snippet) — be moved into an `installing-cairn` skill, mirroring what was done for the
`migrating-to-cairn` skill? This session explores the design space: whether the skill makes
sense, what it should cover, how it compares to the migration skill, and what trade-offs exist
in scope, structure, and README reduction.

---

## Session 2026-06-02

### Context

The README currently has 580 lines. 397 of them (lines 179–575) are pure ops content: prerequisites,
clone+setup, configuration table, four-step AWS provisioning, two IAM policy blocks, server
launch, MCP client config (two IDE formats), AGENTS.md snippet with ADR variants. The marketing
and concept sections (problem framing, feature table, comparison, who it's for, why AWS) occupy
the remaining ~180 lines. The migration skill established a precedent: encapsulate a complex,
interactive operator workflow in a skill file that an agent can load and execute step by step.

---

### Why it makes sense — the agent advantage

The core argument is not just README tidiness. An agent running the skill can do things a human
reading README docs cannot:

1. **Fills in all placeholders automatically** — collects parameters once upfront (region, bucket
   names, index name, IAM principal ARN, IDE choice) and never uses a `YOUR-*` placeholder again.
   The `.env`, the IAM policy JSON, and the MCP client config snippet are all emitted with real
   values.

2. **Validates each step before proceeding** — after creating the S3 bucket, the agent can call
   `aws s3api head-bucket` to confirm it exists before moving to the next step. A human skimming
   the README might miss a failure.

3. **Hard stop at the immutable decision** — the index creation step carries immutable properties
   (dimension, distance metric, key names). The skill can present the resolved values, explain the
   irreversibility, and require explicit operator confirmation before executing. A README warning
   block gets skimmed; a skill step blocks.

4. **Writes files directly** — the `.env`, the MCP client config block, and the AGENTS.md snippet
   can be written by the agent into the right files, not copy-pasted by the human.

5. **Runs `health_check` at the end** — confirms all three AWS services are reachable before the
   operator considers setup complete. The README cannot do this; a skill can.

---

### Naming analysis (authoring-skills conventions)

The convention is a gerund, optionally followed by a preposition phrase:

| Candidate | Pattern | Assessment |
|-----------|---------|------------|
| `installing-cairn` | `<gerund>-<noun>` | Matches the migration skill pattern exactly (`migrating-to-cairn`). Clear, discoverable. |
| `setting-up-cairn` | `<gerund>-<preposition>-<noun>` | Accurate but longer; "setting up" is vaguer than "installing". |
| `provisioning-cairn` | `<gerund>-<noun>` | Accurate for the AWS steps only — undersells the full scope (clone, config, MCP client). |
| `onboarding-to-cairn` | `<gerund>-<preposition>-<noun>` | Too broad; "onboarding" implies team workflow, not server setup. |

**Verdict:** `installing-cairn` is the right name — gerund + noun, same pattern as `migrating-to-cairn`,
unambiguous activation signal.

---

### Skill tier: atomic or composite?

The authoring-skills conventions define two tiers:

- **Atomic** — single-domain, ≤500 lines, one concern.
- **Composite** — cross-cutting workflow that coordinates multiple named atomic skills.

The installation workflow touches AWS CLI operations, file creation, MCP client configuration, and
AGENTS.md editing. However, all of these are in service of one goal: getting cairn-mcp running for
the first time. There are no existing atomic skills to coordinate (unlike a hypothetical composite
that chains `building-with-aws-cdk` + `coding-in-python`). The workflow is sequential and
self-contained.

**Verdict:** Atomic. One concern, no existing atomic skills to delegate to, should fit in ≤500 lines
(the migration skill is 309 lines; installation is comparable in scope).

---

### Proposed workflow steps

**Step 1 — Parameter collection (upfront)**
Collect all values before any action: AWS region, S3 artifact bucket name, S3 Vectors bucket name,
S3 Vectors index name, embedding dimension (default 1024), IAM principal ARN (user or role that
will run the server), IDE choice (OpenCode / Claude Desktop / Cursor / other), team name, project
name. Collecting all parameters upfront means no mid-workflow back-and-forth.

**Step 2 — Pre-flight checks**
Verify: `aws` CLI is available and credentials are configured (`aws sts get-caller-identity`),
`uv` is installed. If either check fails, stop and instruct the operator to fix it before
proceeding.

**Step 3 — Clone and Python setup**
`git clone`, `cd`, `uv sync`. Minimal — the README one-liner is sufficient here.

**Step 4 — AWS provisioning**
Four sub-steps in order:
- 4a: Create S3 artifact bucket (with `us-east-1` variant note)
- 4b: Create S3 Vectors bucket
- 4c: Create S3 Vectors index — **hard stop**: present resolved values (dimension, metric, key
  names), explain they are immutable, require explicit operator confirmation before executing
- 4d: Enable Bedrock model access — this requires Console action; the agent provides the direct
  Console URL and waits for confirmation

**Step 5 — IAM policy generation**
Generate both IAM policy blocks (runtime + provisioning-only) with all `YOUR-*` placeholders
replaced by the values collected in Step 1. Present the policies to the operator for review;
do not attempt to apply them (requires knowing the target role/user ARN attachment point, which
is environment-specific). Instruct the operator to apply the runtime policy before proceeding.

**Step 6 — Configure .env**
Write the `.env` file (or `cp .env.example .env` and fill it in) using the values from Step 1.

**Step 7 — MCP client configuration**
Based on the IDE choice from Step 1, emit the correct config block with real paths and values
and offer to write it to the right file.

**Step 8 — Smoke test**
Start the server (`uv run cairn-mcp`) and call `health_check`. If any component shows `"status":
"error"`, diagnose and report. Only proceed when all components show `"status": "ok"`.

**Step 9 — AGENTS.md snippet**
Ask the operator for their ADR strategy (same two-question gate as the migration skill), then
write the tailored AGENTS.md snippet with the correct ADR variant into the project's `AGENTS.md`.

---

### Key difference from the migration skill

The migration skill runs against a cairn-mcp instance that is already healthy — `health_check`
is Step 1. The installation skill builds the instance from scratch, so **no cairn-mcp MCP tools
are available until Step 8**. Steps 1–7 rely entirely on the agent's Bash tool and file tools;
MCP tools only appear in Step 8.

---

### Script bundling: yes or no?

The migration skill bundles `migrate.py` because bulk writes (≥30 files) cannot feasibly be
done one-by-one in an agent context. Does installation need a bundled script?

| Task | Agent can do it directly | Needs a script |
|------|--------------------------|----------------|
| Run aws CLI commands one by one | Yes | No |
| Generate .env with real values | Yes (file write) | No |
| Generate IAM policy JSON with real values | ~~Yes (string formatting)~~ | ~~No~~ | **Superseded by D17/D20** — IAM policy generation is out of scope; the README provides a static reference with YOUR-* placeholders |
| Generate MCP config snippet | Yes (file write) | No |

**Verdict:** No bundled script needed. Each provisioning step is a single CLI command. The agent
handles file creation natively. A setup script would add maintenance burden (another file to keep
in sync with the README's CLI commands) without solving a real problem.

---

### README reduction strategy

| Section | Current size | After skill | What stays |
|---------|-------------|-------------|------------|
| Prerequisites | ~5 lines | Collapsed to 1 sentence | Pointer to skill |
| Installation (clone+uv) | ~6 lines | Collapsed to 1 sentence | Pointer to skill |
| Configuration table | ~20 lines | Keep | Essential reference for operators who want to understand all knobs |
| AWS Provisioning (4 steps) | ~75 lines | Move to skill | Gone from README |
| IAM policy blocks | ~60 lines | Move to skill | Gone from README |
| Running the server | ~6 lines | Keep (it's the launch command) | One-liner |
| MCP client config (2 IDEs) | ~50 lines | Move to skill | Gone from README |
| AGENTS.md snippet + ADR variants | ~140 lines | Move to skill | Gone from README |

Net README reduction: ~325 lines → README shrinks from 580 to ~255 lines. The remaining content
is all marketing/concept material plus the configuration reference table and server launch command.

---

### Risks and gotchas

**`us-east-1` bucket creation quirk** — S3 bucket creation in `us-east-1` must omit
`--create-bucket-configuration LocationConstraint=us-east-1` (it errors if included). The skill
must branch on region.

**Bedrock model access is a Console-only action** — there is no `aws bedrock` CLI command to
enable model access. The agent can provide the direct Console deep link
(`https://<region>.console.aws.amazon.com/bedrock/home#/modelaccess`) and wait for confirmation
but cannot automate this step.

**IAM policy cannot be applied without knowing the attachment target** — the agent generates the
policy JSON with real values, but applying it (`aws iam create-policy`, `aws iam attach-role-policy`)
requires knowing whether it's a role or a user, and the target ARN. The skill should present the
policy and instruct the operator to apply it, rather than attempting to apply it.

**Existing resources** — if the operator already has some resources (e.g., an S3 bucket from a
previous attempt), the skill must handle gracefully. `aws s3api head-bucket` before attempting
to create; skip if it already exists and report it.

**Size constraint** — the authoring-skills skill sets a hard limit of ≤500 lines. With nine steps,
the skill can use the same technique as `migrating-to-cairn` (one `##` section per step) and should
stay well within limit if the AGENTS.md snippet is kept in a `references/` file rather than
embedded inline.

**ADR strategy re-asking** — Step 9 (AGENTS.md snippet + ADR variant) duplicates the two-option
gate already in the migration skill. This is acceptable duplication — a new project that hasn't
migrated still needs to make the ADR decision. The gate is short (two paragraphs) and should stay
in the skill rather than being shared.

---

### Selected directions

Three things this brainstorm converges on:

1. **Build the `installing-cairn` skill** — the fit is good, the agent advantage is real, the
   naming is clean, atomic tier is right, and the workflow is well-defined.

2. **No bundled script** — agent file and Bash tools are sufficient for each step; a script adds
   maintenance cost without solving a real problem.

3. **Move AGENTS.md snippet to `references/`** — the snippet is 140 lines. Embedding it inline
   would push the skill close to the 500-line limit. Store it in
   `skills/installing-cairn/references/agents-snippet.md` and instruct the agent to load it
   conditionally in Step 9.

---

### Open questions

~~- Should the skill validate that the Bedrock model access is active (e.g. via a `bedrock:InvokeModel`~~
~~  dry-run call) as part of Step 4d, rather than relying on the operator's confirmation? This would~~
~~  require the agent to know a minimal test embedding input, which is feasible but adds complexity.~~
~~- Should `READ_PREFIXES` be collected in Step 1, or deferred to a "you can configure cross-scope~~
~~  reads later" note at the end? Most new installs won't need it immediately.~~

### Decisions (2026-06-02)

**Bedrock model access validation** — Yes, actively validate with a `bedrock:InvokeModel` dry-run
call after the operator confirms Console access, mirroring what the migration skill does. The skill
needs a minimal test embedding input (e.g. a single word); this is feasible and gives the operator
a concrete confirmation that the model is accessible rather than relying on their word. Step 4d
becomes: provide Console deep link → wait for operator confirmation → call
`aws bedrock invoke-model` with a minimal payload → confirm success before proceeding.

**`READ_PREFIXES` collection** — Ask in Step 1 (optional field, can be left blank). Make clear
that it can be updated in `.env` at any time. Most new installs will leave it blank; the question
surfaces the capability without blocking setup.

---

## Session 2026-06-07

### Problem Statement

The ADR strategy decision (git-only vs cairn-mcp-only) currently lives in the migration skill's
Step 2c. Two related problems make this the wrong home for it:

1. **Wrong moment** — if an installation skill exists, the operator has already set up the
   server and configured AGENTS.md. Asking the ADR question again during migration re-opens a
   decision that should already be settled, with the risk of giving a different answer.

2. **Too narrow** — operator feedback surfaced a broader concern: teams not yet advanced with
   AI development may not be ready to move *any* tier-3 artifacts out of the repository, not
   just ADRs. The binary ADR gate does not cover specs, plans, or ad-hoc folders an operator
   wants to keep local permanently.

The goal is to move all exclusion decisions into the installation skill, record them in
AGENTS.md in a machine-readable form, and have the migration skill consume what has already
been decided — with a hard gate if installation hasn't run yet.

---

### Ideas Explored

#### On the exclusion model

1. **Type-only exclusions** — extend the ADR gate to a list of artifact types to keep git-only.
   Simple, but misses path-level cases (a folder of sensitive docs regardless of type).

2. **Path-only exclusions** — a list of folder/file paths to exclude permanently. Covers
   directory-level exclusions but does not align with how agents reason at write time
   (agents think in types, not source file paths).

3. **Unified model: types + paths** — one step collects both. `adr_strategy` is retained as
   a named field (its semantics are richer than just "exclude adr type"); a new `local_only_paths`
   key captures folder and file exclusions. `local_only_types` is derived from paths where
   the mapping is unambiguous.

4. **Named profiles** (Minimal / ADR-local / Conservative / Custom) — fast for common cases,
   but too rigid for idiosyncratic team layouts.

5. **Positive-permission model** — list what IS permitted in cairn-mcp; everything else stays
   local. Safest default, but impossible to configure correctly before teams know what they
   will write.

#### On AGENTS.md encoding

6. **Inline narrative only** — extend the existing Variant A/B prose with additional bullet
   points. Readable but not machine-parseable by agents or the migration skill.

7. **Dedicated section** — a `### Local-only artifacts` section with two bullet lists.
   Better than prose but still unstructured; fragile to reformatting.

8. **Structured HTML-comment config block** — a `<!-- cairn-mcp:config ... -->` block
   containing YAML. Machine-parseable by agents (LLMs can read HTML comments), survives
   surrounding AGENTS.md edits, and is a clear machine-managed zone that humans know
   not to hand-edit freely.

#### On how paths are detected and entered

9. **Operator declares everything manually** — ask "which folders should stay local?"
   Puts the burden on the operator; they may forget the ADR folder or not know the exact path.

10. **Auto-detect from known patterns** — when git-only ADR strategy is chosen, scan for
    common ADR directory names (`docs/adr/`, `docs/adrs/`, `adr/`, `adrs/`, `decisions/`,
    `architecture/`). If exactly one match found, confirm with operator and add it to
    `local_only_paths`. If none found or multiple found, ask the operator to specify.
    After the ADR folder is resolved, ask for any additional folders or files to exclude.

11. **Derive types from paths** — after the path list is final, map known directory patterns
    to artifact types (e.g. `docs/adr/` → `adr`, `docs/specs/` → `spec`) and add them to
    `local_only_types` with operator confirmation. Agents need type-level rules at write time
    (they don't know source file paths); path-level rules alone are not enough.

#### On migration skill installation detection

12. **Check AGENTS.md for config block** — migration skill looks for `<!-- cairn-mcp:config`
    at pre-flight. Present → read exclusions. Absent → hard stop.

13. **Soft warning + inline fallback** — if no config block found, re-ask the exclusion
    questions inline and write the block on the fly. Makes migration self-contained but
    duplicates installation skill logic.

14. **Check health_check instead** — if the server is healthy, installation probably ran.
    Does not capture exclusion decisions; health alone is insufficient.

#### On where exclusions are applied in the migration scan

15. **Post-classification filter** — classify all files first, then drop those matching
    excluded types or paths. Gives the operator a full view before exclusions; slightly
    more transparent.

16. **Scan-time exclusion** — paths in `local_only_paths` are skipped before any
    classification or reading. More efficient; cleaner mental model ("these paths are
    invisible to cairn-mcp").

#### On re-running the installation skill

17. **Append a new config block** — preserves history but risks agents using the wrong
    (older) block.

18. **Update in place** — the config block is machine-managed; when re-running the skill,
    it rewrites the block with the new values. No history, but no ambiguity.

---

### Clusters

**Cluster A — Exclusion model**
Ideas 1–5. Resolves to: unified model (idea 3) — `adr_strategy` retained, `local_only_paths`
added, `local_only_types` derived.

**Cluster B — AGENTS.md format**
Ideas 6–8. Resolves to: structured HTML-comment config block (idea 8) — machine-parseable,
unambiguous, human-visible.

**Cluster C — Path detection and entry**
Ideas 9–11. Resolves to: auto-detect ADR folder when git-only chosen (idea 10), then ask for
additional exclusions, then derive type-level rules (idea 11).

**Cluster D — Migration skill installation gate**
Ideas 12–14. Resolves to: hard stop on absent config block (idea 12). No fallback that
duplicates installation logic.

**Cluster E — Scan-time vs post-classification**
Ideas 15–16. Resolves to: scan-time exclusion (idea 16) — excluded paths are invisible to
the entire migration workflow.

**Cluster F — Config block lifecycle**
Ideas 17–18. Resolves to: update in place (idea 18).

---

### Selected Directions

#### D2 — `adr_strategy` retained; `local_only_paths` added

The config block carries both keys. `adr_strategy: git-only` conveys richer semantics than
simply listing `adr` in `local_only_types` — it signals a single-source-of-truth decision,
not just an exclusion preference. `local_only_paths` is a new list covering any folder or
file the operator wants permanently excluded from cairn-mcp.

#### D3 — `local_only_types` derived from `local_only_paths`

When the operator finalises the path exclusion list, the installation skill maps each path
to a known artifact type (using the same directory-pattern table as the migration skill's
Pass 2 classification) and asks the operator to confirm the inferred types. Agents use
`local_only_types` at write time; the migration skill uses `local_only_paths` at scan time.
Both are needed; both are generated in the same step.

#### D5 — Structured `<!-- cairn-mcp:config ... -->` block in AGENTS.md

YAML inside an HTML comment. Written by the installation skill; read by the migration skill
and by every future agent session. Example:

```
<!-- cairn-mcp:config
installed: 2026-06-07
adr_strategy: git-only
local_only_types:
  - adr
  - spec
local_only_paths:
  - docs/adr/
  - docs/specs/
  - docs/internal/private-design.md
-->
```

Trailing `/` means the entire directory tree. No trailing `/` means an exact file path.
No glob syntax in V1 — keeps parsing unambiguous. The block is machine-managed; humans
should not edit it by hand.

#### D6 — Config block is the installation sentinel

Migration skill pre-flight (before any scan):
1. Check AGENTS.md for `<!-- cairn-mcp:config`.
2. If absent → stop: "cairn-mcp does not appear to be installed for this project.
   Run the `installing-cairn` skill first, then return here."
3. If present → parse `local_only_types` and `local_only_paths` and continue.

No inline fallback — the migration skill does not re-ask exclusion questions.

#### D8 — Installation skill Step 9 revised flow

Step 9 becomes a two-part exclusion configuration step:

**Part A — ADR strategy:**
Ask the operator: git-only or cairn-mcp-only. If git-only:
- Scan for common ADR directory names (`docs/adr/`, `docs/adrs/`, `adr/`, `adrs/`,
  `decisions/`, `architecture/`).
- If exactly one candidate found: "I found `docs/adr/`. I'll add it to the local-only
  path list. Is that correct?"
- If none or multiple found: "Where are your ADRs stored? (provide the folder path)"
- Add the confirmed path to `local_only_paths`; add `adr` to `local_only_types`.

**Part B — Additional exclusions:**
Ask: "Are there any other folders or files that should never go into cairn-mcp?
List them one per line, or press Enter to skip."
For each path provided:
- Attempt to infer an artifact type using the migration skill's path-pattern table.
- If a type is inferred: "This looks like a `{type}` folder — I'll also add `{type}`
  to the never-write types. Confirm?"
- If no type can be inferred: add to `local_only_paths` only (no type-level rule added).

**Part C — Write config block:**
Write the `<!-- cairn-mcp:config ... -->` block to AGENTS.md. If a block already exists
(re-run), replace it in place.

Then write the AGENTS.md narrative snippet (from `references/agents-snippet.md`), including
the correct ADR variant and a standing never-write instruction:

> "Before writing any artifact, check the `cairn-mcp:config` block in AGENTS.md.
> Do not write artifacts whose type appears in `local_only_types`. Do not write artifacts
> whose source file is under a path in `local_only_paths`."

---

### Open Questions

*(none — all decisions resolved)*

---

## Session 2026-06-07 (addendum) — AWS Provisioning Scope

### Problem Statement

The Session 2026-06-07 workflow design included a Step 4 that created the S3 artifact
bucket, S3 Vectors bucket, and S3 Vectors index via AWS CLI commands, and a Step 4d that
guided the operator through enabling Bedrock model access in the Console. This was
identified as scope creep: cairn-mcp is an application server, not an infrastructure
provisioning tool. Operators who adopt cairn-mcp already have AWS workflows and tooling
for resource creation. The installation skill should assume the required AWS resources
exist and focus on connecting the server to them.

A secondary finding: the README currently includes a full `## AWS Provisioning` section
with four sub-steps and CLI commands for creating each resource. This duplicates the
wrong scope into the README. A potential operator reading the README should see what
is required (prerequisites), not a tutorial on creating S3 resources they likely already
know how to create.

### Decision Summary

**D13 — AWS provisioning is out of scope for the installation skill.**
The skill never creates S3 buckets, S3 Vectors indexes, or enables Bedrock model access.
These are operator responsibilities, handled before running the skill by whatever means
the team uses (Console, CDK, Terraform, CLI scripts). The skill is not opinionated about
how they are created.

**D14 — The skill collects values for pre-existing resources.**
Step 1 (parameter collection) asks for the bucket name, vectors bucket name, index name,
AWS region, and AWS profile. All of these must already exist. The skill does not offer to
create them.

**D15 — Pre-flight validates reachability, not existence-by-creation.**
Step 2 expands its validation to include: `s3api head-bucket` on the declared artifact
bucket, `s3vectors describe-index` on the declared vectors index, and a `bedrock:InvokeModel`
call on the embedding model. If any check fails, the skill stops with a clear error
identifying which resource is unreachable. This gives the operator early, specific failure
feedback without the skill needing to understand how to provision the missing resource.

**D16 — README `## AWS Provisioning` section removed.**
The four provisioning sub-steps (create S3 bucket, create Vectors bucket, create Vectors
index, verify Bedrock access) and their CLI commands are removed from the README. The
`## Prerequisites` section is expanded to list what must exist: S3 bucket, S3 Vectors
bucket and index (with the correct dimension and non-filterable key configuration noted),
Bedrock embedding model access, AWS credentials.

**D17 — Provisioning IAM policy removed; runtime IAM policy is a static README reference only.**
The `#### Provisioning IAM policy` block (`CreateIndex`, `DeleteIndex`) is removed from
the README. The `## Minimum IAM Policy` block stays as a **static reference with
`YOUR-*` placeholders** — operators use it as a template when requesting permissions
from their AWS admin. The installation skill never generates, substitutes values into,
or applies any IAM policy document. IAM policy management is entirely the operator's
responsibility; it is not a skill step.

**D18 — No `.env` file is written at any step.**
Already captured from the earlier same-day session. Env vars go exclusively in the IDE's
MCP config file. Recorded here for completeness.

**D19 — IDE config file permission gate.**
Already captured from the earlier same-day session. Recorded here for completeness.

**D20 — Step count is 6; IAM policy generation is absent.**
The IAM policy step is removed entirely — the skill never emits a policy document.
The 6-step workflow is:
1. Parameter collection
2. Pre-flight + resource reachability validation
3. Clone and Python setup
4. MCP client config (env vars in IDE config file, permission ask, merge)
5. Smoke test via `health_check`
6. Exclusion configuration (ADR strategy + additional paths → AGENTS.md config block + snippet)

### Open Questions

*(none — all decisions resolved)*

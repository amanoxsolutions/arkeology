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
| Generate IAM policy JSON with real values | Yes (string formatting) | No |
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

---
type: brainstorming
title: Multi-team / Multi-project Configuration
description: Explores solutions for operators who work across multiple teams and projects and need cairn-mcp to correctly scope artifact writes without restarting the server, ranging from better docs to named profiles and a proxy layer.
tags: []
timestamp: 2026-06-08T00:00:00Z
okf_version: "0.1"
status: ready
references:
  - src/cairn_mcp/config.py
  - docs/planning-artifacts/prd.md
  - https://docs.aws.amazon.com/agent-toolkit/latest/userguide/multi-account-access.html
  - https://opencode.ai/docs/config/
  - https://opencode.ai/docs/mcp-servers/
  - https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
  - https://developers.openai.com/codex/mcp
  - https://github.com/github/copilot-cli/issues/1291
  - https://github.com/github/copilot-cli/issues/2528
authored:
  by: analyst
  date: 2026-06-08
revised:
  by: analyst
  date: 2026-06-08
techniques_used:
  - inversion
  - analogy (AWS mcp-proxy-for-aws profile-per-call pattern)
  - constraint-removal (what if WRITE_PREFIX did not exist?)
  - perspective-shift (agent perspective vs operator perspective)
assumptions_challenged:
  - "WRITE_PREFIX as a server-side enforcement gate is the right abstraction"
  - "One server instance = one project is a fundamental constraint"
  - "team/project fields in the artifact model and WRITE_PREFIX are different things"
  - "The AWS proxy approach (per-call profile) requires a hosted server"
decisions_locked:
  - D1: Direction 2 (per-project MCP config) is the chosen approach — no server code changes
  - D2: WRITE_PREFIX stays as-is; the enforcement fence is valuable and must not be removed
  - D3: Multi-backend isolation (different ARTIFACT_BUCKET per project) is out of scope for now;
        prefix-based isolation within one backend is sufficient; Direction 3 kept on roadmap
  - D5: setting-up-cairn skill must be updated to document all four client setups;
        content and exact syntax documented in Session 3 of this file
  - D6: "opencode merge is additive at the mcp server-name level — a project config that only
        contains a new server name adds it to the global server list without disturbing existing
        global entries; empirically confirmed (Session 4). Same-name override behaviour is
        inferred shallow (replace entire entry) pending a separate test.
        **CORRECTION (installation test)**: `.opencode.json` (dot-prefix) is NOT reliably
        picked up by opencode as a project config — it was not loaded in a session started
        from the project root, while the three global configs were. The officially documented
        project config filename is `opencode.json` (no dot prefix). The dot-prefix variant
        may work in some contexts/versions but cannot be relied upon. Use `opencode.json`."
  - D8: The setting-up-cairn skill must check whether config files already exist and EDIT them
        (insert the cairn entry) rather than create or overwrite; must handle .json and .jsonc
        variants for JSON-based clients and the existing TOML structure for Codex
decisions_pending: []
decisions_closed_not_applicable:
  - D4: Named-profile proxy layer (Direction 3) — deferred indefinitely; Direction 2 is
        sufficient for all current use cases; no stated need for "one session, two projects";
        a proxy adds operational complexity with no immediate benefit; revisit only if a
        concrete cross-project-session requirement emerges
  - D7: Codex mcp_servers merge depth — not applicable; Codex docs describe explicit layering
        for overrides ("set shared defaults, keep profile files focused on what differs");
        cairn is only ever placed in the project config, never in global, so no same-name
        conflict exists; additive behaviour (new section in project adds to global) is the
        only case that matters and follows naturally from TOML table semantics
---

# Multi-team / Multi-project Configuration

## Description

The current design binds a cairn-mcp server instance to a single write scope
(`WRITE_PREFIX = "team/project"`) and a single backend (`ARTIFACT_BUCKET`,
`VECTORS_BUCKET`, `VECTORS_INDEX`) at startup. An operator who works across
multiple teams and projects must either restart the server, juggle multiple
server instances, or accept that all writes go to the same scope. This session
explores solutions from lightweight (better docs) to structural (named profiles,
proxy layer).

## Session 2026-06-08

### Problem Statement

A developer working on several projects simultaneously — or across several teams
— needs cairn-mcp to correctly scope artifact writes to the right team/project
without restarting the server or maintaining one process per project. The current
single-value `WRITE_PREFIX` env var is a per-process constant that does not
survive context switches. Extending this to `ARTIFACT_BUCKET`, `VECTORS_BUCKET`,
and `VECTORS_INDEX` (true multi-backend isolation) makes the problem even harder.

**Key observation from the codebase**: `team` and `project` are *already
mandatory explicit parameters* on every `write_artifact` call. The `WRITE_PREFIX`
serves as a server-side enforcement gate, not as the source of the team/project
values themselves. This creates a structural redundancy that is the root of the
flaw: the agent already knows and passes the correct scope; the server just
refuses to write anywhere that is not the hard-coded prefix.

**On the AWS MCP Server approach**: AWS solved a related problem (per-call AWS
credentials) using a **proxy** (`mcp-proxy-for-aws`) that wraps a *remote hosted*
MCP server endpoint. The proxy adds an `aws_profile` parameter to tool schemas,
maintains dedicated backend connections per profile, and strips the parameter
before forwarding. This is implemented in the proxy layer — *not* inside the
individual MCP servers in `awslabs/mcp`. Local servers in that repo still use a
single `AWS_PROFILE` env var at startup.

### Ideas Explored

**A. Remove WRITE_PREFIX entirely — auto-derive from per-call team/project**
Since `team`/`project` are already required parameters, the S3 prefix could
always be computed as `{team}/{project}` automatically. `WRITE_PREFIX` becomes
redundant. No enforcement gate survives.

**B. WRITE_PREFIXES allowlist**
`WRITE_PREFIX` becomes `WRITE_PREFIXES` (plural, comma-separated). The agent
passes a `scope` hint per call (or it is derived from `team`/`project`). The
server validates it is in the allowlist. If not, it rejects the write.

**C. WRITE_PREFIX in AGENTS.md — agent carries it as an explicit per-call parameter**
Remove `WRITE_PREFIX` from the server's env vars. Each project's `AGENTS.md`
instructs the agent to pass `write_prefix="team-a/project-x"` on every call.
The server validates the value is non-empty (and optionally in an allowlist).

**D. Named contexts / profiles in server config**
Define named profiles in env vars or a config file. Each profile has its own
full set of storage parameters. Agent passes `profile="work"` per call. Server
routes the call to the correct backend config. Analogous to `aws_profile` in
the AWS proxy.

**E. Multiple server instances, one per project (current workaround)**
Declare `cairn-work` and `cairn-personal` as separate MCP server entries in
`opencode.json`, each with its own env. Works today with no code changes. Does
not solve the "one session, two projects" problem.

**F. Per-call backend routing via a proxy layer**
A thin proxy process sits between MCP client and cairn-mcp. The proxy maintains
one cairn-mcp sub-process per profile (each with its own env). Agent passes
`profile` per call; proxy routes it. Server code unchanged. Analogous to
`mcp-proxy-for-aws`, but for cairn-mcp.

**G. No server constraint — agent prompt is the only gate**
Treat cairn-mcp as a dumb S3 gateway. Remove all prefix enforcement. Scope
correctness is entirely the agent's responsibility (enforced by AGENTS.md).

**H. Allowed-teams / allowed-projects fields as the enforcement unit**
Replace `WRITE_PREFIX` with `ALLOWED_TEAMS` + `ALLOWED_PROJECTS` env vars.
The prefix is always auto-derived as `{team}/{project}`. The safety fence
becomes semantically richer and directly tied to the artifact model.

**I. Config file (`cairn.toml`) with named context blocks**
A structured config file replaces env vars for multi-context scenarios. Richer
than the `CAIRN_PROFILE_WORK_ARTIFACT_BUCKET=...` key explosion from Option D.

**J. Per-project MCP config (`.mcp.json` / `opencode.json`) — documentation only**
Document clearly that each project's `.mcp.json` (or opencode's project-scoped
config) can declare its own cairn-mcp env block. Zero code changes. Standard
MCP client behaviour. Different projects get different server configs automatically.

### Clusters

**Cluster 1 — "Remove the constraint" (A, G)**
WRITE_PREFIX disappears. Trust the agent entirely. Maximum flexibility, minimum
safety. Appropriate only if the agent is always instructed via AGENTS.md and
errors are easy to detect and fix.

**Cluster 2 — "Agent carries the context" (C, J)**
WRITE_PREFIX moves out of the server into project-level config (AGENTS.md or
`.mcp.json`). Server may or may not validate. Low implementation cost; relies
on agent compliance. Option J requires zero code changes.

**Cluster 3 — "Server knows multiple contexts" (B, D, H, I)**
The server is configured with a set of valid contexts / profiles / allowed
teams+projects. Agent selects one per call. Server enforces the allowlist.
One server instance, multiple logical scopes. Most powerful, most complex.

**Cluster 4 — "Multiple server instances" (E, F)**
One server per scope. Routing by the MCP client (E) or a proxy (F). Server
code unchanged. Clean separation; multiplies processes.

### Selected Directions

#### Direction 1 — Per-call scope derived from team/project + WRITE_PREFIXES allowlist
*Best of Clusters 1 and 3.*

Drop `WRITE_PREFIX` as a single value. Introduce `WRITE_PREFIXES` (comma-separated
allowlist, or `"*"` for unrestricted). The S3 key prefix is auto-derived from
the mandatory `team` and `project` parameters that the agent already passes on
every write call. The server validates that `{team}/{project}` is in
`WRITE_PREFIXES` (or that `WRITE_PREFIXES` is `"*"`). `READ_PREFIXES` stays
as-is.

**Benefits:**
- Eliminates the redundancy: team/project are already in the call; WRITE_PREFIX
  just repeated them.
- One server instance handles all projects the user is allowed to write to.
- Safety fence survives as an allowlist rather than a hard single value.
- No new server instances needed.

**Risks / challenges:**
- Agent hallucination: a valid but wrong `team`/`project` combination passes
  the allowlist check and lands in the wrong scope. Allowlists only block
  out-of-scope writes, not wrong-but-permitted writes.
- `WRITE_PREFIXES` with many entries can become its own maintenance burden.
- Does not address multi-backend isolation (same bucket/index for all scopes).
- Backward compatibility: operators currently set `WRITE_PREFIX`; migration path
  needed.

#### Direction 2 — Per-project MCP config + documentation (zero-code)
*Cluster 2, Option J.*

Document clearly that users should create one MCP server entry per active project
in their project's `.mcp.json` (or `opencode.json`). Each entry has its own env
block with its own `WRITE_PREFIX`, and optionally its own `ARTIFACT_BUCKET` and
`VECTORS_INDEX` for true backend isolation. This works today with no code changes.

**Benefits:**
- Zero implementation cost; available immediately.
- Enables full backend isolation (different bucket, different vector index) per
  project — which Direction 1 cannot provide.
- Leverages existing MCP client behaviour (project-scoped config already
  overrides global).

**Risks / challenges:**
- Tool list clutter when multiple server entries are active simultaneously.
- Does not solve "one session, two projects" (cross-project artifact references,
  synthesis across project boundaries).
- Requires user to manage separate server configs; onboarding friction.

#### Direction 3 — Named profiles in server config
*Cluster 3, Option D/H.*

Add a `CAIRN_PROFILES` config concept. Each named profile carries its own
`WRITE_PREFIX`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`. Tools
accept an optional `profile` parameter; the server resolves the right backend
config for the call. Default profile used when `profile` is not specified.

**Benefits:**
- Single process, full backend isolation per profile.
- True multi-backend support (different buckets/indexes per team).
- Most powerful long-term.

**Risks / challenges:**
- Significant implementation effort: config parser, per-profile client
  construction, profile-routing layer in every tool, profile validation,
  startup checks for all profiles.
- Env var explosion for multiple profiles (or new config file format decision).
- Tools change signature (new `profile` parameter) — breaking change.
- AWS credential scope: if different profiles need different IAM roles (e.g.,
  different AWS accounts), boto3 sessions would also need to be per-profile,
  since they are currently built once at startup.

### Open Questions

1. **Cross-project sessions: how common are they?** If "one agent session, two
   projects" is rare, Direction 2 (separate server instances per project) is
   perfectly adequate. If it is common (e.g., release agents that touch multiple
   repos), Direction 1 or 3 becomes necessary in the future.

2. **Proxy as a future layer**: Even with Direction 2 chosen now, a
   `cairn-proxy` (inspired by `mcp-proxy-for-aws`) could be added later for
   true multi-account, multi-backend routing without changing the server.
   Should this be explicitly kept on the roadmap? (D4 pending)

3. **Does the setting-up-cairn skill need updating?** It should document the
   per-project MCP config pattern for both opencode and Claude Code. (D5 pending)

## Session 2026-06-08 — Follow-up: opencode config merging depth

### Problem Statement

The user confirmed: Direction 2 is chosen (per-project MCP config). The
WRITE_PREFIX fence stays. The practical question is: when a global
`~/.config/opencode/opencode.json` and a project-level `opencode.json` both
define a `cairn` MCP server entry, does opencode deep-merge at the env-var
level (ideal: project config only needs WRITE_PREFIX) or shallow-merge at the
server-entry level (pragmatic: project config must include the full entry)?

### Findings

**Claude Code** (`.mcp.json` per project): Standard per-project override —
the project-level `.mcp.json` runs a separate server process with its own
env. No merging question: project config is standalone.

**opencode config merging** (from https://opencode.ai/docs/config/ and
https://opencode.ai/docs/mcp-servers/):

The docs state: "Configuration files are merged together, not replaced.
Later configs override earlier ones only for conflicting keys."

However, the "Overriding remote defaults" example is revealing:

```json
// To override just enabled: true on the jira server, the example shows:
{
  "mcp": {
    "jira": {
      "type": "remote",
      "url": "https://jira.example.com/mcp",
      "enabled": true
    }
  }
}
```

The `type` and `url` fields are repeated just to override `enabled`. This
**strongly suggests the merge is shallow at the server-entry level** — i.e.,
`mcp.cairn` in the project config replaces `mcp.cairn` from global entirely,
rather than merging field-by-field within the entry. If the merge were deep,
you would only need `{"mcp": {"jira": {"enabled": true}}}`.

**Practical consequence**: The project-level `opencode.json` must include the
**complete** cairn-mcp server entry (all env vars, command, etc.), not just
the override fields. Global config cannot be used to hold shared backend
settings that project configs inherit.

**Confidence**: Medium — this interpretation is inferred from the example,
not from explicit documentation. An empirical test would confirm it. (D6
pending)

### Recommended Pattern (Direction 2, regardless of merge depth)

Given the shallow-merge finding, the safe recommendation is:

**Option A — Self-contained project config (works with shallow or deep merge):**

`~/.config/opencode/opencode.json` — no cairn-mcp entry (or a disabled
placeholder). Each project's `opencode.json` contains the complete cairn-mcp
entry with its own `WRITE_PREFIX`, `ARTIFACT_BUCKET`, etc.

```json
// project/opencode.json
{
  "mcp": {
    "cairn": {
      "type": "local",
      "command": ["uvx", "cairn-mcp"],
      "environment": {
        "WRITE_PREFIX": "team-a/project-x",
        "ARTIFACT_BUCKET": "my-cairn-bucket",
        "VECTORS_BUCKET": "my-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "AWS_REGION": "eu-central-1"
      }
    }
  }
}
```

**Option B — Global base + project override (works only if merge is deep):**

`~/.config/opencode/opencode.json` holds all shared settings; project config
only overrides `WRITE_PREFIX`. This is simpler but relies on deep-merge
behaviour that has not been empirically confirmed.

**Recommendation**: Document Option A. It is robust regardless of merge
semantics, gives operators explicit full control per project, and aligns
with how Claude Code's `.mcp.json` already works.

### Updated Open Questions

- **D5**: The setting-up-cairn skill should be updated to document the per-project
  setup pattern for all four supported clients (see Session 3 below).
- **D6**: An empirical opencode merge-depth test (place a partial `mcp.cairn`
  entry in project config and check if global env vars survive) would resolve
  ambiguity and potentially unlock Option B documentation as an alternative.

## Session 2026-06-08 — All four MCP clients: per-project config matrix

### Problem Statement

The user confirmed that all four major AI coding tools (Claude Code, opencode,
GitHub Copilot CLI, OpenAI Codex) support local (stdio) MCP servers, so cairn-mcp
is compatible with all of them. The question is: which ones support a
**per-project** config file that lets each project set its own `WRITE_PREFIX`,
so the fence stays correct without touching global config?

### Client-by-Client Findings

#### 1. Claude Code
- **Per-project file**: `.mcp.json` in the project root ✓
- **Global**: `~/.claude/claude_desktop_config.json`
- **Format**: JSON, `mcpServers` object
- **Env vars key**: `env`
- **Notes**: Can be committed to git. Project-level fully overrides global for
  the same server name. Standalone entry (no inheritance).

```json
{
  "mcpServers": {
    "cairn": {
      "command": "uvx",
      "args": ["cairn-mcp"],
      "env": {
        "WRITE_PREFIX": "team-a/project-x",
        "ARTIFACT_BUCKET": "my-cairn-bucket",
        "VECTORS_BUCKET": "my-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "AWS_REGION": "eu-central-1"
      }
    }
  }
}
```

#### 2. opencode
- **Per-project file**: `opencode.json` in the project root ✓
- **Global**: `~/.config/opencode/opencode.json`
- **Format**: JSON/JSONC, `mcp` object
- **Env vars key**: `environment` (not `env` — different from every other client)
- **Merge depth**: Shallow at server-entry level — project entry appears to
  replace global entry entirely; full entry needed in project file (D6 unresolved).
- **Notes**: Project config can be committed to git.

```json
{
  "mcp": {
    "cairn": {
      "type": "local",
      "command": ["uvx", "cairn-mcp"],
      "environment": {
        "WRITE_PREFIX": "team-a/project-x",
        "ARTIFACT_BUCKET": "my-cairn-bucket",
        "VECTORS_BUCKET": "my-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "AWS_REGION": "eu-central-1"
      }
    }
  }
}
```

#### 3. GitHub Copilot CLI
- **Per-project file**: `.mcp.json` at the workspace root ✓ — shipped in v0.0.401
  (≈ February 2026). See Research Note 2 at the end of this document for the full
  source trail.
- **Global fallback**: `~/.copilot/mcp-config.json` (still merges on top of the
  workspace file)
- **Format**: JSON, `mcpServers` object (or root-level) — `servers` key is NOT
  recognised; use `mcpServers`
- **Env vars key**: `env`
- **Shared with Claude Code**: `.mcp.json` with `mcpServers` is read by **both**
  Claude Code and Copilot CLI simultaneously — one file serves two clients.
- **Discovery**: traverses from the working directory up to the git root (v1.0.11+),
  so monorepo setups are covered automatically.
- **Notes**: The "per-repository" MCP config in GitHub repo settings
  (Settings → Copilot → MCP servers) is for the hosted Copilot Cloud Agent and
  Copilot code review — a separate surface that is unrelated to the local CLI.
  VS Code + Copilot Chat uses `.vscode/mcp.json` with the `servers` key; that file
  is different from `.mcp.json` used by Claude Code and Copilot CLI.

```json
{
  "mcpServers": {
    "cairn": {
      "type": "local",
      "command": "uvx",
      "args": ["cairn-mcp"],
      "env": {
        "WRITE_PREFIX": "team-a/project-x",
        "ARTIFACT_BUCKET": "my-cairn-bucket",
        "VECTORS_BUCKET": "my-cairn-vectors",
        "VECTORS_INDEX": "cairn-index",
        "AWS_REGION": "eu-central-1"
      },
      "tools": ["*"]
    }
  }
}
```

#### 4. OpenAI Codex
- **Per-project file**: `.codex/config.toml` in the project root ✓
- **Global**: `~/.codex/config.toml`
- **Format**: TOML, `[mcp_servers.<name>]` table sections
- **Env vars key**: `[mcp_servers.<name>.env]` sub-table
- **Precedence**: Project config wins over global; project layers loaded
  from root down to cwd (closest wins). **Trusted projects only** — Codex must
  have been explicitly trusted; untrusted projects skip project-scoped config.
- **Notes**: Sharing one global `~/.codex/config.toml` for backend settings
  and project `.codex/config.toml` for `WRITE_PREFIX` override is potentially
  supported (Codex merges layers), but the exact merge behaviour for `[mcp_servers]`
  tables needs empirical verification.

```toml
# .codex/config.toml
[mcp_servers.cairn]
command = "uvx"
args = ["cairn-mcp"]

[mcp_servers.cairn.env]
WRITE_PREFIX = "team-a/project-x"
ARTIFACT_BUCKET = "my-cairn-bucket"
VECTORS_BUCKET = "my-cairn-vectors"
VECTORS_INDEX = "cairn-index"
AWS_REGION = "eu-central-1"
```

### Comparison Matrix

| Client | Per-project file | Config format | Env key | Can be in git |
|--------|-----------------|---------------|---------|---------------|
| Claude Code | `.mcp.json` ✓ | JSON | `env` | ✓ |
| opencode | `opencode.json` ✓ (primary — officially documented) | JSON/JSONC | `environment` | ✓ |
| GitHub Copilot CLI | `.mcp.json` ✓ (shared with Claude Code) | JSON | `env` | ✓ |
| OpenAI Codex | `.codex/config.toml` ✓ | TOML | `[mcp_servers.x.env]` | ✓ (trusted) |

### Key Finding ~~(revised — see Research Note 2 below)~~

~~**GitHub Copilot CLI is the outlier**: it has no per-project config file.~~

**All four clients support per-project config.** Copilot CLI added `.mcp.json`
workspace support in v0.0.401 (≈ February 2026). It uses the same file and key
(`mcpServers`) as Claude Code — one `.mcp.json` at the workspace root serves both
clients simultaneously. The `servers` key used by VS Code is NOT recognised by
Copilot CLI. See Research Note 2 below for the full source trail.

The "global only + project-namespaced server name" workaround documented earlier
in this session is obsolete and should not be used.

### Implication for the setting-up-cairn skill (D5)

The skill should:
1. Document all four client configurations with exact syntax.
2. Call out the env key difference: opencode uses `environment`, all others use `env`.
3. Note that `.mcp.json` is shared between Claude Code and Copilot CLI — one file,
   two clients, using `mcpServers` key. `servers` (VS Code's key) is not recognised
   by Copilot CLI.
4. Recommend committing per-project config files to git as the standard pattern for
   all four clients.
5. opencode merge confirmed additive: the full entry is needed only for cairn
   (since it is a new server name not in global config); no need to duplicate
   shared MCP servers.
6. For Codex, note the "trusted projects only" requirement for project config.

### Locked Decisions Update

- **D5**: ✓ Resolved — setting-up-cairn skill needs updating for all four clients
  (matrix documented above provides the content)
- **D7** (new): Codex merge depth for `[mcp_servers]` across global + project
  layers needs empirical verification (analogous to D6 for opencode)

## Session 2026-06-08 — opencode merge depth: empirical confirmation

### Test Setup

The user ran opencode with:

**Global config** (`~/.config/opencode/opencode.json`): contained three MCP
server entries — a proxy-based AWS MCP server, an IaC MCP server with its own
environment block, and a CloudWatch MCP server (disabled). All three have
separate names and unrelated environment variables.

**Project config** (`opencode.json` in the project root — contained a single
MCP server entry named `cairn` with its own environment block including
`WRITE_PREFIX`, backend bucket/index settings, AWS profile, and log levels.
The `cairn` server name did not appear in the global config at all.

### Result

All four servers were active in the session: the three from global config plus
`cairn` from the project config. The project entry was **additively merged** —
not a replacement of the global `mcp` block.

### Conclusions from this test

1. **opencode merges at the server-name level (additive)**: A project config
   that introduces a server name not present in the global config adds it to the
   merged set. Global servers are preserved unchanged.

2. **The pattern works for cairn-mcp**: Put cairn only in the project config.
   Other shared MCP servers (AWS, IaC tooling, etc.) stay in the global config.
   Result: the developer gets all their shared tools plus a project-scoped cairn
   instance with the correct `WRITE_PREFIX` — without any duplication.

3. **Same-name override behaviour not tested**: If `cairn` had also appeared in
   the global config, it is not known whether the project entry would deeply
   merge fields or replace the entire entry. The Copilot docs example still
   suggests shallow (full-entry replacement), but this remains unconfirmed for
   opencode (D6 partially resolved, same-name case still open).

4. **~~`.opencode.json` is a supported config filename~~** ⚠ **RETRACTED — see Research
   Note 3**: This conclusion was incorrect. A subsequent installation test showed that
   opencode did NOT load `.opencode.json` from the project root — the file was silently
   ignored and only the global configs loaded. The officially documented project config
   name is `opencode.json` (no dot prefix).

### Practical Guidance Update for the setting-up-cairn skill

- Check for both `opencode.json`.
- If neither exists, create `opencode.json` (no dot prefix — officially documented name).
  **Do not create `.opencode.json`** — it was not reliably loaded in a subsequent test.
- If one already exists, parse it and insert `mcp.cairn` without disturbing any
  existing keys. This requires JSON-aware editing (not a text append), and must
  handle JSONC (comments) gracefully.
- The cairn entry is self-contained: it need not repeat any settings from the
  global config. Only project-specific values belong here: `WRITE_PREFIX` and
  any env vars that differ per project.
- Do not touch the global config at all during project setup; the global config
  is the user's personal preference layer and must not be overwritten.

### New Requirement: D8 — Safe file editing in the setting-up-cairn skill

The install skill must not blindly create or overwrite config files. Required
behaviour for each client:

| Client | Files to check | If exists | If absent |
|--------|---------------|-----------|-----------|
| Claude Code | `.mcp.json`, `.mcp.jsonc` | Insert `mcpServers.cairn` | Create `.mcp.json` |
| opencode | `opencode.json` | Insert `mcp.cairn` | Create `opencode.json` (no dot; `.opencode.json` does not work) |
| Copilot CLI | `.mcp.json` (**shared with Claude Code**, workspace root) | Insert `mcpServers.cairn` | Create `.mcp.json` |
| Codex | `.codex/config.toml` | Insert `[mcp_servers.cairn]` section | Create `.codex/config.toml` |

For JSON/JSONC files: read → parse (strip comments for JSONC) → merge at the
correct key → write back (preserving existing comment blocks where possible, or
at minimum not destroying the file). A pure text approach (sed/append) is
insufficient and risks producing invalid JSON.

For TOML files: check if `[mcp_servers.cairn]` already exists → if so, confirm
with the user before overwriting → otherwise append the new section.

If the skill is invoked in an environment where Python / `uv` is available, a
small inline Python snippet using `json` (for JSON files) and `tomllib`/
`tomli_w` (for TOML) is more reliable than shell text manipulation.

## Research Note 2026-06-08 — Copilot CLI per-project config: **CORRECTED — feature shipped**

### Question

Does GitHub Copilot CLI support a per-project MCP config file?

### Initial assessment (incorrect)

Based on reading only the issue bodies of #1291 and #2528 (both feature requests)
and a third-party PR, the initial assessment was: "global only — no per-project
config file." This was wrong. The issues were closed because the feature had already
shipped, not because it was rejected.

### Corrected finding (from issue comments)

**GitHub Copilot CLI supports `.mcp.json` at the workspace root. This was shipped in
v0.0.401 (approximately February 2026).**

Sources (all from GitHub API, issue comments):

- **Issue #1291, `mrclrchtr` (Feb 26, 2026)**:
  "https://github.com/github/copilot-cli/releases/tag/v0.0.401 — added .mcp.json support"

- **Issue #1291, `examon` — GitHub site admin (Apr 7, 2026)**:
  "This should be resolved as of v0.0.401, which added support for repository-level
  MCP configuration via `.mcp.json` at the workspace root. The CLI also reads
  `.vscode/mcp.json` and `.devcontainer/devcontainer.json`, and as of v1.0.11 it
  discovers these configs from the working directory up to the git root, which covers
  monorepo setups as well."

- **Issue #1291, user on v1.0.22 (Apr 10, 2026)** — actual CLI warning message:
  "Found .vscode/mcp.json but no .mcp.json. Copilot CLI only reads MCP servers from
  .mcp.json — consider migrating your config"

- **Issue #2528, `hackel` (May 4, 2026)**:
  "the workspace-level MCP configuration is read from `.mcp.json` in the workspace
  root, not in `.github`, which is good as it is standardized with other tools. This
  was added 3 months ago. Note that the servers must be specified in either the root
  of the JSON document, or under the `mcpServers` key. `servers` is not recognized."

### Full specification of Copilot CLI per-project config

- **File**: `.mcp.json` at the workspace root
- **Top-level key**: `mcpServers` (or root-level) — `servers` is NOT recognised
- **Env vars key**: `env` — same as Claude Code
- **Discovery**: traverses from working directory up to the git root (v1.0.11+)
- **Global fallback**: `~/.copilot/mcp-config.json` still applies as a merge/fallback
  on top of the workspace file
- **Shared with Claude Code**: `.mcp.json` with `mcpServers` key is read by BOTH
  clients — one file serves both simultaneously

### Impact on the setting-up-cairn skill

The "global only + namespaced server name" workaround documented earlier in Session 3
is **obsolete**. All four clients now support per-project config. The T31a spec has
been updated accordingly.

The updated comparison matrix — all four clients support per-project config with
committed-to-git files — is now in Session 3 above.

### Watch list

The official Copilot CLI docs page at
https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
has not yet been updated to document `.mcp.json` workspace support (as of June 2026).
When it is, verify the canonical documentation matches the behaviour described here.

## Research Note 3 — 2026-06-08: `.opencode.json` dot-prefix is NOT reliably loaded

### Question

Is `.opencode.json` (dot-prefixed) a valid opencode project config filename, as concluded
in Session 4 Conclusion 4?

### Evidence

An installation test was run where `skills/setting-up-cairn/SKILL.md` created
`.opencode.json` in the project root. After restarting opencode from that project
directory, the opencode startup log showed:

```
service=config path=/home/.../.config/opencode/config.json loading
service=config path=/home/.../.config/opencode/opencode.json loading
service=config path=/home/.../.config/opencode/opencode.jsonc loading
```

`.opencode.json` **never appeared** in the config-loading sequence. Only the three global
configs loaded. The MCP servers from `.opencode.json` (including `cairn`) were not started.

### Conclusion

Session 4 Conclusion 4 was wrong. The earlier test that appeared to confirm `.opencode.json`
support was likely confounded (possible explanations: the test project also had an
`opencode.json` at a parent level, or a different version of opencode was running).

The **officially documented project config name is `opencode.json`** (no dot prefix) — this
is what the opencode docs at https://opencode.ai/docs/config/ describe. The skill must
create `opencode.json`, not `.opencode.json`. The dot-prefix variant should still be checked
during detection (in case an operator already has one from a prior misguided setup) but must
never be created.

### Files corrected

- `docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`
  — Session 4 Conclusion 4 retracted; Practical Guidance and D8 table updated;
    comparison matrix updated; D6 note amended
- `docs/specs/p9-t31a-setting-up-cairn-skill.md`
  — all `.opencode.json` create references updated to `opencode.json`; IDE table updated;
    Requirements updated; testing checklist updated
- `skills/setting-up-cairn/SKILL.md`
  — detection table, entry format heading, permission gate example, and file creation
    target all updated to `opencode.json`

---
type: brainstorming
title: Phase 9 — Skill Distribution via Native Plugin Mechanisms
description: Explores how to wire Arkeology's operator skills into engineers' AI tools (OpenCode, Claude Code, GitHub Copilot) using the Phase 5 native plugin pattern, adapting it for Arkeology's specific characteristics as a Python MCP server with only two skills.
tags: []
timestamp: 2026-06-08T00:00:00Z
okf_version: "0.1"
status: complete
references:
  - docs/brainstorming/brainstorming-2026-06-02-setting-up-arkeology-skill.md
authored:
  by: analyst
  date: 2026-06-08
revised:
  by: Matthieu
  date: 2026-06-10
---

# Phase 9 — Skill Distribution via Native Plugin Mechanisms

## Description

Arkeology already has `skills/` at the repo root with two operator skills
(`setting-up-arkeology`, `migrating-to-arkeology`). Engineers who adopt Arkeology clone the repo to
run the server — the local clone is always present. This session explores how to wire those
skills into engineers' AI tools (OpenCode, Claude Code, GitHub Copilot) using the same native
plugin mechanisms that were proven in Phase 5 of the shared engineering plugin project.

The question is not *whether* to use the Phase 5 pattern — that is settled. The question is
*how to adapt it* for the specific characteristics of arkeology: a Python MCP server with
only two skills and no agents, whose AGENTS.md is server-setup documentation rather than
general engineering conventions.

---

## Decisions

### Locked

- D1: Skip CLAUDE.md @-import — Arkeology AGENTS.md is server-specific; per-project snippet written by setting-up-arkeology already covers this
- D2: Ship sync skill — delivered as arkeology:sync-arkeology-plugin (T34), a cross-IDE generic skill replacing the Claude Code-only plugin-sync concept; distributed via all three channels (OpenCode plugin, Claude Code plugin, Copilot gh skill install)
- D3: Full JS plugin for OpenCode — package.json + .opencode/plugins/arkeology.js config hook; install.sh prints the one-line git+ssh:// snippet
- D4: Brief coexistence note in README — short quick-install section plus a paragraph noting Arkeology coexists with the shared engineering plugin without namespace collision

### Pending

_None._

### Closed — Not Applicable

_None._

## Techniques Used

- analogy
- inversion
- perspective-shift

## Assumptions Challenged

- "A CLAUDE.md @-import is always desirable (false — Arkeology's AGENTS.md contains server-specific setup context, not general conventions applicable to all sessions)"
- "The JS plugin + git+ssh:// mechanism adds value when the clone is already local (partially false — a skills.paths patch is simpler but loses the auto-path-resolution advantage)"
- "sync-arkeology-plugin is only useful for large skill catalogues (false — it saves one manual step even for 2 skills)"
- "Arkeology and the shared engineering plugin install scripts must be coordinated (false — both are idempotent bash scripts that coexist without conflict)"

## Session 2026-06-08

### Problem Statement

The Phase 5 distribution pattern (from the shared engineering plugin) is the reference
implementation. It delivers five features:

| Phase 5 feature | What it does |
|-----------------|-------------|
| F5.1 OpenCode JS plugin | `package.json` + `.opencode/plugins/amanox.js` config hook; one line in `opencode.jsonc` registers all skills |
| F5.2 Claude Code plugin | `.claude-plugin/` + `plugins/amanox/` (symlinks to skills + agents); `amanox:sync-amanox-plugin` skill; `install.sh` wires CLAUDE.md `@`-import + settings.json pre-approval |
| F5.3 Install script | Detects `claude`, `opencode`, `copilot`; applies wiring; symlinks agents; session-refresh output |
| F5.4 Copilot adapter | `gh skill install` loop per skill inside `install.sh` |
| F5.5 README four-layer composability | Documents personal baseline + team + client + project layers |

This pattern maps almost entirely to Arkeology. Three structural differences require
design decisions:

1. **No agents directory** — Arkeology has no agents to distribute. The agents-symlink loop
   in `install.sh` simply does not exist. No design decision needed; the step is absent.

2. **CLAUDE.md `@`-import** — the reference project imports its `AGENTS.md` globally because
   it contains general engineering conventions (methodology, skill philosophy) that apply in
   every session. Arkeology's `AGENTS.md` contains server-setup documentation (env vars,
   bucket config, tool registration, testing conventions for the server codebase). Injecting
   this globally would add Arkeology server context to sessions working on unrelated projects.
   **This is the primary design question.**

3. **`arkeology:sync-arkeology-plugin` path** — the reference project's `sync-amanox-plugin` runs
   `git -C ~/.claude/plugins/amanox pull`. For Arkeology, the equivalent skill targets
   `~/.claude/plugins/arkeology/`. T34 generalised this into a cross-IDE skill
   (`sync-arkeology-plugin`) rather than a Claude Code-only one. The two clones (plugin clone
   and server clone) are separate and updated independently.

Everything else is a direct 1:1 copy of the reference pattern with name substitutions.

---

### The near-1:1 mapping

| Phase 5 | Arkeology equivalent | Difference |
|---------|---------------------|------------|
| `package.json` (name: `amanox-ai-agents`, main: `.opencode/plugins/amanox.js`) | `package.json` (name: `arkeology`, main: `.opencode/plugins/arkeology.js`) | Names only |
| `.opencode/plugins/amanox.js` config hook | `.opencode/plugins/arkeology.js` config hook | Names only; same ~50-line ESM template |
| `.claude-plugin/marketplace.json` | `.claude-plugin/marketplace.json` | Plugin name changes to `arkeology` |
| `plugins/amanox/.claude-plugin/plugin.json` | `plugins/arkeology/.claude-plugin/plugin.json` | Name, description only |
| `plugins/amanox/skills/<name>` symlinks (30+) | `plugins/arkeology/skills/<name>` symlinks (2) | Fewer skills; same symlink pattern |
| `plugins/amanox/agents/<name>.md` symlinks (5) | *(absent — no agents in Arkeology)* | N/A |
| `plugins/amanox/skills/sync-amanox-plugin/SKILL.md` | `plugins/arkeology/skills/sync-arkeology-plugin/SKILL.md` | Generalised to cross-IDE skill in T34 |
| `install.sh` agent symlinks loop | *(absent)* | N/A |
| `install.sh` CLAUDE.md `@`-import step | **Design decision D1** | See below |
| `install.sh` settings.json pre-approval (for `sync-arkeology-plugin`) | Same | Same pre-approval rule: `Bash(git -C * pull)` |
| `install.sh` Claude Code SSH URL only | **Both SSH and HTTPS forms documented** | `claude plugin marketplace add` also accepts `https://github.com/…`; SSH-blocked environments need the HTTPS alternative (see G8) |
| `gh skill install` loop per skill in `install.sh` | Same; 2 skills | Same |
| README quick install section | README quick install section | Different framing (tool-specific, not personal baseline) |

---

### Ideas Explored

#### Cluster A — CLAUDE.md @-import (D1)

**A1 — Skip the @-import entirely**
No line written to `~/.claude/CLAUDE.md`. Skills are available via the plugin namespace
(`arkeology:setting-up-arkeology`, `arkeology:migrating-to-arkeology`) without any global context injection.
The project-specific AGENTS.md snippet written by `setting-up-arkeology` at install time already
places the right context in each project's AGENTS.md — globally injecting a second, different
context file would be redundant and confusing.

**A2 — Import Arkeology's AGENTS.md anyway**
`@<repo>/AGENTS.md` prepended to `~/.claude/CLAUDE.md`. Engineers who use Arkeology across
multiple projects would have the server setup context available globally. However, the content
(env var names, bucket config, test harness details) is irrelevant outside sessions where
Arkeology tools are actively connected. Adds noise; risk of stale or confusing context in
unrelated sessions.

**A3 — Create a dedicated slim agent-usage context file (`AI_CONTEXT.md`)**
A new file at repo root containing only the agent-facing artifact conventions: when to write
artifacts, artifact types, description quality guidance, tier selection. None of the server
setup details. Import this file globally. Engineers in any session connected to an Arkeology
server get the right prompting context; the setup instructions stay in AGENTS.md.

**A4 — No global import; rely on per-project AGENTS.md**
The `setting-up-arkeology` skill already writes a `arkeology:config` block and a narrative
snippet into each project's AGENTS.md. Claude Code reads that per-project AGENTS.md
automatically. The global import adds nothing that isn't already covered per-project.
This reinforces A1 as the right answer.

**Assessment:** A1 + A4 converge on the same conclusion — skip the global import. The
reference project's @-import carries general engineering conventions (methodology); that
use case does not apply here. Each project's AGENTS.md (written by `setting-up-arkeology`)
already contains the right context for sessions in that project.

---

#### Cluster B — sync skill (D2)

**B1 — Include a sync skill**
Same pattern as the reference project. A skill that updates the plugin clone and reloads
skills. Pre-approval rule `Bash(git -C * pull)` written to `settings.json` by `install.sh`.
Engineers invoke the skill to get updated skills without a full reinstall. Initially
scoped to Claude Code only (matching the reference project); later generalised in T34 into
`arkeology:sync-arkeology-plugin` — a cross-IDE skill detecting the running tool and taking the
correct action for each (OpenCode: clear Bun cache + restart; Claude Code: `git pull` +
`/reload-plugins`; Copilot: re-run `install.sh`).

**B2 — Skip the sync skill; document manual update instead**
Arkeology has only 2 skills. `git pull` on the server clone is the primary update action
anyway. Engineers already know to update the server. A skill + pre-approval wiring adds
overhead for a one-command operation engineers already do. README instructions cover it.

**B3 — Sync skill also surfaces server update guidance**
The sync skill updates the plugin clone and reloads skills. The server clone (used to run
Arkeology) is a separate concern. The skill should note that the server requires a separate
`git pull` + `uv sync` + restart. It does NOT run those commands — it only manages the
skills plugin clone.

**Assessment:** B1 is the right call. The skill is trivial to add, consistent with the
reference pattern, and saves one friction point (engineers won't need to look up the manual
update steps). B3 is a gotcha to include in the skill's notes section, not a separate option.
The pre-approval is scoped narrowly (`Bash(git -C * pull)`) — no blanket bash access.

---

#### Cluster C — OpenCode distribution mechanism (D3)

**C1 — Full JS plugin: `package.json` + `git+ssh://` URL in `opencode.jsonc`**
Same as the reference project. Engineers add one line to `~/.config/opencode/opencode.jsonc`;
Bun's resolver fetches and caches the plugin from the git URL; the config hook registers
`skills/` automatically. Works regardless of where the engineer's local clone lives.
The `install.sh` prints (but does not apply) the one-line snippet.

**C2 — Simpler: `install.sh` patches `opencode.jsonc` with a `skills.paths` entry**
Since the clone is always present locally (engineers need it to run the server), `install.sh`
can directly add `"skills": { "paths": ["/absolute/path/to/arkeology/skills"] }` to
`~/.config/opencode/opencode.jsonc`. No `package.json`, no JS, no Bun resolver. Uses the
existing local clone. Official config field — no experimental API.

**C3 — Both: JS plugin is the documented primary path; install.sh patches as the automated path**
The install script detects `opencode`, resolves the REPO_DIR absolute path, and patches
`opencode.jsonc` with a `skills.paths` entry using that absolute path. Also prints the
`git+ssh://` plugin line as an alternative. Engineers who prefer the auto-updating plugin
URL can use it; the install script covers the simpler case.

**Assessment:** C1 (full JS plugin) is the correct choice — consistent with the reference
pattern, auto-updating via Bun, works regardless of clone location, and `package.json` is
already required for the plugin mechanism. C2 is attractive but couples the OpenCode wiring
to a hardcoded absolute path; if the engineer moves their clone, the path breaks. C3 adds
complexity without a clear win over C1. The install script for OpenCode prints the one-line
snippet (same as the reference project) rather than patching the config directly — this
preserves the engineer's existing JSON structure.

---

#### Cluster D — README framing and four-layer composability (D4)

**D1 — "Quick install" section only; no four-layer composability section**
Arkeology is a specific tool, not a personal engineering baseline. The four-layer model
(amanox + team + client + project) makes sense for a shared methodology plugin. For
Arkeology it is just: "add the plugin line, run install.sh, restart your session." A
four-layer section would over-engineer the framing.

**D2 — Brief composability note: Arkeology as a complementary plugin alongside the shared engineering plugin**
Many Arkeology users already have the shared engineering plugin installed. A short note
explaining that both plugins coexist — `amanox:brainstorming` for methodology, `arkeology:setting-up-arkeology`
for this server — is more useful than a full four-layer taxonomy.

**D3 — Same four-layer documentation as the reference project**
Copy the four-layer framing. Adds consistency for engineers who know the reference project's
README. Overkill for a 2-skill distribution.

**Assessment:** D2 is the right call. A short "plays well with others" note explaining
coexistence with the shared engineering plugin is directly useful without the overhead
of the full four-layer model.

---

### Selected Directions

**D1 — Skip CLAUDE.md @-import**
The `install.sh` does NOT prepend an `@`-import to `~/.claude/CLAUDE.md`. The project-level
AGENTS.md snippet (written by `setting-up-arkeology`) already provides the right per-project
context. Global injection would add server-setup noise to unrelated sessions.

**D2 — Ship `arkeology:sync-arkeology-plugin`** *(delivered as T34 — outcome differs from session decision)*
The session selected `arkeology:plugin-sync` (Claude Code-only, ~22 lines, updating the plugin
clone only). T34 later generalised this into `arkeology:sync-arkeology-plugin`: a cross-IDE skill
that detects the running tool and takes the correct update action for each (OpenCode: clear
Bun cache + restart; Claude Code: `git pull` + `/reload-plugins`; Copilot: re-run
`install.sh`; unknown tool: explain all three paths). The skill is distributed through all
three channels (OpenCode plugin auto-discovers it; Claude Code plugin symlink; Copilot via
`gh skill install`). `plugin-sync` was removed when `sync-arkeology-plugin` shipped.
The gotcha note about the server requiring a separate update remains applicable.

**D3 — Full JS plugin for OpenCode**
`package.json` at repo root + `.opencode/plugins/arkeology.js` config hook. Install script prints
the one-line `git+ssh://` snippet. Consistent with the reference pattern; works regardless of
clone location.

**D4 — Brief coexistence note in README**
Short "Quick install" section + a paragraph noting Arkeology coexists with the shared
engineering plugin (no namespace collision; both are active simultaneously). No full four-layer
taxonomy.

---

### Summary of what maps 1:1 vs what differs

| Concern | Decision |
|---------|----------|
| OpenCode JS plugin (`package.json` + config hook) | ✅ Include — same template, name substitution only |
| Claude Code plugin (`.claude-plugin/` + `plugins/arkeology/` + symlinks) | ✅ Include — same pattern; 2 skill symlinks, no agent symlinks |
| `arkeology:sync-arkeology-plugin` skill | ✅ Delivered as T34 — cross-IDE generic skill replacing `plugin-sync`; distributed via all three channels |
| `install.sh` | ✅ Include — no agent symlinks loop; no @-import step; otherwise identical |
| `install.sh` Claude Code URL | ✅ Both SSH and HTTPS — `claude plugin marketplace add` accepts `git@github.com:…` (SSH primary) and `https://github.com/…` (HTTPS fallback for firewalled environments); both forms in session-refresh summary |
| Copilot adapter (`gh skill install` loop) | ✅ Include — same as reference; 2 skills |
| CLAUDE.md `@`-import | ❌ Skip — Arkeology AGENTS.md is server-specific; per-project AGENTS.md already covers this |
| Agent symlinks loop in `install.sh` | ❌ Absent — Arkeology has no agents |
| `settings.json` pre-approval for `sync-arkeology-plugin` | ✅ Include — scoped to `Bash(git -C * pull)` |
| README four-layer composability | ⚡ Abbreviated — short coexistence note only |

---

### Open Questions

All genuinely resolvable questions are resolved above. The following require a decision
before the PM can spec this:

- **Q1 — Copilot empirical verification**: The reference project confirmed `gh skill install`
  works with private repos (closed 2026-06-08 per F5.4). Arkeology's repo URL will differ —
  confirm the same `--from-local` flag works (it installs from the local clone, bypassing
  GitHub API access entirely, so private-vs-public is irrelevant when using `--from-local`).

- **Q2 — `package.json` version field**: The existing `skills/migrating-to-arkeology/schema.yaml`
  references an Arkeology schema version. Should `package.json` carry the same semver as
  `pyproject.toml`, or should it be managed independently? The reference project keeps
  `package.json` version in sync with the overall release version. The same approach is
  recommended here — one source of truth, updated at release time.

- **Q3 — Plugin name in Claude Code**: The `.claude-plugin/marketplace.json` plugin name
  determines the slash command namespace (`arkeology:<skill>`). Confirm `arkeology` is the preferred
  namespace over `arkeology` (shorter to type; unambiguous given there is no other
  `arkeology`-namespaced tool in use).

---

## Known Implementation Gotchas

The following issues were discovered post-delivery in the reference implementation. Every
one caused a silent failure or broken install. They are recorded here so the T33 spec can
prescribe the correct form from the start and avoid a repeat fix cycle.

### G1 — `git+ssh://` URL must use forward slash, not colon

The npm git+ssh specifier requires a forward slash after the hostname:

```
git+ssh://git@github.com/org/repo.git   ← correct
git+ssh://git@github.com:org/repo.git   ← wrong (SCP syntax, invalid Node.js URL)
```

With the colon form, Node.js throws `ERR_INVALID_URL`. The OpenCode plugin manager
silently does nothing: no entry in `node_modules/`, the config hook never fires,
and no skills appear. There is no error message — it just looks like the plugin
was never configured.

**Spec must**: specify the slash form in every place the URL appears
(plugin file comment, README, `install.sh` output, HTTPS alternative).

---

### G2 — SKILL.md `description` values containing `: ` must be double-quoted

Python's `yaml.safe_load` accepts unquoted plain scalars containing `: `. The Go
YAML parser used by `gh skill install` is strict and rejects them with a parse
error. Any skill whose description reads like `"Foo: bar baz"` without quotes
will fail silently during Copilot installation.

**Spec must**: require that all SKILL.md `description` values are double-quoted.
**Also**: add a `scripts/validate.py` (or equivalent pre-commit check) that catches
unquoted descriptions containing `: ` — one that flags them before commit, not after
a broken install.

---

### G3 — `gh skill install` requires four specific flags

All four are mandatory; the command misbehaves or breaks idempotency without them:

| Flag | Why it is required |
|------|--------------------|
| `--from-local` | Installs from local clone; no remote API calls; works offline |
| `--agent github-copilot` | Without it, the command prompts interactively and hangs in a script |
| `--scope user` | User-level install, available everywhere; scope defaults are unreliable |
| `--force` | Overwrites on re-run without prompting; required for idempotency |

**Spec must**: show all four flags in the `gh skill install` command template.

---

### G4 — Copilot detection: `copilot` on PATH, not `gh`

`gh` is GitHub's general-purpose CLI (PRs, issues, releases) — its presence says
nothing about which AI coding tool is installed. Using `command -v gh` as the
Copilot detection signal fires the Copilot section for every developer who has
`gh` installed, regardless of whether they use Copilot at all.

**Spec must**: detection signal = `command -v copilot`. Inside the Copilot section,
check `command -v gh` and `gh skill --help` as prerequisites and print the install
URL if either is missing.

---

### G5 — `marketplace.json` required fields

The minimal valid `marketplace.json` for Claude Code plugin registration requires:

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "<name>",
  "owner": { "name": "<org>" },
  "plugins": [
    {
      "name": "<name>",
      "description": "...",
      "author": { "name": "<org>" },
      "source": "./plugins/<name>",
      "homepage": "..."
    }
  ]
}
```

Missing `owner`, missing `$schema`, or using a bare `path` key instead of `source`
causes the marketplace registration to fail or the plugin to not be found.

**Spec must**: show the complete `marketplace.json` structure with all required fields.
The `source` value must be a relative path to the plugin directory (`"./plugins/arkeology"`).

---

### G6 — `plugin.json` must omit `version`

Including a static `version` string in `plugins/arkeology/.claude-plugin/plugin.json`
pins users to that version permanently. `claude plugin update` sees no change and does
nothing. Omitting `version` causes Claude Code to use the commit SHA, so every push
to the repo is picked up as an update.

**Spec must**: `plugin.json` contains only `name` and `description` — no `version` field.

---

### G7 — Print plugin lines in the final summary, not only mid-script

`install.sh` typically runs for several seconds while wiring multiple tools. By the
time the OpenCode section runs and prints the plugin line, that output has already
scrolled off the terminal when the final summary appears. Engineers copy-paste from
the bottom of the output — not from the middle.

**Spec must**: the session-refresh summary at the bottom of `install.sh` must repeat
both the SSH and HTTPS plugin lines verbatim, even if they were already printed
earlier in the OpenCode section.

---

### G8 — `claude plugin marketplace add` needs an HTTPS alternative

`claude plugin marketplace add` accepts a plain git URL — both SSH (`git@github.com:…`)
and HTTPS (`https://github.com/…`) forms work. The reference project's install script
only uses the SSH form. Engineers in corporate environments where outbound port 22 is
blocked by a firewall cannot use the SSH form, and the `|| true` guard means the failure
is silent: the script exits 0, the marketplace is never registered, and `claude plugin install`
subsequently does nothing — with no error message.

This was not caught in the reference project because all testing was done on machines
with SSH access. It was identified during Arkeology spec review.

**Spec must**: document both SSH and HTTPS forms of `claude plugin marketplace add`
everywhere the command appears — install script session-refresh summary, README, and
CONTRIBUTING.md. The SSH form is primary; the HTTPS form is labelled as the fallback
for SSH-blocked environments.

Note: unlike the OpenCode plugin URL (which uses the npm `git+ssh://` or `git+https://`
specifier format), the `claude plugin marketplace add` argument is a plain git remote URL:
- SSH form: `git@github.com:amanoxsolutions/arkeology.git`
- HTTPS form: `https://github.com/amanoxsolutions/arkeology.git`

These are different formats from the OpenCode plugin URL — do not mix them up.

---
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-06-01"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# ADR Relationship Between Git and cairn-mcp

## Description

cairn-mcp supports `adr` as an artifact type, yet the migration skill instructs operators to
keep ADRs in git after migration ("they are canonical decision records and belong in git
alongside the code they govern"). This creates a genuine design question: if ADRs stay in git,
what role does cairn-mcp play — authoritative store, search index, draft staging area, or
nothing? And what workflow guidance should the migration skill and AGENTS.md give?

This session also surfaces an internal contradiction: the migration skill's "Post-migration
cleanup" table says keep ADRs in git (do not remove them), but the AGENTS.md snippet appended
by the same skill instructs future agents to write `adr` artifacts to cairn-mcp without any
mention of also committing them to git. These two pieces of guidance point agents in different
directions.

---

## Session 2026-06-01

### Contradiction already present in the codebase

Before evaluating options, it is worth naming the contradiction precisely:

| Piece of guidance | What it says |
|---|---|
| `SKILL.md` Step 7, cleanup table | `adr` — **No** — keep ADRs in the repo |
| `SKILL.md` Step 7, AGENTS.md snippet | `adr` / `spec` → tier 3, visibility=shared — agents should `write_artifact` for these |

The cleanup table implies cairn-mcp is an index (the git copy is canonical, don't delete it).
The AGENTS.md snippet implies cairn-mcp is the destination (agents write ADRs there). Neither
piece of guidance says what happens to the git file when an agent writes a new ADR to
cairn-mcp. The gap is "who commits to git?"

Any recommendation must close this gap explicitly.

---

### Option evaluations

#### Option 1 — Git is canonical, cairn-mcp is a search index

ADRs are authored by humans and committed to git. After a commit, the ADR is indexed in
cairn-mcp (either manually, via the migration skill, or by an agent that notices the gap).
cairn-mcp is read-only from the agent's perspective for ADRs; agents search and read, never
write new approved ADRs to cairn-mcp directly.

| Criterion | Score | Notes |
|---|---|---|
| Consistency | ⚠️ Medium | Indexing is a separate step; a committed ADR may be stale in cairn-mcp until re-indexed. An agent that reads the stale cairn-mcp copy acts on outdated information — this is a real failure mode, not just a cosmetic one. |
| Auditability | ✅ High | Git history is the unambiguous record of when and why a decision was made. |
| Discoverability | ✅ High | Semantic search works once indexed. |
| Simplicity | ⚠️ Medium | The indexing step is not automatic. The workflow is: commit to git → also write to cairn-mcp. If the second step is forgotten, cairn-mcp is stale. |
| Reversibility | ✅ High | ADRs are fully intact in git if cairn-mcp is decommissioned. |

**Risk**: The stale-index problem is worse for ADRs than for other artifact types because ADRs
evolve (status changes, superseded decisions, amendments). An agent reading a stale ADR that
has since been superseded might act on a cancelled decision. No technical guard prevents this.

---

#### Option 2 — cairn-mcp is canonical, git is a mirror

Agents author ADRs via `write_artifact`. A commit hook or manual export step writes the
cairn-mcp content to `docs/adr/` in git. The git copy is human-readable backup.

| Criterion | Score | Notes |
|---|---|---|
| Consistency | ⚠️ Medium | Export step is required; without it git diverges from cairn-mcp. |
| Auditability | ❌ Low | Git history is now secondary — authored outside of git, then pushed in. Diffs and blame are less meaningful. The standard ADR property (decision embedded in the repo alongside the code it governs) is lost. |
| Discoverability | ✅ High | |
| Simplicity | ❌ Low | Requires export tooling (or manual copy-paste); no such tooling exists today. |
| Reversibility | ⚠️ Medium | Depends entirely on export discipline. If cairn-mcp is decommissioned without a recent export, ADR history lives only in the vector store, not in git. |

**Verdict**: Sacrifices auditability — the most important property of an ADR — for the benefit
of agents being the primary author. Not appropriate for a document type whose defining purpose
is to be a permanent, auditable decision record.

---

#### Option 3 — Dual write, git-wins on conflict

Agents write ADRs to cairn-mcp (for search) AND commit a markdown file to git (for history).
On conflict, the git version is canonical. Requires workflow discipline, not technical enforcement.

| Criterion | Score | Notes |
|---|---|---|
| Consistency | ❌ Low | Two writes on every ADR event (create, update, status change). Both must be kept in sync manually. Discipline degrades over time, especially in multi-agent or multi-developer teams. |
| Auditability | ✅ High | Git is canonical. |
| Discoverability | ✅ High | |
| Simplicity | ❌ Low | Every ADR interaction is a two-step operation with no guardrails. |
| Reversibility | ✅ High | |

**Risk**: In practice, dual-write disciplines decay. After 6 months one of the two copies will
be ahead of the other for some ADRs. Without a reconciliation tool, operators have no way to
know which ADRs have drifted. `reconcile_index` can rebuild cairn-mcp from S3, but not from
git — there is no git-to-cairn-mcp reconciliation path.

---

#### Option 4 — cairn-mcp for drafts, git for approved ADRs

ADRs go through a lifecycle: draft → approved. During the draft phase, an agent (or the
operator) writes the ADR to cairn-mcp as `visibility=hidden`. When the ADR is approved (by
the team, in a PR), two things happen: the final content is committed to git, and the
cairn-mcp artifact is updated to `visibility=shared`. Git is the approval signal.

| Criterion | Score | Notes |
|---|---|---|
| Consistency | ✅ High | The two copies are in sync by construction: the approved text is committed to git and simultaneously updated in cairn-mcp to shared. Divergence is bounded to the draft phase (hidden, so agents don't search it yet). |
| Auditability | ✅ High | Git captures the final, approved decision. The PR is the approval event. |
| Discoverability | ✅ High | Approved ADRs are searchable (shared). Draft ADRs are hidden from cross-team search. |
| Simplicity | ⚠️ Medium | Requires understanding the two-phase lifecycle. The approval step requires two actions (git commit + cairn-mcp update). A small risk: the approval is committed to git but the cairn-mcp artifact remains hidden, so the approved ADR is invisible to agent search. |
| Reversibility | ✅ High | Approved ADRs are in git; cairn-mcp is the search layer. |

**Risk**: The approval step requires two deliberate actions (commit to git, update cairn-mcp
visibility). Neither action triggers the other automatically. If only one is done:
- Committed to git but not promoted in cairn-mcp: the ADR is invisible to agent search (stale index, still hidden). Agents miss it.
- Promoted in cairn-mcp but not committed to git: the ADR is searchable but not in the repo. Reversibility is compromised.

This lifecycle is elegant but requires tooling or habit to enforce the two-action approval step.

---

#### Option 5 — No ADRs in cairn-mcp at all

Remove `adr` from the type catalogue. All ADRs stay in git. Semantic search over ADRs is not
supported by cairn-mcp. Teams use git grep, GitHub search, or a separate tool.

| Criterion | Score | Notes |
|---|---|---|
| Consistency | ✅ High | No sync problem. |
| Auditability | ✅ High | |
| Discoverability | ❌ Low | No semantic search. An agent mid-session cannot ask "what did we decide about database choice?" and get a ranked answer. This is a significant capability loss — the tier 3 cross-team discovery scenario depends on ADRs being findable. |
| Simplicity | ✅ High | |
| Reversibility | ✅ High | |

**Verdict**: Eliminates the sync problem by eliminating the value. The original vision for
cairn-mcp (in the brainstorming-artifact-store.md, OQ5 and cross-team discovery) explicitly
calls out ADRs as the canonical tier 3 artifacts that flow across team boundaries. Dropping
them from the type catalogue abandons that use case.

---

### Comparative summary

| Option | Consistency | Auditability | Discoverability | Simplicity | Reversibility |
|---|---|---|---|---|---|
| 1 — Git canonical, cairn-mcp index | ⚠️ | ✅ | ✅ | ⚠️ | ✅ |
| 2 — cairn-mcp canonical, git mirror | ⚠️ | ❌ | ✅ | ❌ | ⚠️ |
| 3 — Dual write, git wins | ❌ | ✅ | ✅ | ❌ | ✅ |
| 4 — cairn-mcp drafts, git approved | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| 5 — No ADRs in cairn-mcp | ✅ | ✅ | ❌ | ✅ | ✅ |

---

### Recommended approach

**Option 1, with an explicit re-indexing obligation and the stale-read risk documented.**

Option 4 (draft → approved lifecycle) is architecturally cleaner, but it introduces a
two-action approval step that has no technical enforcement. For a V1 tool, adding a new
workflow obligation with no guard rails is more likely to produce subtle failures (hidden ADRs
that were never promoted) than the stale-index risk of Option 1.

Option 1 is consistent with what the migration skill already implies: migrate ADRs into
cairn-mcp for searchability, keep git as the authority. The skill already handles the initial
bulk indexing. The only missing piece is explicit guidance on what to do when an ADR changes.

**The key additions needed:**

1. The migration skill's cleanup guidance should state explicitly that cairn-mcp holds an
   *index copy* of ADRs, not the authoritative copy.

2. The AGENTS.md snippet must distinguish between reading ADRs (via cairn-mcp search, then
   read) and writing ADRs (to cairn-mcp for indexing, after the human has committed to git).
   The current snippet instructs agents to write `adr` to cairn-mcp without this nuance —
   it will be read as "cairn-mcp is the destination", which is incorrect.

3. When an agent writes an ADR to cairn-mcp, it should note to the operator that the git copy
   must be committed separately. This is a convention, not a technical enforcement.

4. The stale-index risk (ADR updated in git, not re-indexed in cairn-mcp) should be
   acknowledged as a known limitation. The `reconcile_index` tool mitigates it partially —
   but reconcile rebuilds the vector index from S3 (cairn-mcp's own store), not from git.
   If an ADR was updated only in git and never re-indexed to cairn-mcp, reconcile will not
   pick up the git change. This is a gap that should be documented.

---

### What this means for the migration skill

The current Step 7 cleanup table entry is correct in its conclusion ("No — keep ADRs in repo")
but incorrect in its framing (it does not explain *why* they stay, or what the agent's
relationship to the cairn-mcp copy should be going forward).

**Proposed revised entry:**

| Type | Safe to remove from repo | Notes |
|---|---|---|
| `adr` | **No — keep in git permanently** | cairn-mcp holds a *search index copy*, not the authoritative version. Git is the source of truth. When an ADR is updated in git, re-index it in cairn-mcp by calling `write_artifact` again with the new content. Agents use cairn-mcp to *find* ADRs; the git file is the definitive text. |

---

### What this means for the AGENTS.md snippet

The current snippet says:
> `adr` / `spec` / `decision_note` / `synthesis` → tier 3, visibility=shared

This is ambiguous — it implies agents are the *authors* of ADRs in cairn-mcp, with no
mention of the git copy.

**Proposed replacement:**

```markdown
**ADRs (`adr` type):** Git is the authoritative record. When a new ADR is committed to git,
index it in cairn-mcp by calling `write_artifact` (tier 3, visibility=shared). When an ADR
is updated in git, call `write_artifact` again with the new content. To find relevant ADRs
mid-session, use `search_artifacts` — but always treat the cairn-mcp copy as a search index:
if there is any doubt about currency, read the git file directly.
```

The AGENTS.md snippet should not say "write ADRs to cairn-mcp" without the accompanying
"after committing to git" qualification. Without that qualification, agents will treat cairn-mcp
as the destination and skip the git step.

---

### Edge cases and risks

**1. The unindexed new ADR**

An operator commits a new ADR to git but no agent session runs before the next search. The ADR
is not in cairn-mcp. An agent searching for related decisions won't find it. This is the core
stale-index risk of Option 1. Mitigation: the AGENTS.md snippet should instruct agents to
check for new ADR files in `docs/adr/` and index any that are absent from cairn-mcp
(`list_artifacts` + directory comparison).

**2. The superseded ADR**

An ADR is superseded by a later decision. The git file is updated to say "Status: Superseded
by ADR-012." If the cairn-mcp copy is not re-indexed, agents will find and read the superseded
ADR without knowing it has been replaced. The `status` metadata field in cairn-mcp should be
updated to `superseded` simultaneously. This requires the same two-step discipline as Option 4's
approval step — but only on the less frequent "superseded" event, not on every write.

**3. The deleted ADR**

If an ADR file is removed from git (rare but possible after a major architectural reversal),
the cairn-mcp artifact will remain unless explicitly deleted or archived. `archive_artifact`
or `delete_artifact` should be called when an ADR is removed from git. No tooling enforces this.

**4. Draft ADRs authored by agents**

The AGENTS.md snippet currently implies agents may write ADRs. In some workflows agents do
draft ADRs (e.g., "propose an ADR for using Redis as the session store"). If an agent drafts
an ADR in cairn-mcp (tier 3, hidden) for human review, the lifecycle is: hidden draft in
cairn-mcp → human reviews → human commits to git → agent updates cairn-mcp to shared.
This is Option 4's lifecycle for drafts only. It is a valid use case that Option 1 should
accommodate without contradiction. The guidance should say: "Draft ADRs may be written to
cairn-mcp as `visibility=hidden` for review. Once committed to git, update cairn-mcp to
`visibility=shared`."

**5. Cross-team ADR discovery**

The original vision for tier 3 cross-team sharing depends on ADRs in cairn-mcp being
findable across scope boundaries. Option 1 fully supports this — indexed ADRs are shared
across teams — but it depends on every team consistently re-indexing their ADRs after updates.
A platform team that updates an ADR in git but forgets to re-index leaves subscribing teams
with stale cross-team information. This is a governance risk, not a technical one.

---

## Session 2026-06-01 — Deeper Dive: Why Treat ADRs Differently?

### Framing the challenge

The previous session recommended "git canonical, cairn-mcp is a search index" for `adr`
specifically, on the basis that ADRs are "canonical decision records that belong in git
alongside the code they govern." The human challenge is sharp: `docs/planning-artifacts/prd.md`
and `docs/planning-artifacts/plan.md` are both committed to git in *this very project*, and
both are tier 3 artifact types (`spec` and `plan`). If the "belongs in git" argument applies
to ADRs, does it not apply equally to specs and plans? What actually makes ADRs special, if
anything?

This session works through that challenge systematically and surfaces the real driver of the
distinction — which turns out not to be document type at all.

---

### 1. What does git uniquely provide, and does it matter equally across tier 3 types?

The six properties git provides, scored for each tier 3 type:

| Git property | `adr` | `spec` | `plan` | `synthesis` |
|---|---|---|---|---|
| **Version history with diffs** | ✅ High — an ADR's evolution (proposed → superseded) is the record of a decision. Seeing that an ADR changed on the same day as a large PR is meaningful context. | ✅ Medium — spec evolution is useful but often the current version is what matters; historical drafts are noise. | ⚠️ Low-Medium — plans change frequently; full diff history becomes verbose quickly. The *current* plan is what agents need. | ❌ Low — syntheses are derived output; their history is less valuable than their sources' histories. |
| **Blame / authorship** | ✅ High — "who approved this decision" is governance-critical for ADRs. | ⚠️ Medium — authorship matters for human accountability, but agents writing specs have no identity in git. | ⚠️ Low — plan ownership is tracked by project tooling, not git blame. | ❌ Low — synthesis authorship is the model, not a person. |
| **PR-based review and approval workflow** | ✅ High — for many teams, merging the ADR PR *is* the approval act. The PR discussion is part of the decision record. | ✅ High — *if* specs require stakeholder sign-off, a PR is the natural approval gate. Not all specs need this. | ⚠️ Low — plan changes rarely go through PR review; they are updated continuously. | ❌ None — syntheses are never approved through PRs. |
| **Code proximity** | ✅ High — an ADR governing "we use PostgreSQL" lives in the same repo as the migrations that implement it. A code change and its ADR can appear in the same PR, creating an unambiguous causal link. | ⚠️ Medium — a spec describes what will be built, but it precedes the code. It cannot live in the same commit as its implementation without backdating. | ❌ Low — a plan governs work (tickets, priorities), not code. Its relationship to code is indirect. | ❌ None — syntheses summarise knowledge across sessions; they have no natural code neighbour. |
| **Discoverability without a running service** | ✅ High — an engineer debugging a mystery must be able to grep for relevant ADRs without needing AWS credentials or a running cairn-mcp instance. | ✅ Medium — the PRD and plan in `docs/` are easily browsed on GitHub. Useful but not critical; the spec is not usually opened mid-debug. | ⚠️ Low — plans are read in planning sessions, not mid-debug. | ❌ None — syntheses are AI-produced summaries; engineers do not browse them. |
| **Immutable audit trail** | ✅ High — ADRs are decisions; decisions need tamper-evident history. A superseded ADR whose tombstone was silently deleted would be a compliance problem in regulated contexts. | ⚠️ Medium — spec history is useful but not compliance-critical for most teams. | ❌ Low — plan history has no audit significance. | ❌ None — synthesis is ephemeral knowledge infrastructure. |

**Observation:** The git properties that score highest for `adr` are *code proximity*, *PR-based
approval*, and *immutable audit trail*. These three properties are substantially weaker for
`spec`, `plan`, and `synthesis`. The previous session's recommendation was not wrong to
differentiate ADRs — but the reason was understated. It is not that ADRs are "more important"
documents; it is that ADRs are uniquely coupled to *code governance*, *approval ceremony*, and
*tamper-evident history* in ways that specs, plans, and syntheses are not.

That said: the *human challenge stands* for specs. If a spec goes through PR review and sign-off
before implementation begins, it has the same approval-ceremony property as an ADR. The
document type is not the determining factor.

---

### 2. What does cairn-mcp uniquely provide, and does it matter equally across tier 3 types?

| cairn-mcp property | `adr` | `spec` | `plan` | `synthesis` |
|---|---|---|---|---|
| **Semantic search** | ✅ High — "what did we decide about caching?" is a natural agent mid-session query. git grep requires exact terms. | ✅ High — "find the spec for the payments feature" is exactly what agents need before implementing. | ✅ High — "what work is planned for Q3?" benefits from semantic search over free-text plan content. | ✅ High — the entire purpose of synthesis is to be searched and recalled. |
| **Cross-team / cross-project discovery** | ✅ High — a platform team's ADR about API versioning must surface for all consuming-team agents. This is the original F3.2 use case. | ⚠️ Medium — cross-team spec sharing is useful but less critical; specs are usually project-scoped. | ⚠️ Low — plans are almost always team-private. | ✅ High — syntheses are frequently shared across teams. |
| **Metadata filtering** | ✅ High — `type=adr AND feature_tags=$in[auth]` is a practical agent query. | ✅ High — same pattern for specs. | ⚠️ Medium — filtering plans by tag is useful but plans are fewer in number. | ✅ High — filtering syntheses by scope and source_artifacts is a core use case. |
| **Agent-native write path** | ⚠️ Conditional — agents may *draft* ADRs, but the approved ADR still requires human commit to git. The write path is useful for drafts; it is incomplete for approvals. | ✅ High — agents frequently draft and update specs during planning sessions. No git commit is needed for a working draft. | ✅ High — agents updating a plan mid-session should not require a git commit. | ✅ High — syntheses are exclusively agent-authored; the write path is mandatory. |
| **Staleness signalling** | ⚠️ Medium — `check_synthesis_freshness` applies to `synthesis` type only. ADR staleness must be detected by other means (git comparison). | ⚠️ Low — not currently implemented for specs. | ⚠️ Low — not currently implemented for plans. | ✅ High — staleness signalling is purpose-built for synthesis. |

**Observation:** cairn-mcp's value is roughly equal for all four types on semantic search and
metadata filtering. The critical *differentiator* is the **agent-native write path**: for
`synthesis` and working-draft `spec`/`plan` artifacts, the write path is the primary interface.
For *approved* `adr` artifacts, the write path is incomplete without a corresponding git commit.
This is the actual asymmetry — not document importance, but **whether the write path alone
constitutes a complete, authoritative action**.

---

### 3. Is the distinction really about document type or something else?

Exploring the five candidate drivers:

**Change frequency.** ADRs are written once and rarely updated (supersede events are infrequent).
Plans and specs change continuously. This does matter: high-frequency writes to cairn-mcp are
cheap and natural. High-frequency writes to git require commit discipline, PR overhead, and
reviewer fatigue. *Change frequency favours cairn-mcp as the write destination for plans and
specs, and is neutral for ADRs (infrequent writes are manageable in either system).*

**Code coupling.** ADRs govern specific technical decisions that are directly expressed in code.
A spec governs a feature (it precedes the code). A plan governs work (it is parallel to the code).
A synthesis summarises knowledge (it is derived from code discussions). *Code coupling is high only
for ADRs.* This supports git as the natural home for ADRs and cairn-mcp as the natural home for
the others.

**Audience.** ADRs are read by engineers reviewing code, debugging systems, and onboarding.
Their primary consumption context is "I am looking at this code and need to understand why it
was designed this way." Specs are read by agents planning implementation. Plans are read by
agents scheduling work. Syntheses are read by agents catching up between sessions.
*The primary ADR consumer is a human engineer at a terminal with git access, not an agent with
an MCP connection.* This is a meaningful difference in access pattern that favours ADRs being
in git.

**Decision finality.** An approved ADR is closed (its conclusion does not change; at most it is
superseded by a new ADR). A plan is always open (it is updated as work progresses). A spec can
go either way: a "frozen" spec that has been approved is closed; a working spec is open.
*Decision finality is the strongest signal for git*: closed decisions benefit from immutable
audit trail more than living documents do. This property is high for `adr`, variable for `spec`,
and low for `plan` and `synthesis`.

**Review ceremony.** Some teams require ADRs to pass through a PR review before they take
effect. The PR discussion is part of the decision record — a stakeholder can say "I disagree
with this for X reason" and that objection is preserved in the PR thread. cairn-mcp has no
review or approval primitive. *Any document type that uses PR review as its approval mechanism
belongs in git — because the PR IS the approval*, and that approval cannot be replicated
in cairn-mcp. This applies to `adr` by default. It applies to `spec` only if the team uses
PR-based spec approval. It does not apply to `plan` or `synthesis`.

**Synthesised finding on the real driver:**

The "stays in git" argument is not fundamentally about document type. It is about two properties
that may or may not apply to any given document:

1. **The PR is the approval gate.** If the document's approval is expressed by a PR merge, the
   document belongs in git — because removing it from git destroys the approval record.
2. **The document governs code directly and must be discoverable without a running service.**
   If an engineer debugging at 2am needs to find the reason a system behaves a certain way, that
   information must be in the repo, not behind an AWS dependency.

ADRs typically satisfy both conditions. Specs sometimes satisfy condition 1 (if they have formal
approval). Plans and syntheses satisfy neither.

*The distinction is not `adr` vs. everything else. It is "PR-approved and code-governing" vs.
"living, agent-authored, or planning-oriented."*

---

### 4. Four positions evaluated

#### Position A — All tier 3 docs belong in git; cairn-mcp just indexes copies

**Implication for specs and plans:** This project already commits `prd.md` and `plan.md` to
git. Position A says this is correct and all tier 3 documents should follow the same pattern.
The sync problem that applied to ADRs applies equally to every type: every `write_artifact`
call requires a corresponding git commit.

**Consistency check:** Is this position internally consistent? Yes — it is a coherent stance.
But it eliminates the agent-native write path as a first-class capability. Every agent action
that produces a tier 3 artifact becomes a draft that cannot be acted on until a human commits
it. This severely limits agent autonomy for planning and spec-drafting workflows.

**Additional friction:** `synthesis` artifacts are generated entirely by the agent from multiple
source artifacts. Requiring synthesis to be committed to git after every `synthesise_artifacts`
call is impractical — syntheses are ephemeral distillations, not decisions. Position A works
only if synthesis is carved out as an exception, which immediately breaks the "all tier 3 in
git" universality.

**Verdict on Position A:** Internally consistent only if `synthesis` is exempted. Even with
that exemption, it adds commit overhead to `spec` and `plan` workflows where the overhead
buys little (no audit requirement, no code proximity, no PR approval). Position A is most
defensible for organisations that already have git-backed planning workflows and want
consistency over flexibility.

---

#### Position B — No tier 3 doc must be in git; cairn-mcp is the canonical store

**What teams lose without git for specs and plans:** In this project specifically, `prd.md`
and `plan.md` are browsable on GitHub, linkable from issues and PRs, and accessible to any
collaborator without AWS credentials. Removing them from git makes them accessible only via
cairn-mcp, which requires: AWS credentials, a running service, and an MCP-capable client. Human
collaborators who are not using an AI agent (code reviewers, stakeholders, new hires) lose
direct access.

**What happens when cairn-mcp is decommissioned:** All tier 3 artifacts that were never
committed to git become inaccessible. `reconcile_index` can rebuild the vector index from
S3, but if the S3 bucket is also gone, all content is lost. A decommission scenario (account
closure, project abandonment, cost-cutting) is a complete knowledge loss event. For `spec`
and `plan`, this is unfortunate. For `adr`, this would be an audit failure in regulated
environments.

**Can an agent approve a spec via `write_artifact`?** Technically yes — the tool accepts any
content and makes it `visibility=shared`. But this means the "approval" is an agent write call
with no human in the loop and no PR discussion. For teams that require human sign-off on specs,
this is unacceptable. Position B implicitly assumes that agent-written artifacts are
authoritative, which is a significant governance assumption.

**Verdict on Position B:** Reasonable for `synthesis` and for agent-produced working drafts.
Fragile for `spec` and `plan` (human access and decommission risks). Inappropriate for `adr`
(audit trail and code-proximity requirements). Position B works only in fully AI-native workflows
where humans interact exclusively through AI agents — an assumption that does not hold for most
teams today.

---

#### Position C — The distinction is not document type but decision ceremony

This position says: documents that require PR-based human approval go through git *because
the PR is the approval mechanism*. Documents that are living, evolving, or agent-authored
without formal approval can live in cairn-mcp as canonical. Both types can be indexed in
cairn-mcp for search.

**What this implies concretely:**

- `adr` → PR-approved by convention in most teams → git is canonical, cairn-mcp is the index.
- `spec` (approved) → If the team uses PR review for spec approval → git is canonical, cairn-mcp is the index. Same treatment as ADRs.
- `spec` (working draft) → Agent-authored, no formal approval yet → cairn-mcp is canonical, may or may not be committed to git.
- `plan` → Continuously updated, rarely PR-reviewed → cairn-mcp is canonical.
- `synthesis` → Exclusively agent-authored, no approval → cairn-mcp is canonical.

**Tension with this project's current practice:** `prd.md` and `plan.md` are committed to git
in this project. Under Position C, this is fine — they were authored by humans and committed
manually. Position C does not prohibit committing to git; it says cairn-mcp does not *require*
a git commit for documents that lack a formal PR-approval ceremony. The two approaches are
compatible. Teams that want git copies of their plans commit them; teams that do not, don't.

**The grey zone:** A spec that starts as a working draft in cairn-mcp (`visibility=hidden`) and
then gets formally approved via PR — what happens? The PR-merged version in git diverges from
the cairn-mcp draft. Someone must reconcile. Position C does not specify the reconciliation
step, which is the same two-step problem from Option 4 in the previous session.

**Verdict on Position C:** The most semantically precise position. It identifies the real
differentiator (approval ceremony, not document type) and produces guidance that is consistent
with both `prd.md`-in-git (this project's practice) and `synthesis`-in-cairn-mcp-only (the
obvious case). It requires teams to declare upfront whether a document type uses PR-based
approval — which is a workflow decision, not a technical one.

---

#### Position D — cairn-mcp and git serve completely different purposes; the question of "canonical" is a false dichotomy

This position reframes the question: git is for **code governance** (source code, migration files,
infrastructure definitions, and the immediate artefacts of code decisions — ADRs, changelogs,
RFCs). cairn-mcp is for **agent knowledge** (what agents learned, reasoned about, produced, or
recalled across sessions). These overlap for ADRs, but the overlap does not mean one must defer
to the other.

**What this means in practice:**
- An ADR committed to git is the code-governance record. It is owned by the engineering team's
  code review process.
- The same ADR in cairn-mcp is the agent-knowledge record. It is owned by the agent runtime.
- Neither copy "wins." They serve different consumers (human engineers vs. AI agents) and
  different tooling (git/GitHub vs. MCP/cairn-mcp).

**Does this dissolve the sync problem?** Partially. If neither copy is "canonical," then
divergence between them is not a *correctness* problem — it is a *freshness* problem. A stale
cairn-mcp copy of an ADR is a problem only for agents that depend on it being current. A stale
git copy would be bizarre (git copies don't go stale; commits are append-only). The real risk
is a cairn-mcp copy that is never updated after the git ADR is superseded. But this is a
*documentation hygiene* problem, not an architectural one.

**Weakness:** Position D is intellectually satisfying but provides no actionable guidance for
operators setting up workflows. If neither copy is canonical, operators have no principle for
deciding what to do when the two copies diverge. "Both are right for their audience" is a
philosophically defensible answer that is practically useless when an agent surfaces a
superseded ADR as current.

**Verdict on Position D:** Useful as a *framing corrective* — it dissolves the false urgency
of "which is canonical." But it cannot stand alone as workflow guidance because it gives
operators no decision rule for the conflict case. It works best as a preamble to Position C:
"These systems serve different purposes *and* for documents that require human approval, the
git copy is the authority for that approval, while cairn-mcp is the authority for agent search."

---

### Synthesised view — which position best fits cairn-mcp's design intent?

**This is presented as an option for the human to accept, reject, or modify — not as a final
decision.**

Positions C and D are complementary. Position D dissolves the false dichotomy (neither system
must universally "win"). Position C provides the decision rule for the overlap zone (documents
that require human approval go through git because the PR is the approval mechanism; documents
that do not can be cairn-mcp-canonical).

Together they suggest the following framing:

> **The right question is not "which system is canonical for document type X" but "what is the
> approval and governance requirement for this specific document?" Documents with PR-based
> approval stay in git (because removing them would destroy the approval record). Documents
> without formal approval can live in cairn-mcp as the primary store, optionally mirrored to
> git for human browsability.**

Under this framing:
- `adr` earns its "git canonical" status not because it is an ADR but because most teams
  use PR review to approve ADRs.
- `spec` earns the same treatment **only if** the team uses PR review for spec approval — which
  this project does (`prd.md` went through human authoring and was committed, even if not via
  a formal PR). The PRD in `docs/planning-artifacts/` is therefore correctly in git under this
  framing.
- `plan` does not typically require formal approval, changes continuously, and serves primarily
  agent consumers → cairn-mcp is a defensible canonical store, with optional git commits for
  human browsability.
- `synthesis` is never PR-approved and serves exclusively agent consumers → cairn-mcp is the
  only appropriate store.

**The human challenge ("why treat ADRs differently from specs?") is well-founded.** The previous
session's guidance was imprecise. The correct answer is: *ADRs and formally-approved specs
should be treated the same way — both belong in git if their approval ceremony runs through
a PR, and both are indexed in cairn-mcp for search.* The ADR vs. spec distinction is a
default (ADRs are almost always PR-approved; specs are sometimes not), not an intrinsic
property of the type.

---

### 5. Draft guidance table for the migration skill — Post-migration cleanup section

| Type | Remove from git after migration? | Rationale |
|------|----------------------------------|-----------|
| `adr` | **No — keep in git permanently** | ADRs typically go through PR-based approval; the PR discussion *is* the approval record and cannot be replicated in cairn-mcp. ADRs also govern code decisions and must be discoverable without AWS credentials. cairn-mcp holds an *index copy* for agent search; the git file is the authority. When an ADR is updated or superseded in git, re-index it in cairn-mcp by calling `write_artifact` again. |
| `spec` | **Depends on team workflow.** If the spec was formally approved via PR (stakeholder sign-off, merge = approval), **keep in git permanently** — same reasoning as ADRs. If the spec is a working draft authored by an agent and has never been formally approved, **it is safe to leave in cairn-mcp as canonical**; commit to git if human browsability is desired. | The key question is whether the PR merge *was* the approval event. If yes, removing the git file destroys that approval record. If no, the git file is a convenience copy. In this project, `prd.md` was committed to git — it should stay there regardless of cairn-mcp status. |
| `plan` | **Optional.** Plans change continuously and are rarely PR-approved. cairn-mcp is a defensible canonical store. Keeping a git copy is useful for human browsability (GitHub renders markdown, links are shareable) but is not required for auditability. Teams that already commit plans to git may continue to do so; there is no reason to remove them. Teams that do not commit plans to git need not start. | cairn-mcp provides the search and recall value; git provides human browsability. Neither is the sole correct answer. |
| `synthesis` | **Yes — or never add to git in the first place.** Syntheses are AI-generated distillations, produced and updated by agent sessions, and have no natural place in a git repository. They are not decisions, not specs, and not plans. cairn-mcp is the only appropriate home. If any syntheses were manually committed to git during experimentation, they should be removed to avoid confusion. | Syntheses in git would mislead engineers into treating them as authoritative documents. They are knowledge infrastructure, not governance records. |

---

### Residual open questions

1. **Should the migration skill's guidance table be split into "PR-approved" and "not PR-approved"
   rows for `spec`, rather than a single blanket rule?** This would be more precise but adds
   complexity to the operator decision path.

2. **For this project specifically:** `docs/planning-artifacts/prd.md` and `plan.md` are already
   committed to git. Are they also in cairn-mcp? If not, should they be migrated in (so agents
   can search them semantically)? The migration skill would handle this, but the operator must
   decide whether to run it for their own project's planning artifacts.

3. **Does the `spec` type in cairn-mcp conflate two distinct sub-types** — "approved spec" (which
   should follow ADR treatment) and "working draft spec" (which should follow plan treatment)?
   Introducing a sub-type distinction or using `visibility` to proxy the approval state (hidden =
   draft, shared = approved) would give agents more accurate signals, at the cost of additional
   convention to document and enforce.

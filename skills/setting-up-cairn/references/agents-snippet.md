# cairn-mcp AGENTS.md Snippet

This file is loaded by the `setting-up-cairn` skill (Step 6) and appended to the project
`AGENTS.md`. Include **exactly one** of Variant A or Variant B (matching the ADR strategy
chosen in Step 6 Part A). Remove the other variant before writing.

---

````markdown
## cairn-mcp — Persistent Artifact Memory

cairn-mcp is connected to this project. Use it to persist knowledge across sessions.

> **Before writing any artifact:** read the raw text of `AGENTS.md` and find the
> `<!-- cairn-mcp:config ... -->` HTML comment block near the top of the cairn-mcp section.
> This block is an HTML comment — it is **invisible in rendered markdown** but is always
> present in the raw file after cairn-mcp is installed. It lists `local_only_types` and
> `local_only_paths` that must never be written to cairn-mcp.
> Never write an artifact whose `type` is listed in `local_only_types`.
> Never write an artifact whose source file is under a path listed in `local_only_paths`.

### When to write artifacts

- **Start of session** — search for prior context before doing any substantial work.
- **End of session** — write findings, decisions, and implementation notes before closing.
- **After a key decision** — write a `decision_note` or `adr` while the reasoning is fresh.
- **After a code review** — write a `code_review` artifact with findings and recommendations.

### Artifact type selection

| Type | When to use |
|------|-------------|
| `code_review` | After completing a code review — findings, issues, recommendations |
| `session_summary` | End of any productive session — what was decided, implemented, or discovered |
| `brainstorming` | Exploring options or ideating — directions considered, trade-offs weighed |
| `implementation_note` | Implementing a non-obvious solution — why this approach, constraints, edge cases |
| `spec` | Feature specifications and requirements — living documents updated as features evolve |
| `adr` | Architectural Decision Records — a decision that affects system design; tier 3, shared |
| `bug_report` | When a bug is diagnosed — root cause, affected behaviour, fix applied |
| `decision_note` | A lightweight decision with rationale — smaller than an ADR, larger than a comment |
| `synthesis` | Consolidating multiple prior artifacts into a summary; must include `source_artifacts` |
| `prd` | Product Requirements Documents — what to build, user needs, goals, non-goals; tier 3 |
| `plan` | Project or sprint plans — ordered task breakdown, milestones, dependencies; tier 3 |
| `runbook` | Operational runbooks — deployment, rollback, and incident response procedures; tier 3 |
| `changelog` | Changelog entries — features shipped, bugs fixed, breaking changes; tier 2 |
| `postmortem` | Post-incident analyses — timeline, root cause, impact, remediation; tier 2 |

<!-- ADR GUIDANCE — insert exactly one of Variant A or Variant B below -->

<!-- Variant A — git-only ADR strategy -->
**ADRs:** This project keeps ADRs in git. Do NOT write `type=adr` artifacts to
cairn-mcp. When you create or update an ADR, commit it to the project's ADR
directory in git. Git is the single source of truth for ADRs.
<!-- End Variant A -->

<!-- Variant B — cairn-mcp-only ADR strategy -->
**ADRs:** This project stores ADRs in cairn-mcp only. Write ADRs using
`write_artifact` (type=adr, tier=3, visibility=shared). Do NOT commit ADR files
to git — cairn-mcp is the single source of truth. Draft ADRs use `visibility=hidden`
until approved.
<!-- End Variant B -->

### Description quality

The `description` field is the primary search signal. Invest in it.

- Write it as a tweet: ≤ 280 characters, present tense, concrete.
- **Bad:** `"Notes from the session on 2024-11-15"`
- **Good:** `"Evaluates three auth strategies for the payments API; recommends JWT with
  rotating keys; identifies Redis session cache as a dependency"`
- Include the key outcome, technology involved, and any named constraints.

### Tier selection

- **Tier 2** — point-in-time records: `brainstorming`, `code_review`, `session_summary`,
  `implementation_note`, `bug_report`, `changelog`, `postmortem`. Immutable after write;
  keyed by type + date + title.
- **Tier 3** — living documents: `spec`, `adr`, `decision_note`, `synthesis`, `plan`,
  `prd`, `runbook`. Overwrite in place on re-write; keyed by type + title (no date).

### Query strategy — start narrow, broaden only if needed

```python
# Step 1 — Filter by type + feature tags (fastest, most precise)
search_artifacts(query="auth token refresh", type="implementation_note", feature_tags=["auth"])

# Step 2 — If step 1 returns too few results, drop the type filter
search_artifacts(query="auth token refresh", feature_tags=["auth"])

# Step 3 — If still insufficient, pure semantic search
search_artifacts(query="auth token refresh")

# For browsing without a query
list_artifacts(type="adr", project="payments-api")
```

### Synthesis workflow

Use `synthesise_artifacts` to compile multiple prior artifacts into a single reference
document (e.g. summarise an epic, compile related code-review findings).

```python
# 1. Prepare source material — returns full content for top-k matches
result = synthesise_artifacts(query="auth module code reviews", type="code_review", top_k=5)

# 2. Synthesise in-context using the returned content

# 3. Write result back as a tier 3 synthesis artifact
write_artifact(
    type="synthesis",
    tier=3,
    visibility="shared",
    title="Auth Module Code Review Synthesis — Q4 2024",
    description="Consolidated findings from 5 code reviews of the auth module; identifies 3 recurring issues and 2 best-practice patterns.",
    source_artifacts=[r["artifact_id"] for r in result["results"]],
    content="..."
)
```

### Runtime schema precision

For always-current field definitions, valid values, and query guidance, read the MCP
Resources the server exposes at runtime:

- `cairn://schema/artifact` — all fields, valid values, constraints
- `cairn://schema/types` — type catalogue with usage notes
- `cairn://schema/tiers` — tier 2 vs tier 3 semantics
- `cairn://schema/query-strategy` — query strategy guidance
- `cairn://schema/visibility` — cross-scope access rules
````

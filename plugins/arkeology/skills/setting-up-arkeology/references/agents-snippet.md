# Arkeology AGENTS.md Snippet

This file is loaded by the `setting-up-arkeology` skill (Step 6) and appended to the project
`AGENTS.md`. Include **exactly one** of Variant A or Variant B (matching the ADR strategy
chosen in Step 6 Part A). Remove the other variant before writing.

---

````markdown
## arkeology — Persistent Artifact Memory

arkeology is connected to this project. Use it to persist knowledge across sessions.

> **Before writing any artifact:** read the raw text of `AGENTS.md` and find the
> `<!-- arkeology:config ... -->` HTML comment block near the top of the arkeology section.
> This block is an HTML comment — it is **invisible in rendered markdown** but is always
> present in the raw file after arkeology is installed. It lists `local_only_types` and
> `local_only_paths` that must never be written to arkeology.
> Never write an artifact whose `type` is listed in `local_only_types`.
> Never write an artifact whose source file is under a path listed in `local_only_paths`.

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
| `learning` | Durable technical learnings — a living, continuously appended record of lessons, gotchas, corrected assumptions; tier 3 |

<!-- ADR GUIDANCE — insert exactly one of Variant A or Variant B below -->

<!-- Variant A — git-only ADR strategy -->
**ADRs:** This project keeps ADRs in git. Do NOT write `type=adr` artifacts to
arkeology. When you create or update an ADR, commit it to the project's ADR
directory in git. Git is the single source of truth for ADRs.
<!-- End Variant A -->

<!-- Variant B — arkeology-only ADR strategy -->
**ADRs:** This project stores ADRs in arkeology only. Write ADRs using
`write_artifact` (type=adr, tier=3, visibility=shared). Do NOT commit ADR files
to git — arkeology is the single source of truth. Draft ADRs use `visibility=hidden`
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
  `prd`, `runbook`, `learning`. Overwrite in place on re-write; keyed by type + title (no date).

### Query strategy — start narrow, broaden only if needed

```python
# Step 1 — Filter by type + feature tags (fastest, most precise)
search_artifacts(query="auth token refresh", type="implementation_note", tags=["auth"])

# Step 2 — If step 1 returns too few results, drop the type filter
search_artifacts(query="auth token refresh", tags=["auth"])

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

### Referencing other artifacts

- **Proactive `arkeology://` referencing** — when writing an artifact that references a
  target you already know is an arkeology artifact (e.g. an ADR it implements, a spec it
  fulfils, a prior session summary it follows up on), link to it with its
  `arkeology://artifact/{id}` URI rather than a raw file path. This keeps the reference
  resolvable and navigable from any MCP-aware host.
- **Reference healing** — if you encounter a broken or unresolved reference during
  normal work (a `arkeology://artifact/{id}` that no longer resolves, or a raw path that
  looks like it should be an arkeology artifact), search for the likely target with
  `search_artifacts` or `list_artifacts` and **propose the fix to the operator — never
  silently rewrite the reference yourself**.

### Runtime schema precision

For always-current field definitions, valid values, and query guidance, read the MCP
Resources the server exposes at runtime:

- `arkeology://schema/artifact` — all fields, valid values, constraints
- `arkeology://schema/types` — type catalogue with usage notes
- `arkeology://schema/tiers` — tier 2 vs tier 3 semantics
- `arkeology://schema/query-strategy` — query strategy guidance
- `arkeology://schema/visibility` — cross-scope access rules

## Post-Commit Protocol (arkeology)

**At session start:**
Capture the session ULID once and carry it in context for the entire session:
`python -c "from ulid import ULID; print(ULID())"`
Store this value as `since_ulid`.

**After every `git commit` during a session:**
1. Capture the commit SHA: `git rev-parse HEAD`
2. Call `propose_commit_links(commit_sha=<sha>, since_ulid=<since_ulid>)`
   — omit `since_ulid` if this is the very first commit of a brand-new project.
3. Present the proposed list to the operator. They may confirm, remove, or add artifact IDs.
4. If the operator confirms: call `link_metadata(artifact_ids=[...], commit_refs=[<sha>])`
5. Replace `since_ulid` with the `next_since_ulid` value returned by `link_metadata`.
6. Skip silently if `propose_commit_links` returns an empty `proposed` list.

`link_metadata` also backfills the `references` field (pass `references=[...]`) using the
same merge-and-deduplicate mechanism — use it any time a resolved reference needs to be
added to an artifact after it was originally written.

**On annotation-unavailable:** if `link_metadata` returns an `annotation_unavailable`
error, the durable link record could not be written (unsupported region/bucket type, or
missing IAM permission) — see the `setting-up-arkeology` skill's Check 8 for diagnosis. This
does not affect content, search, or embeddings; retry later once the operator has
resolved the underlying cause.
````

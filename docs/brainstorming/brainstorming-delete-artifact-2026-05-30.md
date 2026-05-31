# Delete Artifact Capability

## Description

The cairn-mcp PRD defines an archive mechanism (FR-05, FR-14) that marks an artifact inactive
and excludes it from search and listing. Archive does not remove content from storage. The
question explored here is whether a true deletion capability — permanently removing an artifact
from S3 and the vector index — is needed, and if so, what shape it should take.

Motivation: a 3-year-old bug report is probably irrelevant. Archiving hides it from search
results but the content persists in S3 and is still reachable via `read_artifact` by ID. Beyond
stale content, deletion addresses storage cost, compliance cleanup, and the risk that a confused
agent uses `read_artifact` directly on a known ID and acts on superseded information.

The PRD "Product Value Failure" section explicitly names "stale artifacts misleading agents" as
a key failure mode. Deletion is a stronger remedy than archive for that class of problem.

---

## Session 2026-05-30

### Ideas generated

**What gets deleted**
- Single artifact by `artifact_id`
- Bulk by metadata filter (type, team, project, date range)
- Purge-archived shortcut: hard-delete everything already marked inactive
- All artifacts for a project (decommission scenario)

**Who/what can delete**
- Any agent operating within own scope (mirrors archive gate)
- Human-only via separate CLI/admin mechanism
- `confirm=True` required parameter to prevent one-liner accidental deletion
- Role-restricted (only agent with `author_role=admin`)
- Dry-run first, then confirm call

**Scope**
- Own scope only — non-negotiable; mirrors archive
- Both tier 2 and tier 3 deletable
- Tier 2 deletion requires explicit opt-in flag (preserves immutability spirit)
- Tier 3 only (tier 2 protected as historical record)

**Operation semantics**
- Hard delete: remove S3 object + all section vectors permanently
- Soft delete with new `"deleted"` status (distinct from `"inactive"`)
- Glacier move: remove from vector index, move S3 to cold storage
- Export-then-delete: return full content in response, then delete

**Consistency — ordering problem**
- Delete vectors first, then S3 (safer: orphaned S3 object is reconcilable; artifact invisible from search while S3 cleanup completes)
- Delete S3 first, then vectors (riskier: orphaned vectors make artifact appear in search but `read_artifact` fails with not-found)
- Log partial failures to local tier 1 failure log (mirrors FR-16 write failure pattern)
- Rely on reconciliation (FR-17) to clean up any partial failure

**Reference integrity**
- Block delete if `artifact_id` appears in any active synthesis `source_artifacts` list
- Warn but proceed (return warning in response)
- Silently proceed; FR-20 freshness check surfaces orphaned synthesis references
- Cascade delete any synthesis solely referencing the deleted artifact

**Safety mechanisms**
- `confirm=True` required parameter
- Dry-run mode: return what would be deleted without deleting
- `max_items` ceiling for bulk operations
- No gate — skill discipline is the real protection

**Naming**
- `delete_artifact` (single, by ID)
- `delete_artifacts` (plural, bulk-capable)
- `purge_artifact` (implies permanence)

---

### Selected directions

**D1 — Single hard delete, own scope, both tiers, `confirm=True` required**
Simple, explicit, mirrors the archive pattern in scope gate. Hard delete (not soft) because
archive already covers "hide from results" — a third lifecycle state (`"deleted"`) adds
implementation complexity for no retrieval benefit. Both tiers deletable because the
stale-artifact problem applies to tier 2 most acutely (3-year-old bug reports are tier 2;
the immutability principle is about content editing, not lifecycle management).

Consistency ordering: delete vectors first, then S3. If vectors succeed and S3 fails, the
artifact is invisible from search and the S3 orphan is cleaned up by reconciliation (FR-17).
If vectors fail, S3 is untouched and the artifact is fully intact — cleaner failure mode.

**D2 — Bulk delete by metadata filter, dry-run supported**
Useful for cleanup scenarios: decommission a project, purge all bug_reports before a certain
date, remove all hidden artifacts before a team offboards. Dry-run (`dry_run=True`)
returns what would be deleted before committing. Requires a `max_items` ceiling (suggested:
100) to prevent runaway bulk operations. Bulk can be a separate tool or a parameter variant
of D1.

**D3 — Purge-archived shortcut**
`purge_archived()` hard-deletes everything already marked inactive within own scope. Agents
archive first (hides from search immediately), then purge at their discretion when storage
cleanup is desired. Clean two-step lifecycle: `active → archived → purged`. This is the
lowest-risk path for an agent: the archive gate is the safeguard; purge is just storage
reclamation.

---

### Open questions for the PM / architect

1. **Does "tier 2 immutability" cover existence or only content?**
   The PRD says "content is frozen as a permanent, point-in-time record" and "no content
   editing capability is provided." If immutability is scoped to *content*, deletion is
   compatible. If it covers *existence*, tier 2 artifacts cannot be deleted — only archived.
   This is the most consequential decision for the feature design.

2. **Single tool or two tools?**
   Option A: `delete_artifact(artifact_id, confirm=True)` — individual only; bulk is a
   future concern. Option B: `delete_artifact(artifact_id=..., filter=..., confirm=True)` —
   one tool, two modes. Option C: `delete_artifact` + `purge_archived` as separate tools.

3. **Reference integrity handling?**
   Block on active synthesis reference · warn-and-proceed · silent. Blocking is safest but
   requires a vector scan for each delete. Warn-and-proceed is pragmatic — agents can decide.
   Silent is consistent with how archive currently handles synthesis references (FR-20 is the
   explicit async check).

4. **What happens to the failure log on partial delete?**
   A partial delete (vectors removed, S3 delete failed) should be logged to the tier 1
   failure log with a new entry type (e.g. `partial_delete`). The reconciliation tool
   (FR-17) should be extended to handle these entries. This is consistent with the write
   failure pattern (FR-16) and avoids introducing a new recovery mechanism.

5. **Does this add a new acceptance criterion?**
   Yes — at minimum: "Deleting an artifact by ID removes it from S3 and the vector index;
   it is no longer retrievable by ID and no longer appears in search results."

---

### Decisions needed before spec

- Ruling on tier 2 deletability (Q1 above)
- Scope of initial implementation: D1 only, or D1+D3
- Reference integrity policy (Q3)
- Whether bulk delete is in scope for the initial feature or deferred to Phase 5+

---

## Session 2026-05-30 — Decision record

All open questions resolved. These decisions are frozen inputs for the PM and spec author.

### Q1 — Tier 2 immutability scope: content only ✅

"Immutable" applies to *content* — no content editing after initial write. It does not protect
an artifact from deletion. Tier 2 artifacts are therefore deletable. The PRD and any spec must
clarify this wherever "immutable" appears, e.g.: "Tier 2 project-local artifacts are immutable
(content cannot be edited after the initial write) but may be deleted or archived."

### Q2 — Tool shape: two separate tools ✅

`delete_artifact` — hard-deletes a single artifact by `artifact_id`.
`purge_archived` — hard-deletes all artifacts in own scope that are currently archived
(status=inactive). No filter arguments needed; scope gate enforces own-scope-only.

### Q3 — Synthesis reference integrity: warn-and-proceed, with cascade on full orphaning ✅

A synthesis is a summary. It retains value independent of its source artifacts. Deleting a
source artifact does not invalidate the synthesis — it is still readable and searchable.

Policy:
- `delete_artifact`: if the artifact being deleted is referenced as `source_artifact` in one
  or more active synthesis artifacts, return a warning in the response listing the affected
  synthesis `artifact_id`s. Deletion proceeds regardless.
- `purge_archived` (bulk): before executing, check whether any synthesis artifact has ALL of
  its `source_artifacts` in the to-be-purged set. If so, cascade-delete that synthesis too
  and include it in the response summary. A synthesis whose every source is gone has lost its
  audit trail and should not survive the purge.

### Q4 — Partial delete failure handling: extend reconciliation, no new log entry type ✅

The existing reconciliation tool (FR-17) already handles orphaned S3 objects (artifacts present
in S3 with no vector index entry). The same mechanism covers a partial delete where vectors
are removed but the S3 delete fails.

Ordering: delete vectors first, then S3. Failure modes:
- Vectors deleted, S3 delete fails → orphaned S3 object → reconciliation detects and
  re-indexes it (artifact is recoverable) or operator deletes manually.
- Vectors delete fails → S3 untouched → artifact fully intact, no state change. Return
  structured error. No new log entry needed.

No new partial-delete log entry type is introduced. Reconciliation (FR-17) is the recovery
path for the partial case.

### Q5 — Acceptance criterion ✅

"Deleting an artifact by ID removes it from S3 and the vector index; it is no longer
retrievable by ID and no longer appears in search results."

Additional criterion for `purge_archived`:
"Purging archived artifacts removes all inactive artifacts from S3 and the vector index
within own scope; they are no longer retrievable and no longer appear in any listing."

---

### Summary for PM

Two new tools to add to the plan and PRD:

| Tool | Phase suggestion | Priority |
|---|---|---|
| `delete_artifact(artifact_id, confirm=True)` | Phase 3 (alongside archive) | Should |
| `purge_archived(confirm=True)` | Phase 3 or Phase 5 | Could |

PRD changes needed:
- Add FR for `delete_artifact` (Should — mirrors archive in scope and priority)
- Add FR for `purge_archived` (Could — storage reclamation, lower urgency)
- Update FR-13 and FR-14 immutability language with parenthetical clarification
- Extend FR-17 (reconciliation) to cover partial-delete orphaned S3 objects explicitly
- Add two new acceptance criteria

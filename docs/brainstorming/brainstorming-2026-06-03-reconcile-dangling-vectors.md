---
status: complete
references: []
authored:
  by: "analyst"
  date: "2026-06-03"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
---

# Reconcile Index — Dangling Vector Pruning

## Description

`reconcile_index` handles index-S3 inconsistency in one direction only: artifacts present
in S3 with no vector index entry are re-indexed (Phase 2). The reverse case — vector
index entries whose backing S3 object no longer exists — is not handled. This brainstorming
session explores whether that is a gap, how it arises, and how to address it.

## Session 2026-06-03

### The gap

#### What the original spec covered

FR-17 (PRD) is explicit: *"scans the deployment's own S3 prefix against the vector index
and re-indexes any orphaned objects found — artifacts **present in S3 with no corresponding
vector index entry**."* S3→vectors direction only.

The original reconciliation spec (`p5-t21-reconciliation-tool.md`) framed the tool as *"a
safe, read-then-repair operation with no destructive effects"*, which was accurate for the
S3→vectors direction: re-indexing is an upsert and cannot make things worse. This framing
implicitly excluded any cleanup that removes data.

#### Why the reverse direction was not originally in scope

`brainstorming-delete-artifact-2026-05-30.md` explicitly identified orphaned vectors as a
risk (line 51: *"Delete S3 first, then vectors (riskier: orphaned vectors make artifact
appear in search but `read_artifact` fails with not-found)"*) and resolved it by choosing
**vectors-first deletion order**: the server always deletes vector entries before the S3
object. Under normal server operation, orphaned vectors cannot occur — if vector deletion
fails, the artifact is fully intact; if vector deletion succeeds and S3 delete fails, you
get an orphaned S3 object (handled by Phase 2), not orphaned vectors.

No document explicitly descoped the reverse direction. It was silently narrowed out
because vectors-first deletion prevented it in the server's own failure modes.

#### How orphaned vectors can still arise

The vectors-first ordering prevents orphaned vectors within the server's own operations.
However, they can still arise through external S3 changes:

- S3 object manually deleted outside cairn-mcp
- S3 lifecycle rule or TTL policy deletes the backing object
- S3 bucket migration (copy to new bucket, old objects removed)
- Any other operation that removes S3 objects without going through the MCP delete tool

#### Severity

Dangling vectors are not merely index pollution. The search path returns metadata from
vector entries directly (not fetched from S3 during search). A dangling vector **surfaces
in search and list results with valid-looking metadata**. An agent sees the artifact,
reads its description, decides it is relevant — then calls `read_artifact` and receives
a not-found error. This is the *"the system says it exists but can't deliver"* failure
mode from the PRD's Product Value Failure section.

---

### Design options considered

The key implementation observation: Phase 2 of the current reconcile already collects both
data sets needed for the reverse check — `own_keys` (all S3 objects in own prefix) and
`indexed_artifact_ids` (all unique artifact IDs present in the vector index for own scope).
The reverse detection is a free set difference computed from data already in memory:

```
dangling_artifact_ids = indexed_artifact_ids − set(own_keys)
```

The only new cost is the vector deletion.

| Option | Description | Decision |
|---|---|---|
| A — Auto in reconcile_index | Add Phase 3; always detect and delete dangling vectors automatically, no new params | ✅ **Selected** |
| B — Opt-in `prune_dangling=False` | Default unchanged; `prune_dangling=True` activates deletion; detection always reported | Rejected — see rationale |
| C — New dedicated `prune_vectors` tool | Separate tool with `confirm=True`; preserve reconcile as non-destructive | Rejected — overkill |

---

### Selected direction: Option A — automatic Phase 3 in reconcile_index

#### Rationale

Option B's main argument is behaviour preservation for existing callers and a small window
for an operator to notice an accidental external S3 deletion before the vectors are also
cleaned up. Both are weak in this context:

- The tool has no production callers today (pre-v1, Phase 9 work).
- The "accidental deletion recovery window" is not meaningful: vector metadata does not
  contain artifact content, so preserving dangling vectors does not enable content
  recovery. If an S3 object was deleted by mistake, the operator must restore it from S3
  versioning or re-write it — the vectors are irrelevant to that recovery path.

Option A is simpler and more symmetric: Phase 2 automatically makes the index consistent
with S3 by re-indexing missing entries; Phase 3 automatically makes it consistent in the
other direction by pruning entries with no backing object. The same level of automation,
the same no-confirmation philosophy.

On "destructive effects": deleting dangling vectors IS a destructive effect in the strict
sense — data is permanently removed. But the data being removed references nothing
(the backing S3 object is gone). Calling this "destructive" would equally disqualify
removing entries from the failure log (Phase 1 already does this). The framing from the
original spec was accurate for what reconcile did then; it does not need to be an
eternal constraint now that the scope is extended.

One genuine risk: a bug in the set-difference logic (computing `own_keys` or
`indexed_artifact_ids` incorrectly) could incorrectly identify non-dangling vectors as
dangling and delete them. This is mitigated by unit tests covering the detection logic and
by the fact that `list_objects` and `list_vectors_by_metadata` are both all-or-nothing
calls — if either fails, reconcile returns an error before reaching Phase 3.

#### Implementation sketch

Phase 3 reuses data collected in Phase 2 at zero additional API cost:

```
# Already computed in Phase 2:
#   own_keys: list[str]           — all S3 object keys in own prefix
#   indexed_keys_raw: list[str]   — all vector keys (e.g. "art/id#section-slug")
#   indexed_artifact_ids: set[str] — unique artifact_ids from indexed_keys_raw

# Group vector keys by artifact_id (needed for deletion)
vectors_by_artifact: dict[str, list[str]] = {}
for vk in indexed_keys_raw:
    aid = vk.split("#")[0]
    vectors_by_artifact.setdefault(aid, []).append(vk)

# Reverse orphans: artifact_ids with vectors but no S3 object
dangling_artifact_ids = set(vectors_by_artifact.keys()) - set(own_keys)

# Delete vector entries for each dangling artifact_id
for aid in dangling_artifact_ids:
    vectors.delete_vectors(vectors_by_artifact[aid])
```

#### Response schema additions (additive)

New fields added to the existing response dict — existing fields unchanged:

| New field | Type | Meaning |
|---|---|---|
| `dangling_artifacts_found` | int | Count of artifact IDs with vector entries but no S3 object |
| `dangling_vectors_pruned` | int | Total vector entries deleted across all dangling artifacts |
| `dangling_artifacts` | list[str] | Artifact IDs whose vector entries were deleted |

Existing callers that ignore unknown keys are unaffected.

---

### Open questions

None — decision is made. Design details (error handling, scope gate, response schema) to
be finalised in the implementation spec.

---
type: feature-spec
feature: review-fix-04-readme-critical-documentation-fixes
created: 2026-05-31
status: ready
---

# Review Fix 04 — README Critical Documentation Fixes

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Four errors in `README.md` affect users provisioning and operating the server:

1. **C9** — `s3:ListObjectsV2` is not a valid IAM action. The correct action is
   `s3:ListBucket`. Users following the policy receive Access Denied on `reconcile_index`
   and `purge_archived`.
2. **C10** — `s3vectors:CreateIndex` and `s3vectors:DeleteIndex` appear in the "Minimum
   IAM policy" but are infrastructure provisioning actions, not runtime actions. Including
   `DeleteIndex` in a runtime policy is a destructive misconfiguration risk.
3. **C11** — The status paragraph states "Phase 3 complete" and lists 9 tools. Phase 5 is
   complete and 11 tools are registered in `server.py`.
4. **C12** — The `list_artifacts` row in the tools table documents a `limit` parameter
   that does not exist. Callers passing `limit` receive no useful result or an error.

## User Stories

### Story 1 — IAM policy produces no Access Denied at runtime (P0)

A new user copies the Minimum IAM policy from the README and attaches it to their
runtime role. All 11 tool operations complete without Access Denied errors.

**Acceptance criteria:**
- Given a user copies the Minimum IAM policy block, when they use it as their runtime
  role policy, then no tool raises Access Denied due to a missing or incorrect action.

### Story 2 — Provisioning vs runtime IAM actions are separated (P1)

**Acceptance criteria:**
- Given a user reads the IAM section, when they look for runtime permissions, then
  `s3vectors:CreateIndex` and `s3vectors:DeleteIndex` do not appear in the runtime policy.
- Given a user needs to provision the vector index, when they read the IAM section, then
  the provisioning actions appear in a clearly labelled separate section.

### Story 3 — Status and tool count are accurate (P1)

**Acceptance criteria:**
- Given a user reads the status paragraph, when they check it against `server.py`, then
  the phase and tool count match.

### Story 4 — list_artifacts inputs are accurate (P1)

**Acceptance criteria:**
- Given a user reads the `list_artifacts` row in the tools table, when they call the tool
  with the documented parameters, then the call succeeds with no unexpected errors.
- `limit` does not appear in the `list_artifacts` inputs column.

## Requirements

- WHEN a user copies the Minimum IAM policy THE SYSTEM SHALL provide a policy that allows
  all 11 tool operations without Access Denied at runtime.
- WHEN the IAM section lists runtime actions THE SYSTEM SHALL NOT include
  `s3vectors:CreateIndex` or `s3vectors:DeleteIndex`.
- WHEN the status section describes the project phase THE SYSTEM SHALL state "Phase 5
  complete" and list all 11 tools.
- WHEN the tools table documents `list_artifacts` THE SYSTEM SHALL NOT include `limit` in
  the inputs column.

## Boundaries

**Always:**
- Replace `s3:ListObjectsV2` with `s3:ListBucket` in the IAM policy block.
- Move `s3vectors:CreateIndex` and `s3vectors:DeleteIndex` into a separate clearly
  labelled "Provisioning IAM policy" subsection.
- Update the status paragraph to reflect Phase 5 and 11 tools.
- Remove `limit` from the `list_artifacts` inputs column.

**Ask First:**
- Nothing — all required changes are defined.

**Never:**
- Add new features to `list_artifacts` in this spec — the only change is removing the
  phantom `limit` from documentation.
- Change any source code — this spec is documentation-only.
- Alter the structure of the tools table beyond removing the `limit` cell content.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `README.md` | Modify | Four targeted text changes — no source code changes |

## Testing Approach

No automated tests — this spec covers documentation only. Verification is manual:

1. Confirm `s3:ListBucket` appears in the runtime IAM policy block and `s3:ListObjectsV2`
   does not.
2. Confirm `s3vectors:CreateIndex` and `s3vectors:DeleteIndex` do not appear in the
   runtime policy block and appear only in a provisioning-labelled section.
3. Confirm the status paragraph contains "Phase 5" and lists exactly 11 tools; cross-check
   against `src/cairn_mcp/server.py` `register_tools()`.
4. Confirm `limit` does not appear in the `list_artifacts` row of the tools table.

## Open Questions

- **Provisioning section placement:** confirm with the PM whether the provisioning IAM
  policy should appear as a subsection of the existing IAM section or in a separate
  "Deployment" section. Either is acceptable — default to a subsection unless directed
  otherwise.

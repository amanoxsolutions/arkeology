---
type: code_review
title: Review Fix 04 — README Critical Documentation Fixes
description: Corrects four errors in README.md — wrong IAM action name, runtime policy containing destructive provisioning actions, stale phase and tool count, and a non-existent list_artifacts parameter.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 04 — README Critical Documentation Fixes

<!-- SCOPE BLOCK — frozen after approval -->

## Verification — 2026-08-12

Re-verified against current `main`. This spec was fixed the same day it was authored —
commit `f642725` ("production hardening — 20 review-fix specs", 2026-05-31) applied all
four text corrections to `README.md` — but this document was never annotated to reflect
that. Since then, the IAM policy and the tools table this spec edited were both moved
out of `README.md` into a dedicated `SERVER-REFERENCE.md` (the `installing-cairn` →
`setting-up-cairn` skill rename commit, and later doc-restructuring commits), so the
fixes now live in a different file than the one this spec names throughout.

- **C9 (`s3:ListObjectsV2` → `s3:ListBucket`) — RESOLVED.** The "Minimum IAM Policy" in
  `SERVER-REFERENCE.md` uses `s3:ListBucket`; `s3:ListObjectsV2` does not appear anywhere
  in the repository's documentation.
- **C10 (`CreateIndex`/`DeleteIndex` removed from the runtime policy) — RESOLVED,
  differently from the recommended remediation.** Neither `s3vectors:CreateIndex` nor
  `s3vectors:DeleteIndex` appears in the runtime "Minimum IAM Policy" in
  `SERVER-REFERENCE.md` — but this spec's own repo-wide grep confirms they don't appear
  in a labelled "Provisioning IAM policy" subsection either, because no such section was
  written; the provisioning actions were dropped from the documented policy entirely
  rather than relocated. The acceptance criterion ("do not appear in the runtime policy")
  is satisfied; Story 2's second criterion ("provisioning actions appear in a clearly
  labelled separate section") is not met as literally specified, though index
  provisioning is a one-time step the project now expects to happen outside a
  copy-pasted IAM block (via the `setting-up-arkeology` skill / infra tooling), so the
  gap is not a live documentation defect.
- **C11 (stale phase/tool count) — RESOLVED, restructured rather than restated.** The
  spec asked for "Phase 5 complete" and a count of 11 tools. `README.md`'s Status section
  no longer uses phase numbers or a bare tool count at all — the project switched to
  semver (`> **v0.5.0**`) and now lists all 16 tool names explicitly (matching
  `server.py::register_tools()` at time of writing). The underlying accuracy concern this
  finding raised is resolved; the specific phrasing recommended is no longer applicable
  because the versioning convention changed.
- **C12 (`list_artifacts` `limit` parameter) — RESOLVED.** The tools table (now in
  `SERVER-REFERENCE.md`) documents `list_artifacts`' actual optional parameters (`type`,
  `team`, `project`, `tier`, `status`, `tags`, `commit_refs`, `references`); `limit` does
  not appear.

**Aggregate:** 4 findings, all resolved for their underlying user-facing concern; C10 and
C11 diverge from the letter of the recommended remediation (provisioning actions dropped
rather than relocated to a labelled section; status rewritten around semver rather than
phase count) without leaving a live defect. Nothing here requires further documentation
work.

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
   against `src/arkeology/server.py` `register_tools()`.
4. Confirm `limit` does not appear in the `list_artifacts` row of the tools table.

## Open Questions

- **Provisioning section placement:** confirm with the PM whether the provisioning IAM
  policy should appear as a subsection of the existing IAM section or in a separate
  "Deployment" section. Either is acceptable — default to a subsection unless directed
  otherwise.

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): all 4 findings confirmed resolved for
  their underlying concern.** Fixed same-day by `f642725` (2026-05-31); the IAM policy
  and tools table have since moved from `README.md` to `SERVER-REFERENCE.md`. **C9**
  `s3:ListBucket` in place of `s3:ListObjectsV2`. **C10** `CreateIndex`/`DeleteIndex`
  absent from the runtime policy, though dropped rather than relocated to a labelled
  provisioning subsection as literally recommended. **C11** the phase/tool-count status
  line was replaced by a semver tag (`v0.5.0`) plus an explicit tool-name list, not
  restated as "Phase 5, 11 tools" — the accuracy concern is moot under the new
  convention. **C12** `list_artifacts`' documented parameters no longer include `limit`.
  See inline `## Verification — 2026-08-12` note above.

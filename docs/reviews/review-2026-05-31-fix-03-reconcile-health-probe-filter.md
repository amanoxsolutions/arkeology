---
type: code_review
title: Review Fix 03 — Reconcile Health Probe Filter
description: Prevents reconcile_index from treating a persisted health probe sentinel object as an orphan artifact, avoiding spurious Bedrock embedding calls and junk vector entries.
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
# Review Fix 03 — Reconcile Health Probe Filter

<!-- SCOPE BLOCK — frozen after approval -->

## Verification — 2026-08-12

Re-verified against current `main`. This spec was fixed the same day it was authored —
commit `f642725` ("production hardening — 20 review-fix specs", 2026-05-31) — but this
document was never annotated to reflect that.

- **Story 1 (health probe sentinel ignored by reconcile) — RESOLVED, implementation
  generalised beyond the spec.** `reconcile.py` defines `_PROBE_KEY_MARKER = "_arkeology_"`
  and filters any key whose *final path segment* starts with that marker
  (`k.rsplit("/", 1)[-1].startswith(_PROBE_KEY_MARKER)`) out of the orphan candidate set
  before the vector-index comparison — not the exact `key.endswith("/_arkeology_health_probe")`
  suffix match this spec's Boundaries section specifies. The broader marker now also
  excludes the `startup.py` connectivity probe and the setting-up-arkeology skill's
  annotation probe (added in later phases), all documented in a shared comment above the
  constant. The acceptance criteria (probe key excluded, `orphans_found` unaffected, a
  real orphan alongside the probe still gets reconciled, nested-path probes excluded) all
  hold under the broader filter — it is a superset of what was asked for, not a
  divergence in behaviour for this spec's own scenarios.
- **`health.py` sentinel-naming comment — RESOLVED, comment lives in `reconcile.py`
  instead.** The Files-to-Touch table asked for a comment in `health.py` documenting the
  naming convention. `health.py` itself has no such comment at its
  `probe_key = f"{settings.write_prefix}/_arkeology_health_probe"` line, but
  `reconcile.py`'s `_PROBE_KEY_MARKER` docstring-comment explicitly cross-references
  `tools/health.py`, `startup.py`, and the setting-up-arkeology skill by name — the
  documentation the spec wanted exists, just at the consuming site rather than the
  producing one.

Test coverage exceeds the spec: `tests/unit/test_tools_reconcile.py` has probe-exclusion
tests for the health probe (bare and nested-path), the startup probe, the annotation
probe, and a forward-compatibility test (`test_future_probe_key_excluded_without_code_change`)
proving the marker-based filter needs no code change for new probe types.

**Aggregate:** 1 story, resolved (marker-based filter is a superset of the specified
suffix-match filter; the sentinel-naming documentation exists at a different file than
requested). No open work.

## Problem Statement

`health.py` writes a sentinel object `{write_prefix}/_arkeology_health_probe` to S3 during
the write-prefix probe and deletes it immediately after. If the health check is interrupted
between the write and the delete, the sentinel persists. The `reconcile_index` orphan scan
lists all S3 objects under `write_prefix/`, finds the probe key absent from the vector
index, classifies it as an orphan, and attempts to re-index it — wasting a Bedrock
embedding call and writing a junk vector entry. There is currently no filtering of
`_arkeology_health_probe` keys in the orphan scan.

## User Stories

### Story 1 — Health probe sentinel is ignored by reconcile (P1)

A health check was interrupted and `{write_prefix}/_arkeology_health_probe` persists in S3.
An operator runs `reconcile_index`. The probe key is not treated as an orphan and no
embedding is attempted.

**Acceptance criteria:**
- Given `_arkeology_health_probe` exists in S3 under `write_prefix` but has no vector index
  entries, when `reconcile_index` is called, then `orphans_found` is 0 and the probe key
  does not appear in `reconciled`.
- Given `_arkeology_health_probe` exists alongside a real orphaned artifact, when
  `reconcile_index` is called, then only the real artifact is re-indexed (`orphans_found`
  is 1) and the probe key is ignored.

## Requirements

- WHEN `reconcile_index` lists S3 objects THE SYSTEM SHALL exclude any key whose suffix
  matches `/_arkeology_health_probe` from the orphan candidate list.
- WHEN a health probe sentinel object persists in S3 after an interrupted health check
  THE SYSTEM SHALL NOT attempt to re-index it or include it in `orphans_found`.

## Boundaries

**Always:**
- The sentinel key must be filtered by suffix match (`key.endswith("/_arkeology_health_probe")`),
  not by equality, to handle any write_prefix depth.
- The filter must be applied before the comparison against indexed artifact IDs, not after.

**Ask First:**
- Nothing — behaviour is fully defined.

**Never:**
- Modify the health probe write/delete logic in `health.py`.
- Introduce a shared constant for `_arkeology_health_probe` between `health.py` and
  `reconcile.py` unless both files already import from a shared module — a local string
  literal in the filter is acceptable.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add test: probe key in S3, absent from vectors → `orphans_found == 0`, key not in `reconciled` |
| `src/arkeology/tools/reconcile.py` | Modify | Filter keys ending with `/_arkeology_health_probe` before orphan comparison (around line 287) |
| `src/arkeology/tools/health.py` | Modify | Add comment documenting the sentinel key naming convention (no logic change) |

## Testing Approach

**TDD cycle:** add failing test first (Red) → add filter in `reconcile.py` (Green).

**`tests/unit/test_tools_reconcile.py` — new cases:**
- S3 fake contains only `{write_prefix}/_arkeology_health_probe`, no vector entries →
  `orphans_found == 0`, `reconciled` is empty.
- S3 fake contains `{write_prefix}/_arkeology_health_probe` and one real orphaned artifact,
  no vector entries → `orphans_found == 1`, `reconciled` contains only the real artifact,
  probe key absent from `reconciled`.
- S3 fake contains probe key at a nested path (`{write_prefix}/subdir/_arkeology_health_probe`)
  → still excluded (`endswith` match).

## Open Questions

*(none — all behaviour is defined)*

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): confirmed resolved, filter later
  generalised.** Fixed same-day by `f642725` (2026-05-31). `reconcile.py` now excludes
  any key whose last path segment starts with `_arkeology_` (`_PROBE_KEY_MARKER`) rather
  than the exact `/_arkeology_health_probe` suffix this spec specifies — a superset that
  also covers the startup and annotation probes added in later phases. The
  `health.py`-side documentation comment this spec asked for lives on the `reconcile.py`
  constant instead, cross-referencing `health.py` by name. See inline
  `## Verification — 2026-08-12` note above.

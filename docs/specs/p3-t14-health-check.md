---
type: feature-spec
feature: p3-t14-health-check
created: 2026-05-30
status: ready
phase: 3
task: 14
---

# T14 — Health Check Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

When cairn-mcp misbehaves mid-session — an artifact write fails, search returns nothing,
the server seems unresponsive — an admin needs to diagnose which component is at fault
without reading raw server logs. The health check tool performs an independent connectivity
and accessibility probe for each configured component (S3, S3 Vectors, Bedrock, write
prefix, each read prefix) and returns a structured per-component status report. Unlike the
startup validation sequence which is a hard stop, the health check never throws — it catches
all errors and reports them as component-level failures, letting the admin see at a glance
which component is healthy and which is not.

## User Stories

### Story 1 — Admin diagnoses a misconfigured component without log access (P1)

After a credential rotation, S3 Vectors calls start failing but S3 and Bedrock are still
healthy. The admin calls `health_check` and sees exactly which component reports an error.

**Acceptance criteria:**
- Given all configured components are reachable, when `health_check` is called, then every
  component reports `"ok"` in the response.
- Given one component is misconfigured (e.g. wrong vector index name), when `health_check`
  is called, then that component's entry has a `"status": "error"` with a human-readable
  message, while all other components report `"ok"`.
- Given a credential failure for one component, when `health_check` is called, then that
  component's status is `"error"` with a message indicating a credential problem.

### Story 2 — Each component is reported independently (P1)

A single failing component must not suppress the results of other checks.

**Acceptance criteria:**
- Given S3 Vectors is unreachable but S3 is healthy, when `health_check` is called, then
  the S3 entry is `"ok"` and the vectors entry is `"error"` — both are present in the
  response.
- Given every component fails, when `health_check` is called, then all entries are present
  with `"error"` status — the tool never raises an unhandled exception.

### Story 3 — Health check never raises (P1)

**Acceptance criteria:**
- Given any combination of component failures, when `health_check` returns, then the
  response is always a structured dict — never a raw exception.

## Requirements

- WHEN `health_check` is called THE SYSTEM SHALL perform an independent probe for each of
  the following components: S3 bucket access, S3 Vectors index, Bedrock embedding model,
  WRITE_PREFIX read/write, and each READ_PREFIX in `settings.read_prefixes_list`.
- WHEN a component probe succeeds THE SYSTEM SHALL report `{"status": "ok"}` for that
  component.
- WHEN a component probe fails (any exception, including CredentialError) THE SYSTEM SHALL
  catch the exception and report `{"status": "error", "message": str}` for that component.
- THE SYSTEM SHALL always proceed to all remaining probes regardless of any individual
  failure — errors in one component never skip other components.
- WHEN `health_check` returns THE SYSTEM SHALL return a dict with keys: `"s3"`, `"vectors"`,
  `"bedrock"`, `"write_prefix"`, and one key per read prefix entry (e.g. `"read_prefix:team/artifacts"`).
- THE SYSTEM SHALL use the same probe operations as the startup validation sequence:
  S3 → `head_bucket`; vectors → `describe_index`; bedrock → `embed` with short probe text;
  write prefix → put+get+delete probe object under `settings.write_prefix`; each read
  prefix → `list_objects`.
- THE SYSTEM SHALL never raise — the top-level function must catch any unhandled exception
  and include it in the structured response.

## Boundaries

**Always:**
- All component failures are caught and reported in-band — the tool never propagates
  exceptions to the caller.
- Each component probe is independent of the others.
- The tool reuses the same probe operations defined in `startup.py` (not the startup
  validation functions themselves — those raise; health check catches and returns status).
- The bedrock probe uses a short fixed text (e.g. `"health"`) with the configured model and
  dimensions; the resulting embedding vector is discarded.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not reuse `validate_startup()` directly — it raises on failure; health check must
  catch and convert to status entries.
- Do not skip any configured component even if a prior component failed.
- Do not raise an unhandled exception from the tool function.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_health.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/health.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_health.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `health_check` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_health.py` first → fail → implement
`tools/health.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_health.py` — unit tests (all three fakes: FakeS3, FakeVectors, FakeBedrock):**

Configure the fakes to simulate various combinations of healthy and failing states.

All healthy:
- All components healthy → all entries have `"status": "ok"`.
- Response keys: `"s3"`, `"vectors"`, `"bedrock"`, `"write_prefix"`, plus one per read prefix.
- With no read prefixes configured → no `"read_prefix:..."` keys in response.
- With two read prefixes → two `"read_prefix:..."` keys.

Individual failures:
- `head_bucket` raises `CredentialError` → `"s3"` entry `"error"`; all others `"ok"`.
- `describe_index` raises `VectorIndexNotFoundError` → `"vectors"` entry `"error"`; others
  `"ok"`.
- `embed` raises `CredentialError` → `"bedrock"` entry `"error"`; others `"ok"`.
- `put_object` raises on write-prefix probe → `"write_prefix"` entry `"error"`; others `"ok"`.
- `list_objects` raises on first read prefix → that read prefix `"error"`; other prefixes
  and components `"ok"`.

All failures:
- All fakes raise → all entries `"error"`; no unhandled exception propagates.

Response shape:
- `"status"` field is always `"ok"` or `"error"` — no other values.
- `"error"` entries always include a non-empty `"message"` string.
- `"ok"` entries have no `"message"` field (or it is absent/null).

**`tests/integration/test_tools_health.py` — integration tests (`@pytest.mark.integration`):**

- Call `health_check` with a correctly configured environment → all components `"ok"`.
- Verify each expected key is present in the response.
- No teardown needed — health check is read-only (the write-prefix probe cleans up its own
  probe object).

## Open Questions

*(none — all constraints are defined)*

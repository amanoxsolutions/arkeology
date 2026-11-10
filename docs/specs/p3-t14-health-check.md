---
type: Spec
id: p3-t14-health-check
title: T14 — Health Check Tool
description: Feature spec for the health_check MCP tool that independently probes each configured component (S3, S3 Vectors, Bedrock, prefixes) and returns a structured per-component status report without ever raising.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:01:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T14 — Health Check Tool

## TL;DR

`health_check` lets an admin diagnose which Arkeology component is at fault mid-session without
reading raw server logs. It probes each configured component (S3, S3 Vectors, Bedrock, write prefix,
each read prefix, and the optional Bedrock text model) independently and returns a structured
per-component status report — and, unlike startup validation, it never throws.

## 1. Problem Statement

When Arkeology misbehaves mid-session — an artifact write fails, search returns nothing, the server
seems unresponsive — an admin needs to diagnose which component is at fault without reading raw server
logs; for example, after a credential rotation, S3 Vectors calls start failing but S3 and Bedrock are
still healthy, and the admin calls `health_check` and sees exactly which component reports an error.
The health check tool performs an independent connectivity and accessibility probe for each configured
component (S3, S3 Vectors, Bedrock, write prefix, each read prefix) and returns a structured
per-component status report. Unlike the startup validation sequence which is a hard stop, the health
check never throws — it catches all errors and reports them as component-level failures, letting the
admin see at a glance which component is healthy and which is not.

All three stories this spec covers are priority P1.

## 2. Rules — Probes

### R1 — Every configured component is probed independently

When `health_check` is called, the system performs an independent probe for each of the following
components: S3 bucket access, S3 Vectors index, Bedrock embedding model, WRITE_PREFIX read/write, each
READ_PREFIX in `settings.read_prefixes_list`, and — when `settings.bedrock_text_model` is not `None` —
the Bedrock text generation model. Each component probe is independent of the others: the system always
proceeds to all remaining probes regardless of any individual failure — errors in one component never
skip other components, and a single failing component must not suppress the results of other checks.

**Example**

- Given S3 Vectors is unreachable but S3 is healthy, when `health_check` is called, then the S3 entry
  is `"ok"` and the vectors entry is `"error"` — both are present in the response.
- Given every component fails, when `health_check` is called, then all entries are present with
  `"error"` status — the tool never raises an unhandled exception.

Source: none

### R2 — Probes use the startup validation sequence's probe operations

The system uses the same probe operations as the startup validation sequence:

| Component | Probe operation |
|-----------|-----------------|
| S3 | `head_bucket` |
| vectors | `describe_index` |
| bedrock embedding | `embed` with short probe text |
| bedrock text model | `invoke_text_model` with `"ping"` |
| write prefix | put+get+delete probe object under `settings.write_prefix` |
| each read prefix | `list_objects` |

The tool reuses the same probe operations defined in `startup.py` — not the startup validation
functions themselves, which raise; health check catches and returns status. The Bedrock embedding probe
uses a short fixed text (e.g. `"health"`) with the configured model and dimensions; the resulting vector
is discarded. The Bedrock text model probe calls `invoke_text_model` with `"ping"`; the response text is
discarded.

Source: none

### R3 — The Bedrock text model probe runs only when a text model is configured

When `settings.bedrock_text_model is None`, the Bedrock text model probe is skipped entirely and its
key is absent from the response.

Source: none

## 3. Rules — Response

### R4 — Each component reports `ok` or `error`, with a credential cause where it applies

| Probe outcome | Component entry |
|---------------|-----------------|
| Succeeds | `{"status": "ok"}` |
| Fails with a generic exception (caught) | `{"status": "error", "message": str}` |
| Fails with a `CredentialError` | `{"status": "error", "message": str, "cause": "credential_error"}` |

**Example**

- Given all configured components are reachable, when `health_check` is called, then every component
  reports `"ok"` in the response.
- Given one component is misconfigured (e.g. wrong vector index name), when `health_check` is called,
  then that component's entry has a `"status": "error"` with a human-readable message, while all other
  components report `"ok"`.
- Given a credential failure for one component, when `health_check` is called, then that component's
  status is `"error"` with a message indicating a credential problem.

Source: none

### R5 — The response has one key per configured component

When `health_check` returns, the system returns a dict with keys: `"s3"`, `"vectors"`, `"bedrock"`,
`"write_prefix"`, and one key per read prefix entry (e.g. `"read_prefix:team/artifacts"`). When
`BEDROCK_TEXT_MODEL` is configured, the dict must also include a `"bedrock_text_model"` key; when it is
not configured, that key must be absent entirely.

Source: none

### R6 — `health_check` never raises

The system never raises — the top-level function must catch any unhandled exception and include it in
the structured response. All component failures are caught and reported in-band — the tool never
propagates exceptions to the caller.

**Example**

- Given any combination of component failures, when `health_check` returns, then the response is
  always a structured dict — never a raw exception.

Source: none

## 4. Boundaries

**Always:**
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not reuse `validate_startup()` directly — it raises on failure; health check must catch and
  convert to status entries.
- Do not skip any configured component even if a prior component failed.
- Do not raise an unhandled exception from the tool function.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_health.py` | Create | Written first (Red) |
| `src/arkeology/tools/health.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_health.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `health_check` tool on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_health.py` first → fail → implement `tools/health.py` → unit
tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_health.py` — unit tests (all three fakes: FakeS3, FakeVectors, FakeBedrock):**

Configure the fakes to simulate various combinations of healthy and failing states.

All healthy:
- All components healthy → all entries have `"status": "ok"`.
- Response keys: `"s3"`, `"vectors"`, `"bedrock"`, `"write_prefix"`, plus one per read prefix.
- With no read prefixes configured → no `"read_prefix:..."` keys in response.
- With two read prefixes → two `"read_prefix:..."` keys.

Individual failures:
- `head_bucket` raises `CredentialError` → `"s3"` entry `"error"`; all others `"ok"`.
- `describe_index` raises `VectorIndexNotFoundError` → `"vectors"` entry `"error"`; others `"ok"`.
- `embed` raises `CredentialError` → `"bedrock"` entry `"error"`; others `"ok"`.
- `put_object` raises on write-prefix probe → `"write_prefix"` entry `"error"`; others `"ok"`.
- `list_objects` raises on first read prefix → that read prefix `"error"`; other prefixes and
  components `"ok"`.

All failures:
- All fakes raise → all entries `"error"`; no unhandled exception propagates.

Response shape:
- `"status"` field is always `"ok"` or `"error"` — no other values.
- `"error"` entries always include a non-empty `"message"` string.
- `"ok"` entries have no `"message"` field (or it is absent/null).
- `CredentialError` failures include `"cause": "credential_error"`; generic exceptions do not.

`bedrock_text_model` probe (conditional):
- `BEDROCK_TEXT_MODEL` not set → `"bedrock_text_model"` key absent from response.
- `BEDROCK_TEXT_MODEL` set and reachable → `"bedrock_text_model": {"status": "ok"}`.
- `invoke_text_model` raises `RuntimeError` → `"bedrock_text_model"` `"error"` with message; no
  `"cause"` field.
- `invoke_text_model` raises `CredentialError` → `"bedrock_text_model"` `"error"` with
  `"cause": "credential_error"`.
- `invoke_text_model` raises → other probes still complete and return `"ok"`.

**`tests/integration/test_tools_health.py` — integration tests (`@pytest.mark.integration`):**

- Call `health_check` with a correctly configured environment → all components `"ok"`.
- Verify each expected key is present in the response.
- No teardown needed — health check is read-only (the write-prefix probe cleans up its own probe
  object).

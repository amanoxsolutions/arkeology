---
type: Spec
id: p8-t27-retry-throttle-fix
title: Write Performance P2 — Retry and Throttle Fix
description: Removes the duplicate ThrottlingException retry block from write.py and adds per-retry jitter to bedrock.py's backoff sleep to prevent thundering-herd re-throttling under concurrent embedding.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-02T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T13:29:03Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Write Performance P2 — Retry and Throttle Fix

## TL;DR

`write.py` contains a duplicate `ThrottlingException` catch-and-retry block that compounds
with `bedrock.py`'s internal retry, adding up to 5 s to the cost of a single throttled section.
`bedrock.py`'s retry sleep uses a fixed 2-second delay with no jitter, which causes all
concurrent embed callers to retry at the same moment (thundering herd). This spec removes the
duplicate retry from `write.py` and adds jitter to `bedrock.py`'s backoff sleep.

## 1. Problem Statement

The brainstorming session (2026-06-01) identified three retry-related bottlenecks (RC-3,
RC-4, B2, B3). A single `ThrottlingException` currently costs up to 5 s per section:
`bedrock.py` sleeps 2 s then retries, and if that fails `write.py` sleeps 1 s and retries
again, triggering a second 2-second sleep inside `bedrock.py`. With the concurrent embedding
from P1, multiple sections may throttle at once — without jitter they all retry at the same
instant, re-triggering throttling. These are correctness issues, not just performance issues.

All three user stories this spec states are P1: the duplicate retry in `write.py` is removed,
jitter is added to the `bedrock.py` retry sleep, and non-transient errors are never retried.

## 2. Rules — Retry ownership

### R1 — All retry logic lives in `bedrock.py`

When `write.py` receives any exception from `bedrock.embed`, it does not catch
`ThrottlingException` and retry — all retry logic lives exclusively in `bedrock.py`. An operator
examining `write.py` sees a single, consistent error path: if `bedrock.embed` raises after its
internal retry, `write.py` catches it once, logs to the failure log, and returns a structured
error.

**Example**

- Given Bedrock raises `ThrottlingException` on both the first attempt and the internal retry in
  `bedrock.py`, when `write_artifact` is called, then `bedrock.embed` is called exactly twice (one
  initial + one retry inside `bedrock.py`) — not three times or more.

Source: —

### R2 — An exhausted retry follows the existing failure path

When `bedrock.embed` raises after exhausting its internal retry, `write_artifact` follows the
existing `embed_error` / `doc_embed_error` path: append to failure log, return
`{"error": "partial_write", ...}`.

**Example**

- Given Bedrock raises `ThrottlingException` exhausting all `bedrock.py` retries, when
  `write_artifact` returns, then the response contains `{"error": "partial_write", ...}` and the
  failure log contains one entry — no additional `asyncio.sleep` penalty from `write.py`.

Source: —

### R3 — Non-transient errors are never retried

Removing the `write.py` retry block does not alter the handling of non-transient errors. When a
`CredentialError` is raised in `write.py`, it continues to return
`{"error": "credential_error", ...}` immediately, unchanged from today.

**Example**

- Given Bedrock raises a non-transient `ClientError` (e.g. `ValidationException`), when
  `write_artifact` is called, then `bedrock.embed` is called exactly once (no retry in either
  `write.py` or `bedrock.py`) and the error surfaces immediately as `"partial_write"`.
- Given a `CredentialError`, when `write_artifact` is called, then the response is
  `{"error": "credential_error", ...}` without any retry.

Source: —

## 3. Rules — Retry sleep

### R4 — The retry sleep carries jitter

When `bedrock.py` retries a transient error, it sleeps for
`_RETRY_SLEEP_SECONDS + random.uniform(0, 1)` seconds instead of `_RETRY_SLEEP_SECONDS` exactly,
so that when multiple section embeds throttle simultaneously, they do not all retry at the same
moment.

**Example**

- Given `bedrock.py` triggers a retry sleep for a `ThrottlingException`, when the sleep duration
  is measured, then it equals `_RETRY_SLEEP_SECONDS + jitter` where `jitter` is drawn from
  `random.uniform(0, 1)` — verifiable by patching `random.uniform` in tests.
- Given the same scenario for `ModelTimeoutException` and `ServiceUnavailableException`, when
  retry sleep is measured, then jitter is applied identically.

Source: —

## 4. Boundaries

**Always:**

- Jitter uses `random.uniform(0, 1)` — adds 0 to 1 second of randomness on top of the base
  sleep; the base constant `_RETRY_SLEEP_SECONDS = 2.0` is unchanged.
- `bedrock.py` continues to use `time.sleep` for the retry sleep. With P1's
  `asyncio.to_thread` wrapping, `time.sleep` executes in a worker thread and does not block
  the event loop — this is correct and requires no change in this spec.
- The retry count remains at 1 (two total attempts). No exponential backoff loop is
  introduced in this spec.
- `_RETRY_SLEEP_SECONDS` remains a named constant.

**Ask First:**

- Whether the jitter ceiling of 1 second is appropriate. Raising it would further distribute
  retry bursts but increase maximum latency.

**Never:**

- Do not change `bedrock.py` to `async def embed` in this spec.
- Do not add a retry loop — exactly one retry remains the complete scope.
- Do not remove the `CredentialError` catch in `write.py` — that path is correct and must
  remain.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_bedrock.py` | Modify | Add jitter test: patch `random.uniform`, assert sleep uses base + jitter (written first — Red) |
| `tests/unit/test_tools_write.py` | Modify | Add test verifying `bedrock.embed` is called exactly twice (not 3+) when `ThrottlingException` exhausts retries (written first — Red) |
| `src/arkeology/clients/bedrock.py` | Modify | Add `import random`; change `time.sleep(_RETRY_SLEEP_SECONDS)` to `time.sleep(_RETRY_SLEEP_SECONDS + random.uniform(0, 1))` |
| `src/arkeology/tools/write.py` | Modify | Remove both `except botocore.exceptions.ClientError` blocks that catch `ThrottlingException` and call `asyncio.sleep(1)` + retry `bedrock.embed` (section path and document-level fallback path); retain all `CredentialError` catches |

### Contracts

None.

### Testing Approach

**TDD cycle A (bedrock client):** update `test_fake_bedrock.py` first (Red) →
update `bedrock.py` with jitter (Green).

**TDD cycle B (write tool):** update `test_tools_write.py` first (Red) →
remove duplicate retry from `write.py` (Green).

---

**`tests/unit/clients/test_fake_bedrock.py` — new tests:**

- `test_retry_sleep_includes_jitter` — configure `FakeBedrockClient` to throttle on first
  call; patch `random.uniform` to return `0.5`; patch `time.sleep` to capture the argument;
  call `embed()`; assert the sleep duration equals `_RETRY_SLEEP_SECONDS + 0.5`.
  *(Note: `_RETRY_SLEEP_SECONDS` is imported from `bedrock.py` for the assertion.)*
- `test_retry_sleep_jitter_varies` — call embed twice with throttle on first attempt each time
  (without patching `random.uniform`); assert the two sleep durations are not both exactly
  `_RETRY_SLEEP_SECONDS` (probabilistic guard — confirms jitter is live, not a constant).

**`tests/unit/test_tools_write.py` — new tests:**

- `test_throttle_exhausted_calls_embed_exactly_twice` — configure `FakeBedrockClient` to
  raise `ThrottlingException` on both attempts (already supported via the `throttle_on_next_call`
  flag with two successive setups); spy on `embed`; call `write_artifact` on a single-section
  doc; assert `embed.call_count == 2` and response `"error" == "partial_write"`.
- `test_no_extra_sleep_from_write_on_throttle` — patch `asyncio.sleep` to record calls;
  configure `FakeBedrockClient` to exhaust throttle retries; call `write_artifact`; assert
  `asyncio.sleep` is never called with any positive argument from inside `write.py`.

---
type: Contract
title: arkeology.tools.health
description: The health_check MCP tool — independent per-component connectivity probes for S3, S3 Vectors, Bedrock, the write prefix, and every read prefix, reported as a structured status map that never raises.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p3-t14-health-check.md
  - docs/specs/p1-t5-startup-validation-sequence.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-04
---

# arkeology.tools.health

## Scope

The diagnostic boundary. Its value depends entirely on being able to report a broken component
without itself breaking, so "never raises, and one failure never hides another" is the whole
contract.

## Symbols

### health_check

```python
async def health_check(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> dict[str, Any]: ...
```

**Errors**

Never raises, and never returns a top-level `error` for a component failure — a failing component is
reported *inside* its own entry. Only a failure of the tool itself yields `internal_error`.

**Invariants**
- Every probe runs off the event loop via `asyncio.to_thread`, matching every other tool's
  handling of blocking boto3 calls. Running them inline blocked the loop for the duration of
  the slowest probe, which is the opposite of what a health check should cost.

- Every probe is **independent**. A failing S3 probe must not prevent the Bedrock probe from running
  or being reported. A tool that short-circuited on first failure would hide exactly the correlated
  outage it exists to diagnose.
- Every exception is caught and mapped to a component-level entry. No probe exception escapes.
- A `CredentialError` is distinguished from other failures by a `"cause": "credential_error"` field,
  because credential expiry is the single most common cause and is remediated differently from a
  genuine service or configuration fault.
- `health_check` never writes an artifact, a vector, or an annotation. The write-prefix probe is
  the sole exception to read-only operation: it performs a real PutObject → GetObject →
  DeleteObject cycle on a single fixed probe key under the write prefix, because write
  permission cannot be verified without exercising it. The probe key is excluded from
  `reconcile_index`'s orphan scan, and a `finally` block re-attempts the delete if the cycle
  fails part-way, so a failed probe leaves no durable object. An operator granting the
  health-check principal read-only S3 permissions will see `write_prefix` permanently in
  `error`.

**Preconditions**

- All four clients are required. Passing a client through is what makes the probe meaningful — a
  probe of an unconfigured component would report health it cannot observe.

**Postconditions**

- Returns a dict keyed by `"s3"`, `"vectors"`, `"bedrock"`, `"write_prefix"`, one
  `"read_prefix:{prefix}"` entry per configured read prefix, and — only when a text model is
  configured — `"bedrock_text_model"`.
- Each value is `{"status": "ok"}` or `{"status": "error", "message": str}`, the latter optionally
  carrying `"cause"`.
- The key set reflects **configured** components, so a deployment with no read prefixes yields no
  `read_prefix:` keys — their absence means "none configured", not "not checked".

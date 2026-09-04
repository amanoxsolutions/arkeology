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
  by: ""
  date: YYYY-MM-DD
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

- Every probe is **independent**. A failing S3 probe must not prevent the Bedrock probe from running
  or being reported. A tool that short-circuited on first failure would hide exactly the correlated
  outage it exists to diagnose.
- Every exception is caught and mapped to a component-level entry. No probe exception escapes.
- A `CredentialError` is distinguished from other failures by a `"cause": "credential_error"` field,
  because credential expiry is the single most common cause and is remediated differently from a
  genuine service or configuration fault.
- Probes are read-only. `health_check` never writes an artifact, a vector, or an annotation.

**Preconditions**

- All four clients are required. Passing a client through is what makes the probe meaningful — a
  probe of an unconfigured component would report health it cannot observe.

**Postconditions**

- Returns a dict keyed by `"s3"`, `"vectors"`, `"bedrock"`, `"write_prefix"`, and one
  `"read_prefix:{prefix}"` entry per configured read prefix.
- Each value is `{"status": "ok"}` or `{"status": "error", "message": str}`, the latter optionally
  carrying `"cause"`.
- The key set reflects **configured** components, so a deployment with no read prefixes yields no
  `read_prefix:` keys — their absence means "none configured", not "not checked".

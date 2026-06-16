---
type: spec
title: Phase 1 Overview
description: Foundation phase spec covering runnable server skeleton with startup validation — the base all subsequent phases depend on.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
feature: phase-1-overview
status: ready
phase: 1
references: []
authored:
  by: "architect"
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# Phase 1 — Foundation: Runnable Server with Startup Validation

## Goal

The server starts, validates all configuration, and fails clearly on any misconfiguration. No MCP
tools yet — just the skeleton everything else builds on. Every subsequent phase depends on this
foundation being correct.

---

## Task Status

| # | Task | Spec | Status | Blocked by |
|---|------|------|--------|------------|
| T1 | Bootstrap Python project | [p1-t1-bootstrap-python-project.md](./p1-t1-bootstrap-python-project.md) | ✅ Done | — |
| T2 | FastMCP server skeleton | [p1-t2-fastmcp-server-skeleton.md](./p1-t2-fastmcp-server-skeleton.md) | ✅ Done | T1 |
| T3 | AWS client layer | [p1-t3-aws-client-layer.md](./p1-t3-aws-client-layer.md) | ✅ Done | T1 |
| T4 | Configuration model | [p1-t4-configuration-model.md](./p1-t4-configuration-model.md) | ✅ Done | T1 |
| T5 | Startup validation sequence | [p1-t5-startup-validation-sequence.md](./p1-t5-startup-validation-sequence.md) | ✅ Done | T2, T3, T4 |

> **Status values:** ⬜ Not started · 🔄 In progress · ✅ Done · 🚧 Blocked

Update the table above as you work through the tasks.

---

## TDD Discipline

Every task in Phase 1 that involves business logic follows **strict test-first order**:

1. Write the test file in full. Run it. Confirm it fails (`ImportError` or assertion failure). This is the **Red** state — required before writing any implementation.
2. Write the minimum implementation to make the tests pass. This is the **Green** state.
3. Refactor the implementation for clarity, edge cases, and type safety. Tests stay green throughout.

**Never write implementation code before the test that covers it exists and fails.**

| Task | Has business logic? | TDD applies? | Notes |
|------|---------------------|-------------|-------|
| T1 Bootstrap | No | ✗ | Tooling setup only; no test-drivable logic |
| T2 FastMCP skeleton | Minimal | Partially | Only `configure_logging()` is test-drivable |
| T3 AWS client layer | Yes | ✅ | Two distinct Red/Green cycles: fakes first, then concrete clients |
| T4 Configuration model | Yes | ✅ | Purest TDD case — pure validation logic, no I/O |
| T5 Startup validation | Yes | ✅ | Test-first using fakes from T3 |

Each task spec has a dedicated **TDD Workflow** section with the exact Red/Green/Refactor steps.
Read that section before touching any implementation file for the task.

---



```
T1 Bootstrap
├── T2 FastMCP skeleton
├── T3 AWS client layer
└── T4 Configuration model
         └── T5 Startup validation (requires T2 + T3 + T4)
```

T2, T3, and T4 can be worked in parallel once T1 is done. T5 assembles them.

---

## Resulting Repository Layout

After Phase 1 is complete, the repository must have this layout. The developer should reference
this as the target structure — no files outside this layout should be needed for Phase 1.

```
cairn-mcp/
├── pyproject.toml               # Package config, dependencies, tool settings
├── .python-version              # uv-managed Python version pin
├── .pre-commit-config.yaml      # ruff + mypy pre-commit hooks
├── .gitignore                   # Includes .docs/, failure-log.jsonl, .env
├── README.md                    # (exists, not modified in Phase 1)
├── AGENTS.md                    # (exists, not modified in Phase 1)
│
├── src/
│   └── cairn_mcp/
│       ├── __init__.py          # Package marker
│       ├── __main__.py          # Entry point — calls server.run()
│       ├── server.py            # FastMCP app — transport setup, signal handling
│       ├── config.py            # Settings dataclass, env var parsing + validation
│       ├── startup.py           # Startup validation sequence (5 checks)
│       ├── errors.py            # All structured error types used by the server
│       └── clients/
│           ├── __init__.py
│           ├── interfaces.py    # Abstract base classes for all three clients
│           ├── s3.py            # S3 concrete boto3 implementation
│           ├── vectors.py       # S3 Vectors concrete boto3 implementation
│           ├── bedrock.py       # Bedrock concrete boto3 implementation
│           └── fakes/
│               ├── __init__.py
│               ├── fake_s3.py       # In-memory S3 fake for unit tests
│               ├── fake_vectors.py  # In-memory S3 Vectors fake for unit tests
│               └── fake_bedrock.py  # Deterministic embedding fake for unit tests
│
└── tests/
    ├── conftest.py              # Shared fixtures (fake clients, sample config)
    ├── unit/
    │   ├── test_config.py           # Config parsing + validation
    │   ├── test_startup.py          # Startup sequence (all failure paths, via fakes)
    │   └── clients/
    │       ├── test_fake_s3.py       # S3 fake interface coverage
    │       ├── test_fake_vectors.py  # S3 Vectors fake interface coverage
    │       └── test_fake_bedrock.py  # Bedrock fake interface coverage
    └── integration/
        └── clients/
            ├── test_s3_client.py       # Real boto3 S3 calls (requires AWS creds)
            ├── test_vectors_client.py  # Real S3 Vectors calls (requires provisioned index)
            └── test_bedrock_client.py  # Real Bedrock calls (requires model access)
```

---

## Phase 1 Retrospective Checklist

Before Phase 2 begins, confirm all of the following:

- [ ] `uv run pytest tests/unit/` passes with no warnings
- [ ] `uv run cairn-mcp` starts cleanly when all env vars are valid and AWS is reachable
- [ ] Server refuses to start and prints a clear actionable error for each of the 5 misconfiguration scenarios (individually tested)
- [ ] AWS client fakes fully cover their interface (every method on the abstract base class is implemented and tested)
- [ ] Integration tests pass against a real AWS environment with provisioned resources
- [ ] Pre-commit hooks pass on the entire codebase (`uv run pre-commit run --all-files`)
- [ ] `uv run mypy src/` reports zero errors
- [ ] Configuration reference in AGENTS.md is accurate (all env vars, types, defaults)

---

## Key Architectural Invariants Established in Phase 1

These are not up for re-evaluation in subsequent phases:

1. **All AWS calls go through the client interfaces** — no direct boto3 calls in server, tools, or startup logic. Every boto3 interaction is behind `S3ClientInterface`, `VectorsClientInterface`, or `BedrockClientInterface`.
2. **Credential errors are caught at the client layer** — the interfaces define `CredentialError` as a typed exception; concrete implementations catch `botocore.exceptions.ClientError` and re-raise as `CredentialError`. Nothing above the client layer handles raw botocore exceptions.
3. **Config is validated once at startup, then treated as read-only** — the `Settings` object is constructed once, validated, and injected where needed. It is never re-read from the environment mid-session.
4. **Fakes are the test substrate for all unit tests** — unit tests never touch real AWS. Integration tests use real AWS but are in a separate directory and must be explicitly opted into.
5. **stdio is the transport** — the FastMCP server uses stdio. This must not be hardcoded into the tool logic; the server module is the only place that names the transport.

---

## Phase 1 Done Condition

Phase 1 is complete when:

- The retrospective checklist above is fully checked
- A human has manually verified that `uv run cairn-mcp` starts and logs a clear startup message
- A human has manually verified that missing `AWS_REGION` produces an actionable error before any tool prompt appears

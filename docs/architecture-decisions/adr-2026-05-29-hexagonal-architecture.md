---
type: adr
title: Layered Architecture with Protocol-Based Client Interfaces
description: Records the choice of a layered architecture isolating domain and tool logic from AWS service calls behind typing.Protocol interfaces, with concrete clients injected as dependencies.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# Layered Architecture with Protocol-Based Client Interfaces

## Description

This decision records the structural pattern chosen for arkeology: a layered architecture
that isolates the domain model and tool logic from all AWS service calls behind
`typing.Protocol` interfaces, with concrete clients injected as dependencies.

## Status

Accepted

## Context

The team requires the following from the architecture (NFR-04, NFR-07):

- **Testability without real AWS** — all business logic must be exercisable in unit tests
  without network calls. AWS service interactions are covered by integration tests only.
- **Replaceability** — any storage, vector, or embedding layer must be replaceable without
  touching tool logic. The server is deployment-agnostic; the choice of concrete client
  must be a wiring decision, not woven into every tool.
- **No domain pollution** — artifact ID generation, section parsing, and the `Artifact` model
  must contain zero AWS, I/O, or framework dependencies so they can be reasoned about and
  tested in complete isolation.

Python offers two mechanisms for interface contracts: abstract base classes (`ABC` +
`abstractmethod`) and structural typing (`typing.Protocol`). The distinction matters for
testability: ABC requires concrete implementations and fakes to inherit from the interface
class, creating a coupling that is unnecessary when the goal is duck typing; Protocol allows
any structurally compatible object to satisfy the contract without inheritance.

The project also adopted dependency injection over module-level imports for clients: tool
functions receive `settings`, `s3`, `vectors`, and `bedrock` as parameters rather than
importing them from a global registry.

## Decision

We chose a layered architecture with four distinct concerns:

1. **Domain layer** (`artifact.py`) — pure Python data types and utilities. No imports from
   `boto3`, `fastmcp`, or any other framework. Tested in complete isolation.
2. **Interface layer** (`clients/interfaces.py`) — three `typing.Protocol` classes:
   `S3ClientInterface`, `VectorsClientInterface`, `BedrockClientInterface`. Concrete
   implementations and fakes satisfy these contracts structurally — they do not inherit from
   the interface class. `ABC` and `abstractmethod` are never used in client code.
3. **Adapter layer** (`clients/s3.py`, `clients/vectors.py`, `clients/bedrock.py`) — concrete
   boto3 implementations. Each wraps credential-related boto3 exceptions and re-raises them
   as `CredentialError` so the error type is uniform across all callers.
4. **Tool layer** (`tools/*.py`) — MCP tool implementations. Each tool function receives
   `settings`, `s3`, `vectors`, and `bedrock` as injected parameters. No tool imports any
   concrete client directly.

Clients are constructed once in `__main__.py` and passed into `server.register_tools()`,
which binds them into tool closure variables. Unit tests supply moto-backed real
implementations or `FakeBedrockClient` in place of the concrete AWS clients.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — Protocol interfaces + DI | No inheritance coupling; structurally compatible fakes; domain is AWS-free; any layer replaceable independently | Structural typing requires discipline — protocol drift is not caught at import time without a type checker; verbose DI signature on every tool function |
| ABC + abstractmethod interfaces | Explicit contract enforcement at class definition; familiar to many Python developers | Forces inheritance on fakes and concrete clients; adds coupling that buys nothing when `mypy` is already enforced |
| Module-level singletons (global clients) | Less boilerplate in tool functions | Global state makes unit testing harder; client construction order becomes implicit; replacing a client requires patching module state |
| No interfaces (boto3 calls in tools) | Minimal abstraction | Tools cannot be unit tested without mocking at the boto3 level; replacement of any AWS service requires changes across all tools |

## Consequences

- All unit tests use moto-backed `S3ClientImpl` / `VectorsClientImpl` (with a `query_vectors`
  cosine-similarity extension patched onto `S3VectorsBackend` in `conftest.py`) and
  `FakeBedrockClient` (hash-derived deterministic embeddings). No real AWS calls in unit tests.
- `mypy --strict` enforces that all concrete clients and fakes satisfy the Protocol contracts
  at type-check time; this is the primary guard against structural drift.
- The `filter` parameter in vector client methods is renamed to `filter_expr` throughout to
  avoid shadowing the Python builtin.
- Adding a new AWS service (e.g. a caching layer) follows the same pattern: define a Protocol
  in `interfaces.py`, implement the concrete adapter, inject it into the relevant tools.
- The `_search_helper.py` module is the single source of truth for the re-fetch loop shared
  by `search_artifacts` and `synthesise_artifacts` — fixing search behaviour requires one
  change in one file.

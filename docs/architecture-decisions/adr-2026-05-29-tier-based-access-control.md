---
type: adr
title: Tier-Based Cross-Scope Access Control Model
description: Records the model that controls which artifacts from foreign scopes are readable by a given Arkeology deployment, governed by tier and visibility attributes and enforced server-side.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
status: accepted
references:
  - docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: "architect"
  date: "2026-09-25"
---

# Tier-Based Cross-Scope Access Control Model

## Description

Arkeology is designed to be deployed once per team or project, with each deployment writing
to its own S3 prefix. This decision records the model that controls which artifacts from
foreign scopes are readable by a given deployment, and how that model is enforced.

## Status

Accepted

## Context

A key product requirement is cross-team knowledge sharing (FR-10): platform team ADRs and
architecture decisions must be discoverable by microservices team agents, without those agents
being able to read or overwrite the platform team's working documents (session summaries,
code reviews, implementation notes).

The access model must answer two questions:

1. **Which artifacts from foreign scopes are visible?** — Teams need to share canonical,
   stable knowledge; they do not need to share in-progress working documents.
2. **How is access enforced?** — IAM policies control S3 bucket access at the infrastructure
   level. Server-side enforcement is a higher-level semantic gate, not a security boundary.

Two attributes on every artifact govern cross-scope visibility:

- **Tier**: `2` (project-local, session-scoped, append-only) or `3` (permanent, living
  document, updated in place). Tier 2 includes code reviews, session summaries, and
  implementation notes. Tier 3 includes ADRs, plans, PRDs, and synthesis artifacts.
- **Visibility**: `shared` (discoverable across scopes) or `hidden` (own scope only).

The cross-scope read configuration is set by the operator via `READ_PREFIXES` — a
comma-separated list of S3 prefixes the server is allowed to read from. Startup check 3
validates that each prefix is accessible.

A subtle but critical implementation detail: the scope check must use
`artifact_id.startswith(scope + "/")`, never bare `startswith(scope)`. A bare prefix check
allows a scope of `"team-a"` to incorrectly match keys under `"team-abc/"`.

A second, related constraint on the configuration itself — added 2026-09-05 after a review
found it unenforced — is that **no read prefix may sit at or beneath the write prefix**. With
`WRITE_PREFIX=team` and `READ_PREFIXES=team/proj`, the own-scope test above answers `True` for
the other deployment's artifacts, so they pass every own-scope-only gate and become eligible
for archive, delete, purge, and link backfill. Configuration validation now rejects this, and
the server refuses to start.

The constraint is deliberately *not* full disjointness between the two settings, which is what
this decision originally implied. The precise requirement is one-directional, because the two
scope tests use different matching semantics: `build_scope_filter` selects foreign artifacts by
**exact** equality on the stored `scope` value (`{"scope": {"$in": read_prefixes}}`), while
`is_own_scope` matches hierarchically on the key. The reverse nesting — a write prefix beneath a
read prefix, as in `WRITE_PREFIX=team/proj` with `READ_PREFIXES=team` — is therefore safe and
remains supported: a foreign server writing under `team` stores `scope="team"`, which never
equals `team/proj`, and the own-scope check is consulted before the foreign one, so own always
wins. That shape is a legitimate deployment ("write to my sub-scope, subscribe to the whole
org") and must not be forbidden. Nesting among read prefixes is likewise harmless, for the same
exact-match reason.

## Decision

Access across scope boundaries is governed by two rules, enforced server-side in every read,
search, list, and synthesise tool:

- **Own scope** (`WRITE_PREFIX`): all artifacts are accessible regardless of tier or
  visibility.
- **Foreign scope** (`READ_PREFIXES`): only tier 3 + `visibility=shared` artifacts are
  accessible. Tier 2 artifacts and tier 3 hidden artifacts from foreign scopes are silently
  excluded from results and rejected on direct read.

Write, archive, delete, and purge operations are always restricted to the own scope.

**A `tier` or `visibility` the gate cannot read denies the candidate** (added 2026-09-14 — see the
Revision note below). The rule admits a foreign artifact only on an affirmative reading of both
fields, so an absent value, a `tier` that is not parseable as an integer, and a non-scalar value of
either field are all *not* an affirmative reading and the candidate is denied. The gate never raises
over a stored value: it is a predicate over data this deployment did not write, and an exception is
neither an allow nor a deny.

`is_cross_scope_readable` is where that denial happens, and it is the **authority**: every read
path — read, delete, listing, search, and synthesis — runs it against the candidate's own metadata.
`build_scope_filter` expresses the rule as a server-side S3 Vectors filter — `{"tier": {"$eq": 3}}`
ANDed with `{"visibility": {"$eq": "shared"}}` — but it is a **prefetch optimisation**, not a second
gate. It rejects an absent or unparseable scalar, and it does not reject a *non-scalar* one: `$eq`
means value-in-list for a list-valued field, which `tags` requires, so a stored `tier` of `[3]`
matches the clause. The filter is deliberately not narrowed to close that; the predicate denies it
instead.

The two directions are therefore not symmetrical. A filter that admits more than the predicate costs
a wasted fetch and nothing else. A filter that admits **less** is a bug: the candidate is never
fetched, the predicate never sees it, and a readable artifact silently disappears from every result.
That one direction is pinned by `test_never_rejects_a_candidate_the_predicate_would_admit` in
`tests/unit/test_tools__scope.py`, and both forms live in `_scope.py` inside the declared
mutation-testing scope.

This is a **soft control** enforced at the server layer, and its reach differs by storage
side (revised 2026-07-02 — see the Revision note below):

- **S3 content can be hard-bounded**: IAM supports prefix-scoped object permissions, so a
  team can be denied `s3:GetObject` on foreign prefixes — foreign tier 2 *content* is
  infrastructure-protectable.
- **The shared vector index cannot**: the IAM condition keys applicable to
  `s3vectors:QueryVectors`/`GetVectors`/`ListVectors` (`aws:ResourceTag`,
  `s3vectors:VectorBucketTag`) evaluate at the index/bucket resource level only — no
  condition key references vector keys, vector metadata, or the request's filter
  expression. Any principal with query access to the shared index can read **all**
  participants' vector metadata (titles, descriptions, tags, tier, status) and embeddings —
  including tier 2 and hidden artifacts — with plain AWS API calls; no modified server is
  required.

Sharing a vector index therefore implies **mutual trust between all participating teams at
the metadata, description, and embedding level**. The tier/visibility gate is a policy
convention honoured by unmodified servers, not an access control. The server README
documents this distinction.

Cross-scope semantic search requires all participating deployments to share the same S3
Vectors index, embedding model, and vector dimension. Deployments using separate indexes
cannot perform cross-scope semantic search (documented in deployment prerequisites).

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — Tier + visibility gate | Simple two-attribute model; maps naturally to the tier 2/3 semantic split; no per-artifact ACL to manage | Soft control only — does not replace IAM; visibility is binary (shared/hidden), not fine-grained |
| Full isolation (no cross-scope) | Simplest implementation; no access control logic in tools | Loses the cross-team knowledge sharing use case — a core product differentiator |
| Per-artifact ACL (allowlist of scopes) | Fine-grained control | Significant complexity: ACL storage, evaluation, and management surface for agents; far exceeds the use case requirements |
| IAM only (no server-side gate) | Single enforcement point | IAM policies cannot encode the tier 2 / tier 3 semantic distinction; every artifact in a readable bucket would be accessible |

## Consequences

- Every read, search, list, and synthesise tool contains a scope gate. The gate is tested for
  both the own-scope (unrestricted) and foreign-scope (tier 3 + shared only) cases.
- The scope check `artifact_id.startswith(scope + "/")` is non-negotiable — bare
  `startswith(scope)` is a documented high-friction area in `AGENTS.md` and must never be
  used.
- Cross-scope semantic search is implemented as a single combined `QueryVectors` call using a
  `$or` filter that covers own scope (unrestricted) and each foreign scope (tier 3 + shared).
  This avoids N separate query calls per iteration.
- `WRITE_PREFIX` must not be empty — an empty prefix causes `startswith("" + "/")` to always
  return `True`, silently bypassing the gate for all artifacts. A startup validator enforces
  this.
- Visibility is enforced server-side and is intentionally not exposed as a filter parameter
  to agents — the gate is not bypassable through the MCP API.
- The delete synthesis reference check in `delete_artifact` is scoped to own scope only —
  foreign-scope synthesis identifiers must never appear in delete warnings (confirmed as a
  known bug in Phase 3 and fixed in Phase 6).

## Revision — 2026-07-02

The original Decision text claimed "operators who want a hard boundary must configure IAM
to restrict cross-bucket or cross-prefix access accordingly." No IAM configuration can
provide a tier-aware boundary *within* a shared vector index — verified against the
[Service Authorization Reference for Amazon S3 Vectors](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazons3vectors.html):
all condition keys applicable to the query/read actions evaluate at the index/bucket
resource level (resource tags), never at the vector or metadata level. The Decision text
above now records the content/index asymmetry and the mutual-trust assumption. The tier +
visibility gate itself is unchanged and remains correctly implemented.

Hard-boundary directions, if ever required (candidates for a future ADR; anchored in
requirements.md FR-65, "full cross-scope enforcement of the visibility gate"):

1. **Per-team vector indexes + tier 3 replication** — each team owns a private index; tier 3
   `shared` vectors are additionally written to a shared discovery index. Dual writes and a
   reconcile story, but index-level resource tags then give a true IAM boundary between
   teams.
2. **Metadata redaction for non-shared artifacts** — keep `description` (and optionally
   `title`) out of the shared index for tier 2 / hidden artifacts, shrinking the exposure to
   embeddings only.
3. **Hosted deployment** — a shared server process holds the AWS credentials and clients
   authenticate to it; the gate then runs on the trusted side of the boundary. Requires the
   HTTP transport listed as a future consideration (NFR-05).

## Revision — 2026-09-14

The Decision text stated the gate's rule for well-formed `tier` and `visibility` values only, and
was silent on a value the gate cannot read. The in-process form coerced `tier` with an unguarded
`int(...)` — a coercion that is genuinely required, because `read_artifact` hands the gate S3 object
metadata where `tier` is a stringified integer while the listing and search paths hand it vector
metadata where `tier` is an `int` — so a non-numeric or non-scalar value raised instead of
answering. The Decision text now records that such a value denies, which is what the server-side
filter form has always done, and that the gate never raises over a stored value.

This closes a real availability gap rather than a theoretical one: the gate is applied per candidate
inside a loop, so one foreign record another team's deployment wrote badly took down the whole
listing, search, or reference resolution for that scope. It is not a confidentiality change — the
new outcome is denial everywhere the old code raised, so nothing becomes readable that was not
readable before.

The wider policy this clause belongs to — what every tool does with malformed or ambiguous persisted
data, including the loop-level skip-and-count behaviour that complements this denial — is recorded
in [the malformed and ambiguous persisted data policy](adr-2026-09-14-malformed-persisted-data-policy.md).
The tier + visibility rule itself is unchanged.

## Proposed Revision — 2026-09-25

> **Pending.** Proposed by ADR-016 (draft, awaiting review); takes effect when ADR-016 is
> accepted. Until then this ADR's Decision stands as written above.

[The OKF v0.2 adoption ADR](adr-2026-09-25-okf-v02-adoption.md) proposes extending what the gate is
applied to and how a withheld link is reported. The rule itself — both forms, and denial on an unreadable
`tier` or `visibility` — is unchanged and reused as-is.

- **`sources` entries that point into Arkeology** (`arkeology://artifact/{id}`) now pass the gate,
  as `relationships` entries do. Previously they did not, because sources were external only. URLs
  and unresolved paths pass untouched.
- **Unreadable link entries are redacted, not dropped.** When `sources` or `relationships` are
  returned to a foreign-scope reader, the entries it could not independently read are removed and
  one in-list `{withheld: n}` marker per list carries only their count — no id, resource, title or
  timestamp. It is emitted on every capability that returns the lists, without exception. This
  applies to entries *inside* a returned artifact; the Decision's exclusion of unreadable artifacts
  from result sets is unchanged.
- **The returned content's frontmatter is redacted the same way.** For a foreign-scope reader the
  `sources:` and `relationships:` blocks of the *returned* content are rewritten with the same
  entries removed and the same marker, because migration writes resolved sources into the
  frontmatter and redacting only the field would leave every withheld id beside it. The stored
  object is never modified. The surfaces are reading, listing (the field), synthesis preparation
  and the data resources; search returns neither link fields nor content. The body is out of
  scope — it is authored prose.
- **The shared index exposes a little more.** Lifecycle `status`, `archived`, and the
  `generated.by` / `revised.by` actor strings — which for humans are `human:<id>` — now sit in
  vector metadata and fall under this ADR's mutual-trust assumption.

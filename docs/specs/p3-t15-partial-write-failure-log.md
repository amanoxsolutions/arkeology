---
type: Spec
id: p3-t15-partial-write-failure-log
title: T15 — Partial Write Failure Log
description: Feature spec for the structured failure log that records partial write failures (S3 succeeds but Bedrock or S3 Vectors indexing fails) at one fixed per-user location for each artifact bucket, the failure_logged flag that tells the caller whether an entry was actually written, and a Bedrock throttle retry mechanism.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: Architecture review — Arkeology (whole design record)
    last_modified: 2026-11-10T11:21:17Z
  - resource: https://specifications.freedesktop.org/basedir/latest/
    title: XDG Base Directory Specification
  - resource: docs/specs/p5-t21-reconciliation-tool.md
    title: T21 — Reconciliation Tool
    last_modified: 2026-11-09T13:13:28Z
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology-recheck.md
    title: "Architecture review — Arkeology (whole design record), re-check of C-1 to C-3"
    last_modified: 2026-11-10T16:49:29Z
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html
    title: Amazon S3 User Guide — General purpose bucket naming rules
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-12T21:20:24Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "human:mlnrt"
    at: 2026-11-12T21:20:30Z
---

# T15 — Partial Write Failure Log

## TL;DR

When `write_artifact` stores an artifact in S3 but the following Bedrock embed or S3 Vectors
`put_vector` call fails, the server appends a structured entry to a failure log and returns a
structured `partial_write` error naming the artifact, so no write is ever silently lost and
reconciliation can later re-index it. The log lives at one fixed per-user location for each
artifact bucket, never in the
directory a client happened to start the server in, and every response that promises an entry says
through `failure_logged` whether it was actually written. A Bedrock throttle is retried exactly once
after a short back-off before it counts as such a failure.

## 1. Problem Statement

A write operation can partially fail: S3 succeeds (the artifact content is stored durably) but the
subsequent Bedrock embedding or S3 Vectors indexing call fails. Without a recovery mechanism, the
artifact is permanently invisible to search — stored in S3 but never indexed. This is a silent data
loss scenario that violates NFR-11 ("never silently discard a write operation"). T15 closes that gap by
writing a structured entry to a local tier 1 failure log when a partial write occurs, then surfacing a
structured error to the agent that includes the artifact identifier and a note that a failure log
entry was written. The reconciliation tool (T19, FR-17) will later use this log to re-index orphaned
artifacts.

Additionally, Bedrock throttling is a transient error that should be retried once with back-off before
being surfaced as a hard failure.

Two further conditions decide whether a logged entry is ever replayed. The log must sit where every
later repair run finds it: a path relative to the working directory puts entries wherever the MCP
client happened to start the server — a project folder, a desktop client's own launch directory, a
CI runner's workspace that is destroyed when the job ends — and a `reconcile_index` run started
anywhere else never sees them. This matters most for an entry written after an object re-PUT,
which holds the only remaining copy of the annotations that re-PUT cleared. And the agent must be
told when the append itself failed, rather than receive a code promising an entry that does not
exist. R7 and R9–R13 cover both; telling a pipeline agent to reconcile before its job ends belongs
to the setting-up skill's AGENTS.md snippet (T31a R26, R28).

Every story this spec covers is priority P1, including those behind R7 and R9–R13.

## 2. Rules — Partial write logging

### R1 — A partial write is logged before the error is returned

When an S3 write in `write_artifact` succeeds but a subsequent Bedrock embed or `put_vector` call fails
(for any non-credential reason), the system writes a structured JSON entry to the local failure log
before returning a structured error. A partial write failure is never silent.

**Example**

- Given a simulated Bedrock failure after the S3 write succeeds, when `write_artifact` returns, then the
  response contains `"error": "partial_write"`, the `artifact_id`, `"failure_logged": true`,
  and a message indicating the failure log was written.
- Given a simulated S3 Vectors `put_vector` failure after the S3 write succeeds, when `write_artifact`
  returns, then the response contains `"error": "partial_write"`, the `artifact_id`,
  `"failure_logged": true`, and a message indicating the failure log was written.

Source: NFR-11

### R2 — A failure log entry carries the artifact's identity and the failure

The failure log entry includes: `artifact_id` (the full S3 key), `title`, `type`, `tier`, `date`,
`failure_step` (one of: `"bedrock_embed"`, `"put_vector"`), `reason` (exception message), and a
timestamp. The entry is machine-readable and includes the failure reason (e.g. which step failed).

**Example**

- Given a partial write occurred, when the failure log file is read, then it contains a
  machine-readable entry with the artifact identifier, title, type, tier, and failure reason.

Source: none

### R3 — The failure log is append-only newline-delimited JSON

The failure log is append-only newline-delimited JSON (`.jsonl`), one JSON object per line. It is
appended to (not overwritten) so multiple failures accumulate. When the failure log file does not
exist, the system creates it.

Source: none

### R4 — A failure log write never raises, and a failed one is reported rather than hidden

Failure log writes must never raise — if the log write itself fails, the system logs the error to
stderr (Python logging) at ERROR, naming the artifact id and the failed step and nothing else of the
entry, and continues to return the partial-write error to the agent, with `"failure_logged": false`
(R11).

**Why:** an entry can carry the artifact's links — its sources, relationships and commit refs — and,
after an object re-PUT, the only remaining copy of its annotations, and the vision rates the store's
data as sensitive (`vision.md` § Operating Context, "Data sensitivity"). stderr lands in the AI
client's own log files and in CI job logs, which are often readable more widely than the store, so
the entry never goes there. The cost is accepted: when both the operation and its log append fail,
the entry is lost, and the operation's caller repeats the operation, adding again by hand any link
only the entry held.

Source: NFR-11; the ERROR line names only the artifact and the failed step (Operator, 2026-11-12)

### R5 — Credential errors are not partial writes

When a `CredentialError` occurs (not a partial write — credential errors are hard failures), the
system does not write a failure log entry; it returns a credential-error response as before. Credential
errors remain credential errors and are NOT treated as partial write failures.

Source: none

### R6 — The partial-write error response shape

The structured error response on partial write contains
`{"error": "partial_write", "message": str, "artifact_id": str, "failure_logged": bool}`. When
`failure_logged` is `false`, `message` does not claim the failure was recorded.

Source: none

### R7 — The failure log lives at one fixed per-user location for each artifact bucket, never in the working directory

The failure log is a tier 1 artifact: local to the host and never committed to a repository. Its
location never depends on the directory the MCP client started the server in. The path is
configurable via the optional `FAILURE_LOG_PATH` setting, which is used as given. When that is not
set, the path names the artifact bucket:
`$XDG_STATE_HOME/arkeology/<ARTIFACT_BUCKET>/failures.jsonl`, or
`~/.local/state/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` when `XDG_STATE_HOME` is unset, empty
or not an absolute path — the XDG Base Directory Specification's rule for user state that must
persist between restarts. Every server the same user runs on the host against one artifact bucket,
whichever project, client or directory started it, therefore appends to and reconciles from the
same file, and a server configured with another bucket never reads it. An operator who sets
`FAILURE_LOG_PATH` gives each artifact bucket a path of its own: one path shared by the servers of
two buckets is not a supported configuration.

**Example**

- Given `FAILURE_LOG_PATH` unset, `ARTIFACT_BUCKET=team-store` and
  `XDG_STATE_HOME=/home/u/.state`, when a partial write is logged, then the entry is appended to
  `/home/u/.state/arkeology/team-store/failures.jsonl`, whatever the working directory.
- Given `FAILURE_LOG_PATH` and `XDG_STATE_HOME` both unset, `ARTIFACT_BUCKET=team-store` and
  `HOME=/home/u`, then the entry is appended to
  `/home/u/.local/state/arkeology/team-store/failures.jsonl`.
- Given `XDG_STATE_HOME=state` (a relative path), then it is ignored and the `~/.local/state`
  location is used.
- Given two servers of one user on one host, both with write prefix `team-a` but configured with
  the artifact buckets `store-a` and `store-b`, when the `store-a` server logs a partial write and
  the `store-b` server then runs `reconcile_index`, then that run never reads the entry, and it
  stays in `…/arkeology/store-a/failures.jsonl` for a `store-a` run to replay.

**Why:** an entry written after an object re-PUT holds the only remaining copy of the annotations
that re-PUT cleared. A path relative to the working directory scatters entries across project
folders, a desktop client's own launch directory, or a CI runner's workspace that is destroyed when
the job ends, where no later `reconcile_index` run finds them. The default names the bucket because
a write prefix alone does not tell two stores apart: a user whose clients point at two stores that
use the same write prefix — a personal or staging store beside the team's, or the stores of two
organisations — would otherwise have one store's `reconcile_index` take the other's entries for its
own, re-index or restore them against an object of the same id in the wrong store, and prune them,
leaving the store that wrote them with no copy at all. A general purpose bucket's name is unique
within its AWS partition and uses only lowercase letters, digits, dots and hyphens, never two dots
in a row, so it names a directory as it stands.

Source: NFR-11; the per-user, per-bucket location (Operator, 2026-11-12); https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html

### R9 — The path is resolved once at startup, its directory is created, and the result is logged

WHEN the server starts THE SYSTEM SHALL resolve the failure log path once to an absolute path and
log it at INFO; every append and every `reconcile_index` run then uses that path. An operator-set
`FAILURE_LOG_PATH` has a leading `~` expanded, and a value still relative after that is resolved
against the startup working directory; nothing else is added to it, the artifact bucket included.
WHEN the resolved path's parent directory does not exist THE SYSTEM SHALL create it, and every
missing directory above it, with owner-only permissions (`0700`); WHEN it cannot be created THE
SYSTEM SHALL refuse to start with an error naming the path, rather than accept writes whose entries
could never be recorded.

**Example**

- Given `FAILURE_LOG_PATH=~/arkeology/failures.jsonl` and `HOME=/home/u`, when the server starts,
  then an INFO line names `/home/u/arkeology/failures.jsonl` and entries are appended there.
- Given the default location, `ARTIFACT_BUCKET=team-store` and no `arkeology` directory under the
  state directory, when the server starts, then `arkeology` and `arkeology/team-store` exist under
  it, each with mode `0700`.
- Given a parent directory that cannot be created, when the server starts, then it exits with an
  error naming the path and serves no request.

Source: NFR-11; refusing to start when the directory cannot be created, and a relative path resolved against the startup directory (Operator, 2026-11-12)

### R10 — A non-empty log at the old default in the startup directory is warned about, never read

WHEN the server starts and its working directory holds a non-empty `.arkeology_failures.jsonl` that
is not the resolved failure log THE SYSTEM SHALL log a WARNING naming that file, the resolved log
path, and the one-time action: with every Arkeology server stopped, append the old file's lines to
the failure log that a server configured with the artifact bucket they were written against
resolves (R7) — this server's resolved log when that bucket is its own, and by default
`$XDG_STATE_HOME/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` or
`~/.local/state/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` for any bucket — delete the old file,
then run `reconcile_index` from such a server. The warning repeats on every start until the file is
gone or empty. THE SYSTEM SHALL never read, merge or replay the old file itself. The release's
CHANGELOG entry states the same action and the per-bucket path shape, because a server sees only
the old file in the directory it starts from, and others may sit in other directories.

**Example**

- Given `FAILURE_LOG_PATH` unset and a three-entry `.arkeology_failures.jsonl` in the startup
  directory, when the server starts, then one WARNING names the old file, the resolved log
  `…/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` and the action, and the old file is unchanged.
- Given that file empty, or the very file `FAILURE_LOG_PATH` names, then no warning is logged.

**Why:** reading or merging the old file automatically would be a second read path, which the
project rules out (AGENTS.md `## Non-Negotiable Rules`: no fallback paths or dual-store reads). The
servers are stopped first because a hand-made append does not take the lock they append under
(R13). The old file took the entries of every server started in its directory, whatever bucket it
used, and an entry records no bucket, so the operator assigns its lines by the store the clients
started there were configured with — normally one — rather than to this server's log by default.

Source: NFR-11

### R11 — Every response that promises a failure-log entry says whether it was written

WHEN a tool returns a response after which its contract says a failure-log entry exists THE SYSTEM
SHALL include `failure_logged`: `true` when the append succeeded, `false` when it failed (R4).
Those responses are `partial_write`; a `credential_error` or `annotation_unavailable` returned after
the operation's own object write had landed, on the terms the write and archive contracts state;
and a `link_metadata` response carrying `vector_write_failed`, where one `failure_logged` covers the
whole list and is `true` only when every listed artifact's entry was appended. The bulk tools'
per-item results carry it on the same terms as the single-artifact tool they delegate to. No other
response carries the field, so its presence also tells the caller that stored state had already
changed; a success whose write recorded only a leftover-vector cleanup entry carries none. WHEN
`failure_logged` is `false` the response's message SHALL NOT claim the failure was recorded:
`reconcile_index` cannot complete that operation from the log, and no copy of the entry exists — the
ERROR line R4 writes names only the artifact and the failed step.

**Example**

- Given a vector write that fails after the object write landed, when the append succeeds, then
  `partial_write` carries `"failure_logged": true` and the log holds the entry.
- Given the same failure with the append raising `OSError`, then `partial_write` carries
  `"failure_logged": false`, its message does not say the failure was recorded, the log is
  unchanged, and an ERROR line names the artifact and the failed step but holds none of the entry.
- Given a `credential_error` raised before any object write, then the response has no
  `failure_logged` key.

Source: NFR-11; `failure_logged`, one flag for a whole `link_metadata` list, present only once stored state has changed (Operator, 2026-11-12)

### R12 — `reconcile_index` leaves other write prefixes' entries in the shared log untouched

One per-user log for each artifact bucket holds the entries of every project and write prefix the
user runs against that bucket (R7); another bucket's entries are in another file. WHEN
`reconcile_index` replays it THE SYSTEM SHALL leave every entry whose `artifact_id` does not start
with its own `write_prefix + "/"` exactly as read: not re-indexed (T21 R2), not pruned, not stamped
with a retry count, and not reported in `reconciled`, `failed` or `stuck_failures`. Such entries
are expected rather than a misconfiguration, so they are not logged as warnings. Its
`failure_log_entries_before` and `failure_log_entries_after` count only the entries under its own
`write_prefix + "/"`, so a run that resolved every entry of its own reports a
`failure_log_entries_after` of zero whatever other prefixes' entries the log still holds.

**Example**

- Given a log holding one entry under `team-a/…` and one under `team-abc/…`, when
  `reconcile_index` runs with write prefix `team-a` and resolves its own entry, then the
  `team-abc/…` entry is still in the log byte for byte, appears in no response list, and no
  warning names it, and the response reports `failure_log_entries_before` 1 and
  `failure_log_entries_after` 0.

Source: FR-17; both counts cover the own write prefix only (Operator, 2026-11-12)

### R13 — One exclusive lock serialises every append and rewrite, so servers sharing the log never interleave

WHEN several server processes on one host append to the same log, or `reconcile_index` rewrites it
while others append, THE SYSTEM SHALL hold one exclusive advisory lock on the file for each append
and for each rewrite's re-read and replace, so no line is torn, interleaved or lost and an entry
appended during a rewrite survives it. The lock coordinates processes on one host only: servers on
several hosts sharing one log file over a network filesystem is not a supported configuration, and
by default each host keeps its own per-user log for each artifact bucket.

Source: NFR-11

## 3. Rules — Bedrock throttle retry

### R8 — A Bedrock throttle is retried exactly once

When a Bedrock embed call raises a throttling error (HTTP 429 / ThrottlingException), the system waits a
short back-off (suggested: 1 second) and retries once before treating it as a partial write failure.
When the retry succeeds, the system proceeds normally — no failure log entry, no error. When the retry
also fails (any reason), the system writes the failure log entry and returns a partial-write error
response. The Bedrock retry is a single retry only — no exponential back-off loop. Throttling detection
identifies the standard AWS ThrottlingException / 429 error code; non-throttling errors are not
retried.

Rationale: Bedrock throttling is a transient error that should be retried once with back-off before
being surfaced as a hard failure.

**Example**

- Given Bedrock responds with a throttling error on the first embed call, when `write_artifact`
  processes the response, then exactly one retry is attempted after a short back-off.
- Given the retry succeeds, when `write_artifact` returns, then the artifact is written normally with no
  error and no failure log entry.
- Given the retry also fails (non-throttle error or throttle again), when `write_artifact` returns, then
  the failure log is written and a partial-write error is returned.

Source: none

## 4. Boundaries

**Always:**
- The tool receives the failure log path from `settings.failure_log_path`, resolved once at
  startup (R9).

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write a failure log entry for credential errors.
- Do not overwrite the failure log — always append.
- Do not raise from the failure log write path — log to stderr and continue.
- Do not retry non-throttling errors.
- Do not read, merge or replay a log left at the old relative default — warn only (R10). Revisit
  if operators report entries stranded in old files that neither the warning nor the CHANGELOG
  reached.
- Do not fall back to another log location when the configured one cannot be created — refuse to
  start (R9). Revisit if a supported host turns out to have no writable per-user state directory.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_failure_log.py` | Create | Written first (Red) — failure_log module |
| `src/arkeology/failure_log.py` | Create | Written after unit tests (Green) |
| `tests/unit/test_tools_write.py` | Modify | Add partial failure + retry test cases (Red) |
| `src/arkeology/tools/write.py` | Modify | Add failure logging + Bedrock retry (Green) |
| `src/arkeology/config.py` | Modify | Add `FAILURE_LOG_PATH` optional setting |
| `.gitignore` | Modify | Add `.arkeology_failures.jsonl` (and pattern for custom paths) |

**Failure log location and reporting (R4, R6, R7, R9–R13):**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/conftest.py` | Modify | B-15: every unit test runs with `FAILURE_LOG_PATH` redirected. Lands first, so no test writes to the developer's real per-user log |
| `tests/unit/test_config.py` | Modify | Red first: R7's per-bucket default and fallbacks, and an operator-set path that gains no bucket; R9's `~` expansion and relative resolution |
| `src/arkeology/config.py` | Modify | Default, naming `artifact_bucket`, and resolution of `failure_log_path`. Pure computation: constructing `Settings` creates no directory |
| `tests/unit/test_main.py` / `test_startup.py` | Modify | Red first: R9's directory creation, refusal and INFO line; R10's warning cases. *Uncertain:* whether `__main__.py` or `startup.py` owns this step |
| `src/arkeology/__main__.py` / `startup.py` | Modify | R9 and R10 at startup |
| `tests/unit/test_failure_log.py` | Modify | Red first: the append reports whether the line was written; a failed append's ERROR record names the artifact id and the failed step and holds no other entry field |
| `src/arkeology/failure_log.py` | Modify | `append_failure_entry` returns whether it wrote the line, and still never raises |
| `tests/unit/test_tools_write.py`, `test_tools_archive.py`, `test_tools_link_metadata.py` | Modify | Red first: R11's cases per tool |
| `src/arkeology/tools/write.py`, `tools/archive.py`, `tools/link_metadata.py` | Modify | Carry `failure_logged`; the "failure recorded in …" message only when it is `true` |
| `tests/unit/test_tools_reconcile.py` | Modify | Red first: R12's foreign-prefix entry, and both counts covering own-prefix entries only |
| `src/arkeology/tools/reconcile.py` | Modify | No warning per foreign-prefix entry; `failure_log_entries_before` and `failure_log_entries_after` count own-prefix entries only (R12) |
| `CHANGELOG.md` | Modify | Under the release's Changed entry: the new default path, which names the artifact bucket — `$XDG_STATE_HOME/arkeology/<ARTIFACT_BUCKET>/failures.jsonl`, else `~/.local/state/arkeology/<ARTIFACT_BUCKET>/failures.jsonl` — and R10's one-time action, appending each old file's lines to the log of the bucket they were written against |
| `SERVER-REFERENCE.md` | Modify | `FAILURE_LOG_PATH` row: the new default, `$XDG_STATE_HOME/arkeology/<ARTIFACT_BUCKET>/failures.jsonl`, else `~/.local/state/arkeology/<ARTIFACT_BUCKET>/failures.jsonl`; an operator-set path used as given, one path per artifact bucket; `~` expansion; resolution at startup |
| `.gitignore` | None | Keep `.arkeology_failures.jsonl`: it still covers old files left in a repository root |

### Contracts

The `failure_logged` and shared-log rules are stated in these contracts, amended with this
revision: `arkeology.tools.write` and `arkeology.tools.archive` (the `failure_logged`
postcondition), `arkeology.tools.link_metadata` (`failure_logged` beside `vector_write_failed`),
`s3-annotations.artifact` (the durability facts after a landed write), and
`arkeology.tools.reconcile` (other prefixes' entries left untouched, and its count postcondition
covering own-prefix entries only).

### Testing Approach

**TDD cycle A (unit — failure log module):** write `test_failure_log.py` first → fail → implement
`failure_log.py` → pass.

**TDD cycle B (unit — write tool changes):** extend `test_tools_write.py` with partial failure and retry
cases → fail → modify `tools/write.py` → pass.

**`test_failure_log.py` — unit tests (filesystem, no AWS):**

Use `tmp_path` (pytest fixture) as the log path.

Happy path:
- `append_failure_entry(path, entry_dict)` on a non-existent file → creates file; one line.
- `append_failure_entry` called twice → two lines, each valid JSON.
- Each line is a valid JSON object with all required fields.

Required fields in each entry:
- `artifact_id`, `title`, `type`, `tier`, `date`, `failure_step`, `reason`, `timestamp`.
- `timestamp` is a valid ISO-8601 string.

Resilience:
- `append_failure_entry` on a path in a non-existent directory → logs to stderr, does not raise.
- `append_failure_entry` when disk is full (simulate `OSError`) → logs to stderr, does not raise.

**`tests/unit/test_tools_write.py` — additional test cases:**

Bedrock retry:
- Bedrock raises throttle error on first call, succeeds on second → artifact written normally; no
  failure log entry; `write_artifact` returns success.
- Bedrock raises throttle error on first call, raises again on second → partial_write error returned;
  `artifact_id` in response; failure log entry written with `failure_step="bedrock_embed"`.
- Bedrock raises non-throttle error → no retry; partial_write error; failure log entry written.

Partial write on put_vector failure:
- S3 write succeeds, `put_vector` raises → partial_write error with `artifact_id`; failure log entry
  written with `failure_step="put_vector"`.

Failure log integrity:
- After a partial write failure, failure log contains exactly one entry with all required fields.
- After two partial write failures, failure log contains two entries (append behaviour).

Credential errors unchanged:
- Bedrock raises `CredentialError` → credential_error response; no failure log entry.
- `put_vector` raises `CredentialError` → credential_error response; no failure log entry.

**No integration tests for this task** — the failure log is a local tier 1 artifact and does not
interact with real AWS services. The existing integration tests for `write_artifact` (T7) provide
sufficient end-to-end coverage of the non-failure path; they run unchanged.

**TDD cycle C (unit — log location and reporting, R4, R6, R7, R9–R13):** each test file in the
amendment table under Files to Touch is written red before the implementation file listed after
it. B-15's redirect lands first, so no unit test writes to the developer's real per-user log.

- Location (R7, R9): `XDG_STATE_HOME` absolute, unset, empty and relative, each default naming the
  artifact bucket, so two settings that differ only in bucket resolve different logs; `~` expansion
  and relative resolution of an operator-set path, which gains no bucket; every missing directory
  created `0700`; startup refused, with
  the path named, when it cannot be created; the INFO line names the resolved path.
- Old default (R10): a non-empty old file in the startup directory gives one WARNING naming both
  paths and leaves the file unchanged; an empty one, or one that is the configured log, gives none.
- Reporting (R4, R6, R11): for write, archive and `link_metadata`, an append that succeeds gives
  `failure_logged: true`; an append patched to raise gives `false`, a message that does not claim a
  record, and an ERROR record naming the artifact id and the failed step, with no link, annotation
  or other entry field in it; a pre-write `credential_error`, a
  `validation_error`, a `conflict` and a success carry no key.
- Shared log (R12, R13): a foreign-prefix entry survives a reconcile run byte for byte, unreported,
  unwarned and counted in neither `failure_log_entries_before` nor `failure_log_entries_after`; two concurrent appenders leave every line whole.

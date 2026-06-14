---
status: draft # draft | ready | in-progress | done
references:
  - docs/architecture-decisions/adr-2026-05-29-stdio-transport.md
  - docs/architecture-decisions/adr-2026-05-29-tier-based-access-control.md
  - docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
  - docs/brainstorming/brainstorming-2026-06-10-mcp-transport-strategy.md
  - docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md
  - docs/specs/p4-t18-mcp-resources.md
  - docs/brainstorming/research-visual-reading-interface.md
authored:
  by: "analyst"
  date: 2026-06-14
revised:
  by: ""
  date:
techniques_used:
  - multi-agent adversarial challenge (5 analyst subagents, one idea each, each challenging the anchor)
  - inversion (publish-once vs query-live; "what would make a localhost reader fail?")
  - perspective-shift (in-session engineer vs team/org reader vs non-engineer)
  - constraint-removal (what if the MCP server lived in AWS, not on the operator machine?)
  - analogy (AWS Cognito+SSO identity model; static-site generators; AWS proxy per-call identity)
  - cross-pollination (used each subagent's idea to answer another's challenge)
assumptions_challenged:
  - "Reading happens in-session, so reusing the already-running MCP process is the right host"
  - "A localhost-only reader is sufficient — shareable links and deep-links don't matter"
  - "The reader's audience is the engineer running the MCP server"
  - "Live semantic search is needed for human reading and browsing"
  - "Bundling a SPA + mermaid.js + a JS build toolchain inside the Python MCP package is acceptable"
  - "We must build a bespoke UI rather than reuse renderers that already exist (Obsidian/GitHub/MkDocs/MCP hosts)"
  - "Rendering should happen live at read time rather than once at write/publish time"
  - "localhost-only neatly sidesteps the auth/transport question"
  - "The soft tier/visibility gate is adequate when humans read via their own broad local AWS credentials"
  - "A containerized reader should connect to cairn AS AN MCP CLIENT (the MCP tool contract is a stable decoupling boundary)"
  - "A single local container can serve as a team-wide reader by changing its bind address"
  - "Auth can stay minimal for a self-hosted reader because it is local/internal"
decisions_locked: []
decisions_pending:
  - D1: Which reader audience(s) are in scope for v1 — in-session engineer, team/org reader, or both?
  - D2: Is the chosen surface local (per-operator) or hosted in AWS (team-wide)? This depends on the MCP-in-AWS reframe.
  - D3: Is live semantic search a v1 requirement for the human UI, or is faceted + lexical search (with precomputed semantic neighbours) sufficient?
  - D4: Should cairn ship the near-free "data resources + export" baseline (Direction 3) regardless of which larger direction wins?
  - D5: For a hosted surface, how does the per-process WRITE_PREFIX/READ_PREFIXES scope model map to per-request authenticated identity (Cognito/SSO groups)?
  - D6: Does adding any HTTP surface force resolution of the open stdio-vs-HTTP transport question (transport-strategy brainstorm)?
  - D7: Should a self-hosted reader ship inside the cairn-mcp package (pulling a frontend build + image-publish + infra into a project that "owns no infra") or as a separate companion repo/product (e.g. cairn-lens)?
  - D8: Version-sync — how does the cairn version baked into a reader image stay in lockstep with the cairn version agents write with (new metadata fields / ID scheme)?
decisions_closed_not_applicable: []
---

# Visual Reading / Browsing Interface for cairn-mcp Artifacts

## Description

cairn-mcp moved artifact content to AWS S3 and made it searchable to *agents* via S3
Vectors behind an MCP server. Humans (operators) still need to **read** those artifacts —
ADRs, specs, code reviews, session summaries — and since the files no longer live on disk,
there is no user-friendly way to open and render them. This session explores how to give
humans a visual reading/browsing surface that can list/search many documents, apply
multi-facet filters (e.g. type + date), select a document, and render markdown **and**
mermaid diagrams. It deliberately considers a reframe the user invited: a future where the
MCP server (or a read-only twin of its logic) no longer runs only on the operator's machine
but is hosted in AWS.

## Session 2026-06-14

### Problem Statement

How should humans read cairn artifacts now that content lives in S3 with no local file to
open? The desired capabilities: list/search multiple documents, multi-facet listing/search
(document type & date, plus team/project/tier/tags), select a specific document, and render
markdown + mermaid. The method for this session: the lead analyst proposed an **anchor
idea** (a local companion web reader) and five analyst subagents each proposed one
alternative idea **and** adversarially challenged the anchor's hidden assumptions. The lead
then answered every challenge (cross-pollinating across ideas) and selected the most
promising directions.

### Known Constraints

| Constraint | Source |
|---|---|
| cairn-mcp runs locally today, one process per project, stdio transport, scoped by `WRITE_PREFIX` | stdio-transport ADR |
| Artifact content lives in S3; embeddings + metadata in S3 Vectors; embeddings via Bedrock Titan v2 | AGENTS.md |
| Rich metadata already exists: type, tier (2/3), visibility (shared/hidden), team/project, date-anchored IDs, feature_tags, commit_refs | artifact model |
| The tier+visibility cross-scope gate is a **soft** server-side control; IAM is the hard boundary | tier-based-access-control ADR |
| HTTP transport is a one-line FastMCP change but currently undecided | transport-strategy brainstorm (in-progress) |
| MCP resources are registered but currently **schema-only** (no AWS calls) | T18 spec + resources.py |
| `list_artifacts` already performs server-side faceted filtering (type/tier/team/project/tags/commit_refs/status) behind the scope gate | list tool |
| The package is already a Python CLI (`uvx cairn-mcp`); CI is pytest/ruff/mypy — no JS toolchain today | AGENTS.md |
| Deployment-agnostic stance today: no infra owned by the project | AGENTS.md |

### Ideas Explored

**Anchor (lead) — Local companion web reader.**
A `--web` mode on the already-running cairn-mcp process. The same process reuses its
S3/S3-Vectors/Bedrock clients and scope/tier gates and serves a read-only SPA on
`localhost:PORT`. Lists artifacts, multi-facet filter, full-text + semantic search, select a
doc, fetch markdown from S3, render markdown + mermaid client-side. No AWS deploy, binds to
localhost, reuses local AWS credentials. *Outcome of the session: dominated on every axis —
see Challenge Synthesis. Retained only as a possible component of the in-session engineer
experience, not as the primary answer.*

**Idea 1 — Serverless AWS knowledge portal ("Cairn Atlas").**
Relocate cairn's **read path** into AWS as a durable, multi-user portal at a stable team URL.
Static React/Next SPA on S3 + CloudFront (OAC); read API on API Gateway + Lambda packaging a
read-only subset of cairn's existing Python logic (`list`/`read`/`search`/`synthesise`/
`freshness`), reusing the Protocol-based, dependency-injected clients, the `filter.py`
evaluator, and the scope gate unchanged. Semantic + multi-facet search served from the *same*
S3 Vectors index and Bedrock model agents already use — single source of truth, zero sync.
Auth via Cognito federated to corporate SSO (IAM Identity Center / Okta / Entra); a Lambda
authorizer maps the user's SSO group claims to an "own-scope set" and applies the existing
foreign-scope gate (tier-3 + shared only). CDK stack; read-only IAM role is the only S3
principal. The local MCP server is unchanged for agents.
*Unique unlocks: shareable deep-links, always-on, zero per-operator setup, cross-team
discovery, mobile, centralized audit, and it upgrades the soft gate into an enforced one
(humans never hold AWS creds).*
*Costs: real build + ops (SSO federation, domain/cert, a read-only twin to keep in lockstep),
Lambda cold-start + Bedrock embed latency floor, a public (even if authenticated) attack
surface, drift risk between the twin and the MCP server.*

**Idea 2 — IDE-native reader (VS Code extension + `cairn open` CLI).**
Render artifacts inside the editor engineers already live in. A "Cairn" activity-bar view:
filterable tree (type/date/tags/tier) + semantic search box; selecting an artifact opens a
webview rendering markdown + mermaid. `commit_refs` become clickable jump-to-code links — a
structural advantage no browser tab has. Talks to cairn via the local MCP server / MCP
resources (preferred: thin presentation layer, reuses the gate), with spawn-on-demand
fallback so reading never depends on an active agent session. A `cairn open <id>` CLI covers
non-VS-Code/terminal users.
*Unique unlocks: zero context switch, code↔artifact deep-linking, reuse of editor creds,
distribution via Marketplace/Open VSX.*
*Costs: editor lock-in (VS Code beachhead; JetBrains/Neovim/Emacs unserved), webview still
ships markdown+mermaid assets, non-engineers unserved, marketplace publishing overhead.*

**Idea 3 — "Reuse, don't build" (MCP data resources + on-demand export).**
Challenge the premise of building a UI at all.
- *Surface A — data resources (near-zero build):* upgrade the schema-only resources to
  data resources (`cairn://artifact/{id}`, `cairn://artifacts`, `cairn://artifacts/type/{t}`)
  backed by the existing `read_artifact`/`list_artifacts` code paths. Rendered for free by
  MCP Inspector, Claude Desktop, IDE MCP panels. ~tens of lines; reuses the gate verbatim.
  Weakness: most MCP host UIs don't execute mermaid; faceting limited to host capability.
- *Surface B — `cairn export`/`publish` (re-materialize files on demand):* a human-facing CLI
  that walks the scope-gated listing, fetches content, and writes a folder of `.md`
  (front-matter preserved) or a static-site bundle. Open with tools that already render
  mermaid natively: **GitHub** (native since 2022), **Obsidian** (native; tags/backlinks/
  search for free; the highest-leverage target), **MkDocs Material** (pure-Python, built-in
  lunr search + mermaid via one config line), or Docusaurus.
- *Surface C — presigned S3 + thin shim:* `cairn share <id>` returns a time-boxed presigned
  URL — an escape hatch, not a product.
*Unique unlocks: minimal code, mermaid + faceted search + full-text "for free" from mature
renderers, stack-fit (MkDocs Material is pure Python).*
*Costs: snapshot (no live freshness), re-materializes files (partially undoes "content lives
in S3"), semantic search lost (lexical only), gate applied once at export then ungoverned.*

**Idea 4 — `cairn browse` terminal-native reader (no browser, no server).**
A read-mode subcommand set in the same Python package, reusing clients + gate in-process:
`cairn browse` (interactive Textual TUI: filterable list pane + rendered-markdown pane),
`cairn read <id>`, `cairn search <q> [--json]`, `cairn ls`. Markdown via Rich. The honest
mermaid story is graceful degradation: (1) show syntax-highlighted source; (2) on-demand
render-and-open a PNG/SVG/HTML in the OS viewer; (3) inline pixels on sixel/kitty/iTerm2
terminals; (4) `cairn export <id> --html` as the pressure-relief valve.
*Unique unlocks: zero deploy/auth/port/CORS, headless/SSH/CI native, single Python package
(no JS toolchain, no mermaid.js to track), one code path for the gate, pipe-composable.*
*Costs: mermaid never renders as live pixels in a bare terminal, wide tables/diagrams clip,
no shareable URL, nothing for non-terminal humans.*

**Idea 5 — Publish-on-write static knowledge site (S3 + CloudFront, zero read-time backend).**
Invert the anchor's "live query backend" assumption: artifact memory is a slowly-changing
corpus read many times, so do the expensive work once at write time. On `write_artifact`
(and a backfill via reconcile/migrate), a publisher renders markdown→HTML and **pre-renders
every mermaid block to inline SVG server-side**, writes rendered HTML to a `SITE_BUCKET`,
updates per-facet browse manifests (by type/date/team/tags), incrementally rebuilds a
client-side search index (Pagefind preferred; Lunr simpler), and invalidates CloudFront.
Recommended placement: **S3-event-triggered Lambda** (keeps the local write path light and
decoupled), with a batch `publish_site` pass for backfill/disaster-recovery/template changes.
Access control becomes **publish-time partitioning**: shared artifacts → team distribution;
hidden/scope-private → a separate distribution/prefix reachable only by the owning scope's
principals (separate CloudFront+OAC, Cognito group, or scoped signed-URL issuer). Visibility
changes require an explicit un-publish/move + invalidation.
*Unique unlocks: shareable stable URLs; mermaid rendered once (no client JS, no version
drift, failures caught in one place, diagrams become selectable/searchable/accessible SVG
text); zero read-time infra; survives the MCP server being offline and even Bedrock/Vectors
being degraded; one canonical render for the whole team; pennies cost (compute only at write
time).*
*Costs: semantic/vector search lost (client-side index is lexical) — mitigated by
precomputing per-doc "related artifacts" via one Bedrock call at publish time; staleness /
rebuild-trigger management; new infra to own (contradicts the current no-infra stance).*

### Clusters

- **Cluster 1 — In-session engineer surfaces (local, reuse the running context):** Anchor
  (local web reader), Idea 4 (TUI), parts of Idea 2 (IDE extension). Serve the engineer who
  already has a process/creds; cannot serve non-engineers or produce shareable links.
- **Cluster 2 — Team/org reader surfaces (hosted in AWS, durable & shareable):** Idea 1
  (serverless portal), Idea 5 (publish-on-write static site). Require the MCP-in-AWS reframe;
  deliver shareable URLs, non-engineer access, single team-wide view, enforced gate.
- **Cluster 3 — Build-as-little-as-possible (reuse existing renderers/surfaces):** Idea 3
  (data resources + export). Near-free; validates demand; leans on mature renderers.

### Selected Directions

The challenges established two distinct audiences — the **in-session engineer** and the
**team/org reader** (including non-engineers) — and that the anchor served neither well. The
three most promising directions span low→high investment and can be staged.

*Ranking note (lead analyst, independent re-rank confirmed 2026-06-14):* the order below is
deliberate. Direction 1 (static site) ranks first because it satisfies **every** stated
capability — list/search, faceted by type + date, select, render markdown **and** mermaid,
and shareable URLs — at the lowest ongoing cost while serving all reader audiences. Direction
2 (portal) ranks second because its principal addition over the static site is *live*
semantic search, judged a power-user nicety for human reading rather than a core need (see
D3). Direction 3 (lean baseline) ranks third as an *end-state* but is the recommended *first
increment* (cheapest, demand-validating). The IDE-native reader (Idea 2) is retained as an
explicit honourable mention below — kept in this document at the operator's request as a
candidate for the in-session-engineer surface and a likely future companion to Direction 1.

#### Direction 1 (recommended primary) — Publish-on-write static knowledge site (Idea 5)

**Why most promising:** best ratio of delivered value to ongoing cost for the audience the
request actually centers on (people who need to *read* shared artifacts). It directly
satisfies every stated capability — list/search, multi-facet browse (type & date), select,
render markdown **and** mermaid — while solving the anchor's fatal gaps: shareable stable
URLs, non-engineer access, no "is the server running?" dependency, and one canonical render.
Mermaid pre-rendered to SVG eliminates the "JS bundle in a Python wheel" maintenance/CVE
burden entirely. Cost is pennies (compute only at write time).
**What it requires:** a `SITE_BUCKET` + CloudFront (OAC), a publisher (S3-event Lambda with
server-side mermaid rendering) + a batch backfill pass, client-side search index generation,
publish-time access partitioning mapped from tier/visibility, and CDK to own it. This is the
"MCP-read-path-in-AWS" reframe in its lightest form.
**Key trade-off accepted:** semantic search is replaced by faceted + lexical search, with
precomputed semantic-neighbour links baked in at publish (recovers most of the value at zero
read-time cost). Staleness/rebuild triggers (write, delete/archive, visibility change,
template change) must be handled explicitly.

#### Direction 2 — Serverless AWS knowledge portal (Idea 1)

**Why promising:** the richest *visual app* and the natural premium evolution of Direction 1
— it can read the same S3/S3-Vectors backend. Adds what the static site sacrifices: **live
semantic search** in the UI and a centrally **enforced** access gate (users hold no AWS
creds; one read-only Lambda role; per-identity gate). Best fit if cross-team governance,
live concept-search, or always-fresh reads prove to be hard requirements.
**What it requires:** the static-site infra *plus* a read API (API Gateway + Lambda over a
read-only twin of cairn's logic), Cognito↔SSO federation, a per-request identity→scope
mapping (D5), domain/cert, and lockstep maintenance of the read-only twin.
**Key trade-off:** materially higher build + ops cost and a new authenticated internet
surface, for benefits (live semantic search) that may be a power-user nicety rather than a
core human-reading need (D3).

#### Direction 3 — Lean reuse baseline: MCP data resources + on-demand export (Idea 3), with TUI companion (Idea 4)

**Why promising:** near-zero build, ships now, and **de-risks the larger bets** by validating
how often and how humans actually read before investing in hosted infra. Surface A (data
resources backed by existing read/list code) makes the browse→select→read loop work in MCP
Inspector / Claude Desktop today. Surface B (`cairn export`) hands artifacts to renderers
that already do markdown + mermaid + faceted search natively (Obsidian / GitHub / MkDocs
Material). The Idea 4 TUI (`cairn browse`/`read`/`search`) serves the terminal-first,
SSH/headless engineer with no server, port, or auth surface.
**What it requires:** upgrade resources from schema-only to data resources (~tens of lines);
a `cairn export` CLI walking the scope-gated listing; optionally a Rich/Textual TUI. All pure
Python, reusing the in-process gate — no JS toolchain, no new infra.
**Key trade-off:** snapshot freshness (export) and lexical-only search; re-materializes files
on disk on demand; not a single hosted shareable surface on its own.

**Staging:** Direction 3 first (cheap, immediate, demand-validating) → Direction 1 (the
durable shareable team surface) → Direction 2 only if live semantic search / central
governance prove necessary. Directions 1 and 2 share storage and can coexist; Direction 5's
static site can be the default reading surface with the portal's live search as a power-user
overlay.

**Considered but not selected as primary:**
- *Anchor (local web reader):* dominated — heavier than the TUI for the engineer, unable to
  serve the team reader. Retained at most as an optional local view; superseded by Idea 4 for
  the in-session case.
- *IDE-native reader (Idea 2) — honourable mention, explicitly retained for further study:*
  the strongest answer for the *in-session engineer* specifically, and the only option with a
  structural capability none of the selected directions have — turning `commit_refs` (and
  file paths) inside an artifact into **clickable jump-to-code** actions, and conversely
  enabling a future "which ADRs touch this file?" lens because the editor knows the open file.
  Preferred wiring is a thin presentation layer over the local MCP server / MCP resources
  (reusing the scope gate, no duplicated logic), with spawn-on-demand fallback so reading
  never depends on an active agent session; a `cairn open <id>` CLI covers non-VS-Code users.
  Why it is not the primary answer: editor lock-in (VS Code beachhead; JetBrains/Neovim/Emacs
  unserved without separate plugins), it still ships markdown+mermaid assets (inside a `.vsix`
  rather than a wheel), it does nothing for non-engineers, and it produces no shareable URL.
  **Best role:** a companion to Direction 1/2 once a hosted reading surface exists — giving
  engineers in-editor reading + code-linking while the hosted site serves everyone else.
  Worth a dedicated follow-up brainstorm if the in-session-engineer audience (D1) is
  prioritised.

### Challenge Synthesis (assumptions stress-tested, with the lead's answers)

The subagents posed ~50 questions; they reduce to eight load-bearing assumptions in the
anchor. Each was answered using other ideas in the set (cross-pollination).

1. **"localhost can produce no shareable/deep-link."** Conceded — the anchor's biggest
   structural flaw. Solved by Directions 1 & 5 (stable CloudFront URLs / signed URLs).
2. **"The reader is the engineer running the server."** Conceded — excludes PMs, architects,
   leadership, other teams (no process, no AWS creds). Only a hosted surface reaches them.
   Reframes the problem into two audiences.
3. **"Per-process scope is the right unit."** Conceded — `WRITE_PREFIX`+`READ_PREFIXES` gives
   a per-project keyhole; a team view requires multi-scope, which is most of the way to a
   hosted portal. Identity-derived scope (Idea 1) is the clean answer.
4. **"Reading can depend on a live agent session."** Conceded — Idea 2 spawn-on-demand,
   Idea 4 CLI, and hosted Directions all decouple reading from an agent runtime.
5. **"Bundling a SPA + mermaid.js into the Python wheel is acceptable."** Rejected — Idea 5's
   publish-time SVG (zero client JS, no drift, one logged failure point) and Idea 3's reuse of
   self-patching renderers both avoid the maintenance/CVE burden. Do not embed a bespoke SPA
   in the Python package.
6. **"We must build a bespoke UI."** Rejected as the first move — Idea 3 Surface A is nearly
   free and should likely exist regardless, validating demand before any SPA is built.
7. **"Local creds + in-process gate are fine."** Partially defended (in-process reuse passes
   the same gate; grants nothing beyond existing IAM) but a hosted portal (Idea 1) *upgrades*
   the soft gate into an enforced one — strictly better for cross-team governance.
8. **"Live semantic search is needed for human reading."** Rejected as a strong requirement —
   humans mostly navigate by type/date/team/tag/title; faceted + lexical (plus precomputed
   semantic neighbours) covers most needs, making Idea 5's sacrifice acceptable and weakening
   the anchor's main differentiator.

Bonus reframes surfaced: render-once-vs-live (Idea 5), the HTTP-transport slippery slope
("if you serve HTTP at all, why stop at localhost?" → favours Direction 1/2 over the anchor),
and code↔artifact deep-linking as a unique IDE-native advantage (Idea 2).

### Open Questions

1. **Audience scope for v1 (D1):** in-session engineer, team/org reader, or both? This
   single decision selects the cluster.
2. **Local vs hosted (D2):** does the team accept the MCP-in-AWS reframe and the
   accompanying infra ownership (contradicting the current deployment-agnostic stance)?
3. **Is live semantic search a v1 requirement (D3)** or is faceted + lexical + precomputed
   neighbours sufficient for human reading? (Selects Direction 5 vs Direction 1.)
4. **Ship the lean baseline regardless? (D4)** Data resources + export are cheap and
   demand-validating — adopt independently of the larger direction?
5. **Identity→scope mapping for a hosted gate (D5):** how do SSO group claims map onto the
   existing tier/visibility model, and how is "own scope" derived per request?
6. **Transport coupling (D6):** does adding any HTTP surface force resolution of the open
   stdio-vs-HTTP transport question? Genuinely unresolved pending the transport brainstorm.
7. **Read frequency / usage evidence:** how often do humans actually read artifacts, and do
   artifacts contain enough wide diagrams to justify rich rendering over a TUI? No data yet.

## Session 2026-06-14 — Follow-up: self-hosted single-container reader (operator-requested)

### Problem Statement

The operator asked whether a small, locally-run container packaging a web frontend (SPA) +
a FastAPI/Python backend-for-frontend (BFF) that talks to cairn is a viable reading surface,
and to brainstorm it in the same adversarial-challenge format. A dedicated analyst subagent
(grounded in `server.py` and `resources.py`) fleshed it out and challenged the lead's
assumptions; the lead answered. This refines the deployment spectrum named in the first
session (in-process localhost ↔ hosted AWS) by filling the **self-hosted middle**.

### Idea 6 — "Cairn Lens": single self-hosted Docker image (SPA + FastAPI BFF)

A single OCI image runs a static-served SPA (markdown + mermaid rendering, faceted
list/search/read UI) and a FastAPI BFF behind one port. The operator runs `docker compose up`
and opens `localhost:PORT`. The BFF is the only component touching cairn's data plane; the
browser never sees AWS. Runs against the operator's local AWS credentials (mounted), with no
AWS deployment pipeline. Intended as the **fast path to a working visual reader** that is
portable to a small shared internal host or ECS/Fargate later.

### Wiring options (how the BFF reaches cairn's data) — and the verdict

- **Option A — BFF spawns cairn-mcp as a stdio subprocess and acts as MCP client.** Keeps
  stdio (no transport decision forced) but the BFF inherits MCP session + subprocess
  lifecycle management (single session per process → serialize or pool subprocesses) that
  has nothing to do with serving a GUI.
- **Option B — cairn-mcp runs over Streamable HTTP as a second process/container; BFF
  connects by URL.** The "clean decoupling" story, but it *forces the currently-undecided
  HTTP transport into a hard dependency of the human UI*, adds an authenticated network
  listener, and means two containers + a private network — no longer "a single small
  container."
- **Option C — BFF imports cairn's read logic in-process** (S3/Vectors/Bedrock clients +
  the `_inner` read/list/search functions + the metadata filter, wired as `__main__.py`
  already does). No JSON-RPC hop, no transport decision, no LLM-shaped envelope; the BFF
  shapes its own paginated/faceted/sorted human API.

**Verdict (lead): Option C.** cairn's MCP tool contract is *not* a more stable boundary than
its Python modules — same repo, same release, same team, they change together — so
connecting "as an MCP client" buys ~nothing and costs either fragile subprocess management
(A) or forcing HTTP transport (B). **Consequently this idea is explicitly NOT "a web
interface that pulls from an MCP server" — it is a reader that reuses cairn's read logic as a
library, packaged in Docker.**

A dedicated MCP-UI prior-art scan (see the *Addendum* in `research-visual-reading-interface.md`)
**confirms Option C as an informed choice**: no mature human "MCP resource browser" product
exists (only dev/debug tools — MCP Inspector, mcp-explorer, a VS Code extension — mostly
JSON-first, no mermaid); the dominant MCP→web bridge (mcpo) exposes *tools, not resources*; and
Anthropic's own guidance steers away from direct MCP/tool consumption (LLM-shaped I/O) toward
code APIs. The one nuance: *if* MCP coupling were ever wanted, couple to MCP **resources**
(spec-designed for human display: `text/markdown` mimeType, `audience:["user"]`) via the FastMCP
client — never the LLM-shaped tool layer.

### Lead's answers to the subagent's challenges (synthesized)

1. **MCP-client coupling (challenges 1, 2, 8, 10):** dropped. Option C is correct; the
   container's honest delta over a `cairn-mcp --web` in-process mode is **packaging +
   frontend-dependency isolation + portability to a shared host/ECS** — not a different data
   architecture. Assumptions 1 and 2 are retracted.
2. **MCP-as-human-API mismatch (challenges 3, 4):** disappears under Option C — the BFF calls
   the underlying clients + filter and builds its own pagination/facet-counts/sort, so the
   **agent tool schemas are NOT polluted** with UI-only parameters. Fetch-and-count in the
   BFF is fine at cairn's realistic per-scope corpus sizes (hundreds–low thousands).
3. **Scope / auth / creds (challenges 5, 6, 7):** conceded. One container = one `WRITE_PREFIX`
   scope + one credential identity = one project's view (own + shared tier-3). It does **not**
   become a team reader by changing the bind address; that needs an authn/authz/per-user-scope
   identity model the gate doesn't express — exactly where Direction 2 (serverless portal,
   Cognito/SSO→scope) takes over. "Minimal auth" is honest only at loopback; a shared
   multi-project host reintroduces the auth/CORS/multi-tenant problem the anchor avoided.
4. **Single image + scope creep (challenges 9, 11, 12):** a single image (SPA + FastAPI) is
   fine; the win is that the **agents' `cairn-mcp` wheel stays lean** (frontend deps live in
   the image, patched by rebuild), not "no JS to maintain." Two real risks: **version sync**
   (D8 — pin the cairn dependency, read defensively, surface a version indicator) and **scope
   creep** (D7 — shipping a frontend build + image-publish + infra into a project that "owns
   no infra" argues for a **separate companion repo**, e.g. `cairn-lens`).

### Where it sits — refined deployment spectrum

```
in-process @ localhost   ──►   self-hosted Docker          ──►   serverless in AWS
  (anchor, --web mode)         (Idea 6, single-operator)         (Direction 2 portal)
```

Idea 6 is the **self-hosted middle**: lower ceremony than the portal (no AWS deploy, runs
offline against existing creds), more portable/isolated than the in-process anchor. It is a
credible **first hosted-ish increment** — but it is honestly a *single-scope* reader, not the
team/org surface. As a selected direction it slots beside Direction 3 (lean baseline) as a
pragmatic build target; if/when many humans across teams need access, it is superseded by
Direction 2 (portal), not extended into it.

### Open Questions (added)

- **D7** — package home: inside cairn-mcp vs a separate `cairn-lens` companion repo.
- **D8** — version-sync between the cairn baked into the image and the cairn agents write with.
- Does Idea 6 (Option C) make Direction 1 (static publish-on-write site) redundant for the
  single-operator case, or are they complementary (live reader for the operator; static site
  for sharing/non-engineers)?

> Internet research into comparable self-hosted/containerized knowledge-base readers (Onyx,
> Khoj, AnythingLLM, AWS Bedrock KB sample UIs, ADR/doc viewers, mermaid rendering norms) is
> compiled separately in `research-visual-reading-interface.md`.

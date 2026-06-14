---
status: complete
references:
  - docs/brainstorming/brainstorming-2026-06-14-visual-reading-interface.md
authored:
  by: "analyst"
  date: "2026-06-14"
revised:
  by: ""
  date: ""
techniques_used:
  - market scan (directly-comparable vs adjacent matches)
  - build-vs-adopt comparison against off-the-shelf tools
  - gap analysis (where the concept sits relative to existing camps)
assumptions_challenged:
  - "A self-hosted Docker reader over S3 + S3 Vectors + Bedrock for human reading is novel / has no close prior art"
  - "The mainstream self-hosted RAG stack is a document reader (it is overwhelmingly chat/Q&A-first)"
  - "AWS reference architectures for knowledge bases are containerised (they are uniformly serverless and chat-oriented)"
  - "Mermaid and faceted search must be custom-built (mature renderers exist; faceted browse is the real gap)"
  - "There is a mature, reusable human web UI for MCP servers we could adopt instead of building (there is not — only dev/debug tools)"
  - "If we couple a web UI to MCP, coupling to the tool layer is fine (it is LLM-shaped; couple to resources, or better, decouple)"
---

# Research — Visual Reading / Browsing Interface for cairn-mcp Artifacts

## Description

Research notes compiled 2026-06-14 to support the visual-reading-interface brainstorming
session (`brainstorming-2026-06-14-visual-reading-interface.md`). Surveys existing projects,
products, and reference architectures comparable to a **self-hosted (Docker) web app for
humans to read and browse a markdown corpus** (ADRs, specs, code reviews, design docs): an SPA
frontend rendering markdown + mermaid, a FastAPI/Python backend, reading content from AWS S3,
with vector embeddings in **AWS S3 Vectors** and semantic search via **Amazon Bedrock Titan**,
plus multi-facet filtering (type, date, tags).

**Scope note:** the primary scan (below) deliberately **excluded** MCP / Model Context
Protocol per operator direction — no "MCP UI", "GUI for MCP servers", or
"web-interface-over-an-MCP-server" angle. A **complementary MCP-UI prior-art scan was added
later** as a dedicated section at the end of this document (see *"Addendum — MCP-UI Prior
Art"*), at the operator's request, to record the library-vs-MCP-client decision as *informed*
rather than merely out-of-scope.

---

## Problem Summary

The market splits cleanly into **two camps**, and the cairn reading concept sits in the
**unoccupied middle**:

1. **Self-hosted RAG apps** have the semantic-search backend (FastAPI + vector store +
   embeddings) but are **chat / Q&A interfaces**, not document readers — they do not render
   mermaid or offer faceted document browsing.
2. **Doc / ADR portals** (Material for MkDocs, Log4brains, adr-viewer, wikis) are **human
   readers with markdown/mermaid and tags**, but use **keyword (not semantic) search**, have
   no S3 / S3 Vectors / Bedrock backend, and are mostly build-time static generators.

**No maintained product matches all dimensions** — (reader-not-chat) + (semantic search) +
(mermaid) + (S3 Vectors/Bedrock) + (self-hosted Docker) + (multi-facet filtering). The closest
individual matches each hit only a subset. The strongest off-the-shelf "build vs. adopt"
challenger is **Material for MkDocs**; cairn's differentiators over it are semantic search,
true multi-facet filtering, an S3-backed dynamically-growing corpus, and no static rebuild on
every change.

| Camp | Has reader UI + mermaid | Has semantic search | S3 Vectors/Bedrock | Self-hosted Docker | Multi-facet filter |
|---|---|---|---|---|---|
| Self-hosted RAG (Onyx, Khoj, Open WebUI…) | ✗ (chat) | ✓ | mostly ✗ | ✓ | ✗ |
| Doc/ADR portals (MkDocs-Material, Log4brains…) | ✓ | ✗ (keyword) | ✗ | ✓ (static) | partial (tags) |
| AWS RAG samples | ✗ (chat) | ✓ | rare | ✗ (serverless) | ✗ |
| **cairn reading concept** | **✓** | **✓** | **✓** | **✓** | **✓ (the gap)** |

---

## Source Tracking

### Closest matches (directly comparable, by subset)

### Source 1 — S3 Vectors Fashion Products sample (aws-samples)
- **URL:** https://github.com/aws-samples/sample-s3-vectors-fashion-products
- **Summary:** Semantic search over ~44k product images; 1024-dim embeddings via Bedrock Titan
  multimodal stored in an **S3 Vectors** cosine index with metadata; served by a **Streamlit**
  web UI with a **Dockerfile** (local / ECS / EKS).
- **Relevance:** The only sample found combining cairn's exact backbone — S3 Vectors + Bedrock
  embeddings + a containerised browser UI. **Difference:** single search box over
  product/image data, not a browsable markdown corpus with mermaid; Streamlit, not SPA+FastAPI.

### Source 2 — Log4brains
- **URL:** https://github.com/thomvaill/log4brains
- **Summary:** Purpose-built docs-as-code knowledge base **for ADRs**; builds a publishable,
  searchable static site from a flat folder of markdown in git. Official Docker image.
- **Relevance:** Closest *purpose* match (ADR portal, human reader, search, Docker).
  **Difference:** no semantic search (client-side text only), no S3/vector/Bedrock backend,
  **weak mermaid support**; maintained but slow (v1.1.0, Dec 2024).

### Source 3 — Material for MkDocs
- **URL:** https://squidfunk.github.io/mkdocs-material/
- **Summary:** Reads a folder of markdown; first-class **tags** with a tags index, built-in
  **client-side Lunr search**, **mermaid via `pymdownx.superfences`**, official Docker image.
- **Relevance:** The strongest off-the-shelf option and the main "build vs. adopt" question.
  **Difference:** build-time static generator (rebuild on every change), **keyword search only**
  (no embeddings), single-dimension tags rather than true multi-facet filtering, no S3/Bedrock.

### Source 4 — rag-web-ui
- **URL:** https://github.com/rag-web-ui/rag-web-ui
- **Summary:** Closest *architectural shape* — Next.js SPA + async **FastAPI** backend + vector
  store (ChromaDB/Qdrant) + MinIO object storage, via Docker Compose.
- **Relevance:** Validates the SPA + FastAPI + Docker shape. **Difference:** a chat/Q&A app with
  a document-management dashboard, not a reader; self-described "not ready for production"; no
  S3 Vectors/Bedrock; mermaid unconfirmed.

### Source 5 — Self-hosted RAG / knowledge-base apps (Category 1, chat-first)
Almost the entire mainstream category is **chat/Q&A-first**; faceted type/date/tag filtering is
essentially absent.
- **Onyx** (ex-Danswer) — https://github.com/onyx-dot-app/onyx — most mature (30k+ stars,
  active 2026); FastAPI backend, Docker/K8s, Vespa hybrid vector+keyword. Enterprise chat, heavy.
- **Khoj** — https://github.com/khoj-ai/khoj — personal "second brain"; FastAPI, Docker,
  pgvector; ingests markdown; chat/search-first, not browseable.
- **Open WebUI** — https://github.com/open-webui/open-webui — most popular (142k+ stars);
  FastAPI + Svelte, Docker; supports **9 vector stores including an `S3Vector` option** (only
  researched project referencing S3-backed vectors); rich markdown+LaTeX rendering. Still a chat UI.
- **AnythingLLM** — https://github.com/Mintplex-Labs/anything-llm — polished (61k+ stars),
  Docker; **Node/Express backend (off-stack)**, chat-first.
- **RAGFlow** — https://github.com/infiniflow/ragflow — strong document chunking/visualisation,
  Python, Docker, Elasticsearch default; KB management + Q&A, not reading.
- **Quivr** — https://github.com/QuivrHQ/quivr — pivoted to a RAG *library*; no deployable
  reader; stale.
- **Verba (Weaviate)** — https://github.com/weaviate/Verba — same FastAPI+SPA+Docker shape but
  **archived/read-only (June 2026)** — do not adopt.
- **Cognita (TrueFoundry)** — https://github.com/truefoundry/cognita — FastAPI + React +
  Postgres metadata, Docker; **archived (March 2026)**, stale.
- **create-llama (LlamaIndex)** — https://github.com/run-llama/create-llama — scaffolds a
  FastAPI+SPA chat starter; stale.
- **Haystack (deepset)** — https://github.com/deepset-ai/haystack — orchestration library, no UI.
- Niche markdown-corpus search tools confirming the gap: **Atomic**
  (https://github.com/kenforthewin/atomic), **QMD** (https://github.com/tobi/qmd).

### Source 6 — AWS reference patterns (Category 2, serverless + chat)
Everything AWS publishes here is **chat/Q&A-oriented and fully serverless** (Lambda / API
Gateway / CDK) — not a containerised reader.
- **Amazon S3 Vectors** — preview (Jul 15 2025)
  https://aws.amazon.com/blogs/aws/introducing-amazon-s3-vectors-first-cloud-storage-with-native-vector-support-at-scale/
  ; **GA Dec 2 2025** (2B vectors/index, 14 regions). Latency-optimised for "subsecond" — a good
  fit for a human reader, not ultra-high-QPS. Most existing RAG samples predate it and still use
  OpenSearch Serverless.
- **Generative AI Application Builder on AWS** —
  https://github.com/aws-solutions/generative-ai-application-builder-on-aws — React UIs on S3 +
  Lambda/API Gateway/DynamoDB + Bedrock + Kendra/Bedrock KB; chatbot-oriented, fully serverless,
  no S3 Vectors.
- **aws-genai-llm-chatbot** — https://github.com/aws-samples/aws-genai-llm-chatbot — flagship
  RAG sample; React UI, OpenSearch/Aurora pgvector/Kendra, CDK serverless; conversational.
- **amazon-bedrock-rag** — https://github.com/aws-samples/amazon-bedrock-rag — React + Lambda,
  OpenSearch Serverless, Titan embeddings, ingests from S3; Q&A chatbot.
- **Amazon Bedrock Knowledge Bases samples** —
  https://github.com/aws-samples/amazon-bedrock-samples — metadata-filter and RAG examples;
  API/notebook-oriented, no reader UI. S3 Vectors is now a supported KB backend (a managed
  alternative to hand-rolling the vector layer).
- **awslabs/generative-ai-cdk-constructs** —
  https://github.com/awslabs/generative-ai-cdk-constructs — reusable CDK constructs that
  **already include an S3 Vectors construct** (signals maturing AWS support); serverless, no UI.
- **S3 Vectors getting-started notebook** —
  https://aws-samples.github.io/sample-ai-possibilities/snippets/s3-vector-search — validates the
  write/search loop; no UI.

### Source 7 — ADR / design-doc viewers and documentation portals (Category 3)
Two architectures: **static-site generators** (flat markdown folder + client-side search; fit
the "browse an existing corpus" model) and **DB-backed wikis** (server-side search; own/author
content).
- **adr-viewer** — https://github.com/mrwilson/adr-viewer — Python; renders an ADR markdown
  folder to a browsable page; **renders mermaid**; but **no search, no tag/facet filtering**.
- **adr-tools** — https://github.com/npryce/adr-tools — authoring CLI only (defines the ADR
  convention cairn artifacts likely follow); dormant since 2018.
- **MADR** — https://github.com/adr/madr — a format/template standard, not a tool.
- **Docusaurus** — https://docusaurus.io/ — front-matter tags + tag index; mermaid via
  `@docusaurus/theme-mermaid`; search via Algolia DocSearch or Lunr plugins; heavier (React/MDX/Node).
- **Backstage TechDocs** — https://backstage.io/docs/features/techdocs/ — MkDocs-based;
  server-side search; mermaid via plugins; requires adopting all of Backstage (overkill).
- **Outline** — https://github.com/outline/outline — polished team KB, **native mermaid**,
  server-side Postgres full-text search, Docker; but a **DB-of-record authoring app**, not a
  read-only viewer over a markdown folder.
- **BookStack** — https://github.com/BookStackApp/BookStack — tags + server-side search, Docker;
  diagrams via drawio (mermaid not native); DB-backed.
- **Wiki.js** — https://github.com/requarks/wiki — tags + pluggable search + diagram rendering;
  Docker; notably supports **git/disk markdown sync** while DB-backed at runtime; closest wiki.
- **Obsidian Publish** — https://obsidian.md/publish — **not self-hosted** (proprietary hosted);
  excluded by the Docker requirement.
- **Logseq / AppFlowy / TriliumNext** — desktop-first or DB-backed PKM apps; deployment/data-model
  mismatch.

### Source 8 — Mermaid rendering & search-index norms (Category 4)
Mermaid rendering is always **mermaid.js client-side**, triggered by ` ```mermaid ` fenced blocks:

| Tool | Native or Plugin |
|---|---|
| GitHub (since Feb 2022), GitLab, Obsidian, Notion | Native |
| Material for MkDocs | Plugin (`pymdownx.superfences` custom fence) |
| Docusaurus | Plugin (`@docusaurus/theme-mermaid`) |
| VS Code preview | Plugin (extension required) |

- Mermaid: https://mermaid.js.org/intro/ , https://github.com/mermaid-js/mermaid ,
  https://github.blog/developer-skills/github/include-diagrams-markdown-files-mermaid/ ,
  https://docs.gitlab.com/user/markdown/ ,
  https://squidfunk.github.io/mkdocs-material/reference/diagrams/ ,
  https://docusaurus.io/docs/markdown-features/diagrams

Search-index norms, three tiers by scale:
- **Client-side, build-time index** (small/static): **Pagefind** (https://pagefind.app —
  chunked index, scales to thousands of pages, near-zero ops; current default), **Lunr.js**
  (https://lunrjs.com — ships whole index), **FlexSearch** (https://github.com/nextapps-de/flexsearch).
- **Hosted index** (large public docs): **Algolia DocSearch** (https://docsearch.algolia.com).
- **Self-hosted search server** (private/dynamic, relevance tuning): **Meilisearch**
  (https://www.meilisearch.com — also offers vector/semantic search), **Typesense**
  (https://typesense.org). *Note: all client-side options are **keyword**, not semantic —
  cairn's embeddings-based search is a step up from the doc-portal norm.*

---

## Key Patterns & Takeaways

- **Chat vs. browse is the defining split.** The entire mainstream self-hosted RAG category
  (Onyx, Khoj, Open WebUI, AnythingLLM, RAGFlow, Verba, Cognita, rag-web-ui) is chat/Q&A-first.
  A human-facing **document reader/browser** with semantic search as a *secondary* feature is an
  unmet niche.
- **FastAPI + Docker + vector store is well-trodden** as a backend shape (Onyx, Khoj, Open WebUI,
  RAGFlow, rag-web-ui, Verba, Cognita); AnythingLLM (Node) is the outlier. cairn's proposed
  Python/FastAPI BFF is mainstream and validated.
- **AWS RAG samples are uniformly serverless and chat-oriented** (Lambda/API Gateway/CDK;
  OpenSearch Serverless / Aurora pgvector / Kendra). A self-hosted *container* reading S3 is the
  opposite of AWS's published model — which makes Direction 5 (serverless static site) the more
  "AWS-idiomatic" path and the Docker reader (Idea 6) the deliberately un-idiomatic but lower-ops one.
- **S3 Vectors is the newest load-bearing piece** (preview Jul 2025, GA Dec 2025). Most RAG
  references predate it; choosing it is a deliberate cost/simplicity bet. Maturing-support signals:
  Open WebUI's `S3Vector` store option and the `awslabs/generative-ai-cdk-constructs` S3 Vectors
  construct.
- **Mermaid norm = client-side mermaid.js** on ` ```mermaid ` fences. Native/first-class in
  MkDocs-Material, Docusaurus, adr-viewer, Outline; weak/absent in Log4brains, BookStack, Wiki.js,
  and PKM apps. *Corroborates Idea 5's "pre-render to SVG at publish" as a way to sidestep
  client-side mermaid.js entirely.*
- **Client-side search at small scale = keyword, not semantic** (Pagefind default). cairn's
  embeddings give it a capability the doc-portal norm lacks — but several tools (Meilisearch) now
  blur the line.
- **Faceted (multi-dimension) filtering is genuinely under-served.** Static generators offer
  single-dimension tag indexes; wikis offer entity tags; AWS samples treat metadata as a vector
  filter / RBAC. **Simultaneous type + date + tag filtered browsing over a large corpus is the
  clearest differentiator** — and cairn's `list_artifacts` already does exactly this server-side.
- **Watch staleness in anything borrowed:** Verba and Cognita are **archived**; Quivr and
  create-llama are stale. Actively-maintained FastAPI references are Onyx, Khoj, Open WebUI, RAGFlow.

---

## Notable Gaps / What Does NOT Seem to Exist Yet

The cairn reading concept — **a self-hosted Docker web app that is a human-facing
reader/browser for a markdown corpus (ADRs/specs/reviews), with mermaid rendering, multi-facet
filtering, and semantic search backed by S3 + S3 Vectors + Bedrock** — does **not appear to
exist as a maintained product**. It sits in the unoccupied middle between chat-first RAG apps
and keyword-search doc portals. No AWS-published sample is a markdown document reader; the only
S3 Vectors + Bedrock + containerised web-UI sample (Fashion Products) is product/image search.

The combination of **(reader-not-chat) + (semantic search) + (mermaid) + (S3 Vectors/Bedrock)
+ (self-hosted Docker) + (multi-facet filtering)** is a real gap. The strongest "build vs.
adopt" challenger to justify against is **Material for MkDocs** — cairn's differentiators are
semantic search, true multi-facet filtering, an S3-backed dynamically-growing corpus, and no
static rebuild on every change.

**Honesty caveats:** a few UI-level details (exact mermaid rendering and faceted-filter support
inside some RAG projects) could not be confirmed from READMEs/landing pages alone and would
require inspecting each running UI; Notion's native mermaid support was confirmed via a
secondary source rather than Notion's own docs.

---

# Addendum — MCP-UI Prior Art (added 2026-06-14)

**Scope:** this addendum covers the category the primary scan excluded — **web UIs and GUI
clients for MCP servers** — researched later at the operator's request to make the
library-vs-MCP-client decision *informed*. Bottom line up front: prior art **reinforces** the
brainstorm's verdict (Idea 6 should reuse cairn's read logic as a library, not couple to MCP),
with one nuance — *if* coupling is ever wanted, couple to MCP **resources** (spec-designed for
human display), never to the LLM-shaped **tool** layer.

A clean three-way split emerged: **(a)** human resource/document browsers over MCP (directly
comparable — but only dev/debug tools exist); **(b)** agent chat clients that happen to support
MCP (adjacent — they surface *tools for agents*, not resources for humans); **(c)** the
"mcp-ui / MCP Apps" ecosystem, which despite the name is the *inverse* of our use case (AI
assistants *rendering* interactive UI, not humans *browsing* a server).

## Directly comparable (human web/GUI browsers over MCP resources)

### Source M1 — MCP Inspector (official)
- **URL:** https://github.com/modelcontextprotocol/inspector
- **Summary:** The canonical tool. React web UI (default `localhost:6274`) + a Node proxy
  bridging the browser to the server. A human can list/invoke tools, **list resources and read
  their contents**, and exercise prompts via auto-generated forms with real-time JSON
  visualization. Supports stdio, SSE, Streamable HTTP. Actively maintained (0.22.0, June 2026).
- **Relevance:** Proves browser → proxy → MCP resource-read is trivial, but it is explicitly a
  **developer debugging tool** — JSON-first, no markdown/mermaid rendering, no curation,
  ephemeral. Not a reading product.

### Source M2 — mcp-explorer
- **URL:** https://github.com/dlaporte/mcp-explorer
- **Summary:** Web MCP explorer — browse tools/resources/prompts, invoke, inspect, chain calls;
  **renders markdown** (React Markdown) and parses inline JSON; no mermaid. Auth: None / Bearer
  / Custom Header / OAuth 2.0.
- **Relevance:** Closest *intent* match to "read resources and render them nicely" — but
  experimental/abandoned (~1 star, 2 commits, no releases). The niche exists; no mature product.

### Source M3 — VS Code "MCP Tool Explorer"
- **URL:** https://marketplace.visualstudio.com/items?itemName=jurgen178.mcp-tool-explorer
- **Summary:** VS Code extension (IDE, not web). Lists resources and **reads contents with
  syntax highlighting**; renders prompts; sandboxed iframes for MCP Apps. No markdown/mermaid.
- **Relevance:** Same "human reads resources" goal, IDE-bound — confirms the capability keeps
  being built as a *developer* affordance, not an end-user portal.

## Adjacent / partial matches

- **MCP spec — resource model** (https://modelcontextprotocol.io/docs/concepts/resources):
  resources are **"application-driven"**; the spec suggests hosts "expose resources through UI
  elements ... in a tree or list view" and "allow the user to search through and filter," defines
  a **`text/markdown` mimeType**, and an **`annotations.audience: ["user"|"assistant"]`** hint
  plus `priority`/`lastModified`. The protocol *anticipates* human browsing + markdown but
  mandates no UI and ships no reader. **Directly relevant: cairn's resources can carry
  `text/markdown` + `audience:["user"]`.**
- **Agent chat clients (tool-calling, not resource reading):** LibreChat
  (https://www.librechat.ai/docs/features/mcp — web; MCP servers in a chat dropdown/settings
  panel; Streamable HTTP for multi-user), Open WebUI via **mcpo**, AnythingLLM
  (https://docs.anythingllm.com/mcp-compatibility/overview — MCP management UI, but scoped to
  agent tool-calling). None is a browsable resource reader.
- **Bridges / proxies (MCP → web):** **mcpo** (https://github.com/open-webui/mcpo — "expose any
  MCP tool as an OpenAPI HTTP server"; **tools only — resources ignored**; API key + OAuth 2.1),
  **mcp-proxy** (https://github.com/sparfenyuk/mcp-proxy — transport bridge, no UI),
  **supergateway** (https://github.com/supercorp-ai/supergateway — run stdio servers over
  SSE/WS/Streamable HTTP). The dominant "MCP → REST so a SPA can call it" pattern is mcpo —
  and it drops resources entirely.
- **Client SDKs a custom UI would use:** `@modelcontextprotocol/sdk`
  (https://github.com/modelcontextprotocol/typescript-sdk — ships a **Streamable HTTP client
  transport** for browser/web clients); **FastMCP Python client**
  (https://gofastmcp.com/clients/resources — `read_resource()` / `list_resources()`; relevant
  since cairn-mcp is fastmcp); **mcp-use** (https://github.com/mcp-use/mcp-use — agent/app
  framework, not a reader).
- **The "MCP UI" naming trap:** **mcp-ui / MCP Apps** (https://mcpui.dev) is the standard for
  **AI assistants to render interactive HTML/JS UI** returned by tools — server→AI-host
  rendering, the inverse of human→server reading. Top hit for "MCP UI"; easy to mis-scope.
- **MCP-as-human-backend friction:** Anthropic — *"Code execution with MCP"*
  (https://www.anthropic.com/engineering/code-execution-with-mcp) argues for presenting MCP
  servers as **code APIs** rather than direct tool calls (tool defs inflate context; every
  intermediate result must pass through the model; results are LLM-shaped). Targeted search for
  "MCP as backend for a human web app" returned essentially nothing — the discourse is thin.

## Key Patterns & Takeaways

- **The plumbing is solved and standard:** MCP server → bridge/proxy → web (mcpo for REST,
  supergateway/mcp-proxy for transport, or the TS SDK's Streamable HTTP client for direct
  browser access).
- **Streamable HTTP is the de-facto web transport** (Inspector, LibreChat multi-user, mcpo, TS
  SDK); stdio is local-only; SSE is legacy/deprecated.
- **Auth converges on Bearer token + OAuth 2.1** bolted on at the bridge/frontend — there is no
  MCP-native human-session auth.
- **Proxies expose tools, not resources.** The most-used bridge (mcpo) maps tools→OpenAPI and
  **ignores resources**; resource browsing survives only in dev-tool clients.
- **The protocol invites human resource browsing but nobody productised it** (tree/list pickers,
  `text/markdown`, `audience:["user"]` are all in the spec).
- **Markdown rendering is rare; mermaid is absent** in MCP clients — only mcp-explorer renders
  markdown; nothing renders mermaid from resources.
- **Where MCP meets humans it's a developer-debugging context, not an end-user product.**
- **Anthropic's own guidance pushes away from direct MCP/tool consumption** toward code APIs —
  i.e. MCP I/O is LLM-shaped, not UI-shaped.
- **FastMCP gives a clean programmatic client** (`read_resource`/`list_resources`) — so a custom
  backend *could* sit on the resource API without the LLM-shaped tool layer, if MCP coupling were
  ever wanted.

## Implication for the Idea 6 Decision (confirms Option C)

- **(b) Reuse an existing MCP GUI client — weak.** The only human-facing browsers (Inspector,
  mcp-explorer, VS Code Tool Explorer) are dev/debug tools — JSON-first, no curation, mostly no
  markdown/mermaid, official-but-debugging or experimental/abandoned. None is a presentable
  ADR/spec reading portal.
- **(a) Custom web app coupling to MCP — viable but caveated.** If coupling, the least-bad path
  is reading **resources** (not tools) via the FastMCP/TS client and rendering markdown yourself
  — resources are spec-designed for human display. But the most-used bridge (mcpo) ignores
  resources, so ecosystem momentum won't help, and tool results are explicitly LLM-shaped.
- **(c) Call the underlying logic as a library / build a non-MCP read API — best supported.**
  Every signal (proxies surface tools not resources; MCP I/O is LLM-shaped; no mature human
  resource browser exists; Anthropic steers toward code APIs) reinforces that the human reader
  should sit on a **purpose-built read API over the same S3 / S3-Vectors / Bedrock logic**. The
  MCP server and the human UI then become **two thin frontends over one shared library** —
  avoiding LLM-shaped responses, the transport/bridge tax, and the resource-support gap. This is
  exactly **Idea 6, Option C**; the prior-art scan makes that an *informed* choice, not a default.

## Notable Gaps / What Does NOT Seem to Exist Yet

- No mature, end-user-facing "read my MCP server's markdown documents" web product — everything
  human-facing is a developer debug tool.
- No bridge/proxy that exposes MCP **resources** (vs tools) as a web/REST API — mcpo and peers
  are tool-only.
- No mermaid rendering of MCP resource content anywhere found; markdown rendering only in one
  experimental client.
- No semantic-search-over-resources human UI — cairn's exact niche is unoccupied here too.
- Almost no written discourse on "MCP server as a backend for a human web app" — little
  community consensus to lean on.

**Method caveat:** WebSearch was unavailable to the research agent (permission denied); it used
DuckDuckGo HTML search via fetch plus direct primary-source fetches. The Open WebUI `mcpo` doc
page 404'd, but mcpo's behaviour is confirmed from its GitHub repo.

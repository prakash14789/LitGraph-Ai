# LitGraph — Technical Architecture Document

> **Version:** 1.0  
> **Last Updated:** August 11, 2026  
> **Author:** Prakash  
> **Status:** Draft  

---

## 1. System Overview

LitGraph is a **GraphRAG system** for academic literature. It ingests research papers, extracts entities and relationships using LLMs, builds a knowledge graph in Neo4j, and answers natural language queries using hybrid retrieval (vector search + graph traversal).

### 1.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (React)                          │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │  Chat UI     │  │ Graph Explorer   │  │ Paper Management       │  │
│  │  (Q&A)       │  │ (D3/Cytoscape)   │  │ (Upload, Collections)  │  │
│  └──────┬───────┘  └────────┬─────────┘  └───────────┬────────────┘  │
│         └──────────────────┬┘                         │              │
│                            │ REST API                 │              │
└────────────────────────────┼──────────────────────────┼──────────────┘
                             │                          │
┌────────────────────────────┼──────────────────────────┼──────────────┐
│                        BACKEND (FastAPI)                             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                      API Layer (Routers)                        │ │
│  │  /ingest  │  /query  │  /graph  │  /papers  │  /collections     │ │
│  └─────┬─────┴─────┬────┴────┬─────┴─────┬─────┴──────┬───────────┘ │
│        │           │         │            │             │            │
│  ┌─────▼───────────▼─────────▼────────────▼─────────────▼─────────┐ │
│  │                     Service Layer                               │ │
│  │                                                                 │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │ │
│  │  │  Ingestion   │  │  Retrieval   │  │  Generation        │     │ │
│  │  │  Service     │  │  Service     │  │  Service           │     │ │
│  │  │              │  │              │  │                    │     │ │
│  │  │ PDF Parser   │  │ Vector Search│  │ Context Builder    │     │ │
│  │  │ Chunker      │  │ Graph Travrsl│  │ LLM Caller         │     │ │
│  │  │ Extractor    │  │ Hybrid Scorer│  │ Citation Formatter │     │ │
│  │  │ Resolver     │  │              │  │                    │     │ │
│  │  │ Graph Writer │  │              │  │                    │     │ │
│  │  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘     │ │
│  │         │                 │                    │                 │ │
│  └─────────┼─────────────────┼────────────────────┼─────────────────┘ │
│            │                 │                    │                  │
│  ┌─────────▼─────────────────▼────────────────────▼─────────────────┐ │
│  │                     Data Layer                                   │ │
│  │                                                                  │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐      │ │
│  │  │  PostgreSQL  │  │   Neo4j      │  │  ChromaDB /        │      │ │
│  │  │  (metadata,  │  │  (knowledge  │  │  Qdrant            │      │ │
│  │  │   users,     │  │   graph)     │  │  (vector           │      │ │
│  │  │   sessions)  │  │              │  │   embeddings)      │      │ │
│  │  └──────────────┘  └──────────────┘  └────────────────────┘      │ │
│  │                                                                  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                  External Services                               │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐      │ │
│  │  │  LLM API     │  │  Embedding   │  │  ArXiv /           │      │ │
│  │  │  (OpenAI /   │  │  API         │  │  Semantic Scholar   │      │ │
│  │  │   Anthropic) │  │  (OpenAI /   │  │  API               │      │ │
│  │  │              │  │   local)     │  │                    │      │ │
│  │  └──────────────┘  └──────────────┘  └────────────────────┘      │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack

### 2.1 Stack Choices & Rationale

| Layer | Technology | Why This |
|-------|-----------|----------|
| **Backend Framework** | FastAPI (Python) | Async support, auto-generated OpenAPI docs, Pydantic validation, best Python ML ecosystem integration |
| **Primary Database** | PostgreSQL | Stores paper metadata, user data, sessions, extraction job status. Reliable, well-known, free |
| **Knowledge Graph** | Neo4j (Community Edition) | Purpose-built for graph queries (Cypher). Handles relationship traversal natively. Free community edition sufficient for portfolio scale |
| **Vector Store** | ChromaDB (MVP) → Qdrant (production) | ChromaDB: zero-config, embedded, fast to start. Qdrant: better performance at scale, filtering, production-grade |
| **LLM API** | **Default (build phase): Gemini API free tier**, with a 2nd Gemini key auto-switched to on quota exhaustion, and **Groq (free, OpenAI-compatible) as a manual fallback provider**. **Scale option: OpenAI (GPT-4o-mini/GPT-4o) OR Anthropic (Haiku/Sonnet)** — swap via `LLM_PROVIDER` config, no code changes | Gemini free tier: measured live (EXTRACT-001) at a much stricter ~20 requests/day/model than the generally-published 1,500 RPD figure — the 2nd key + Groq fallback exist because of that. Groq: no card, 1,000 RPD on `llama-3.3-70b-versatile`, live-verified working through the same unified client. OpenAI/Anthropic wired in from day one so scaling later (higher quality, higher volume, no training-data usage) is a config flip, not a rebuild |
| **Embedding Model** | **Default: `all-MiniLM-L6-v2`** (local, sentence-transformers, free, no API call) — **Scale option: `text-embedding-3-small`** (OpenAI, better quality, costs money) | Local model = zero cost + zero rate limit during build. Swap to OpenAI embeddings later if retrieval quality needs a bump at scale |
| **PDF Parsing** | **MVP: PyMuPDF (fitz) only.** GROBID considered but **not implemented** — no docker-compose service exists for it. Listed here as a documented future upgrade path, not a current dependency | PyMuPDF: fast, extracts text/tables/structure via heuristics, zero extra infra. GROBID would give academic-paper-aware parsing (cleaner section/reference extraction) but is a heavy Java service — add later only if PyMuPDF heuristics prove insufficient on real papers |
| **Frontend** | React + TypeScript + Tailwind CSS | Standard modern stack. TypeScript catches bugs. Tailwind speeds up styling |
| **Graph Visualization** | Cytoscape.js (primary) or D3.js (custom) | Cytoscape: built for graph/network visualization, has layout algorithms. D3: more control but more work |
| **Task Queue** | Celery + Redis | Paper ingestion is slow (LLM calls per paper). Celery handles async background jobs. Redis as broker |
| **Containerization** | Docker + Docker Compose | Packages all services (FastAPI, Neo4j, PostgreSQL, ChromaDB, Redis) into one `docker-compose up` command |

### 2.2 Development Tools

| Tool | Purpose |
|------|---------|
| **Git + GitHub** | Version control, CI/CD |
| **Poetry** | Python dependency management (better than pip for reproducible builds) |
| **Alembic** | PostgreSQL schema migrations |
| **pytest** | Testing framework |
| **Ruff** | Python linting + formatting (fast, replaces black + flake8) |
| **Pre-commit hooks** | Auto-run linting/formatting before commits |

---

## 3. Project Structure

```
litgraph/
├── docker-compose.yml              # All services: FastAPI, Neo4j, PostgreSQL, ChromaDB, Redis
├── Dockerfile                      # Backend container
├── pyproject.toml                   # Poetry dependencies
├── .env.example                     # Environment variable template
├── .pre-commit-config.yaml          # ruff + ruff-format as git pre-commit hooks (SETUP-009)
├── alembic/                         # Database migrations
│   ├── alembic.ini
│   └── versions/
│
├── src/
│   ├── main.py                      # FastAPI app entry point
│   ├── config.py                    # Settings (Pydantic BaseSettings, loads from .env)
│   ├── db.py                        # SQLAlchemy async engine + session factory (added SETUP-004 —
│   │                                 # not in the original tree, needed a home for engine/sessionmaker)
│   │
│   ├── api/                         # API Layer — route definitions only
│   │   ├── __init__.py
│   │   ├── router.py                # Main router aggregator
│   │   ├── routes/
│   │   │   ├── ingest.py            # POST /ingest/upload, GET /ingest/status/{job_id} — built
│   │   │   │                        # INGEST-004. POST /ingest/arxiv still not built (POLISH-004).
│   │   │   │                        # Upload is per-file partial-success, not all-or-nothing: one
│   │   │   │                        # bad file in a batch is reported as "rejected" in that file's
│   │   │   │                        # result entry, the rest still queue — not specified either way
│   │   │   │                        # by the ticket, chosen for upload UX (10 files, 1 corrupt
│   │   │   │                        # shouldn't block the other 9). Paper+ExtractionJob commit
│   │   │   │                        # happens per-file, right after creation — not deferred to
│   │   │   │                        # Depends(get_db)'s end-of-request commit like everywhere else
│   │   │   │                        # — because the Celery dispatch right after must find a durable
│   │   │   │                        # row; dispatching before commit risks the worker racing ahead
│   │   │   │                        # of the transaction. Still atomic per-paper (see SETUP-004's
│   │   │   │                        # atomicity note in 05_FEATURE_TICKETS.md).
│   │   │   ├── query.py             # POST /query/vanilla — built INGEST-005. POST /query —
│   │   │   │                        # built RETRIEVAL-005: chains retrieve_seeds ->
│   │   │   │                        # retrieve_subgraph -> score_subgraph -> build_context ->
│   │   │   │                        # generate_graphrag_answer exactly as RETRIEVAL-001 through
│   │   │   │                        # -004 built them. Citations are built from the graph data
│   │   │   │                        # itself, not parsed out of the LLM's free-form answer:
│   │   │   │                        # every Paper node that made the ranked subgraph, plus
│   │   │   │                        # (title resolved via the same _paper_titles() helper
│   │   │   │                        # /query/vanilla already uses) any paper that only surfaced
│   │   │   │                        # through a chunk match and never made the ranked top-K —
│   │   │   │                        # parsing citations out of prose would be fragile and
│   │   │   │                        # couldn't guarantee the ticket's "citations match actual
│   │   │   │                        # papers" criterion the way reading it straight off the
│   │   │   │                        # graph does. retrieved_subgraph in the response is
│   │   │   │                        # RankedSubgraph's nodes/edges as-is (with each node's score/
│   │   │   │                        # vector_similarity/graph_distance/avg_edge_confidence, for
│   │   │   │                        # future frontend use — GRAPH-viz epic). retrieval_stats
│   │   │   │                        # covers the ticket's own "vector results, graph nodes, final
│   │   │   │                        # context size" ask plus latency_ms. POST /query/compare —
│   │   │   │                        # built RETRIEVAL-006: runs query_graphrag and query_vanilla
│   │   │   │                        # concurrently via asyncio.gather(), each given its own
│   │   │   │                        # AsyncSession (SQLAlchemy's isn't safe shared across
│   │   │   │                        # concurrent tasks, and both are called directly as plain
│   │   │   │                        # async functions here, not through FastAPI's own routing,
│   │   │   │                        # so there's no Depends(get_db) session to share anyway).
│   │   │   │                        # Real concurrency required a small fix to both existing
│   │   │   │                        # routes: llm_client.complete() is a blocking sync call, and
│   │   │   │                        # calling it straight from an `async def` (as both routes did
│   │   │   │                        # before this ticket) blocks the whole event loop for the
│   │   │   │                        # call's duration — invisible with one request in flight, but
│   │   │   │                        # would have serialized the two LLM calls back-to-back under
│   │   │   │                        # asyncio.gather(), failing the ticket's own "latency =
│   │   │   │                        # max(graphrag, vanilla), not the sum" criterion. Fixed by
│   │   │   │                        # wrapping just the LLM-call sites in `asyncio.to_thread` (the
│   │   │   │                        # dominant cost — seconds, vs tens of ms for embed()/
│   │   │   │                        # query_similar()/DB calls, so only that call needed it).
│   │   │   │                        # Verified live in the test: a mocked LLM made to sleep 0.3s
│   │   │   │                        # measures ~0.48s wall-clock total for both pipelines
│   │   │   │                        # together, not ~0.6s+ serial.
│   │   │   ├── graph.py             # GET /graph/overview, /graph/subgraph, /graph/entity/{id},
│   │   │   │                        # /graph/search — built GRAPH-001. /graph/subgraph reuses
│   │   │   │                        # RETRIEVAL-002's retrieve_subgraph() with a single-entity
│   │   │   │                        # seed rather than a second traversal implementation. Every
│   │   │   │                        # node gets one generic `usage_count` field (not the ticket's
│   │   │   │                        # literal 4 differently-named examples) — Paper's is a
│   │   │   │                        # relationship-degree proxy since no CITES edge is ever
│   │   │   │                        # written (relation_extractor.py extracts it as a candidate
│   │   │   │                        # type, pipeline.py never persists it); Method/Dataset/Author
│   │   │   │                        # come from real USES_METHOD/EVALUATES_ON/AUTHORED_BY counts.
│   │   │   │                        # /graph/search added 3 new fulltext indexes (schema.py) for
│   │   │   │                        # Dataset/Author/Claim — only Paper/Method had one before.
│   │   │   ├── papers.py            # GET /papers, GET /papers/{id}, DELETE /papers/{id} — built
│   │   │   │                        # INGEST-007. Once EXTRACT-004 (graph writer) landed, detail's
│   │   │   │                        # entities/relationships lists reflect the real graph — FE-002's
│   │   │   │                        # PaperDetailModal renders them live. The delete route
│   │   │   │                        # delegates entirely to services/papers/deletion.py.
│   │   │   └── collections.py       # CRUD for paper collections
│   │   ├── schemas/                 # Pydantic request/response models
│   │   │   ├── ingest.py            # UploadResult, JobStatusResponse — built INGEST-004
│   │   │   ├── query.py             # VanillaQueryRequest/Response, SourceChunk — built INGEST-005.
│   │   │   │                        # QueryRequest/Response, Citation, RetrievedSubgraphSchema
│   │   │   │                        # (SubgraphNodeSchema/SubgraphEdgeSchema), RetrievalStats —
│   │   │   │                        # built RETRIEVAL-005 for POST /query. CompareQueryRequest/
│   │   │   │                        # Response — built RETRIEVAL-006 for POST /query/compare
│   │   │   │                        # (wraps one QueryResponse + one VanillaQueryResponse plus
│   │   │   │                        # total_latency_ms, no new fields of their own needed).
│   │   │   ├── graph.py             # GraphOverview, GraphNodeSchema (reuses query.py's
│   │   │   │                        # SubgraphEdgeSchema for edges rather than a duplicate),
│   │   │   │                        # EntityDetailResponse, SearchResponse — built GRAPH-001
│   │   │   └── papers.py            # PaperListItem/PaperDetail/PaperEntity/PaperRelationship —
│   │   │                            # built INGEST-007
│   │   └── dependencies.py          # FastAPI dependency injection (DB sessions, auth)
│   │
│   ├── services/                    # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── ingestion/               # Paper → Graph pipeline
│   │   │   ├── __init__.py
│   │   │   ├── pdf_parser.py        # PDF → raw text + sections + tables — built INGEST-001.
│   │   │   │                        # Section split is a header-line heuristic (known academic
│   │   │   │                        # section names), not font analysis. Title/author extraction
│   │   │   │                        # skips rotated text (arXiv sidebar watermarks) and merges
│   │   │   │                        # multi-line titles at the same font size. Reference
│   │   │   │                        # splitting tries numbered ([1]) and name-year styles, keeps
│   │   │   │                        # whichever actually segmented — real reference parsing is
│   │   │   │                        # what GROBID exists for (considered, not used — too heavy).
│   │   │   ├── chunker.py           # Sections → overlapping chunks — built INGEST-002.
│   │   │   │                        # Sentence-boundary packing (tiktoken cl100k_base), sliding
│   │   │   │                        # overlap between chunks. page_number resolved by searching
│   │   │   │                        # each chunk's text in the paper's raw per-page text
│   │   │   │                        # (whitespace-normalized both sides); tables get their real
│   │   │   │                        # page number straight from PyMuPDF's Table.page instead.
│   │   │   ├── embedding_storage.py # Chunks → ChromaDB paper_chunks — built INGEST-003. Batches
│   │   │   │                        # embed calls (100/batch, one API call per batch not per
│   │   │   │                        # chunk). Skips re-embedding if paper_id already has chunks
│   │   │   │                        # stored (checked via collection.get(where={"paper_id":...}))
│   │   │   ├── entity_extractor.py  # Section → entities (LLM-based) — built EXTRACT-001.
│   │   │   │                        # Operates on pdf_parser's raw section text, not chunker's
│   │   │   │                        # ~1000-token chunks — a whole section gives the model more
│   │   │   │                        # context to attribute a metric to the right method/dataset.
│   │   │   │                        # One retry on unparseable JSON (markdown fences and
│   │   │   │                        # prose-wrapped JSON are stripped first); still-unparseable
│   │   │   │                        # after the retry returns an empty extraction rather than
│   │   │   │                        # failing the paper — same never-raises contract as
│   │   │   │                        # pdf_parser.parse_pdf. Filters out anything below
│   │   │   │                        # entity_confidence_threshold and any claim whose "type"
│   │   │   │                        # isn't one of the schema's 4 values. Live-tested against 5
│   │   │   │                        # real papers (Attention, BERT, ResNet, Adam, a GAN survey)
│   │   │   │                        # covering survey-style/many-methods and math-heavy edge
│   │   │   │                        # cases — measured precision well above the 80% bar, JSON
│   │   │   │                        # parsed cleanly on every real call. Initially misdiagnosed a
│   │   │   │                        # suspected hallucination here (model output terms like
│   │   │   │                        # "scaled dot-product attention" that aren't in the visible
│   │   │   │                        # abstract paragraph) — re-checked the exact text the model
│   │   │   │                        # actually received and found those terms genuinely present,
│   │   │   │                        # in the page-1 author-contribution footnote that
│   │   │   │                        # pdf_parser's "abstract" section bundles in alongside the
│   │   │   │                        # abstract paragraph (everything before the next recognized
│   │   │   │                        # header counts as one section). Not a bug — correct
│   │   │   │                        # extraction from the literal given text the whole time. Left
│   │   │   │                        # the closed-book instruction in the prompt anyway ("ignore
│   │   │   │                        # what you recall about this paper, extract only from the
│   │   │   │                        # text below") as a reasonable defensive precaution for a
│   │   │   │                        # genuine future case, but it wasn't fixing anything real
│   │   │   │                        # this time.
│   │   │   ├── relation_extractor.py # Section → relationships (LLM-based) — built EXTRACT-002.
│   │   │   │                        # Two passes per the ticket: extract_intra_paper_relations
│   │   │   │                        # (USES_METHOD/EVALUATES_ON/INTRODUCES/REPORTS_RESULT — the
│   │   │   │                        # paper to its own entities, no outside knowledge) and
│   │   │   │                        # extract_cross_paper_relations (EXTENDS/OUTPERFORMS/
│   │   │   │                        # CONTRADICTS/CITES — the paper's entities to a candidate
│   │   │   │                        # list of entities from OTHER papers, standing in for a
│   │   │   │                        # real Neo4j lookup until EXTRACT-004 exists). AUTHORED_BY
│   │   │   │                        # is deliberately not extracted here — pdf_parser already
│   │   │   │                        # parses paper.authors as structured data, nothing for an
│   │   │   │                        # LLM to add. Cross-paper target is code-enforced to be one
│   │   │   │                        # of the given candidates (not just prompt-instructed) — a
│   │   │   │                        # model that invents one anyway gets filtered out rather
│   │   │   │                        # than trusted. Shares parse-retry-once JSON handling with
│   │   │   │                        # entity_extractor.py via the new src/utils/llm_json.py.
│   │   │   │                        # Live-tested against the same 5 papers as EXTRACT-001,
│   │   │   │                        # 2 rounds — caught and fixed 2 real issues: EVALUATES_ON's
│   │   │   │                        # target was ambiguous (method vs dataset) and the model
│   │   │   │                        # picked inconsistently across papers, fixed by requiring
│   │   │   │                        # target=dataset explicitly; and the cross-paper pass
│   │   │   │                        # over-linked to topically-plausible-but-unnamed candidates
│   │   │   │                        # (e.g. "LSTM" just because it was in the candidate list,
│   │   │   │                        # when the text only said "existing best results"), fixed
│   │   │   │                        # by requiring the candidate be specifically named/
│   │   │   │                        # identified, not just plausible. Known remaining
│   │   │   │                        # limitation after both fixes: BERT's abstract still
│   │   │   │                        # produced 4 OUTPERFORMS relations against a candidate
│   │   │   │                        # "ELMo" that the given abstract text never names by name
│   │   │   │                        # (factually true in the real world, but not strictly
│   │   │   │                        # grounded in the literal given text) — the model's prior
│   │   │   │                        # knowledge of well-known comparisons still leaks through
│   │   │   │                        # sometimes on the cross-paper pass specifically. Not fully
│   │   │   │                        # solved; flagged for EXTRACT-003/004 to reconsider if it
│   │   │   │                        # proves problematic once real candidate lists exist.
│   │   │   ├── entity_resolver.py   # Deduplicate entities across papers — built EXTRACT-003,
│   │   │   │                        # the ticket's own "hardest engineering problem" flag.
│   │   │   │                        # resolve_entity(new, candidates) runs the ticket's 5-step
│   │   │   │                        # cascade: exact name match -> merge immediately; fuzzy
│   │   │   │                        # name/alias + embedding-description similarity ->
│   │   │   │                        # unioned candidate shortlist; LLM verification
│   │   │   │                        # (best-scoring candidate first) -> merge on first
│   │   │   │                        # confirmed match; nothing confirmed -> create new. Takes
│   │   │   │                        # a candidate list, doesn't query Neo4j itself — nothing
│   │   │   │                        # to query yet until EXTRACT-004 exists; that ticket wires
│   │   │   │                        # in the real candidate lookup.
│   │   │   │                        #
│   │   │   │                        # Live-tested against the ticket's own acceptance-criteria
│   │   │   │                        # examples and found both of the ticket's literal
│   │   │   │                        # thresholds don't work as specified against a real
│   │   │   │                        # embedding model: "BERT" vs "BERT-base" scores ~0.62 on a
│   │   │   │                        # plain fuzzy ratio (spec: >0.85) and real
│   │   │   │                        # paraphrased-same-entity description pairs scored
│   │   │   │                        # 0.57-0.64 cosine (spec: >0.90) — as literally specified,
│   │   │   │                        # neither of the ticket's own two examples would ever
│   │   │   │                        # reach the LLM step. Fixed with two targeted,
│   │   │   │                        # boundary/stopword-aware pattern checks layered onto the
│   │   │   │                        # fuzzy pass — a suffix-variant check ("BERT"/"BERT-base",
│   │   │   │                        # "GPT"/"GPT2") and an acronym check ("BERT" vs its own
│   │   │   │                        # full expansion) — plus recalibrated
│   │   │   │                        # entity_resolution_embedding_threshold (0.55, not the
│   │   │   │                        # ticket's 0.90, evidence-based off the real measurements).
│   │   │   │                        # Re-verified live after the fix: both examples merge
│   │   │   │                        # correctly, with the shorter name kept as canonical
│   │   │   │                        # ("BERT") and the longer one demoted to an alias. The
│   │   │   │                        # negative example ("BERT" the NLP model vs "BERT" a
│   │   │   │                        # person) is satisfied by the entity_type guard — Method
│   │   │   │                        # vs Author never even reach step 1. Known remaining gap,
│   │   │   │                        # left as the ticket literally specifies rather than
│   │   │   │                        # silently patched: an exact-name match merges immediately
│   │   │   │                        # with no LLM check, so two same-type entities that
│   │   │   │                        # happen to share an exact name but are genuinely
│   │   │   │                        # unrelated would still auto-merge — judged rare enough in
│   │   │   │                        # an academic corpus not to slow down the common, safe
│   │   │   │                        # case. Performance measured live: 16.8ms for steps 1-3
│   │   │   │                        # (excluding the LLM call, per the ticket's own carve-out).
│   │   │   ├── graph_writer.py      # Write entities + relationships to Neo4j — built EXTRACT-004,
│   │   │   │                        # the ticket every prior "candidate list stands in for a real
│   │   │   │                        # Neo4j lookup" comment (INGEST-007, EXTRACT-002, EXTRACT-003)
│   │   │   │                        # was waiting for. MERGE for nodes (idempotent — reprocessing
│   │   │   │                        # a paper updates the same node, never duplicates it), CREATE
│   │   │   │                        # for relationships (per the ticket; only entity/node
│   │   │   │                        # idempotency is in the acceptance criteria, not relationship
│   │   │   │                        # idempotency, so reprocessing can duplicate edges — a known,
│   │   │   │                        # deliberately out-of-scope gap, not silently accepted).
│   │   │   │                        #
│   │   │   │                        # Two node families, matching what §4.2 gives each type:
│   │   │   │                        # write_named_entity(label, resolution, paper_id) handles
│   │   │   │                        # Method/Dataset/Author/Metric — anything entity_resolver.py
│   │   │   │                        # resolved — MERGE-keyed on canonical_name (Method/Dataset) or
│   │   │   │                        # name (Author/Metric), same key resolve_entity's own
│   │   │   │                        # exact-match step already uses. Only Method/Dataset get an
│   │   │   │                        # embedding + a Chroma entity_embeddings upsert — §4.2's node
│   │   │   │                        # examples don't give Author/Metric an embedding field, and
│   │   │   │                        # §4.3 explicitly scopes that collection to
│   │   │   │                        # "method/dataset/claim". write_claim() is separate and NOT
│   │   │   │                        # run through entity_resolver — a claim isn't a named,
│   │   │   │                        # cross-paper-shared entity (§4.2 gives it a singular
│   │   │   │                        # source_paper_id, not the shared source_papers list
│   │   │   │                        # Method/Dataset get); deduped instead by a content hash of
│   │   │   │                        # (paper_id, text). write_authors() MERGEs Author nodes
│   │   │   │                        # straight from paper.authors and CREATEs the
│   │   │   │                        # Paper-[:AUTHORED_BY]->Author edges with no LLM step — this is
│   │   │   │                        # the module relation_extractor.py's own comment pointed to
│   │   │   │                        # ("pdf_parser already parses paper.authors as structured
│   │   │   │                        # data — nothing for an LLM to add").
│   │   │   │                        #
│   │   │   │                        # Chroma's entity_embeddings metadata tracks source_papers as
│   │   │   │                        # a comma-joined string, not the list shown in §4.3's
│   │   │   │                        # illustrative JSON — Chroma metadata values must be
│   │   │   │                        # str/int/float/bool, no lists, discovered live writing this.
│   │   │   │                        #
│   │   │   │                        # Live-verified against real Neo4j + real Chroma containers
│   │   │   │                        # (tests/integration/test_graph_writer.py), not mocked — the
│   │   │   │                        # ticket's own acceptance criteria explicitly wants a direct
│   │   │   │                        # Chroma query proving the embedding write, not just a Neo4j
│   │   │   │                        # check. That live run surfaced a real, general bug: Neo4j's
│   │   │   │                        # async driver pools connections tied to the event loop that
│   │   │   │                        # created them, but pytest-anyio gives every test function its
│   │   │   │                        # own loop — a connection pooled by one test crashed the next
│   │   │   │                        # with "got Future attached to a different loop" once tests
│   │   │   │                        # started hammering Neo4j back-to-back (test_papers_api.py's
│   │   │   │                        # more spread-out Neo4j calls had happened not to trigger it —
│   │   │   │                        # same latent bug, just not yet exposed). Fixed via
│   │   │   │                        # tests/integration/conftest.py's close_neo4j_driver_after_test
│   │   │   │                        # fixture, opted into (not autouse — test_embedding_storage.py
│   │   │   │                        # in the same directory has sync, non-Neo4j tests an autouse
│   │   │   │                        # async fixture would break) by the two files that actually
│   │   │   │                        # call get_driver(): test_graph_writer.py, test_papers_api.py.
│   │   │   └── pipeline.py          # Orchestrates parse -> chunk -> embed -> extract entities ->
│   │   │                            # extract relations -> resolve -> write graph. parse/chunk/
│   │   │                            # embed built INGEST-006; extract/relate/resolve/write added
│   │   │                            # EXTRACT-005, finally connecting EXTRACT-001 through 004 (each
│   │   │                            # already live-tested standalone) into the real upload flow —
│   │   │                            # before this ticket, uploading a paper never touched Neo4j at
│   │   │                            # all, only Chroma/Postgres.
│   │   │                            #
│   │   │                            # Two separate try/except blocks, not one. Block 1
│   │   │                            # (parse/chunk/embed, unchanged since INGEST-006): on failure,
│   │   │                            # deletes any chunks that made it into Chroma and marks
│   │   │                            # job+paper FAILED — without that cleanup,
│   │   │                            # embedding_storage's duplicate check (only checks whether
│   │   │                            # *any* chunks exist for a paper_id) would see partial data
│   │   │                            # and skip re-embedding forever on retry. Block 2
│   │   │                            # (extract/relate/resolve/write): wrapped independently
│   │   │                            # because by the time it runs, chunks are already durable and
│   │   │                            # paper.ingestion_status is already COMPLETED — a crash here
│   │   │                            # must not roll that back. That's the ticket's own acceptance
│   │   │                            # criterion (paper still queryable via vanilla RAG even if
│   │   │                            # graph extraction fails) and it's exactly what happened live:
│   │   │                            # a real Gemini per-minute rate-limit 429 (free tier, 5
│   │   │                            # RPM on whatever "gemini-flash-latest" currently resolves
│   │   │                            # to) hit mid-run during testing, retried twice via
│   │   │                            # llm_client's backoff, still failed, and block 2's except
│   │   │                            # correctly marked the ExtractionJob FAILED while the Paper
│   │   │                            # row stayed COMPLETED — caught by the design, not a bug.
│   │   │                            # On success, only entity/node writes are guaranteed
│   │   │                            # idempotent on a pipeline retry (via graph_writer.py's MERGE
│   │   │                            # keys) — relationships are CREATE per EXTRACT-004's own
│   │   │                            # documented scope trim, so no explicit rollback/cleanup
│   │   │                            # exists for block 2 the way _cleanup_partial_chunks exists
│   │   │                            # for block 1.
│   │   │                            #
│   │   │                            # REPORTS_RESULT relationships are synthesized directly from
│   │   │                            # entity_extractor's own claims list (paper -> each claim,
│   │   │                            # using the claim's own text/confidence), NOT from
│   │   │                            # relation_extractor's independently-worded REPORTS_RESULT
│   │   │                            # output — fuzzy-matching two separate LLM calls' claim text
│   │   │                            # against each other to find "the same" claim node is
│   │   │                            # fragile; writing the claim and its edge from the same text
│   │   │                            # in the same step isn't. CONTRADICTS and CITES are extracted
│   │   │                            # (relation_extractor.py still returns them) but not written
│   │   │                            # to the graph — both need claim-to-claim / paper-to-paper
│   │   │                            # resolution-by-text infrastructure this ticket doesn't build;
│   │   │                            # skipped deliberately, not silently, flagged here for a
│   │   │                            # future ticket if eval surfaces a real need. Metrics
│   │   │                            # (entity_extractor's 4th entity kind) also get no graph node
│   │   │                            # of their own — §4.2's EVALUATES_ON edge example already
│   │   │                            # carries metric/value/dataset as edge properties, so a
│   │   │                            # separate Metric node would duplicate that data for no
│   │   │                            # relation type in the schema to point at it.
│   │   │                            #
│   │   │                            # graph/queries.py's new EXISTING_NAMED_ENTITIES +
│   │   │                            # graph_writer.py's new fetch_candidate_entities() (both
│   │   │                            # EXTRACT-005) are the real Neo4j lookup entity_resolver.py's
│   │   │                            # and relation_extractor.py's candidate-list interfaces were
│   │   │                            # always designed to eventually take — INGEST-007,
│   │   │                            # EXTRACT-002, and EXTRACT-003 had all built and tested
│   │   │                            # against a stand-in candidate list because this lookup
│   │   │                            # didn't exist yet. That candidate list is seeded into the
│   │   │                            # pipeline's per-entity name_index BEFORE resolving this
│   │   │                            # paper's own entities — found live, missing this seed step
│   │   │                            # meant a cross-paper EXTENDS/OUTPERFORMS relation correctly
│   │   │                            # extracted against a pre-existing candidate got dropped as
│   │   │                            # "unlinked" purely because that candidate's node id was
│   │   │                            # never indexed, only entities this run itself wrote were.
│   │   │                            #
│   │   │                            # Live-verified end to end (tests/integration/
│   │   │                            # test_ingestion_pipeline.py::test_pipeline_extracts_and_
│   │   │                            # writes_real_graph): real LLM, real Neo4j, real Chroma, no
│   │   │                            # mocks — completed in ~33s against Groq (well under the
│   │   │                            # ticket's <90s budget), correctly merged "WidgetNet-9000"
│   │   │                            # into "WidgetNet" via EXTRACT-003's suffix-variant heuristic
│   │   │                            # + LLM confirmation, wrote the Method node's embedding to
│   │   │                            # both Neo4j and Chroma's entity_embeddings. Also directly
│   │   │                            # observed live: real same-minute Gemini free-tier rate
│   │   │                            # limiting (a genuinely different failure mode than the
│   │   │                            # ~20/day calendar cap documented in entity_resolver.py's
│   │   │                            # tree comment) can push a run's wall-clock time past 90s
│   │   │                            # purely from retry/backoff under repeated same-minute test
│   │   │                            # load — an environment/quota characteristic, not a pipeline
│   │   │                            # defect; a single clean run comfortably clears the budget.
│   │   │                            # src/tasks/ingest_task.py is just the thin sync Celery
│   │   │                            # entrypoint (asyncio.run(run_pipeline(job_id))) — the real
│   │   │                            # logic used to live there directly (INGEST-004), moved here
│   │   │                            # once this ticket existed to build it properly (INGEST-006).
│   │   │
│   │   ├── retrieval/               # Query → Retrieved Context
│   │   │   ├── __init__.py
│   │   │   ├── vector_retriever.py  # Built RETRIEVAL-001 — retrieve_seeds(query) embeds the
│   │   │   │                        # query once and searches both Chroma collections: top-K
│   │   │   │                        # entity_embeddings (EntitySeed — node_id is a Neo4j
│   │   │   │                        # elementId, parsed straight off graph_writer.py's
│   │   │   │                        # f"entity_{elementId}" Chroma id, no 2nd Neo4j round-trip
│   │   │   │                        # needed) and top-K paper_chunks (ChunkSeed). paper_ids is
│   │   │   │                        # the deduplicated union of chunk seeds' own paper_id and
│   │   │   │                        # every entity seed's source_papers metadata — satisfies the
│   │   │   │                        # ticket's "same paper in both results counts once"
│   │   │   │                        # criterion without RETRIEVAL-002 having to do that
│   │   │   │                        # bookkeeping itself. Empty graph -> chunks-only fallback
│   │   │   │                        # needs no special-casing: Chroma's query() against an
│   │   │   │                        # empty/no-match collection returns empty lists, not an
│   │   │   │                        # error. Global search, not scoped by collection_id — the
│   │   │   │                        # ticket's own "MVP scoping decision": neither chunk nor
│   │   │   │                        # entity metadata carries collection_id, and entity
│   │   │   │                        # resolution intentionally merges the same entity across
│   │   │   │                        # every paper, so real per-collection scoping is deferred to
│   │   │   │                        # POLISH-005. Live-verified against a real Chroma index (real
│   │   │   │                        # embeddings, not mocked) finding a genuine semantic match.
│   │   │   ├── graph_retriever.py   # Built RETRIEVAL-002 — retrieve_subgraph(seeds, hops,
│   │   │                        # relationship_types, entity_types, max_nodes). Entity seeds'
│   │   │                        # node_id is already a Neo4j elementId (used directly);
│   │   │                        # SeedResult.paper_ids are Postgres paper_id strings, resolved to
│   │   │                        # their Paper node's elementId with one extra lookup so both seed
│   │   │                        # kinds land in the same elementId space the traversal query
│   │   │                        # uses. One Cypher query does the N-hop expansion
│   │   │                        # (`-[rel:TYPE1|TYPE2*1..hops]-`, hops clamped 1-4) and orders
│   │   │                        # rows by edge confidence descending — same can't-parameterize-a-
│   │   │                        # label reason queries.py's own docstring gives, safe here
│   │   │                        # because relationship_types is checked against
│   │   │                        # _KNOWN_REL_TYPES (the fixed set graph_writer.py/pipeline.py
│   │   │                        # ever actually write) before it's interpolated. entity_types
│   │   │                        # filters newly-discovered nodes only, in Python — seeds always
│   │   │                        # survive it, they were already judged relevant by
│   │   │                        # RETRIEVAL-001. The 200-node cap is then applied greedily over
│   │   │                        # that pre-sorted row list: keep an edge if both endpoints
│   │   │                        # already fit or are already in, skip otherwise —
│   │   │                        # "highest-confidence edges first" without a second Cypher round-
│   │   │                        # trip. A requested relationship_types filter with no valid
│   │   │                        # entries short-circuits to an empty subgraph rather than
│   │   │                        # silently matching everything. Live-verified with 6 tests
│   │   │                        # against real Neo4j: 2-hop traversal, paper_id seed
│   │   │                        # resolution, type filtering, unknown-type short-circuit,
│   │   │                        # confidence-ordered node capping, empty-seed fallback.
│   │   │                        # Subgraph gained a `seed_ids` field this same ticket (the
│   │   │                        # elementIds actually used to seed the traversal) — added so
│   │   │                        # RETRIEVAL-003's BFS distance calculation gets its distance-0
│   │   │                        # anchors for free instead of re-running the paper_id lookup.
│   │   │   ├── hybrid_scorer.py     # Built RETRIEVAL-003 — score_subgraph(subgraph, seeds,
│   │   │   │                        # top_k, alpha, beta, gamma) implements the ticket's formula
│   │   │   │                        # exactly: alpha*vector_similarity + beta*(1/graph_distance)
│   │   │   │                        # + gamma*avg_edge_confidence. vector_similarity comes
│   │   │   │                        # straight off an EntitySeed's own score for a node that IS
│   │   │   │                        # one; for a Paper node, from the best-scoring ChunkSeed
│   │   │   │                        # sharing its paper_id (the paper was seeded because that
│   │   │   │                        # chunk matched, so its score is the paper's best available
│   │   │   │                        # evidence) — anything reached purely by traversal gets 0.0.
│   │   │   │                        # graph_distance is a plain multi-source BFS over the
│   │   │   │                        # subgraph's own edges (undirected, matching how
│   │   │   │                        # graph_retriever's own traversal pattern works), seeded from
│   │   │   │                        # Subgraph.seed_ids at distance 0 — clamped to 1 before the
│   │   │   │                        # division since the ticket's literal 1/graph_distance can't
│   │   │   │                        # express distance 0 without dividing by zero.
│   │   │   │                        # avg_edge_confidence is the mean `confidence` property (0.0
│   │   │   │                        # default, same as graph_retriever's own coalesce) over
│   │   │   │                        # every subgraph edge touching that node. Ties broken by the
│   │   │   │                        # ticket's own explicit Method > Paper > Dataset preference
│   │   │   │                        # (anything else — Author, Metric, Claim — sorts last).
│   │   │   │                        # top_k/weights default to settings.context_max_nodes/
│   │   │   │                        # hybrid_alpha/beta/gamma (env-configurable per the ticket)
│   │   │   │                        # but both are overridable per call.
│   │   │   └── context_builder.py   # Built RETRIEVAL-004 — build_context(ranked, seeds,
│   │   │                        # max_tokens) turns RETRIEVAL-003's RankedSubgraph +
│   │   │                        # RETRIEVAL-001's SeedResult.chunks into the ticket's exact
│   │   │                        # ENTITIES/RELATIONSHIPS/RELEVANT TEXT CHUNKS text format.
│   │   │                        # Entities grouped by type (Method/Dataset/Paper/Author/
│   │   │                        # Metric/Claim first, per the ticket; anything else after),
│   │   │                        # ranked-best-first within a group since RankedSubgraph.nodes
│   │   │                        # already comes that way. A Method/Dataset's "introduced by
│   │   │                        # Paper" annotation is read off an INTRODUCES edge already in
│   │   │                        # the ranked subgraph (Paper is always its source, per
│   │   │                        # relation_extractor.py's own prompt contract) and folded
│   │   │                        # into the entity line rather than repeated as its own
│   │   │                        # RELATIONSHIPS line; AUTHORED_BY is dropped from
│   │   │                        # RELATIONSHIPS the same way (no evidence/confidence, not
│   │   │                        # useful QA signal alone — the Author node itself still shows
│   │   │                        # under ENTITIES). REPORTS_RESULT's target is a Claim node
│   │   │                        # (pipeline.py synthesizes that edge from entity_extractor's
│   │   │                        # claims directly, not relation_extractor's own text) — skips
│   │   │                        # the generic "(evidence: ...)" suffix other types get, since
│   │   │                        # the claim's own text already IS the evidence and repeating
│   │   │                        # it would duplicate the same sentence on one line.
│   │   │                        # Token budget (8K max, tiktoken's cl100k_base — same
│   │   │                        # encoding chunker.py already uses): ENTITIES/RELATIONSHIPS
│   │   │                        # are never trimmed (RETRIEVAL-003's top_k=20 cap keeps that
│   │   │                        # section small in practice — ponytail: upgrade path if a
│   │   │                        # pathological subgraph ever did blow the budget alone is
│   │   │                        # dropping its lowest-ranked entities first). RELEVANT TEXT
│   │   │                        # CHUNKS (already ranked best-first by vector_retriever/
│   │   │                        # Chroma) are added one at a time, checking the real token
│   │   │                        # count of the whole candidate text each time — exact against
│   │   │                        # what's actually sent, not summed per-line estimates —
│   │   │                        # stopping the moment one more would cross the limit.
│   │   │
│   │   ├── generation/              # Context → Answer
│   │   │   ├── __init__.py
│   │   │   ├── generator.py         # Built RETRIEVAL-005 — generate_answer(query, context)
│   │   │   │                        # takes context_builder.py's BuiltContext, asks the LLM for a
│   │   │   │                        # cited answer. DB-free like vanilla_rag/generator.py: only
│   │   │   │                        # sees context.text (paper titles/entity names/evidence
│   │   │   │                        # already baked in by context_builder.py) — never needs a
│   │   │   │                        # paper_id -> title lookup itself, since the route layer
│   │   │   │                        # resolves citations separately from the same ranked
│   │   │   │                        # subgraph, not by parsing this answer's prose (fragile, and
│   │   │   │                        # can't guarantee the ticket's "citations match actual
│   │   │   │                        # papers" criterion the way reading the graph data directly
│   │   │   │                        # does). System prompt instructs: context-only, cite papers
│   │   │   │                        # by name, reference the specific relationship/chunk, say "I
│   │   │   │                        # don't know" rather than guess. Empty context (nothing
│   │   │   │                        # retrieved from either the graph or vector search) skips the
│   │   │   │                        # LLM call entirely and returns that same message directly —
│   │   │   │                        # same defensive short-circuit vanilla_rag/generator.py
│   │   │   │                        # already uses for zero chunks. Same `from src.utils import
│   │   │   │                        # llm_client` + module-qualified call style as
│   │   │   │                        # vanilla_rag/generator.py, required for the mock_llm_client
│   │   │   │                        # test fixture (module-attribute monkeypatch) to intercept it.
│   │   │   ├── prompts.py           # All prompt templates (extraction, generation, etc.) —
│   │   │   │                        # ENTITY_EXTRACTION_SYSTEM_PROMPT (EXTRACT-001),
│   │   │   │                        # RELATION_EXTRACTION_INTRA_PROMPT/_CROSS_PROMPT
│   │   │   │                        # (EXTRACT-002), and ENTITY_RESOLUTION_VERIFICATION_PROMPT
│   │   │   │                        # (EXTRACT-003 — the resolver's step-4 "are these the same
│   │   │   │                        # real-world entity?" yes/no check) built here, ahead of
│   │   │   │                        # this directory's own generator.py — entity_extractor.py/
│   │   │   │                        # relation_extractor.py/entity_resolver.py (in ingestion/)
│   │   │   │                        # import from here per the ticket's file layout rather
│   │   │   │                        # than keeping prompts local to each module.
│   │   │   └── faithfulness.py      # Check: does answer follow from context? (self-audit)
│   │   │
│   │   ├── vanilla_rag/             # Baseline comparison system — built INGEST-005
│   │   │   ├── __init__.py
│   │   │   ├── retriever.py         # embed query -> query_similar(paper_chunks) -> top-K chunks
│   │   │   │                        # with cosine similarity scores (1 - Chroma's cosine distance)
│   │   │   └── generator.py         # Chunks -> context -> llm_client.complete() -> cited answer.
│   │   │                            # paper_id -> title resolution needs a DB session, so it's
│   │   │                            # done by the route layer, not here — keeps this module
│   │   │                            # DB-free like retriever.py/store.py.
│   │   │
│   │   └── papers/                  # Paper lifecycle logic outside ingestion — built INGEST-007
│   │       ├── __init__.py
│   │       └── deletion.py          # delete_paper(db, paper_id) — the full cascade, as one
│   │                                # function so it's testable independent of the route and
│   │                                # reusable by future account-deletion logic. Order is
│   │                                # leaf-data-first, Postgres row last (PDF file -> Neo4j
│   │                                # orphan cleanup -> Chroma chunks + orphaned entity
│   │                                # embeddings -> Postgres row) — a deliberate deviation from
│   │                                # the ticket's literal 1-PDF/2-Postgres/3-Chroma/4-Neo4j
│   │                                # listing: deleting Postgres first would mean a crash
│   │                                # mid-cascade leaves orphaned files/vectors/graph data with
│   │                                # no record anywhere that they still need cleanup. Neo4j
│   │                                # orphan detection matches the ticket's own suggested Cypher
│   │                                # shape: detach this paper's edges, then delete any neighbor
│   │                                # left with zero remaining relationships. Verified with real
│   │                                # hand-created Neo4j nodes (see test_papers_api.py) since
│   │                                # EXTRACT-004 hasn't landed to populate real ones yet.
│   │
│   ├── models/                      # Database Models (SQLAlchemy for PostgreSQL)
│   │   ├── __init__.py
│   │   ├── base.py                  # Shared DeclarativeBase (added — Alembic autogenerate needs
│   │   │                             # one place that imports every model's metadata)
│   │   ├── paper.py                 # Paper metadata table
│   │   ├── collection.py            # Collection (group of papers)
│   │   ├── extraction_job.py        # Tracks ingestion job status
│   │   ├── query_log.py             # Query history (matches §4.1's query_log table — the
│   │   │                             # original tree omitted this file even though the table
│   │   │                             # was always in the schema)
│   │   └── user.py                  # User accounts (not built — no auth in MVP, see Security §2.1)
│   │
│   ├── repositories/                # Generic CRUD (added SETUP-004 — not in the original tree)
│   │   ├── __init__.py              # instantiates one Repository per model
│   │   └── base.py                  # Repository[Model]: create/get_by_id/list/delete. Only
│   │                                 # flushes, never commits — src/api/dependencies.get_db()
│   │                                 # owns the transaction so multi-row operations in one
│   │                                 # request commit/rollback together.
│   │
│   ├── graph/                       # Neo4j Interaction Layer
│   │   ├── __init__.py
│   │   ├── connection.py            # Neo4j driver setup + session management
│   │   ├── queries.py               # Cypher query templates. PAPER_SUBGRAPH and
│   │   │                            # DELETE_PAPER_CASCADE (INGEST-007) are ahead of the rest —
│   │   │                            # written against §4.2's schema before EXTRACT-004 (graph
│   │   │                            # writer) exists to populate real nodes.
│   │   └── schema.py                # Graph schema initialization (constraints, indexes)
│   │
│   ├── vectorstore/                 # Vector Store Interaction Layer
│   │   ├── __init__.py
│   │   ├── store.py                 # ChromaDB/Qdrant abstraction. Collections created with
│   │   │                            # metadata={"hnsw:space": "cosine"} (INGEST-005 fix) — Chroma
│   │   │                            # defaults to l2, which doesn't match how sentence-transformer
│   │   │                            # embeddings are meant to be compared and doesn't give a
│   │   │                            # bounded score the hybrid scorer (RETRIEVAL-003) can combine
│   │   │                            # with graph distance/confidence. Only takes effect at
│   │   │                            # creation — caught and fixed before any real data existed.
│   │   └── embedder.py              # Text → embedding (OpenAI or local model). warm_up()
│   │                                # (INGEST-005) pre-loads the local model at FastAPI startup —
│   │                                # measured live that a cold model load costs ~10s, which would
│   │                                # otherwise land on whichever request happens to embed first
│   │                                # and blow the vanilla RAG endpoint's <10s latency budget.
│   │
│   ├── tasks/                       # Celery Async Tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Celery configuration. include=["src.tasks.ingest_task"] is
│   │   │                            # required, not decorative — the worker process starts via
│   │   │                            # `celery -A src.tasks.celery_app` and never otherwise imports
│   │   │                            # task modules, so a task defined without being in `include`
│   │   │                            # registers on the API process (which does import it) but the
│   │   │                            # worker rejects it as "unregistered".
│   │   └── ingest_task.py           # litgraph.process_paper — built INGEST-004, reduced to a
│   │                                # thin sync Celery entrypoint in INGEST-006 once
│   │                                # src/services/ingestion/pipeline.py existed to hold the
│   │                                # real orchestration logic.
│   │
│   └── utils/                       # Shared Utilities
│       ├── __init__.py
│       ├── llm_client.py            # Unified LLM client — Gemini (default)/OpenAI/Anthropic/
│       │                            # Groq/OpenRouter, all via the OpenAI SDK against each
│       │                            # provider's OpenAI-compatible endpoint. Retry + rate
│       │                            # limiting live here too (no separate rate_limiter.py — one
│       │                            # small class, one caller, not worth its own file). _KeyRing
│       │                            # (added 2026-08-13, same day EXTRACT-001 measured Gemini's
│       │                            # free tier hitting a ~20-requests/day wall) walks forward
│       │                            # through a provider's key list on a 429 and never goes
│       │                            # back — generic over any provider's key list, not
│       │                            # Gemini-specific: Gemini and Groq both got a 2nd key the
│       │                            # same day (Groq measured hitting its own 100K
│       │                            # tokens/day cap during EXTRACT-002), openai/anthropic stay
│       │                            # single-key. OpenRouter (4th provider, added 2026-08-13
│       │                            # once Gemini and Groq were both near/at their real caps the
│       │                            # same day) is also single-key so far. Switching provider
│       │                            # entirely (e.g. to Groq once both Gemini keys are spent) is
│       │                            # still manual — LLM_PROVIDER + a matching model name; the
│       │                            # OpenRouter switch is a live reminder of a real gap found
│       │                            # doing this same thing for Groq earlier: llm_client passes
│       │                            # `model` straight through with no check that it's actually
│       │                            # valid for whichever provider LLM_PROVIDER currently
│       │                            # selects — already bit GENERATION_MODEL/EXTRACTION_MODEL
│       │                            # once (see routes/query.py's tree comment, RETRIEVAL-005).
│       │                            # Model quality/speed tradeoff measured live on
│       │                            # OpenRouter's free tier: openai/gpt-oss-20b:free produces
│       │                            # correct output (a full real EXTRACT-005 pipeline run
│       │                            # completed successfully on it — real Neo4j graph written)
│       │                            # but is slow, 10-40s/call, ~181s for a full multi-section
│       │                            # paper — over the pipeline's own 90s budget test; a faster
│       │                            # nano model (nvidia/nemotron-nano-9b-v2:free, 6.6s) returned
│       │                            # EMPTY content instead, not investigated further. Free
│       │                            # OpenRouter model slugs rotate in/out — query GET
│       │                            # https://openrouter.ai/api/v1/models and filter for ids
│       │                            # ending ":free" rather than guessing (two guessed llama
│       │                            # slugs 404'd live as "no longer free").
│       ├── llm_json.py              # parse_json_response()/to_confidence() — pulled out of
│       │                            # entity_extractor.py during EXTRACT-002 once
│       │                            # relation_extractor.py needed the exact same "strip
│       │                            # markdown fences, fall back to the outermost {...} block"
│       │                            # recovery logic — one shared helper instead of two copies.
│       └── logging.py               # Structured logging setup
│
├── tests/
│   ├── conftest.py                  # Fixtures (test DB, mock LLM, sample papers) — built SETUP-009.
│   │                                # Test DB is dropped and recreated every session (INGEST-004
│   │                                # fix), not created-once-if-missing — create_all() only adds
│   │                                # tables/types that don't exist, it never ALTERs an existing
│   │                                # Postgres ENUM to add new values, so a test DB left over from
│   │                                # before a model change would silently keep the stale enum and
│   │                                # fail. Also added test_client (httpx wrapping the real FastAPI
│   │                                # app, get_db overridden to the test engine) — built on a fresh
│   │                                # per-request session, not the rollback-based db_session, since
│   │                                # some handlers (POST /ingest/upload) deliberately commit
│   │                                # mid-request.
│   ├── unit/
│   │   ├── test_llm_client.py       # Built SETUP-008 — mocked retry/rate-limit/no-retry-on-auth
│   │   ├── test_fixtures.py         # Built SETUP-009 — proves conftest fixtures actually work
│   │   ├── test_pdf_parser.py       # Built INGEST-001 — synthetic PDF (deterministic, no real
│   │   │                            # papers committed); heuristics separately verified live
│   │   │                            # against 2 real arXiv papers during development
│   │   ├── test_chunker.py          # Built INGEST-002 — hand-built ParsedPaper fixtures,
│   │   │                            # tiny monkeypatched token limits to force multi-chunk cases
│   │   ├── test_retriever.py        # Built INGEST-005 — mocked Chroma response
│   │   ├── test_generator.py        # Built INGEST-005 — mock_llm_client fixture
│   │   ├── test_embedder.py         # Built INGEST-005 — warm_up()'s provider branching only
│   │   ├── test_entity_extractor.py # Built EXTRACT-001 — mocked LLM (mock_llm_client), covers
│   │   │                            # JSON parsing (plain/fenced/prose-wrapped), confidence-
│   │   │                            # threshold filtering, invalid-claim-type dropping, the
│   │   │                            # retry-once-then-empty behavior on unparseable responses.
│   │   │                            # Real prompt-quality verification against 5 live papers was
│   │   │                            # done separately (see entity_extractor.py's tree comment) —
│   │   │                            # not re-run on every test pass, real Gemini calls cost quota.
│   │   ├── test_relation_extractor.py # Built EXTRACT-002 — mocked LLM, covers both passes:
│   │   │                            # intra defaulting source to "paper", EVALUATES_ON keeping
│   │   │                            # metric/value/method in properties, OUTPERFORMS keeping
│   │   │                            # metric/dataset/margin, cross-paper target filtered to the
│   │   │                            # given candidate list (code-enforced, not just prompted),
│   │   │                            # confidence filtering, retry-once-then-empty. Real
│   │   │                            # prompt-quality verification (2 rounds, live) against the
│   │   │                            # same 5 papers as EXTRACT-001 was done separately — see
│   │   │                            # relation_extractor.py's tree comment for the 2 real issues
│   │   │                            # it caught and fixed.
│   │   ├── test_entity_resolver.py  # Built EXTRACT-003 — mocked LLM + mocked embed(), 14
│   │   │                            # tests: exact/case/whitespace matching, entity_type
│   │   │                            # isolation, fuzzy+LLM and embedding+LLM merge/reject
│   │   │                            # paths, the suffix-variant and acronym-variant pattern
│   │   │                            # checks (each with a boundary-safety negative test),
│   │   │                            # merge logic (shorter canonical, union aliases, longest
│   │   │                            # description), multi-candidate ranking/fallthrough, an
│   │   │                            # acronym-collision case that reaches the LLM rather than
│   │   │                            # auto-merging. Real threshold calibration (see
│   │   │                            # entity_resolver.py's tree comment) was done live against
│   │   │                            # real embeddings/LLM calls, not re-run on every test pass.
│   │   ├── test_vector_retriever.py # Built RETRIEVAL-001 — mocked query_similar (both
│   │   │                            # collections), covers: combining entity+chunk seeds,
│   │   │                            # empty-graph fallback to chunks-only, paper_ids dedup when
│   │   │                            # the same paper appears via both an entity's source_papers
│   │   │                            # and a chunk's own paper_id, fully-empty-corpus case.
│   │   ├── test_hybrid_scorer.py    # Built RETRIEVAL-003 — pure computation over hand-built
│   │   │                            # Subgraph/SeedResult fixtures, no I/O needed (unlike
│   │   │                            # graph_writer.py/graph_retriever.py, this module never
│   │   │                            # touches Neo4j/Chroma itself). 5 tests: all three signals
│   │   │                            # combine per the formula, weights overridable per call,
│   │   │                            # output ranked with top_k truncation dropping edges to
│   │   │                            # excluded nodes, ties broken by Method > Paper > Dataset,
│   │   │                            # a Paper node inheriting its best matching chunk's score.
│   │   ├── test_context_builder.py  # Built RETRIEVAL-004 — pure computation over hand-built
│   │   │                            # RankedSubgraph/SeedResult fixtures, no I/O (same rationale
│   │   │                            # as test_hybrid_scorer.py). 6 tests: Method's "introduced
│   │   │                            # by Paper" annotation + evidence text on a generic relation
│   │   │                            # line, EVALUATES_ON/OUTPERFORMS's metric/value/dataset/
│   │   │                            # margin formatting matches the ticket's own example exactly,
│   │   │                            # REPORTS_RESULT skips the redundant evidence suffix,
│   │   │                            # AUTHORED_BY excluded from RELATIONSHIPS but its Author node
│   │   │                            # still listed under ENTITIES, chunk inclusion + graceful
│   │   │                            # truncation under a deliberately tight token budget, empty
│   │   │                            # graph falling back to a chunks-only context.
│   │   └── test_graphrag_generator.py # Built RETRIEVAL-005 — mock_llm_client fixture, same
│   │                                # pattern as test_generator.py (vanilla's). Named
│   │                                # test_graphrag_generator.py, not test_generator.py, since
│   │                                # both live in tests/unit/ and a directory can't hold two
│   │                                # files with the same name. 2 tests: LLM called with the
│   │                                # BuiltContext's text in the prompt, empty context skips the
│   │                                # LLM call entirely and returns "I don't know" directly.
│   ├── integration/
│   │   ├── __init__.py               # Added RETRIEVAL-001 (alongside tests/__init__.py and
│   │   │                             # tests/unit/__init__.py) — pytest's default import mode
│   │   │                             # can't tell apart two test files sharing a basename in
│   │   │                             # different directories without one; hit live the moment
│   │   │                             # this ticket added tests/unit/test_vector_retriever.py
│   │   │                             # alongside tests/integration/test_vector_retriever.py
│   │   │                             # ("import file mismatch" on collection). Making tests/ a
│   │   │                             # real package fixes it for any future same-name pair too,
│   │   │                             # not just this one.
│   │   ├── conftest.py               # Built EXTRACT-004 — close_neo4j_driver_after_test fixture
│   │   │                             # (see graph_writer.py's tree comment for the "different event
│   │   │                             # loop" bug this fixes). Opt-in via
│   │   │                             # pytest.mark.usefixtures(...), NOT autouse — this directory
│   │   │                             # also has test_embedding_storage.py, whose tests are sync and
│   │   │                             # never touch Neo4j; an autouse *async* fixture requested by a
│   │   │                             # *sync* test isn't handled by any pytest plugin and warns
│   │   │                             # it'll be a hard error in pytest 9 (found live making it
│   │   │                             # autouse first). test_graph_writer.py, test_papers_api.py,
│   │   │                             # and (EXTRACT-005) test_ingestion_pipeline.py opt in — the
│   │   │                             # files that actually call get_driver().
│   │   ├── test_embedding_storage.py # Built INGEST-003 — talks to the real ChromaDB
│   │   │                             # container, not a mock (that's the actual thing worth
│   │   │                             # verifying: add/get(where=)/duplicate-skip against
│   │   │                             # Chroma's real API)
│   │   ├── test_ingest_api.py        # Built INGEST-004 — real HTTP requests via httpx against
│   │   │                             # the real FastAPI app + test DB. process_paper.delay is
│   │   │                             # mocked (this ticket's scope is "dispatch correctly", not
│   │   │                             # "the task ran"). Covers upload success/rejection, file-
│   │   │                             # count limit, status endpoint, and the Paper+ExtractionJob
│   │   │                             # atomicity guarantee (forces a failure between the two
│   │   │                             # creates, asserts the Paper doesn't survive it either).
│   │   ├── test_ingestion_pipeline.py # Built INGEST-004, renamed from test_ingest_task.py in
│   │   │                             # INGEST-006 to match pipeline.py — the real parse->chunk
│   │   │                             # ->embed logic against the real test DB and real ChromaDB,
│   │   │                             # using a synthetic PDF. Covers completed, failed
│   │   │                             # (bad pdf_path), unknown-job-id, and (INGEST-006) partial-
│   │   │                             # chunk cleanup on failure — simulates one chunk actually
│   │   │                             # landing in Chroma before a later step blows up, asserts
│   │   │                             # zero chunks remain for that paper afterward.
│   │   │                             # test_pipeline_extracts_and_writes_real_graph (EXTRACT-005):
│   │   │                             # no mocks anywhere — real LLM, real Neo4j, real Chroma — the
│   │   │                             # one test proving the full parse->chunk->embed->extract->
│   │   │                             # relate->resolve->write chain actually connects end to end.
│   │   │                             # See pipeline.py's tree comment for what it found live
│   │   │                             # (the candidate-seeding bug, real Gemini rate limiting).
│   │   │                             # Cleanup is relationship-scoped, same orphan-safety pattern
│   │   │                             # as DELETE_PAPER_CASCADE (only deletes a Method/Dataset
│   │   │                             # connected to this test's paper if it has no connection to
│   │   │                             # any OTHER paper) rather than name-substring matching — an
│   │   │                             # earlier name-substring version missed entities the LLM
│   │   │                             # extracted under names the test didn't anticipate (e.g.
│   │   │                             # "transformer" from the Method section text) and they
│   │   │                             # leaked into the dev graph across repeated live runs before
│   │   │                             # being caught and cleaned up by hand.
│   │   ├── test_query_api.py         # Built INGEST-005 — real HTTP request against the real
│   │   │                             # FastAPI app + real ChromaDB, mocked LLM. Live-verified
│   │   │                             # separately (not in this file — needs a running worker +
│   │   │                             # real Gemini key) that a real end-to-end query answers
│   │   │                             # coherently with citations in ~2.5-4.5s once warmed up.
│   │   ├── test_papers_api.py        # Built INGEST-007 — real HTTP requests against the real
│   │   │                             # FastAPI app + test Postgres + real ChromaDB + real Neo4j.
│   │   │                             # Covers list/filter-by-collection, detail (sections present,
│   │   │                             # entities/relationships correctly empty pending
│   │   │                             # EXTRACT-004), 404s, and full delete cascade (PDF file,
│   │   │                             # Postgres row, Chroma chunks). The shared-entity acceptance
│   │   │                             # test hand-creates Method/Claim nodes matching §4.2's schema
│   │   │                             # (no pipeline writes real ones yet), deletes one of two
│   │   │                             # papers, and proves against real Neo4j that the shared
│   │   │                             # Method survives while the paper-exclusive Claim is deleted.
│   │   ├── test_graph_writer.py      # Built EXTRACT-004 — real Neo4j + real Chroma containers,
│   │   │                             # no mocks (the ticket wants a direct Chroma query proving
│   │   │                             # the embedding write, not just a Neo4j check). 6 tests:
│   │   │                             # write_paper idempotency (reprocess updates, doesn't
│   │   │                             # duplicate, and overwrites via SET n +=), write_named_entity
│   │   │                             # merge-on-reprocess + Chroma upsert with accumulating
│   │   │                             # source_papers, Author/Metric correctly getting neither
│   │   │                             # embedding nor a Chroma row, write_claim content-hash dedup,
│   │   │                             # write_authors' MERGE+AUTHORED_BY edges, and
│   │   │                             # write_relationship's confidence/evidence_text properties.
│   │   │                             # Surfaced a real, general bug — see graph_writer.py's tree
│   │   │                             # comment and tests/integration/conftest.py.
│   │   ├── test_review_extraction.py # Built EXTRACT-006 — real Postgres + real Neo4j (candidate
│   │   │                             # fetch has no quota cost), mocked LLM: a formatting/wiring
│   │   │                             # check, not a prompt-quality one — the script itself is the
│   │   │                             # tool for that, meant to be run manually against real LLM
│   │   │                             # calls. 3 tests: missing paper, unparsed paper (no
│   │   │                             # sections), and entities/relations/resolution-decisions all
│   │   │                             # printed correctly for a mocked extraction. Real live run
│   │   │                             # also done separately (not in this file) against a real
│   │   │                             # Groq call — see review_extraction.py's tree comment.
│   │   ├── test_vector_retriever.py  # Built RETRIEVAL-001 — real ChromaDB + real local
│   │   │                             # embedding model, no mocks: proves retrieve_seeds() finds
│   │   │                             # a genuine semantic match (a hand-added "BERT" entity +
│   │   │                             # chunk, queried with "What is BERT?") against a real HNSW
│   │   │                             # index, not just that it parses a mocked Chroma response
│   │   │                             # shape — that's what the unit test file covers.
│   │   ├── test_graph_retriever.py   # Built RETRIEVAL-002 — real Neo4j, no mocks. Graph built
│   │   │                             # directly via Cypher (not graph_writer.py — this suite is
│   │   │                             # about traversal/filtering/capping, not write-idempotency).
│   │   │                             # 6 tests: 2-hop traversal reaches nodes at both hop
│   │   │                             # distances, paper_id seed resolves to the Paper node's
│   │   │                             # elementId, relationship_types keeps only matching edges,
│   │   │                             # an unknown relationship_types entry returns empty rather
│   │   │                             # than silently matching everything, max_nodes keeps the
│   │   │                             # highest-confidence edges first, empty seeds short-circuit
│   │   │                             # without a Neo4j round-trip.
│   │   ├── test_graphrag_query_api.py # Built RETRIEVAL-005 — real HTTP request through the real
│   │   │                             # FastAPI app, real Postgres/Neo4j/ChromaDB, mocked LLM
│   │   │                             # (mock_llm_client), same overall pattern test_query_api.py
│   │   │                             # uses for /query/vanilla. Proves the full retrieve_seeds ->
│   │   │                             # retrieve_subgraph -> score_subgraph -> build_context ->
│   │   │                             # generate_answer chain actually connects end to end against
│   │   │                             # real infrastructure, not just that each stage's own unit
│   │   │                             # tests pass in isolation — hand-creates a real Paper+Method
│   │   │                             # node + USES_METHOD edge in Neo4j, a matching Chroma entity
│   │   │                             # embedding and chunk, and a matching Postgres Paper row,
│   │   │                             # then asserts the response's answer/citations/
│   │   │                             # retrieved_subgraph/retrieval_stats all reflect it. Setup/
│   │   │                             # cleanup lives inline in the test (try/finally), not a
│   │   │                             # shared autouse fixture — a first draft used one and its
│   │   │                             # yield-based Neo4j cleanup ran *after*
│   │   │                             # close_neo4j_driver_after_test had already closed the driver
│   │   │                             # (fixture teardown order between an autouse fixture and a
│   │   │                             # usefixtures-marked one isn't guaranteed), caught live via a
│   │   │                             # "driver already closed" DeprecationWarning on an otherwise-
│   │   │                             # passing run; rewritten to match test_graph_writer.py/
│   │   │                             # test_graph_retriever.py's own inline try/finally pattern,
│   │   │                             # which sidesteps the ordering question entirely.
│   │   ├── test_query_compare_api.py # Built RETRIEVAL-006 — real HTTP request, real Postgres/
│   │   │                             # ChromaDB, mocked LLM. The one thing worth proving for real
│   │   │                             # (a shape-only check wouldn't catch it): the mocked LLM call
│   │   │                             # is made to sleep 0.3s, and wall-clock time for the whole
│   │   │                             # /query/compare request is asserted between 0.9x and 1.8x
│   │   │                             # that single sleep — proves the two pipelines' LLM calls
│   │   │                             # actually overlap (measured ~0.48s) rather than serializing
│   │   │                             # (would measure ~0.6s+ real DB/Chroma overhead on each side).
│   │   ├── test_retrieval_pipeline.py
│   │   └── test_graph_api.py          # Built GRAPH-001 — real HTTP requests, real Neo4j, hand-
│   │                                   # built Cypher fixtures (same pattern as
│   │                                   # test_graph_retriever.py). 7 tests: overview counts include
│   │                                   # a fixture Paper/Method/edge, subgraph expansion returns a
│   │                                   # correct usage_count (Method used by 2 papers -> 2),
│   │                                   # subgraph 404 for an unknown entity_id, entity detail
│   │                                   # returns its relationships + usage_count with direction,
│   │                                   # entity 404, fulltext search finds a tagged fixture and
│   │                                   # respects the type filter, unknown type -> 400.
│   └── eval/
│       ├── eval_dataset.json         # 50 multi-hop questions with gold answers
│       ├── run_eval.py               # Run both systems, score, output comparison
│       └── eval_results/             # Stored evaluation results
│
├── frontend/                        # React Frontend — scaffold built FE-001
│   │                                 # (Vite + React 18 + TS, hand-written rather than the
│   │                                 # interactive `npm create vite` wizard — more reliable in a
│   │                                 # non-interactive shell and no functional difference).
│   │                                 # `npm run dev` verified live (curl 200 on / and on Vite's
│   │                                 # dev-transformed .tsx/.css endpoints — confirms Tailwind +
│   │                                 # the shadcn/ui token pipeline actually processes our
│   │                                 # classes, not just that the config files exist); `npm run
│   │                                 # build`/`typecheck` also verified clean. `npm audit` flags
│   │                                 # 4 moderate/high advisories (esbuild dev-server-only
│   │                                 # request forgery, react-router open-redirect/SSR-hydration)
│   │                                 # — both require either a breaking major bump (vite 5→8) or
│   │                                 # don't apply to this app's usage (no SSR, no untrusted
│   │                                 # redirect targets); left as a known, disclosed tradeoff
│   │                                 # rather than forcing an untested major-version jump for a
│   │                                 # local-only dev tool. hooks/ and stores/ (Zustand — package
│   │                                 # installed per the ticket, no store files yet) stay empty:
│   │                                 # no real page has a consumer for either until FE-002/FE-003
│   │                                 # actually need one — YAGNI, not an oversight. No test
│   │                                 # framework added either — FE-001 has no real branching
│   │                                 # logic yet (declarative routes, a trivial cn() helper), and
│   │                                 # `npm run dev`/`build`/`typecheck` already ran live as this
│   │                                 # ticket's actual verification.
│   ├── package.json
│   ├── vite.config.ts                # dev server port 3000 (ticket's own acceptance criterion),
│   │                                  # @/ alias -> src/
│   ├── tsconfig.json                 # references app + node configs (standard Vite split, so
│   │                                  # vite.config.ts's Node-only globals don't leak into
│   │                                  # browser-side type-checking)
│   ├── tsconfig.app.json
│   ├── tsconfig.node.json
│   ├── tailwind.config.js            # shadcn/ui's CSS-variable color tokens (values in
│   │                                  # index.css) + entity-type colors (04_FRONTEND_
│   │                                  # SPECIFICATION.md §3.1), ready for GRAPH-002/FE-004
│   ├── postcss.config.js
│   ├── components.json               # shadcn CLI config — lets `npx shadcn add <component>`
│   │                                  # drop future components (Card, Dialog, Badge, ...) into
│   │                                  # components/ui/ matching this project's aliases, without
│   │                                  # hand-writing each one the way button.tsx was
│   ├── index.html
│   ├── .env.example                  # VITE_API_URL
│   ├── public/
│   │   └── favicon.svg
│   └── src/
│       ├── main.tsx                  # QueryClientProvider + BrowserRouter root
│       ├── App.tsx                   # Route table (4 tabs + / -> /chat redirect), global
│       │                              # layout shell (header + flex-1 main, per 04_FRONTEND_
│       │                              # SPECIFICATION.md §4.1's "no outer scroll" rule)
│       ├── index.css                 # Tailwind directives + shadcn light/dark CSS variables —
│       │                              # primary set to the brand blue (#2563EB) rather than
│       │                              # shadcn's near-black default, dark theme pre-wired so
│       │                              # POLISH-003's toggle is just a class swap. Also a small
│       │                              # hand-rolled `.markdown` block (FE-003) styling react-
│       │                              # markdown's output — chose this over adding the
│       │                              # @tailwindcss/typography plugin since only 5 element
│       │                              # kinds needed styling (headers/bold/italic/code/lists).
│       ├── vite-env.d.ts
│       ├── lib/
│       │   └── utils.ts              # cn() — shadcn's standard clsx+tailwind-merge helper
│       ├── components/
│       │   ├── Header.tsx            # Sticky nav (4 tabs, active-tab styling via NavLink).
│       │   │                          # UserMenu/dark-mode toggle is a disabled placeholder
│       │   │                          # button (real one lands POLISH-003) — kept disabled
│       │   │                          # rather than omitted so it doesn't look like a live,
│       │   │                          # working control that silently does nothing.
│       │   └── ui/
│       │       └── button.tsx        # First real shadcn/ui component — proves the pattern
│       │                              # renders correctly (this ticket's own acceptance
│       │                              # criterion); more added the same way as pages need them,
│       │                              # not all pre-built now with no caller (Card/Dialog/Badge/
│       │                              # etc. per 04_FRONTEND_SPECIFICATION.md §3.4)
│       ├── pages/
│       │   ├── ChatPage.tsx          # FE-003: message history, markdown answers, citation
│       │   │                          # cards, auto-resize input, typing indicator, inline
│       │   │                          # error+retry. No collection selector — retrieval is
│       │   │                          # global (RETRIEVAL-001's MVP scoping decision), so a
│       │   │                          # selector here would either do nothing or misleadingly
│       │   │                          # imply filtering; add once POLISH-005b lands per-
│       │   │                          # collection retrieval.
│       │   ├── GraphPage.tsx         # GRAPH-002: search box + GraphCanvas — a minimal real
│       │   │                          # consumer proving the canvas actually works end to end,
│       │   │                          # not the full toolbar/filters/legend/entity-sidebar page
│       │   │                          # (that's GRAPH-003's separate 2-day scope).
│       │   ├── PapersPage.tsx        # FE-002: native drag-and-drop upload zone (no react-
│       │   │                          # dropzone — HTML5 DnD events cover the AC), paper list
│       │   │                          # polling GET /papers (not the per-job status endpoint —
│       │   │                          # no job_id survives a page refresh) while anything is
│       │   │                          # pending/processing, stats card, delete via
│       │   │                          # window.confirm(). ArXiv URL input rendered disabled
│       │   │                          # ("coming soon") — POST /ingest/arxiv is POLISH-004's
│       │   │                          # scope and doesn't exist yet, so the ticket's own ArXiv
│       │   │                          # AC is deliberately deferred rather than faked.
│       │   └── ComparePage.tsx       # Placeholder — real side-by-side comparison lands COMPARE-001
│       ├── store/
│       │   └── chatStore.ts          # FE-003: Zustand store, owns the send/retry API-call
│       │                              # logic (not just state) so ChatPage stays a dumb view.
│       │                              # Session-only — no persist middleware, matches the
│       │                              # ticket's own "preserved during session" AC, not more.
│       │                              # ChatMessage also carries retrievedSubgraph (FE-004)
│       │                              # straight from QueryResponse, no separate fetch.
│       ├── lib/
│       │   ├── entityColors.ts       # Entity-label -> Tailwind border/text class map + a
│       │   │                          # displayName() properties fallback chain — centralized
│       │   │                          # (FE-004) once a 3rd consumer (ContextPanel) needed the
│       │   │                          # same map PaperDetailModal/EntityDetailModal already had.
│       │   ├── graphElements.ts      # GRAPH-002: node/edge styling tables (04_FRONTEND_
│       │   │                          # SPECIFICATION.md §4.3) + the pure nodes/edges ->
│       │   │                          # Cytoscape-elements mapping (nodeSize/edgeLabel/
│       │   │                          # toElements), split out of GraphCanvas.tsx so it's
│       │   │                          # testable without mounting a real DOM/Cytoscape instance.
│       │   │                          # Uses explicit `.ts`-extension relative imports
│       │   │                          # (allowImportingTsExtensions) — graphElements.check.ts
│       │   │                          # runs directly under plain `node`, no bundler to resolve
│       │   │                          # extension-less specifiers for it.
│       │   └── graphElements.check.ts # Manual self-check (assert-based, no test framework in
│       │                              # this project) for graphElements.ts's branching logic —
│       │                              # Claim's fixed size, usage_count sqrt-scaling/clamping,
│       │                              # EVALUATES_ON/OUTPERFORMS's property-built labels,
│       │                              # toElements dropping an edge that points outside the
│       │                              # given node set. Run: `node src/lib/graphElements.check.ts`
│       ├── components/
│       │   ├── PaperDetailModal.tsx  # FE-002: native <dialog> (not a Radix Dialog — none
│       │   │                          # installed yet) for X/Escape/outside-click close for free.
│       │   ├── GraphCanvas.tsx       # GRAPH-002: Cytoscape.js wrapper, shared by FE-004's mini
│       │   │                          # panel and GRAPH-003's full explorer. Built-in `cose`
│       │   │                          # layout (force-directed, ships with cytoscape core — no
│       │   │                          # extra layout plugin dependency). Double-click-to-expand
│       │   │                          # calls GET /graph/subgraph (GRAPH-001) itself, so every
│       │   │                          # consumer gets the same expand behavior for free. Double-
│       │   │                          # tap detected manually via a timestamp ref (300ms) —
│       │   │                          # cytoscape has no native dblclick event. Hover tooltip is
│       │   │                          # a plain positioned div (no cytoscape-popper/Tippy.js),
│       │   │                          # repositioned via renderedPosition() on the node's own
│       │   │                          # `position` event plus the core-level `pan`/`zoom` events
│       │   │                          # (which don't fire through a delegated node selector, so
│       │   │                          # the hovered id is tracked separately for those). Responsive
│       │   │                          # via ResizeObserver -> cy.resize(). cytoscape ships its own
│       │   │                          # TS types (no separate @types/cytoscape needed).
│       │   ├── ContextPanel.tsx      # FE-004: sources list + color-coded entity tags for the
│       │   │                          # latest answer, placeholder container for GRAPH-004's
│       │   │                          # Cytoscape canvas (no Cytoscape code here — that ticket's
│       │   │                          # own scope note). One `collapsed` boolean drives both a
│       │   │                          # lg+ sidebar (narrows to an icon strip) and a <lg bottom
│       │   │                          # sheet (slides to a pull-tab) via Tailwind `lg:` classes —
│       │   │                          # no JS media-query listener.
│       │   └── EntityDetailModal.tsx # FE-005: same native <dialog> pattern. Scoped to the
│       │                              # *current answer's* retrieved subgraph (nodes/edges
│       │                              # QueryResponse already returned) — "related entities" and
│       │                              # "source papers" mean within this answer's context, not
│       │                              # the full graph, since global per-entity lookup is
│       │                              # GRAPH-001's scope and isn't built. Clicking a related
│       │                              # entity swaps the modal's content in place (the ticket's
│       │                              # own documented alternative to navigating to a Graph page
│       │                              # that doesn't exist yet either).
│       ├── services/
│       │   └── api.ts                # Axios client, VITE_API_URL base (04_FRONTEND_
│       │                              # SPECIFICATION.md §7.1 — no auth interceptors, MVP has no
│       │                              # auth). Only wraps endpoints that exist today
│       │                              # (RETRIEVAL-005/006, INGEST-004, papers list/detail/
│       │                              # delete) — graph/collections calls land with their own
│       │                              # tickets (GRAPH-001, POLISH-005) rather than being stubbed
│       │                              # against routes that would just 404.
│       └── types/
│           └── index.ts              # Mirrors src/api/schemas/query.py and papers.py's
│                                      # PaperListItem/PaperDetail/PaperEntity/PaperRelationship —
│                                      # kept to what api.ts actually consumes
│                                      # today, extended per-field as later pages need more.
│
├── scripts/
│   ├── review_extraction.py          # Built EXTRACT-006 — `python -m scripts.review_extraction
│   │                                  # <paper_id>`. Developer tool, not user-facing: re-runs
│   │                                  # entity extraction -> relation extraction -> entity
│   │                                  # resolution for an already-parsed paper (paper.sections
│   │                                  # populated) and prints a human-readable, color-coded
│   │                                  # review (green >=0.8, yellow 0.5-0.8, red <0.5 confidence)
│   │                                  # of every entity/relation/resolution decision — used to
│   │                                  # iterate on prompt wording without a real ingest each
│   │                                  # time. Never writes to Neo4j/Chroma: reuses
│   │                                  # extract_entities/extract_intra_paper_relations/
│   │                                  # extract_cross_paper_relations/resolve_entity/
│   │                                  # fetch_candidate_entities exactly as pipeline.py
│   │                                  # (EXTRACT-005) does, so "what this script shows" and
│   │                                  # "what a real ingest would decide" can't drift apart —
│   │                                  # just skips the graph_writer.write_* calls, a deliberate
│   │                                  # dry run, verified live (no graph_writer.* log lines, zero
│   │                                  # Neo4j writes confirmed by direct query after a real run
│   │                                  # against real Groq calls). REPORTS_RESULT relations print
│   │                                  # with their relation_extractor-derived target text here
│   │                                  # (unlike pipeline.py, which synthesizes that edge directly
│   │                                  # from entity_extractor's claims instead) — this script is
│   │                                  # a read-only report, not a graph write, so there's no
│   │                                  # target-node-identity problem to work around.
│   ├── seed_sample_papers.py         # Download + ingest sample paper set for demos
│   ├── export_graph.py               # Export Neo4j graph to JSON
│   └── run_eval.sh                   # Full evaluation pipeline script
│
├── docs/
│   ├── 01_PRD.md
│   ├── 02_TECHNICAL_ARCHITECTURE.md
│   ├── 03_SECURITY_ACCESS.md
│   ├── 04_FRONTEND_SPECIFICATION.md
│   ├── 05_FEATURE_TICKETS.md
│   └── API.md                        # Auto-generated from FastAPI (OpenAPI spec)
│
└── README.md                         # Setup instructions, architecture overview, demo
```

---

## 4. Database Design

### 4.1 PostgreSQL Schema (Relational Data)

```sql
-- Papers metadata (source of truth for paper info)
CREATE TABLE papers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    authors         JSONB NOT NULL,           -- ["Author A", "Author B"]
    year            INTEGER,
    venue           TEXT,
    arxiv_id        TEXT UNIQUE,
    doi             TEXT UNIQUE,
    abstract        TEXT,
    pdf_path        TEXT NOT NULL,             -- Path to stored PDF
    raw_text        TEXT,                      -- Full extracted text
    sections        JSONB,                     -- {"introduction": "...", "method": "..."}
    ingestion_status ENUM('pending','processing','completed','failed'),
    collection_id   UUID REFERENCES collections(id) ON DELETE SET NULL,  -- deleting a collection
                                                       -- must not delete or block-delete its papers
                                                       -- (POLISH-005: "delete collection, papers remain")
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Paper collections
CREATE TABLE collections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Extraction job tracking
CREATE TABLE extraction_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id        UUID REFERENCES papers(id) ON DELETE CASCADE,
    status          ENUM('queued','parsing','chunking','embedding','extracting_entities',
                         'extracting_relations','resolving_entities','writing_graph',
                         'completed','failed'),
                    -- parsing/chunking/embedding added INGEST-004 (migration 7a1e9c2b4d8f) —
                    -- the original list jumped straight from queued to extracting_entities,
                    -- leaving no way to report progress during Epic 1's own processing steps.
    entities_found  INTEGER DEFAULT 0,
    relations_found INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Query history (for self-improvement feedback loop — future)
CREATE TABLE query_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT NOT NULL,
    graphrag_answer TEXT,
    vanilla_answer  TEXT,
    retrieved_nodes JSONB,                    -- Node IDs used in answer
    user_feedback   ENUM('good','bad','none') DEFAULT 'none',
    latency_ms      INTEGER,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_papers_collection ON papers(collection_id);
CREATE INDEX idx_papers_arxiv ON papers(arxiv_id);
CREATE INDEX idx_papers_status ON papers(ingestion_status);
CREATE INDEX idx_jobs_paper ON extraction_jobs(paper_id);
CREATE INDEX idx_jobs_status ON extraction_jobs(status);
```

### 4.2 Neo4j Graph Schema

```cypher
// Constraints (enforce uniqueness)
CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE;
CREATE CONSTRAINT method_canonical IF NOT EXISTS FOR (m:Method) REQUIRE m.canonical_name IS UNIQUE;
CREATE CONSTRAINT dataset_canonical IF NOT EXISTS FOR (d:Dataset) REQUIRE d.canonical_name IS UNIQUE;
CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE;

// Indexes (speed up lookups)
CREATE INDEX paper_title IF NOT EXISTS FOR (p:Paper) ON (p.title);
CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year);
CREATE INDEX method_category IF NOT EXISTS FOR (m:Method) ON (m.category);
CREATE INDEX dataset_domain IF NOT EXISTS FOR (d:Dataset) ON (d.domain);

// Full-text search indexes
CREATE FULLTEXT INDEX paper_search IF NOT EXISTS FOR (p:Paper) ON EACH [p.title, p.abstract];
CREATE FULLTEXT INDEX method_search IF NOT EXISTS FOR (m:Method) ON EACH [m.canonical_name, m.description];
// Added GRAPH-001 — GET /graph/search needs to rank-search these labels too:
CREATE FULLTEXT INDEX dataset_search IF NOT EXISTS FOR (d:Dataset) ON EACH [d.canonical_name, d.description];
CREATE FULLTEXT INDEX author_search IF NOT EXISTS FOR (a:Author) ON EACH [a.name];
CREATE FULLTEXT INDEX claim_search IF NOT EXISTS FOR (c:Claim) ON EACH [c.text];

// Node structure examples:
// (:Paper {paper_id, title, authors, year, venue, abstract, embedding: [float]})
// (:Method {canonical_name, aliases: [string], category, description, embedding: [float]})
// (:Dataset {canonical_name, aliases: [string], domain, description, embedding: [float]})
// (:Claim {text, claim_type, source_paper_id, embedding: [float]})
// (:Author {name, aliases: [string], affiliations: [string]})
// (:Metric {name, higher_is_better: boolean})

// Relationship structure examples:
// (p1:Paper)-[:CITES {confidence: 0.95}]->(p2:Paper)
// (p:Paper)-[:USES_METHOD {evidence_text: "...", confidence: 0.88}]->(m:Method)
// (p:Paper)-[:EVALUATES_ON {metric: "F1", value: 92.3, evidence_text: "..."}]->(d:Dataset)
// (m1:Method)-[:OUTPERFORMS {metric: "accuracy", dataset: "ImageNet", margin: 2.1}]->(m2:Method)
// (p:Paper)-[:INTRODUCES {evidence_text: "..."}]->(m:Method)
// (m1:Method)-[:EXTENDS {evidence_text: "...", confidence: 0.82}]->(m2:Method)
// (c1:Claim)-[:CONTRADICTS {evidence_text: "...", confidence: 0.75}]->(c2:Claim)
```

### 4.3 Vector Store Schema (ChromaDB)

```python
# Collection: paper_chunks
# Each chunk stores:
{
    "id": "chunk_{paper_id}_{chunk_index}",
    "document": "chunk text content...",
    "embedding": [0.012, -0.034, ...],  # 1536-dim (OpenAI) or 384-dim (MiniLM)
    "metadata": {
        "paper_id": "uuid",
        "paper_title": "Attention Is All You Need",
        "section": "methodology",
        "chunk_index": 3,
        "page_number": 4
    }
}

# Collection: entity_embeddings
# Each entity (method/dataset/claim) also stored with embedding for vector search
{
    "id": "entity_{neo4j_node_id}",
    "document": "entity description or canonical name + context",
    "embedding": [0.012, -0.034, ...],
    "metadata": {
        "entity_type": "Method",
        "canonical_name": "BERT",
        "source_papers": "uuid1,uuid2"  # comma-joined string, not a list — Chroma metadata
                                         # values must be str/int/float/bool (EXTRACT-004,
                                         # graph_writer.py, found live)
    }
}
```

---

## 5. Core Pipeline Details

### 5.1 Ingestion Pipeline (paper → graph)

```
PDF Upload
    │
    ▼
┌─────────────────────────────────────────────────┐
│ Step 1: PDF Parsing (PyMuPDF)                    │
│                                                  │
│ Input:  PDF file                                 │
│ Output: {                                        │
│   title, authors, year, venue, abstract,         │
│   sections: {intro: "...", method: "...", ...},  │
│   references: ["ref1", "ref2", ...],             │
│   tables: [{headers: [...], rows: [...]}]        │
│ }                                                │
│                                                  │
│ Strategy (MVP):                                  │
│ - PyMuPDF + heuristic section detection          │
│   (bold/large text → section header patterns)    │
│ - Extract tables separately (camelot / PyMuPDF)  │
│ - Fallback: if section detection fails, treat    │
│   entire text as one section                     │
│                                                  │
│ NOT implemented in MVP: GROBID. Considered as a  │
│ future upgrade for higher-quality academic-aware │
│ parsing, but adds a heavy Java service + no       │
│ docker-compose entry exists for it yet. See       │
│ §2.1 tech stack table for status.                │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 2: Chunking                                 │
│                                                  │
│ Strategy: Section-aware chunking                 │
│ - Primary split: by section (intro, method,      │
│   results, etc.)                                 │
│ - Secondary split: if section > 1500 tokens,     │
│   split into overlapping chunks (1000 tokens,    │
│   200 token overlap)                             │
│ - Keep section label as metadata                 │
│ - Tables: stringify as markdown, keep as         │
│   separate chunks with "table" section label     │
│                                                  │
│ Output: List[{text, section, chunk_index, page}] │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 3: Embedding + Vector Store                 │
│                                                  │
│ - Embed each chunk → ChromaDB                    │
│ - This enables vanilla RAG (baseline) AND        │
│   provides seed vectors for hybrid retrieval     │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 4: Entity Extraction (LLM)                  │
│                                                  │
│ Process per section (not per chunk — sections     │
│ have better context for extraction):              │
│                                                  │
│ Prompt (simplified):                             │
│ """                                              │
│ Given this section of a research paper,          │
│ extract all entities:                            │
│                                                  │
│ METHODS: Any model, algorithm, technique,        │
│   architecture, or approach mentioned.           │
│   Include: name, brief description, whether      │
│   this paper introduces it or just uses it.      │
│                                                  │
│ DATASETS: Any dataset, benchmark, or corpus.     │
│   Include: name, domain.                         │
│                                                  │
│ METRICS: Any evaluation metric with its value.   │
│   Include: metric name, value, which method,     │
│   which dataset.                                 │
│                                                  │
│ CLAIMS: Key findings, conclusions, limitations.  │
│   Include: claim text, type (RESULT/HYPOTHESIS/  │
│   LIMITATION/FUTURE_WORK).                       │
│                                                  │
│ Output as JSON. If unsure, include with          │
│ confidence < 0.5.                                │
│ """                                              │
│                                                  │
│ Output: List[Entity] with confidence scores      │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 5: Relationship Extraction (LLM)            │
│                                                  │
│ Two passes:                                      │
│                                                  │
│ Pass A — Intra-paper relationships:              │
│ Given paper's entities + full text, extract:     │
│ - USES_METHOD (paper → method)                   │
│ - EVALUATES_ON (paper → dataset, with metrics)   │
│ - INTRODUCES (paper → method/dataset)            │
│ - REPORTS_RESULT (paper → claim)                 │
│                                                  │
│ Pass B — Cross-paper relationships:              │
│ Given paper's entities + existing graph entities, │
│ extract:                                         │
│ - EXTENDS (method A builds on method B)          │
│ - OUTPERFORMS (method A > method B on metric M)  │
│ - CONTRADICTS (claim A opposes claim B)          │
│ - CITES (paper → paper, from reference list)     │
│                                                  │
│ Output: List[Relationship] with evidence text    │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 6: Entity Resolution                        │
│                                                  │
│ For each extracted entity, check if it already   │
│ exists in the graph:                             │
│                                                  │
│ Strategy (cascading):                            │
│ 1. Exact match on canonical_name → merge         │
│ 2. Fuzzy match (Levenshtein > 0.85) on name     │
│    + aliases → candidate list                    │
│ 3. Embedding similarity (cosine > 0.90) between  │
│    entity descriptions → candidate list          │
│ 4. If candidates found, LLM verification:        │
│    "Are these the same entity? {entity_A} vs     │
│    {entity_B}. Context: ..." → yes/no            │
│ 5. If no match → create new node                 │
│                                                  │
│ Merge strategy:                                  │
│ - Keep canonical_name from highest-confidence    │
│   source                                         │
│ - Union all aliases                              │
│ - Keep longest description                       │
│ - Preserve all source paper references           │
│                                                  │
│ Output: Resolved entity list (new or existing ID)│
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 7: Graph Write (Neo4j + Chroma)             │
│                                                  │
│ - MERGE nodes (create or update) in Neo4j        │
│ - CREATE relationships with properties in Neo4j  │
│ - Embed entity nodes (name + description text)   │
│ - Store embedding as a Neo4j node property        │
│   (lets Cypher-side similarity ops use it too)    │
│ - ALSO write the same embedding to ChromaDB's     │
│   `entity_embeddings` collection:                 │
│     chroma.entity_embeddings.add(                 │
│       id=f"entity_{neo4j_node_id}",                │
│       embedding=entity_embedding,                  │
│       document=canonical_name + description,       │
│       metadata={entity_type, canonical_name,        │
│                 source_papers}                      │
│     )                                             │
│   This step was previously missing — Retrieval    │
│   Step 2 depends on this collection for seed       │
│   entity search and returns nothing without it.    │
│ - New entity → add to Chroma. Merged/updated       │
│   entity (from resolution) → upsert (overwrite     │
│   existing id) so Chroma never drifts from Neo4j.  │
│ - Update PostgreSQL job status → completed         │
└─────────────────────────────────────────────────┘
```

### 5.2 Retrieval Pipeline (query → context)

```
User Query: "What methods improved on BERT for question answering?"
    │
    ▼
┌─────────────────────────────────────────────────┐
│ Step 1: Query Analysis                           │
│                                                  │
│ - Embed the query                                │
│ - Optional: LLM extracts query entities          │
│   ("BERT", "question answering") and query type  │
│   (multi-hop traversal needed? comparison?       │
│    single-entity lookup?)                        │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 2: Vector Seed Retrieval                    │
│                                                  │
│ - Search ChromaDB (entity_embeddings collection) │
│   for top-5 similar entities                     │
│ - Search ChromaDB (paper_chunks collection)      │
│   for top-10 similar chunks                      │
│ - Extract entity/paper node IDs from results     │
│   → these are "seed nodes"                       │
│                                                  │
│ Output: seed_node_ids = ["bert_node", ...]       │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 3: Graph Traversal                          │
│                                                  │
│ From each seed node, traverse N hops (default 2):│
│                                                  │
│ Cypher query:                                    │
│ MATCH path = (seed)-[r*1..2]-(connected)         │
│ WHERE seed.id IN $seed_ids                       │
│ RETURN path, nodes(path), relationships(path)    │
│                                                  │
│ Optionally filter by relationship type:          │
│ - If query asks "what extended X" → filter       │
│   EXTENDS relationships                          │
│ - If query asks "what contradicts" → filter      │
│   CONTRADICTS                                    │
│                                                  │
│ Output: subgraph (nodes + edges)                 │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 4: Hybrid Scoring                           │
│                                                  │
│ Each node in the subgraph gets a combined score: │
│                                                  │
│ score = α * vector_similarity(node, query)       │
│       + β * (1 / graph_distance_from_seed)       │
│       + γ * edge_confidence                      │
│                                                  │
│ Where:                                           │
│   α = 0.4 (semantic relevance weight)            │
│   β = 0.4 (graph proximity weight)               │
│   γ = 0.2 (extraction confidence weight)         │
│                                                  │
│ These weights are tunable hyperparameters.        │
│                                                  │
│ Rank all nodes by score, take top-K (default 20) │
│                                                  │
│ Output: ranked_subgraph                          │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 5: Context Building                         │
│                                                  │
│ Convert ranked subgraph into structured text:    │
│                                                  │
│ "The following entities and relationships were   │
│  found relevant to your query:                   │
│                                                  │
│  ENTITIES:                                       │
│  - [METHOD] BERT (introduced by Paper:           │
│    'BERT: Pre-training...', 2018)                │
│  - [METHOD] SpanBERT (introduced by Paper:       │
│    'SpanBERT...', 2019)                          │
│  - [DATASET] SQuAD 2.0 (domain: NLP)            │
│                                                  │
│  RELATIONSHIPS:                                  │
│  - SpanBERT EXTENDS BERT (evidence: '...')       │
│  - SpanBERT EVALUATES_ON SQuAD 2.0              │
│    (F1: 88.7)                                    │
│  - SpanBERT OUTPERFORMS BERT on SQuAD 2.0       │
│    (F1 margin: +2.3)                             │
│                                                  │
│  RELEVANT CHUNKS:                                │
│  [chunk texts from vector retrieval]"            │
│                                                  │
│ Output: structured_context string                │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 6: Answer Generation (LLM)                  │
│                                                  │
│ Prompt:                                          │
│ """                                              │
│ You are a research assistant. Answer the user's  │
│ question using ONLY the provided graph context.  │
│ Cite papers by [Author, Year]. Reference         │
│ specific relationships (e.g., "X extends Y").    │
│ If the context doesn't contain enough info,      │
│ say so explicitly.                               │
│                                                  │
│ Context: {structured_context}                    │
│ Question: {user_query}                           │
│ """                                              │
│                                                  │
│ Output: answer with citations                    │
└─────────────────────────────────────────────────┘
```

---

## 6. Configuration Management

### 6.1 Environment Variables (.env)

```bash
# ─── Application ───
APP_NAME=litgraph
APP_ENV=development                    # development | staging | production
APP_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000     # Frontend URL

# ─── PostgreSQL ───
POSTGRES_HOST=localhost
POSTGRES_PORT=5432                     # container-internal port — always 5432
POSTGRES_HOST_PORT=5432                # host-side port docker-compose maps to. Change this (and
                                        # POSTGRES_PORT to match, for host-side tools) if you already
                                        # have a local Postgres on 5432 — a real conflict hit during
                                        # SETUP-004 build, since a native Postgres install silently
                                        # shadowed the container on the default port
POSTGRES_DB=litgraph
POSTGRES_USER=litgraph_user
POSTGRES_PASSWORD=<generate-strong-password>   # required, no default — app fails at startup with a
                                                # clear error if this is missing, not a buried auth error

# ─── Neo4j ───
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<generate-strong-password>

# ─── ChromaDB ───
CHROMA_HOST=localhost                  # use "chromadb" (the service name) when backend/worker
                                        # talk to it over the Docker network
CHROMA_PORT=8000                       # container-internal port — always 8000, even though the
                                        # host-mapped port below is 8001. Backend/worker connect
                                        # over the Docker network at container-internal 8000; 8001
                                        # is only for reaching it from your host machine (curl, etc.)
CHROMA_COLLECTION_CHUNKS=paper_chunks
CHROMA_COLLECTION_ENTITIES=entity_embeddings

# ─── Redis (Celery broker) ───
REDIS_URL=redis://localhost:6379/0

# ─── LLM API ───
# BUILD PHASE (default): gemini — free tier, no card. Measured live
# (EXTRACT-001): a free key's actual daily cap can be as low as ~20
# requests/model, well under the generally-published 1500 RPD figure.
# GEMINI_API_KEY_FALLBACK is a 2nd key llm_client.py's key ring switches to
# automatically on a 429. GROQ_API_KEY (added same day, after both Gemini
# keys were spent) is a manual fallback provider — free, no card,
# OpenAI-compatible, 100K tokens/day on llama-3.3-70b-versatile (on a
# shorter rolling window than Gemini's calendar-day reset — recovers in
# ~20min, not next-day) — flip LLM_PROVIDER=groq + point
# EXTRACTION_MODEL/GENERATION_MODEL at a Groq model name when Gemini is out
# for the day. GROQ_API_KEY_FALLBACK gets its own key ring the same way
# Gemini does (the ring is generic over any provider's key list). Both
# Groq keys live-verified working independently.
# SCALE PHASE (later): flip to openai or anthropic — just change this one value,
# rest of the pipeline code stays the same (unified llm_client abstracts provider)
LLM_PROVIDER=gemini                    # gemini | openai | anthropic | groq
GEMINI_API_KEY=AIza...
GEMINI_API_KEY_FALLBACK=AIza...        # optional 2nd key, auto-switched to on 429
GROQ_API_KEY=gsk_...                   # get from https://console.groq.com/keys
GROQ_API_KEY_FALLBACK=gsk_...          # optional 2nd key, auto-switched to on 429
OPENAI_API_KEY=sk-...                  # keep unset/blank until scaling
ANTHROPIC_API_KEY=sk-ant-...           # keep unset/blank until scaling

# Model names use "-latest" aliases, not dated snapshots — verified live that
# Google retires dated Gemini models for new API keys fast: gemini-2.5-flash-lite
# and gemini-2.5-flash both 404 ("no longer available to new users") as of
# 2026-08, while gemini-flash-latest works. gemini-flash-lite-latest is worth
# trying for extraction (cheaper) but 503s ("high demand") often — fall back
# to gemini-flash-latest if so.

# Extraction model (high volume, cheaper/faster)
EXTRACTION_MODEL=gemini-flash-latest
EXTRACTION_MAX_TOKENS=4096
EXTRACTION_TEMPERATURE=0.1             # Low temp for structured extraction

# Generation model (user-facing, higher quality)
GENERATION_MODEL=gemini-flash-latest   # scale: gpt-4o | claude-sonnet-4-6
GENERATION_MAX_TOKENS=2048
GENERATION_TEMPERATURE=0.3
LLM_RATE_LIMIT_RPM=15                  # Gemini free tier default (Flash: 15 RPM)

# ─── Embedding ───
# BUILD PHASE (default): local — free, no API call, no rate limit
# SCALE PHASE (later): flip to openai for better retrieval quality
EMBEDDING_PROVIDER=local               # local | openai
EMBEDDING_MODEL=all-MiniLM-L6-v2       # scale: text-embedding-3-small
EMBEDDING_DIMENSION=384                # 384 for MiniLM, 1536 for OpenAI
# ⚠️ NOTE: ChromaDB locks a collection's vector dimension at creation time.
# Switching EMBEDDING_PROVIDER (local ↔ openai) after papers are already
# ingested does NOT just work by flipping this env var — the existing
# `paper_chunks` and `entity_embeddings` collections were created at the old
# dimension and will reject writes at the new one. You must delete and
# recreate both collections (and re-embed/re-ingest all papers) when
# changing embedding provider. Fine to switch before ingesting real data;
# plan for a full re-ingestion if switching after.

# ─── Retrieval Config ───
VECTOR_TOP_K=10                        # Chunks to retrieve from vector search
ENTITY_TOP_K=5                         # Entity seeds from vector search
GRAPH_TRAVERSAL_HOPS=2                 # How many hops in graph traversal
HYBRID_ALPHA=0.4                       # Vector similarity weight
HYBRID_BETA=0.4                        # Graph distance weight
HYBRID_GAMMA=0.2                       # Confidence weight
CONTEXT_MAX_NODES=20                   # Max nodes in generated context

# ─── Ingestion Config ───
MAX_PAPERS_PER_UPLOAD=50
MAX_PDF_SIZE_MB=50
CHUNK_SIZE_TOKENS=1000
CHUNK_OVERLAP_TOKENS=200
ENTITY_CONFIDENCE_THRESHOLD=0.5        # Min confidence to include entity
RELATION_CONFIDENCE_THRESHOLD=0.5

# ─── File Storage ───
UPLOAD_DIR=./data/uploads
PROCESSED_DIR=./data/processed
```

### 6.2 Config Class (Pydantic)

**As actually implemented** (`src/config.py`, SETUP-003 + SETUP-004) — kept in sync with the real file rather than hand-maintained, since this drifted from an earlier draft (old Pydantic v1 `class Config` style, missing several fields that later tickets needed):

```python
# src/config.py
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "litgraph"
    app_env: Literal["development", "staging", "production"] = "development"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "litgraph"
    postgres_user: str = "litgraph_user"
    postgres_password: str  # required — no safe default, fail loudly at startup if missing

    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN (used from SETUP-004 onward)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn(self) -> str:
        """Raw asyncpg DSN (used for the /health ping — no ORM involved)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required — no safe default, fail loudly at startup if missing

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection_chunks: str = "paper_chunks"
    chroma_collection_entities: str = "entity_embeddings"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_provider: Literal["gemini", "openai", "anthropic", "groq", "openrouter"] = "gemini"
    gemini_api_key: str = ""
    gemini_api_key_fallback: str = ""  # auto-switched to by llm_client's key ring on 429
    groq_api_key: str = ""             # manual fallback provider — free, higher daily cap
    groq_api_key_fallback: str = ""    # 2nd Groq key, own key ring, same mechanism
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""       # 4th provider, added 2026-08-13 — see llm_client.py's
                                        # tree comment for the model speed/correctness tradeoffs
                                        # measured live on its free tier
    extraction_model: str = "gemini-flash-latest"
    extraction_max_tokens: int = 4096
    extraction_temperature: float = 0.1
    generation_model: str = "gemini-flash-latest"
    generation_max_tokens: int = 2048
    generation_temperature: float = 0.3
    llm_rate_limit_rpm: int = 15  # Gemini free tier default (Flash: 15 RPM)

    # Embedding
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Retrieval
    vector_top_k: int = 10
    entity_top_k: int = 5
    graph_traversal_hops: int = 2
    hybrid_alpha: float = 0.4
    hybrid_beta: float = 0.4
    hybrid_gamma: float = 0.2
    context_max_nodes: int = 20

    # Ingestion
    max_papers_per_upload: int = 50
    max_pdf_size_mb: int = 50
    chunk_size_tokens: int = 1000
    chunk_overlap_tokens: int = 200
    entity_confidence_threshold: float = 0.5
    relation_confidence_threshold: float = 0.5
    entity_resolution_fuzzy_threshold: float = 0.85
    entity_resolution_embedding_threshold: float = 0.55  # not the ticket's 0.90 — see
                                                          # entity_resolver.py's tree comment

    # File storage
    upload_dir: str = "./data/uploads"
    processed_dir: str = "./data/processed"


settings = Settings()
```

### 6.3 Docker Compose

**As actually implemented** (SETUP-002 through SETUP-007) — `frontend` is still the target shape from `FE-001`, not built yet, so it's kept here as documentation of where this is headed rather than current state. Everything else below matches the real `docker-compose.yml`, including two things the original draft got wrong/incomplete: `chromadb/chroma:latest` was silently breaking on version-mismatch with the pinned Python client (see §8's tradeoffs table), and nothing had a `restart` policy, so a crashed container needed a manual `docker compose up` to come back.

```yaml
# docker-compose.yml
services:
  backend:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
      - neo4j
      - chromadb
      - redis
    volumes:
      - ./data:/app/data

  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-litgraph}
      POSTGRES_USER: ${POSTGRES_USER:-litgraph_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}
    ports:
      # Configurable host port — a native Postgres install on the dev machine silently shadowed
      # the container on the default port during SETUP-004; see POSTGRES_HOST_PORT in §6.1.
      - "${POSTGRES_HOST_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-litgraph_user}"]
      interval: 5s
      timeout: 5s
      retries: 10

  neo4j:
    image: neo4j:5-community
    restart: unless-stopped
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?NEO4J_PASSWORD must be set in .env}
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"     # Browser
      - "7687:7687"     # Bolt
    volumes:
      - neo4jdata:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

  chromadb:
    image: chromadb/chroma:1.0.0   # pinned, not :latest — a client/server version mismatch on
    restart: unless-stopped        # :latest crashed app startup during SETUP-006 (KeyError: '_type')
    ports:
      - "8001:8000"
    volumes:
      - chromadata:/chroma/chroma

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  celery_worker:
    build: .
    restart: unless-stopped
    command: celery -A src.tasks.celery_app worker --loglevel=info
    env_file: .env
    depends_on:
      - redis
      - postgres
      - neo4j
      - chromadb
    volumes:
      - ./data:/app/data

  # --- Not built yet (FE-001) — target shape, shown here for the full picture ---
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  pgdata:
  neo4jdata:
  chromadata:
```

**Resource footprint note:** This brings up 7 containers simultaneously (postgres, neo4j, chromadb, redis, backend, celery_worker, frontend) on the dev machine. Budget **6-8GB+ free RAM** for Docker Desktop — Neo4j alone defaults to a non-trivial JVM heap. If local resources are tight, reduce Neo4j's heap via `NEO4J_dbms_memory_heap_max__size` in the environment block, or run backend/frontend outside Docker during active development and only containerize the stateful services (postgres/neo4j/chromadb/redis).

---



## 7. API Endpoints

### 7.1 Ingestion

| Method | Endpoint | Description |
|--------|---------|-------------|
| `POST` | `/api/v1/ingest/upload` | Upload PDF files (multipart form). Returns job IDs. |
| `POST` | `/api/v1/ingest/arxiv` | Submit ArXiv URLs/IDs. Downloads + ingests. Returns job IDs. |
| `GET` | `/api/v1/ingest/status/{job_id}` | Check ingestion job progress. Returns status + entity/relation counts. |

### 7.2 Query

| Method | Endpoint | Description |
|--------|---------|-------------|
| `POST` | `/api/v1/query` | GraphRAG query. Returns answer + citations + retrieved subgraph. |
| `POST` | `/api/v1/query/compare` | Same query run on both GraphRAG and vanilla RAG. Returns both answers for comparison. |
| `POST` | `/api/v1/query/vanilla` | Vanilla RAG only (baseline). |

### 7.3 Graph

| Method | Endpoint | Description |
|--------|---------|-------------|
| `GET` | `/api/v1/graph/overview` | Graph stats: total nodes, edges, entity type counts. |
| `GET` | `/api/v1/graph/subgraph?entity_id={id}&hops={n}` | Get N-hop subgraph from an entity. For visualization. |
| `GET` | `/api/v1/graph/entity/{id}` | Full entity details + all connected relationships. |
| `GET` | `/api/v1/graph/search?q={text}&type={entity_type}` | Search entities by text + optional type filter. |

**As actually implemented (GRAPH-001):** `entity_id`/`{id}` are Neo4j
elementIds (same space RETRIEVAL-001/002 already use, not a separate ID
scheme). `hops` defaults to 2, clamped 1-4. `type` on `/search` must be one
of `Paper|Method|Dataset|Author|Claim` (400 if not — `Metric` has no
fulltext index, same scope trim as its missing `usage_count`). `/subgraph`
and `/entity/{id}` both return a `usage_count: int | null` per node — see
`src/api/schemas/graph.py`'s docstring for exactly what it measures per
type, notably that Paper's is a relationship-degree proxy since no `CITES`
edge is ever written.

### 7.4 Papers

| Method | Endpoint | Description |
|--------|---------|-------------|
| `GET` | `/api/v1/papers` | List all ingested papers with metadata. |
| `GET` | `/api/v1/papers/{id}` | Paper details + extracted entities/relationships. |
| `DELETE` | `/api/v1/papers/{id}` | Remove paper + its entities/relationships from graph. |

### 7.5 Collections

| Method | Endpoint | Description |
|--------|---------|-------------|
| `POST` | `/api/v1/collections` | Create a new collection. |
| `GET` | `/api/v1/collections` | List all collections. |
| `PUT` | `/api/v1/collections/{id}` | Update collection name/description. |
| `DELETE` | `/api/v1/collections/{id}` | Delete collection (papers remain). |

---

## 8. Key Technical Decisions & Tradeoffs

| Decision | Choice | Tradeoff |
|----------|--------|----------|
| **LLM for extraction (not fine-tuned model)** | Using GPT-4o-mini / Haiku API calls for entity + relationship extraction | Pro: No training data needed, works out of the box, handles diverse paper styles. Con: Slower, costs per paper, extraction quality depends on prompt engineering. |
| **Neo4j over networkx** | Using Neo4j even for MVP (not in-memory networkx) | Pro: Cypher query language is powerful for graph traversal, persists across restarts, handles larger graphs. Con: Adds infrastructure complexity (Docker service), learning curve for Cypher. |
| **Section-aware chunking over fixed-size** | Chunks respect section boundaries | Pro: Better context for extraction + retrieval ("method" section chunks stay coherent). Con: Uneven chunk sizes, some sections very long. |
| **Separate vector store (ChromaDB) from graph (Neo4j)** | Not using Neo4j's built-in vector index | Pro: ChromaDB is faster for pure vector search, easier to swap out. Con: Two systems to maintain, need to keep IDs consistent. |
| **Async ingestion (Celery)** | Paper processing runs in background workers | Pro: User doesn't wait 60s per paper in the UI. Con: Adds Redis + Celery infrastructure. |
| **Gemini free tier as default LLM/embedding provider** | Build phase uses Gemini (free) + local embeddings (free); OpenAI/Anthropic wired in but dormant | Pro: Zero-cost build and demo, no card needed. Con: Gemini free tier RPM/RPD caps slow down large-batch ingestion (need retry/backoff), and free-tier prompts may be used by Google for training — swap to paid provider before processing anything sensitive or before scaling volume. |
| **Hybrid scoring with tunable weights** | α/β/γ weights as config, not hardcoded | Pro: Can tune retrieval quality empirically. Con: Three hyperparameters to tune, no obvious "right" values without eval data. |
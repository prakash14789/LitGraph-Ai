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
| **LLM API** | **Default (build phase): Gemini API free tier** (Flash-Lite for extraction, Flash/Pro for generation). **Scale option: OpenAI (GPT-4o-mini/GPT-4o) OR Anthropic (Haiku/Sonnet)** — swap via `LLM_PROVIDER` config, no code changes | Gemini free tier: no card, 1,500 RPD / 15 RPM / 1M TPM on Flash — enough to build + demo at zero cost. OpenAI/Anthropic wired in from day one so scaling later (higher quality, higher volume, no training-data usage) is a config flip, not a rebuild |
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
│   │   │   ├── ingest.py            # POST /ingest/upload, POST /ingest/arxiv
│   │   │   ├── query.py             # POST /query, POST /query/compare (graphrag vs vanilla)
│   │   │   ├── graph.py             # GET /graph/subgraph, GET /graph/entity/{id}
│   │   │   ├── papers.py            # GET /papers, GET /papers/{id}, DELETE /papers/{id}
│   │   │   └── collections.py       # CRUD for paper collections
│   │   ├── schemas/                 # Pydantic request/response models
│   │   │   ├── ingest.py
│   │   │   ├── query.py
│   │   │   ├── graph.py
│   │   │   └── papers.py
│   │   └── dependencies.py          # FastAPI dependency injection (DB sessions, auth)
│   │
│   ├── services/                    # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── ingestion/               # Paper → Graph pipeline
│   │   │   ├── __init__.py
│   │   │   ├── pdf_parser.py        # PDF → raw text + sections + tables
│   │   │   ├── chunker.py           # Sections → overlapping chunks (for vector store)
│   │   │   ├── entity_extractor.py  # Chunk/section → entities (LLM-based)
│   │   │   ├── relation_extractor.py # Entities → relationships (LLM-based)
│   │   │   ├── entity_resolver.py   # Deduplicate entities across papers
│   │   │   ├── graph_writer.py      # Write entities + relationships to Neo4j
│   │   │   └── pipeline.py          # Orchestrates the full ingestion pipeline
│   │   │
│   │   ├── retrieval/               # Query → Retrieved Context
│   │   │   ├── __init__.py
│   │   │   ├── vector_retriever.py  # Query → top-K similar chunks (ChromaDB)
│   │   │   ├── graph_retriever.py   # Seed entities → N-hop subgraph (Neo4j Cypher)
│   │   │   ├── hybrid_scorer.py     # Combine vector + graph scores → ranked results
│   │   │   └── context_builder.py   # Subgraph → structured text context for LLM
│   │   │
│   │   ├── generation/              # Context → Answer
│   │   │   ├── __init__.py
│   │   │   ├── generator.py         # LLM call with graph context → cited answer
│   │   │   ├── prompts.py           # All prompt templates (extraction, generation, etc.)
│   │   │   └── faithfulness.py      # Check: does answer follow from context? (self-audit)
│   │   │
│   │   └── vanilla_rag/             # Baseline comparison system
│   │       ├── __init__.py
│   │       ├── retriever.py         # Standard vector-only retrieval
│   │       └── generator.py         # Standard RAG generation
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
│   │   ├── queries.py               # Cypher query templates
│   │   └── schema.py                # Graph schema initialization (constraints, indexes)
│   │
│   ├── vectorstore/                 # Vector Store Interaction Layer
│   │   ├── __init__.py
│   │   ├── store.py                 # ChromaDB/Qdrant abstraction
│   │   └── embedder.py              # Text → embedding (OpenAI or local model)
│   │
│   ├── tasks/                       # Celery Async Tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Celery configuration
│   │   └── ingest_task.py           # Background paper ingestion task
│   │
│   └── utils/                       # Shared Utilities
│       ├── __init__.py
│       ├── llm_client.py            # Unified LLM client — Gemini (default)/OpenAI/Anthropic,
│       │                            # all via the OpenAI SDK against each provider's
│       │                            # OpenAI-compatible endpoint. Retry + rate limiting live
│       │                            # here too (no separate rate_limiter.py — one small class,
│       │                            # one caller, not worth its own file).
│       └── logging.py               # Structured logging setup
│
├── tests/
│   ├── conftest.py                  # Fixtures (test DB, mock LLM, sample papers) — built SETUP-009
│   ├── unit/
│   │   ├── test_llm_client.py       # Built SETUP-008 — mocked retry/rate-limit/no-retry-on-auth
│   │   ├── test_fixtures.py         # Built SETUP-009 — proves conftest fixtures actually work
│   │   ├── test_chunker.py          # Not built yet — lands with INGEST-002
│   │   ├── test_entity_extractor.py # Not built yet — lands with EXTRACT-001
│   │   ├── test_entity_resolver.py  # Not built yet — lands with EXTRACT-003
│   │   ├── test_hybrid_scorer.py    # Not built yet — lands with RETRIEVAL-003
│   │   └── test_context_builder.py  # Not built yet — lands with RETRIEVAL-004
│   ├── integration/
│   │   ├── test_ingestion_pipeline.py
│   │   ├── test_retrieval_pipeline.py
│   │   └── test_graph_queries.py
│   └── eval/
│       ├── eval_dataset.json         # 50 multi-hop questions with gold answers
│       ├── run_eval.py               # Run both systems, score, output comparison
│       └── eval_results/             # Stored evaluation results
│
├── frontend/                        # React Frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx          # Main Q&A interface
│   │   │   ├── GraphPage.tsx         # Graph visualization explorer
│   │   │   ├── PapersPage.tsx        # Paper upload + management
│   │   │   └── ComparePage.tsx       # GraphRAG vs vanilla RAG comparison
│   │   ├── components/
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── CitationCard.tsx
│   │   │   ├── GraphCanvas.tsx       # Cytoscape.js wrapper
│   │   │   ├── PaperUploader.tsx
│   │   │   ├── SubgraphPanel.tsx     # Shows retrieved subgraph for current answer
│   │   │   └── EntityDetailModal.tsx
│   │   ├── hooks/
│   │   │   ├── useQuery.ts
│   │   │   └── useGraph.ts
│   │   ├── services/
│   │   │   └── api.ts                # Axios API client
│   │   └── types/
│   │       └── index.ts              # TypeScript type definitions
│   └── public/
│
├── scripts/
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
    status          ENUM('queued','extracting_entities','extracting_relations',
                         'resolving_entities','writing_graph','completed','failed'),
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
        "source_papers": ["uuid1", "uuid2"]
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
# BUILD PHASE (default): gemini — free tier, no card, 1500 RPD/15 RPM on Flash
# SCALE PHASE (later): flip to openai or anthropic — just change this one value,
# rest of the pipeline code stays the same (unified llm_client abstracts provider)
LLM_PROVIDER=gemini                    # gemini | openai | anthropic
GEMINI_API_KEY=AIza...
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
    llm_provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
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
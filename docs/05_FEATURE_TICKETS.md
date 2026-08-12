# LitGraph — Feature Ticket List

> **Version:** 1.0  
> **Last Updated:** August 11, 2026  
> **Author:** Prakash  
> **Status:** Draft  

---

## How to Read This Document

Each ticket follows this format:

```
[TICKET-ID] Title
Priority: P0 (must-have) | P1 (should-have) | P2 (nice-to-have)
Estimate: time in days (1 day = ~6 focused hours)
Dependencies: tickets that must be completed first
Acceptance Criteria: what "done" looks like
```

Tickets are grouped by **Epic** (a large feature area). Within each epic, tickets are ordered by implementation sequence.

**Total estimated time: ~60-70 working days (12-14 weeks) for a solo developer.**

---

## Epic 0: Project Setup & Infrastructure

### [SETUP-001] Initialize Project Repository & Structure
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** None  
**Description:**  
Create GitHub repo. Set up project folder structure matching the technical architecture document. Initialize Poetry for Python deps, create `pyproject.toml`. Set up `.gitignore` (include `.env`, `data/`, `__pycache__/`, `node_modules/`). Create `README.md` with project overview. Add MIT license.

**Acceptance Criteria:**
- Repo exists on GitHub with proper structure
- `poetry install` works
- `.gitignore` covers all sensitive/generated files
- README has project name, one-paragraph description, and "setup coming soon"

---

### [SETUP-002] Docker Compose Environment
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** SETUP-001  
**Description:**  
Create `docker-compose.yml` with all services: PostgreSQL 16, Neo4j 5 Community, ChromaDB, Redis 7. Create `Dockerfile` for the FastAPI backend. Create `.env.example` with all required environment variables (no real secrets). Verify all services start and are reachable from the backend container.

**Acceptance Criteria:**
- `docker-compose up` starts all 5 services without errors
- Backend can connect to PostgreSQL, Neo4j, ChromaDB, and Redis
- Neo4j browser accessible at `localhost:7474`
- `.env.example` documents every variable with descriptions

---

### [SETUP-003] FastAPI Application Skeleton
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** SETUP-002  
**Description:**  
Create FastAPI app in `src/main.py`. Set up Pydantic `Settings` class (`src/config.py`) loading from `.env`. Create router aggregator (`src/api/router.py`). Set up CORS middleware. Create health check endpoint (`GET /health` → returns service connectivity status for PostgreSQL, Neo4j, ChromaDB). Set up structured logging with `structlog`.

**Acceptance Criteria:**
- `GET /health` returns `200` with status of each dependency
- `GET /docs` shows Swagger UI
- Settings loaded from `.env` via Pydantic
- Structured JSON logging working

---

### [SETUP-004] PostgreSQL Schema & Migrations
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** SETUP-003  
**Description:**  
Set up SQLAlchemy async ORM with asyncpg. Create models: `Paper`, `Collection`, `ExtractionJob`, `QueryLog`. Set up Alembic for migrations. Create initial migration. Create repository classes for each model with basic CRUD operations.

**Acceptance Criteria:**
- `alembic upgrade head` creates all tables
- Repository classes support: create, get_by_id, list, delete for each model
- Async database sessions properly managed (no connection leaks)

---

### [SETUP-005] Neo4j Schema Initialization
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Create Neo4j driver setup (`src/graph/connection.py`). Create schema initialization script that creates constraints and indexes (as defined in tech arch doc). Create `src/graph/queries.py` with Cypher query templates as named constants. Verify connectivity and schema creation on app startup.

**Acceptance Criteria:**
- Neo4j constraints and indexes created on startup
- Driver connection pool properly configured
- Basic Cypher query (create node, read node, delete node) works from Python

---

### [SETUP-006] Vector Store Setup
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Create ChromaDB client wrapper (`src/vectorstore/store.py`). Create embedder wrapper (`src/vectorstore/embedder.py`) supporting both OpenAI API and local sentence-transformers model (configurable). Create two collections: `paper_chunks` and `entity_embeddings`. Verify: embed a test string, store it, retrieve by similarity.

**Acceptance Criteria:**
- Embed + store + retrieve cycle works for both collections
- Embedder supports both OpenAI and local model via config switch
- Proper error handling when API key missing / model not found

---

### [SETUP-007] Celery + Redis Task Queue
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Set up Celery app (`src/tasks/celery_app.py`) with Redis broker. Create a test task that logs "hello" and verify it runs via Celery worker. Set up Celery worker as a Docker Compose service. Configure task serialization (JSON), result backend (Redis), and task timeout (10 min per task).

**Acceptance Criteria:**
- `celery -A src.tasks.celery_app worker` starts without errors
- Test task dispatched from FastAPI endpoint and executed by worker
- Task result retrievable from Redis

---

### [SETUP-008] LLM API Client
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** SETUP-003  
**Description:**  
Create unified LLM client (`src/utils/llm_client.py`) that supports Gemini, OpenAI, and Anthropic APIs behind one interface. Configurable via `LLM_PROVIDER` env var — default `gemini` (free tier, used for the whole build phase), with `openai`/`anthropic` wired in and ready as a one-line config flip when scaling later. Support: `complete(system_prompt, user_prompt, model, max_tokens, temperature)` → returns text. Add retry logic (3 attempts, exponential backoff) for transient errors — important on Gemini free tier since RPM/RPD caps will trigger 429s during batch ingestion. Add rate limiter tuned to Gemini free tier limits (15 RPM / 1,500 RPD on Flash by default). Log token usage per call.

**Acceptance Criteria:**
- Same interface works for Gemini, OpenAI, and Anthropic — switching provider is a config change only, no code change
- Retry + backoff works for Gemini 429 rate-limit responses as well as timeout/rate-limit errors from other providers
- Non-retryable errors (auth, content policy) fail immediately
- Token usage logged per call
- Rate limiter prevents exceeding Gemini free-tier RPM before it happens (proactive throttling, not just reactive retry)

---

### [SETUP-009] Testing Infrastructure
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Set up pytest with `conftest.py`. Create fixtures: test PostgreSQL database (separate DB for tests), mock LLM client (returns canned responses), sample paper data (2-3 small papers as test fixtures). Set up test coverage reporting. Add pre-commit hooks for Ruff linting + formatting.

**Acceptance Criteria:**
- `pytest` runs and passes with 0 tests (infrastructure works)
- Mock LLM client fixture available
- Pre-commit hooks catch formatting issues

---

**Epic 0 Total: ~7.5 days**

---

## Epic 1: PDF Ingestion Pipeline (Baseline RAG)

### [INGEST-001] PDF Parser
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** SETUP-004  
**Description:**  
Create `src/services/ingestion/pdf_parser.py`. Accept a PDF file path. Extract: full text, section headers + section content (heuristic detection: look for bold/large text followed by body text, common section names like "Introduction", "Related Work", "Method", etc.), reference list, tables (as markdown strings), metadata (title from first large text, authors if detectable). Handle: single-column, two-column, LaTeX-generated PDFs. Use PyMuPDF (fitz) as primary parser. Add fallback for papers where section detection fails (treat entire text as one section).

**Acceptance Criteria:**
- Given 5 test papers (varied formats), correctly extracts:
  - Full text with >95% character accuracy
  - At least 3 major sections identified per paper
  - Reference list extracted (at least paper titles)
- Graceful handling of non-parseable PDFs (returns error, doesn't crash)
- Processing time: <5 seconds per typical paper

---

### [INGEST-002] Section-Aware Chunker
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** INGEST-001  
**Description:**  
Create `src/services/ingestion/chunker.py`. Input: parsed paper sections. Output: list of chunks with metadata. Strategy: split by section first, then split long sections into overlapping chunks (configurable: default 1000 tokens, 200 overlap). Each chunk carries metadata: `{paper_id, section_name, chunk_index, page_number}`. Tables become separate chunks tagged as `section: "table"`. Token counting via tiktoken.

**Acceptance Criteria:**
- No chunk exceeds `CHUNK_SIZE_TOKENS + 50` (small overflow OK for sentence boundaries)
- Chunks don't split mid-sentence (split on sentence boundaries)
- Section metadata preserved on every chunk
- 100% of paper text represented in chunks (no content dropped)

---

### [INGEST-003] Chunk Embedding & Storage
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** INGEST-002, SETUP-006  
**Description:**  
Embed each chunk using the configured embedding model. Store in ChromaDB `paper_chunks` collection with metadata. Handle batch embedding (send chunks in batches of 100 to embedding API). Handle duplicate detection (don't re-embed if paper already ingested).

**Acceptance Criteria:**
- All chunks from a paper stored in ChromaDB with correct metadata
- Duplicate paper re-upload doesn't create duplicate chunks
- Batch embedding works (single API call per batch, not per chunk)

---

### [INGEST-004] Upload API Endpoint
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** INGEST-003, SETUP-007  
**Description:**  
Create `POST /api/v1/ingest/upload` endpoint. Accept multipart form with multiple PDF files + `collection_id`. Validate: file type (PDF magic bytes), file size (<50MB), file count (≤50). Save PDFs to `UPLOAD_DIR`. Create `Paper` record in PostgreSQL (status: pending). Create `ExtractionJob` record. Dispatch Celery task for each paper. Return list of job IDs.

Create `GET /api/v1/ingest/status/{job_id}` endpoint. Return current job status, entity/relation counts, error message if failed.

**Atomicity note (from SETUP-004):** the `Paper` create and its `ExtractionJob` create must happen in **one transaction** — do both through the same `Depends(get_db)` session within a single request handler and let it commit once at the end. `Repository.create()` only flushes, it does not commit (deliberately, see `src/repositories/base.py`) — the request-scoped session in `src/api/dependencies.get_db()` is what commits. Don't call `create()` from two separate sessions/requests for the same paper, or a failed `ExtractionJob` insert will leave an orphaned `Paper` with no job.

**Acceptance Criteria:**
- Upload 3 PDFs → get 3 job IDs back
- Invalid files rejected with descriptive error
- Job status endpoint returns current processing step
- Files saved with UUID names (not user-provided names)
- Paper + ExtractionJob creation is atomic: if the ExtractionJob insert fails, the Paper row must not persist either (test by forcing a failure between the two creates)

---

### [INGEST-005] Vanilla RAG Query (Baseline)
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** INGEST-003, SETUP-008  
**Description:**  
Create `src/services/vanilla_rag/retriever.py` and `generator.py`. Retriever: embed query → search ChromaDB `paper_chunks` → return top-K chunks with scores. Generator: format chunks as context → send to LLM with generation prompt → return answer with source references.

Create `POST /api/v1/query/vanilla` endpoint.

This is the **baseline system** that GraphRAG will be compared against.

**Acceptance Criteria:**
- Given ingested papers, a relevant query returns a coherent answer
- Answer includes citations to source papers
- Latency < 10 seconds for typical query
- Returns retrieved chunks with scores for debugging/comparison

---

### [INGEST-006] Ingestion Pipeline Orchestrator
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** INGEST-004  
**Description:**  
Create `src/services/ingestion/pipeline.py`. This is the Celery task that orchestrates the full pipeline for one paper: parse PDF → chunk → embed → (later: extract entities → extract relations → resolve entities → write graph). For now, implement up to embedding (entity extraction added in Epic 2). Update job status at each step. Handle errors: if any step fails, mark job as failed with error message, don't leave partial state.

**Acceptance Criteria:**
- Full pipeline runs as Celery task
- Job status updates visible via status endpoint in real-time
- Failed jobs: status = "failed", error message captured
- Partial state cleaned up on failure (no orphaned chunks)

---

### [INGEST-007] Papers CRUD API (List, Detail, Delete Cascade)
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** INGEST-006, EXTRACT-004  
**Description:**  
**This ticket did not exist in the original plan — `FE-002` (Papers Management Page) was being built against an API that no ticket actually created. This fills that gap.**

Create `src/api/routes/papers.py` implementing the three endpoints defined in the architecture doc (§7.4):

- `GET /api/v1/papers` — list papers, optionally filtered by `collection_id`. Returns metadata + ingestion status per paper.
- `GET /api/v1/papers/{id}` — full paper detail: metadata, extracted entities, extracted relationships, sections (for the `PaperDetailModal` in `FE-002`).
- `DELETE /api/v1/papers/{id}` — deletes the paper and **cascades exactly as specified in Security §8.2**:
  1. Delete the PDF file from disk/storage
  2. Delete the `Paper` row from PostgreSQL (cascades to its `ExtractionJob` records)
  3. Delete this paper's chunks + entity embeddings from ChromaDB (`paper_chunks` and `entity_embeddings`, filtered by `paper_id` in metadata)
  4. Delete this paper's entities/relationships from Neo4j — **but only entities not referenced by any other paper.** A shared entity (e.g. `BERT`, used by 12 papers) must survive deletion of any single paper that mentions it. Implementation: for each entity linked to this paper, check if any other `Paper` node still connects to it after removing this paper's edges; only delete the entity node if it becomes orphaned (Cypher: detach this paper's relationships first, then `MATCH (n) WHERE NOT (n)--() AND <was-touched> DETACH DELETE n`, or track reference counts explicitly)
  5. Log the deletion event (paper title/id, not content) for audit per Security §7.2

Implement as a single service function (`src/services/papers/deletion.py`) so the cascade logic is testable independent of the route, and reusable by future account-deletion logic.

**Acceptance Criteria:**
- `GET /papers` returns correct list, filterable by `collection_id`
- `GET /papers/{id}` returns full extraction detail (entities + relationships + sections)
- `DELETE /papers/{id}` removes: PDF file, Postgres row, this paper's Chroma chunks/embeddings, and any entities/relationships now orphaned by the deletion
- **Shared-entity test:** ingest two papers that both use/introduce the same method (e.g. both cite BERT). Delete one paper. Verify the shared entity node still exists in Neo4j and is still findable via the surviving paper. Verify a fully orphaned entity (used only by the deleted paper) IS removed.
- Deleting a nonexistent paper returns 404, not a silent no-op
- Deletion is logged (paper id/title only, no content) per audit requirements

---

**Epic 1 Total: ~8.5 days**

---

## Epic 2: Entity & Relationship Extraction

### [EXTRACT-001] Entity Extraction Prompt Design
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** SETUP-008  
**Description:**  
Design and test the LLM prompt for entity extraction. Create `src/services/ingestion/entity_extractor.py`. The prompt takes a paper section and extracts: Methods (name, description, category), Datasets (name, domain), Metrics (name, value, which method, which dataset), Claims (text, type: RESULT/HYPOTHESIS/LIMITATION/FUTURE_WORK). Output must be structured JSON. Include confidence scores.

Iterate on prompt design with 5+ test papers. Test edge cases: survey papers (many methods mentioned but not introduced), short papers, papers with heavy math notation.

**Acceptance Criteria:**
- On 5 test papers, extraction precision ≥80% (manual review)
- JSON output consistently parseable (no format failures on 20+ attempts)
- Confidence scores roughly calibrated (low-confidence entities are genuinely uncertain)
- Handles section-by-section processing (not whole paper at once)
- Prompt documented in `src/services/generation/prompts.py`

---

### [EXTRACT-002] Relationship Extraction Prompt Design
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** EXTRACT-001  
**Description:**  
Design LLM prompt for relationship extraction. Create `src/services/ingestion/relation_extractor.py`. Two-pass design:

Pass A (intra-paper): Given paper's extracted entities + text, extract: USES_METHOD, EVALUATES_ON (with metric values), INTRODUCES, REPORTS_RESULT, AUTHORED_BY.

Pass B (cross-paper): Given paper's entities + list of existing graph entities (from other papers), extract: EXTENDS, OUTPERFORMS, CONTRADICTS, CITES.

Each relationship must include: source evidence (text span), confidence score.

**Acceptance Criteria:**
- On 5 test papers, relationship precision ≥70% (manual review)
- Cross-paper relationships correctly link to existing entities (not create duplicates)
- Evidence text is actual text from the paper (not hallucinated)
- OUTPERFORMS relationships include metric name, dataset, and margin
- All relationship types from the schema are extractable

---

### [EXTRACT-003] Entity Resolution System
**Priority:** P0  
**Estimate:** 3 days  
**Dependencies:** EXTRACT-001, SETUP-006  
**Description:**  
Create `src/services/ingestion/entity_resolver.py`. Given a newly extracted entity, determine if it matches an existing entity in the graph. Implement cascading strategy:

1. Exact canonical name match → merge
2. Fuzzy string match (Levenshtein ratio > 0.85) on name + aliases → candidate list
3. Embedding similarity (cosine > 0.90) between descriptions → candidate list
4. LLM verification for ambiguous candidates: "Are these the same? {A} vs {B}" → yes/no
5. No match → create new entity

Implement merge logic: keep best canonical name, union aliases, keep longest description.

This is the hardest engineering problem in the project. Expect iteration.

**Acceptance Criteria:**
- "BERT", "BERT-base", "Bidirectional Encoder Representations" correctly merge
- "BERT" (the NLP model) and "BERT" (if used as a person's name) do NOT merge
- Merge preserves all source paper references
- Resolution decision logged with rationale (for debugging)
- Performance: <2 seconds per entity resolution (excluding LLM call if needed)

---

### [EXTRACT-004] Graph Writer
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** EXTRACT-003, SETUP-005, SETUP-006  
**Description:**  
Create `src/services/ingestion/graph_writer.py`. Takes resolved entities + extracted relationships. Writes to Neo4j using MERGE (create-or-update) for nodes and CREATE for relationships. Each node gets an embedding stored as a Neo4j property. Each edge gets confidence score and evidence text. Handle: idempotent writes (re-processing a paper doesn't create duplicates).

**Critical — do not skip:** the same entity embedding must ALSO be written to ChromaDB's `entity_embeddings` collection (`chroma.entity_embeddings.add(id=f"entity_{neo4j_node_id}", embedding=..., document=canonical_name+description, metadata={entity_type, canonical_name, source_papers})`). Storing the embedding as a Neo4j property alone is not enough — `RETRIEVAL-001` (vector seed retriever) searches the Chroma `entity_embeddings` collection directly and will silently return zero entity seeds if this write is skipped. New entity → `add` to Chroma. Entity updated via resolution/merge → `upsert` (overwrite existing id) so Chroma never drifts out of sync with Neo4j.

**Acceptance Criteria:**
- Entities written as correctly-typed nodes (Paper, Method, Dataset, etc.) in Neo4j
- Relationships written with all properties (confidence, evidence_text)
- Re-processing same paper: entities updated, not duplicated, in both Neo4j and Chroma
- Entity embeddings stored on Neo4j nodes **AND** written to Chroma's `entity_embeddings` collection — verify with a direct Chroma query after ingesting a test paper, not just a Neo4j check
- Merged entities (from EXTRACT-003 resolution) upsert their Chroma record instead of leaving a stale/duplicate one
- Graph constraints (uniqueness) enforced

---

### [EXTRACT-005] Integrate Extraction into Ingestion Pipeline
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** EXTRACT-004, INGEST-006  
**Description:**  
Update the ingestion pipeline (`pipeline.py`) to include: entity extraction → relationship extraction → entity resolution → graph write after the existing parse → chunk → embed steps. Update job status tracking to reflect new steps. Handle extraction failures gracefully (paper still has chunks in vector store even if graph extraction fails).

**Acceptance Criteria:**
- Full pipeline: PDF → parse → chunk → embed → extract entities → extract relations → resolve → write graph
- Job status shows correct step throughout
- If extraction fails, paper is still queryable via vanilla RAG (chunks exist)
- Pipeline processes a paper end-to-end in <90 seconds (excluding queue wait)

---

### [EXTRACT-006] Extraction Quality Review Script
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** EXTRACT-005  
**Description:**  
Create `scripts/review_extraction.py`. For a given paper, prints: all extracted entities (with confidence), all extracted relationships (with evidence text), all entity resolution decisions. Formatted for easy manual review. This is a developer tool, not user-facing — used to iterate on prompt quality.

**Acceptance Criteria:**
- Human-readable output for manual review
- Color-coded confidence (green ≥0.8, yellow 0.5-0.8, red <0.5)
- Shows resolution decisions ("BERT merged with existing BERT node" vs "Created new node: SpanBERT")

---

**Epic 2 Total: ~10.5 days**

---

## Epic 3: Hybrid Retrieval Engine

### [RETRIEVAL-001] Vector Seed Retriever
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** INGEST-003, EXTRACT-004  
**Description:**  
Create `src/services/retrieval/vector_retriever.py`. Given a query string: (a) embed the query, (b) search `entity_embeddings` collection for top-K similar entities (seeds), (c) search `paper_chunks` collection for top-K similar chunks. Return combined seed node IDs (entity IDs + paper IDs from chunk metadata).

**MVP scoping decision (applies to `RETRIEVAL-001` through `RETRIEVAL-005`):** retrieval is **global across all ingested papers, not filtered by `collection_id`.** This is deliberate, not an oversight — chunk/entity metadata doesn't carry `collection_id` today, and entity resolution (`EXTRACT-003`) intentionally merges the same entity (e.g. `BERT`) across every paper regardless of collection, so "one global deduplicated graph" and "scope retrieval to one collection" are in tension. Building true per-collection retrieval scoping means adding `collection_id` to chunk/entity metadata and accepting that a shared entity used across collections shows up in results for all of them — that's real design work, not a quick filter, and is deferred to `POLISH-005` (P1/future) rather than MVP. Collections remain useful for organizing uploads/Papers page filtering (`INGEST-007`, `FE-002`) — just not for scoping Chat/Query answers yet. Do not add a silent `collection_id` filter here without also updating `INGEST-002`/`EXTRACT-004` to write it into chunk/entity metadata first, or the filter will just return nothing.

**Acceptance Criteria:**
- Returns top-K entities + top-K chunks ranked by similarity score
- Handles empty graph (no entities yet) — falls back to chunks only
- Deduplicates: if same paper appears in both entity and chunk results, counts once
- Confirmed: search runs across the full corpus, not scoped to a single collection (matches MVP decision above)

---

### [RETRIEVAL-002] Graph Traversal Retriever
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** RETRIEVAL-001, SETUP-005  
**Description:**  
Create `src/services/retrieval/graph_retriever.py`. Given seed node IDs from vector retriever, traverse the Neo4j graph N hops outward. Return the full subgraph (nodes + edges with all properties). Support: configurable hop depth (1-4), optional relationship type filter (e.g., only EXTENDS and OUTPERFORMS), optional entity type filter. Handle large subgraphs: cap at max 200 nodes (take highest-confidence edges first).

Cypher query must be efficient — use parameterized queries, leverage indexes.

**Acceptance Criteria:**
- 2-hop traversal from a well-connected node returns a meaningful subgraph
- Relationship type filtering works (only EXTENDS, only CONTRADICTS, etc.)
- Large graphs: capped at 200 nodes without timeout
- Query execution time: <500ms for typical traversal

---

### [RETRIEVAL-003] Hybrid Scorer
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** RETRIEVAL-002  
**Description:**  
Create `src/services/retrieval/hybrid_scorer.py`. Takes the subgraph from graph traversal + vector similarity scores. Computes combined score for each node:

```
score = α * vector_similarity + β * (1/graph_distance) + γ * avg_edge_confidence
```

Where α, β, γ are configurable weights (default 0.4, 0.4, 0.2). Rank all nodes by score. Return top-K (default 20) with their scores and the edges connecting them.

**Acceptance Criteria:**
- Scoring formula correctly combines all three signals
- Weights configurable via environment variables
- Output is a ranked list of nodes with scores + connecting edges
- Tied scores broken by entity type preference (Methods > Papers > Datasets)

---

### [RETRIEVAL-004] Context Builder
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** RETRIEVAL-003  
**Description:**  
Create `src/services/retrieval/context_builder.py`. Takes the scored subgraph and converts it into a structured text context for the LLM. Format:

```
ENTITIES:
- [METHOD] BERT (introduced by Paper: 'BERT: Pre-training...', 2018)
- [METHOD] SpanBERT (introduced by Paper: 'SpanBERT...', 2019)

RELATIONSHIPS:
- SpanBERT EXTENDS BERT (evidence: "SpanBERT builds on BERT by...")
- SpanBERT EVALUATES_ON SQuAD 2.0 (F1: 88.7)
- SpanBERT OUTPERFORMS BERT on SQuAD 2.0 (F1 margin: +2.3)

RELEVANT TEXT CHUNKS:
[top vector-similar chunks included for additional context]
```

Context must fit within LLM context window (track token count, truncate if needed).

**Acceptance Criteria:**
- Structured context is human-readable and LLM-parseable
- Token count tracked — context truncated gracefully if exceeding limit (8K tokens max)
- Entities grouped by type
- Relationships include evidence text
- Both graph entities and vector chunks included

---

### [RETRIEVAL-005] GraphRAG Query Endpoint
**Priority:** P0  
**Estimate:** 1 day  
**Dependencies:** RETRIEVAL-004, SETUP-008  
**Description:**  
Create `src/services/generation/generator.py`. Takes structured context + user query → calls LLM with generation prompt → returns answer with citations. Prompt instructs LLM to: only use provided context, cite papers, reference relationships, say "I don't know" when context insufficient.

Create `POST /api/v1/query` endpoint. Returns: `{answer, citations, retrieved_subgraph, retrieval_stats}`.

**Acceptance Criteria:**
- Answers reference specific papers and relationships from context
- "I don't know" returned for questions outside the graph's coverage
- Citations match actual papers in the collection
- Response time: <15 seconds end-to-end
- Retrieval stats included (vector results, graph nodes, final context size)

---

### [RETRIEVAL-006] Compare Endpoint (GraphRAG vs Vanilla)
**Priority:** P1  
**Estimate:** 0.5 days  
**Dependencies:** RETRIEVAL-005, INGEST-005  
**Description:**  
Create `POST /api/v1/query/compare` endpoint. Runs the same query through both GraphRAG and vanilla RAG pipelines. Returns both answers + retrieval info side by side. Both run in parallel (async).

**Acceptance Criteria:**
- Both answers returned in single response
- Latency = max(graphrag_time, vanilla_time) + small overhead (parallel execution)
- Each answer includes its retrieval details (chunks vs subgraph)

---

**Epic 3 Total: ~7.5 days**

---

## Epic 4: Frontend — Core UI

### [FE-001] React Project Setup
**Priority:** P0  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Initialize React + TypeScript project with Vite. Install: Tailwind CSS, shadcn/ui, React Router, Zustand, Axios, React Query, Lucide icons. Set up folder structure: pages/, components/, hooks/, services/, stores/, types/. Create API client with base URL config and interceptors. Create global layout with header + navigation tabs.

**Acceptance Criteria:**
- `npm run dev` serves the app at localhost:3000
- Navigation between 4 tabs works (Chat, Graph, Papers, Compare)
- API client configured with base URL from env var
- Tailwind + shadcn/ui rendering correctly

---

### [FE-002] Papers Management Page
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** FE-001, INGEST-004, INGEST-007  
**Description:**  
Build Papers page with: drag-and-drop upload zone (react-dropzone), ArXiv URL input, paper list with cards showing metadata + ingestion status, progress bar for processing papers (polls status endpoint), paper action menu (view details, delete), graph stats summary card at bottom. Paper list, detail view, and delete action are backed by `INGEST-007`'s CRUD endpoints — do not start this ticket until `INGEST-007` is done, the list/delete UI has nothing to call otherwise.

**Acceptance Criteria:**
- Drag PDFs into zone → upload starts → progress bars show
- ArXiv URL submission works
- Paper cards show: title, authors, year, status (processing/done/failed)
- Processing papers poll status every 3 seconds, auto-update UI
- Delete paper: confirmation dialog → calls `DELETE /papers/{id}` → removes from list on success
- Graph stats show total counts of papers, entities, relationships

---

### [FE-003] Chat Interface
**Priority:** P0  
**Estimate:** 2.5 days  
**Dependencies:** FE-001, RETRIEVAL-005  
**Description:**  
Build Chat page with: message history (scrollable), user/assistant message bubbles, markdown rendering for assistant messages, citation cards below answers, chat input (auto-resize textarea + send button), collection selector dropdown, loading state (typing indicator), error state (retry button).

**MVP scoping decision:** the knowledge graph is global — retrieval (`RETRIEVAL-001` → `RETRIEVAL-005`) does NOT filter by `collection_id` (see note on those tickets). So for MVP, the collection selector here is a **display/organizational label only** — it can be shown for consistency with the Papers page, but it must NOT be presented as "scoping this chat to only these papers," because it doesn't. Either hide the selector on this page for MVP, or show it with a small note ("papers across all your collections are searchable") so the UI doesn't promise filtering the backend can't do yet. Full per-collection retrieval scoping is deferred — see `POLISH-005`.

**Acceptance Criteria:**
- Type question → see loading indicator → see answer with markdown formatting
- Citations render as clickable cards below answer
- Markdown: headers, bold, italic, code blocks, lists all render correctly
- Chat history preserved during session (Zustand)
- Empty state: "Ask a question about your papers" prompt
- Error: inline error message with retry button
- Collection selector (if shown) does not claim to filter answers — no UI copy implying answers are scoped to the selected collection

---

### [FE-004] Context Side Panel
**Priority:** P1  
**Estimate:** 1.5 days  
**Dependencies:** FE-003  
**Description:**  
Build collapsible side panel on Chat page showing: list of source papers used, entity tags (clickable badges showing entity type + name), and a **placeholder slot** for the subgraph visualization (empty state / "Graph view coming" — the actual Cytoscape mini-graph is built separately in `GRAPH-004` once the shared `GraphCanvas` component exists, to avoid building Cytoscape integration twice). Panel updates when a new answer arrives. Collapsible via toggle button. On mobile: bottom sheet instead of side panel.

**Note:** Do NOT implement a Cytoscape canvas here — that's explicitly `GRAPH-004`'s scope (it reuses the `GraphCanvas` component from `GRAPH-002`). This ticket only needs to leave a properly-sized, styled container div for `GRAPH-004` to drop the canvas into.

**Acceptance Criteria:**
- Panel shows sources list + entity tags for the current answer
- Panel has a clearly bounded container reserved for the subgraph view (correct dimensions/styling, empty/placeholder state) — no Cytoscape code in this ticket
- Entity tags color-coded by type (Method=green, Paper=blue, etc.)
- Clicking entity tag opens entity detail modal
- Panel collapsible/expandable
- Mobile: renders as bottom sheet, not sidebar

---

### [FE-005] Entity Detail Modal
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** FE-004  
**Description:**  
Build modal (shadcn Dialog) showing full entity details: name, type, description, aliases, related entities (linked list), source papers, extracted relationships. Clicking a related entity in the modal navigates to that entity (updates modal content or navigates to Graph page).

**Acceptance Criteria:**
- All entity properties displayed
- Related entities clickable
- Source papers listed with year
- Modal closeable via X button, Escape key, or clicking outside

---

**Epic 4 Total: ~7.5 days**

---

## Epic 5: Graph Visualization

### [GRAPH-001] Graph API Endpoints
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** EXTRACT-004  
**Description:**  
Create Graph API routes: `GET /graph/overview` (stats), `GET /graph/subgraph` (N-hop from entity), `GET /graph/entity/{id}` (full entity details), `GET /graph/search` (text search entities). All filtered by collection_id. Subgraph/entity responses must include the computed usage counts the frontend uses for node sizing (Frontend Spec §4.3): citation count for Papers, papers-using-it count for Methods, evaluation count for Datasets, paper count for Authors. These are `COUNT()` aggregations over relationships (e.g. `MATCH (m:Method)<-[:USES_METHOD]-(p:Paper) RETURN m, count(p) AS usage_count`), not stored node properties — compute them in the Cypher query, don't try to read them off the node.

**Acceptance Criteria:**
- Overview returns node/edge counts by type
- Subgraph returns Cytoscape-compatible format (nodes + edges arrays)
- Subgraph/entity nodes include the relevant usage count field (`usage_count`, `citation_count`, `evaluation_count`, etc. per entity type) so the frontend can size nodes without a second round-trip
- Search returns matching entities ranked by relevance
- All endpoints respect collection_id filter

---

### [GRAPH-002] Cytoscape.js Graph Canvas Component
**Priority:** P1  
**Estimate:** 3 days  
**Dependencies:** GRAPH-001, FE-001  
**Description:**  
Build `GraphCanvas` React component wrapping Cytoscape.js. Features: node styling by entity type (shape, color, size per spec), edge styling by relationship type (line style, color, label per spec), force-directed layout (default), pan/zoom controls, node click → select (highlight + connected edges), node double-click → expand (load 2-hop subgraph from that node), hover tooltip (entity name + type), responsive sizing.

**Acceptance Criteria:**
- Graph renders with correct node shapes/colors per entity type
- Edges styled per relationship type (solid/dashed/dotted, labeled)
- Smooth pan/zoom interaction
- Click selects node, double-click expands subgraph
- Force-directed layout doesn't overlap nodes for graphs up to 200 nodes
- Performance: smooth interaction for graphs up to 500 nodes

---

### [GRAPH-003] Graph Explorer Page
**Priority:** P1  
**Estimate:** 2 days  
**Dependencies:** GRAPH-002  
**Description:**  
Build full Graph Explorer page with: toolbar (collection selector, entity type filter, relationship type filter, text search, layout switcher [force/hierarchy/grid], zoom controls), graph canvas (main area), entity detail panel (right sidebar, shows selected entity details). Search highlights matching nodes. Layout switching animates smoothly.

**Acceptance Criteria:**
- Full graph for collection loads on page visit
- Filtering by entity type hides non-matching nodes + edges
- Text search highlights matching nodes with visual pulse
- Layout switching works (force, hierarchy, grid)
- Entity detail panel shows on node click, closes on deselect
- Legend displayed on canvas

---

### [GRAPH-004] Subgraph View in Chat Context Panel
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** GRAPH-002, FE-004  
**Description:**  
Integrate the shared `GraphCanvas` component (built in `GRAPH-002`) into the placeholder slot left by `FE-004` in the Chat context panel, configured as a small/mini canvas. When a query answer arrives, render the retrieved subgraph (from the query response's `retrieved_subgraph` field) in that container. Nodes clickable → open entity detail modal. "View full graph" button → navigates to Graph page with this subgraph highlighted.

**This is the only ticket that writes Cytoscape integration code for the chat panel** — `FE-004` intentionally left this as an empty placeholder to avoid building the same Cytoscape wiring twice.

**Acceptance Criteria:**
- Mini graph renders inside the container `FE-004` reserved (320px wide)
- Reuses `GraphCanvas` from `GRAPH-002` (same styling, simplified: no edge labels, smaller nodes) rather than a separate implementation
- Clickable nodes → entity detail modal
- "View full graph" navigates correctly

---

**Epic 5 Total: ~7 days**

---

## Epic 6: Compare Mode

### [COMPARE-001] Compare Page UI
**Priority:** P1  
**Estimate:** 2 days  
**Dependencies:** FE-001, RETRIEVAL-006  
**Description:**  
Build Compare page with: shared query input at top, two-panel layout (Vanilla RAG left, GraphRAG right), each panel shows: retrieved data (chunks list vs. subgraph mini-viz), generated answer (markdown), stats (latency, tokens, source count). On mobile: stacked with tab switcher.

**Acceptance Criteria:**
- Same question runs through both systems simultaneously
- Side-by-side layout on desktop, stacked on mobile
- Each panel clearly labeled
- Stats displayed: latency, token count, source count
- Loading state: both panels show loading indicator
- Clear visual differentiation between panels

---

### [COMPARE-002] Verdict / Vote Feature
**Priority:** P2  
**Estimate:** 0.5 days  
**Dependencies:** COMPARE-001  
**Description:**  
Add optional "Which answer was better?" vote below comparison results. Options: "Vanilla was better", "GraphRAG was better", "Both equally good", "Both bad". Store votes in `query_log` table. This data is for future self-improvement (not user-facing analytics).

**Acceptance Criteria:**
- Vote buttons appear after both answers loaded
- Vote stored in database tied to query
- User can change vote within session
- No vote required (optional)

---

**Epic 6 Total: ~2.5 days**

---

## Epic 7: Evaluation & Demo

### [EVAL-001] Build Evaluation Dataset
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** EXTRACT-005  
**Description:**  
Curate a demo paper set: 20-30 papers from a specific subfield (suggested: "Transformer architectures for NLP" — BERT, GPT, T5, etc. — well-known, easy to verify). Manually create 50 evaluation questions with gold answers:

- 20 single-hop questions (answerable by vanilla RAG)
- 20 multi-hop questions (require graph traversal)
- 10 comparison/contradiction questions

Store as `tests/eval/eval_dataset.json`.

**Acceptance Criteria:**
- 20-30 papers ingested and fully processed
- 50 questions with gold answers written
- Questions categorized by type (single-hop, multi-hop, comparison)
- Gold answers include source paper references

---

### [EVAL-002] Automated Evaluation Script
**Priority:** P0  
**Estimate:** 2 days  
**Dependencies:** EVAL-001, RETRIEVAL-006  
**Description:**  
Create `tests/eval/run_eval.py`. Runs all 50 questions through both GraphRAG and vanilla RAG. Scores each answer against gold answer using: (a) LLM-as-judge (does the answer correctly address the question? does it cite the right papers?), (b) retrieval recall (what fraction of gold-answer entities appear in retrieved context?). Output: comparison table, overall scores, per-category breakdown.

Save results to `tests/eval/eval_results/`.

**Acceptance Criteria:**
- Full evaluation runs end-to-end (50 questions × 2 systems = 100 LLM calls for answers + 100 for judging)
- Output includes: overall accuracy per system, per-category accuracy, specific examples where GraphRAG wins
- Results saved as JSON + human-readable markdown report
- GraphRAG outperforms vanilla RAG on multi-hop questions (target: 2x accuracy)

---

### [EVAL-003] Demo Seed Script
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** EVAL-001  
**Description:**  
Create `scripts/seed_sample_papers.py`. Downloads the demo paper set (from ArXiv), runs full ingestion pipeline, and populates the graph. A new developer can run this script after `docker-compose up` to have a working demo with real data in <10 minutes.

**Acceptance Criteria:**
- Script runs unattended (no manual steps)
- Downloads papers from ArXiv (handles network errors)
- Full pipeline: download → ingest → extract → resolve → graph
- After script: demo queries return meaningful answers

---

### [EVAL-004] README & Documentation
**Priority:** P0  
**Estimate:** 1.5 days  
**Dependencies:** All above  
**Description:**  
Write comprehensive `README.md`: project overview (what + why), architecture diagram (ASCII or linked image), tech stack list, quick start guide (docker-compose up + seed script), usage examples (example queries with screenshots), evaluation results summary (GraphRAG vs vanilla RAG comparison table), key technical decisions and tradeoffs, future roadmap. Also: populate `docs/` with all 5 specification documents.

**Acceptance Criteria:**
- New developer can go from clone → running demo in <15 minutes following README
- Architecture clearly explained with diagram
- Evaluation results prominently shown (this is the recruiter hook)
- Screenshots of all 4 pages (Chat, Graph, Papers, Compare)

---

**Epic 7 Total: ~6.5 days**

---

## Epic 8: Polish & Production Readiness (P1/P2)

### [POLISH-001] Error Handling & Edge Cases
**Priority:** P1  
**Estimate:** 2 days  
**Dependencies:** All Epics 1-6  
**Description:**  
Audit all error paths. Add: graceful handling for empty graph (no papers), LLM timeout recovery, partial extraction handling (paper partially processed), concurrent upload handling, graph traversal on disconnected graphs. Add proper HTTP error responses with request IDs.

---

### [POLISH-002] Rate Limiting
**Priority:** P1  
**Estimate:** 0.5 days  
**Dependencies:** SETUP-003  
**Description:**  
Add rate limiting via slowapi on all endpoints (as per Security doc §5.1 limits). Implement only the non-auth rows (`/ingest/upload`, `/query`, `/query/compare`, all-other-endpoints) — the `/auth/login` and `/auth/refresh` rows in that table describe the future production/multi-user system and don't apply since MVP has no auth (§2.1). Skip them; they're not a gap in this ticket.

---

### [POLISH-003] Dark Mode
**Priority:** P2  
**Estimate:** 1 day  
**Dependencies:** FE-001  
**Description:**  
Implement dark mode toggle in header. Use Tailwind dark mode classes. Graph colors adapt to dark background. Persist preference in localStorage.

---

### [POLISH-004] ArXiv Auto-Import
**Priority:** P1  
**Estimate:** 1.5 days  
**Dependencies:** INGEST-004  
**Description:**  
Create `POST /api/v1/ingest/arxiv` endpoint. Accept ArXiv URL or paper ID. Download PDF via ArXiv API. Extract metadata from ArXiv API (title, authors, abstract, year). Run through ingestion pipeline. Frontend: URL input field on Papers page.

---

### [POLISH-005] Collection Management (Organizational Only — MVP Scope)
**Priority:** P1  
**Estimate:** 1 day  
**Dependencies:** SETUP-004, FE-002, INGEST-007  
**Description:**  
Full CRUD for collections in API + frontend: create collection, rename, delete, assign papers to collections. Filter the **Papers page only** by selected collection (already supported by `INGEST-007`'s `GET /papers?collection_id=`).

**Scope correction from earlier draft:** this ticket does **NOT** include filtering Chat or Graph answers by collection — that requires adding `collection_id` to chunk/entity metadata and deciding how shared entities across collections should behave (see the MVP scoping decision on `RETRIEVAL-001`). That's split out below as `POLISH-005b`, explicitly P2/deferred, so it doesn't silently ride along with this ticket's estimate.

**Acceptance Criteria:**
- Create/rename/delete collection works via API + UI
- Assigning papers to a collection works
- Papers page list/filter by collection works correctly
- Chat and Graph pages are NOT claimed to be collection-filtered by this ticket

---

### [POLISH-005b] Per-Collection Retrieval Scoping (Deferred — Not MVP)
**Priority:** P2  
**Estimate:** 2-3 days (rough — real design work, not a quick filter)  
**Dependencies:** POLISH-005, INGEST-002, EXTRACT-004  
**Description:**  
Only build this if/when collection-scoped answers are actually needed. Requires: (1) adding `collection_id` to `paper_chunks` and `entity_embeddings` metadata in Chroma (touches `INGEST-002` chunking and `EXTRACT-004` graph/vector writes), (2) filtering `RETRIEVAL-001`'s vector search and `RETRIEVAL-002`'s graph traversal by `collection_id`, (3) an explicit decision on shared-entity behavior — an entity like `BERT` resolved from papers in two different collections either (a) shows up in both collections' results (entity is collection-agnostic, only the paper/chunk provenance is scoped), or (b) gets resolved separately per collection (defeats global dedup, more Neo4j nodes). Recommend (a) — simpler, matches how `EXTRACT-003` already works. Write this decision into `02_TECHNICAL_ARCHITECTURE.md` §5 before implementing.

**Acceptance Criteria:**
- Query in Collection A never returns citations from papers only in Collection B
- Shared entities behave per the decision documented above (not ad-hoc per query)
- `RETRIEVAL-001`/`RETRIEVAL-002` tickets' "global retrieval" note updated to reflect the change once this ships

---

### [POLISH-006] Faithfulness Check (Self-Audit)
**Priority:** P2  
**Estimate:** 2 days  
**Dependencies:** RETRIEVAL-005  
**Description:**  
Create `src/services/generation/faithfulness.py`. After generating an answer, run a second LLM call: "Does this answer follow from the provided context? Score each claim." If faithfulness score < threshold, add a warning to the response: "⚠️ Low confidence — some claims may not be fully supported by the retrieved sources."

---

### [POLISH-007] Export Graph Data
**Priority:** P2  
**Estimate:** 0.5 days  
**Dependencies:** EXTRACT-004  
**Description:**  
Create `GET /api/v1/graph/export?format=json` endpoint. Export full graph as JSON (nodes + edges). Frontend: "Export" button on Graph page.

---

**Epic 8 Total: ~8.5 days core (P1) + ~2-3 days optional/deferred `POLISH-005b` (P2, not counted in MVP total below)**

---

## Summary

| Epic | Name | Tickets | Estimated Days |
|------|------|---------|---------------|
| 0 | Project Setup & Infrastructure | 9 | 7.5 |
| 1 | PDF Ingestion Pipeline (Baseline RAG) | 7 | 8.5 |
| 2 | Entity & Relationship Extraction | 6 | 10.5 |
| 3 | Hybrid Retrieval Engine | 6 | 7.5 |
| 4 | Frontend — Core UI | 5 | 7.5 |
| 5 | Graph Visualization | 4 | 7 |
| 6 | Compare Mode | 2 | 2.5 |
| 7 | Evaluation & Demo | 4 | 6.5 |
| 8 | Polish & Production Readiness (P1 core) | 7 | 8.5 |
| — | `POLISH-005b` Per-Collection Retrieval Scoping (P2, deferred, not in MVP total) | 1 | 2-3 (not counted) |
| | **TOTAL (MVP, P0-P1)** | **50 tickets** | **~66 days** |

### Suggested Sprint Plan (2-week sprints)

| Sprint | Epics | Goal |
|--------|-------|------|
| Sprint 1 (Week 1-2) | Epic 0 + Epic 1 | Infrastructure running + vanilla RAG baseline working |
| Sprint 2 (Week 3-4) | Epic 2 | Entity/relationship extraction pipeline working |
| Sprint 3 (Week 5-6) | Epic 3 | Hybrid retrieval working — core GraphRAG functional |
| Sprint 4 (Week 7-8) | Epic 4 | Frontend chat + papers pages working |
| Sprint 5 (Week 9-10) | Epic 5 + Epic 6 | Graph visualization + comparison mode |
| Sprint 6 (Week 11-12) | Epic 7 | Evaluation + demo + documentation |
| Sprint 7 (Week 13-14) | Epic 8 | Polish, edge cases, production readiness |

### Critical Path

The minimum viable demo requires completing these tickets in order:

```
SETUP-001 → SETUP-002 → SETUP-003 → SETUP-004/005/006 (parallel)
  → SETUP-008 → INGEST-001 → INGEST-002 → INGEST-003
  → EXTRACT-001 → EXTRACT-002 → EXTRACT-003 → EXTRACT-004 → EXTRACT-005
  → RETRIEVAL-001 → RETRIEVAL-002 → RETRIEVAL-003 → RETRIEVAL-004 → RETRIEVAL-005
  → FE-001 → FE-003
  → EVAL-001 → EVAL-002
```

Note: `INGEST-007` (Papers CRUD API) isn't on this minimal path — the bare chat demo above doesn't need a papers list/delete UI. It IS required before `FE-002` (Papers Management Page), so if you want the Papers page working alongside the chat demo, insert `INGEST-007` after `EXTRACT-005` and before `FE-002`.

This path gives you: a working GraphRAG system with a chat UI and evaluation results. Everything else (graph viz, compare mode, polish) is important but not on the critical path.
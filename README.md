# LitGraph

LitGraph is a **GraphRAG system for academic literature**: it ingests research papers, extracts entities and relationships with an LLM, builds a knowledge graph in Neo4j, and answers multi-hop questions (e.g. *"what methods improved on BERT and by how much?"*) that plain vector-search RAG can't — with an evaluation suite that measures the difference against a vanilla RAG baseline.

Why this exists: standard RAG retrieves chunks of text that are *semantically similar* to a question. That's fine for "what does BERT's abstract say?", but it can't answer "which of these five papers actually beats BERT, and on what metric?" — that's a relationship query across multiple documents, which a vector index alone has no structure to represent. LitGraph builds that structure explicitly (a knowledge graph of methods, datasets, claims, and how papers relate to them) and retrieves by *traversing* it, not just embedding-searching it.

## Quick Start

Requires Docker + Docker Compose, at least one LLM provider API key (a free-tier key is enough), and four managed cloud services — all free-tier: [Supabase](https://supabase.com) (Postgres), [Neo4j AuraDB](https://neo4j.com/cloud/aura-free/) (graph), [Qdrant Cloud](https://cloud.qdrant.io) (vectors), [Upstash](https://upstash.com) (Redis/Celery broker). See [`.env.example`](.env.example) for every variable.

```bash
git clone <this repo>
cd LitGraph-Ai
cp .env.example .env
# edit .env:
# - DATABASE_URL (Supabase), NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD (AuraDB),
#   QDRANT_URL/QDRANT_API_KEY (Qdrant Cloud), REDIS_URL (Upstash) — one free
#   instance of each is enough to run the whole stack
# - set GEMINI_API_KEY (or GROQ_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY)
#   and matching LLM_PROVIDER — .env.example documents every option

docker compose up -d
docker compose exec backend python scripts/seed_sample_papers.py
```

`docker compose up` only starts `backend` and `celery_worker` — the four data stores are managed cloud services, not local containers, so there's nothing else to bring up.

The seed script downloads a curated 10-paper demo set (BERT, GPT-2, GPT-3, RoBERTa, ELECTRA, XLNet, DistilBERT, ALBERT, T5, and "Attention Is All You Need") and runs each through the real ingestion pipeline. It prints progress as papers finish; a fresh run typically takes a few minutes per paper on a cloud LLM provider (much longer on a free-tier-exhausted day, since the pipeline then falls back to a local Ollama model — see [Key Decisions](#key-decisions-and-tradeoffs) below).

Once seeding finishes:

| Page | URL | What it's for |
|---|---|---|
| Chat | http://localhost:3000 | Ask a question, get an answer with cited sources |
| Graph Explorer | http://localhost:3000/graph | Visually browse the knowledge graph |
| Papers | http://localhost:3000/papers | Upload new PDFs, manage collections |
| Compare | http://localhost:3000/compare | Side-by-side GraphRAG vs vanilla RAG on the same question |

Backend API docs (FastAPI's auto-generated OpenAPI UI): http://localhost:8000/docs
Backend health (confirms all 4 cloud services are reachable): http://localhost:8000/health
Neo4j Browser (inspect the graph directly in Cypher): open your instance from the [Aura console](https://console.neo4j.io) — "Open" launches its browser against the cloud instance directly, no local port.

> Screenshots of all four pages go here — not included in this pass; take them against a locally seeded instance and drop them in `docs/screenshots/`.

## Example Queries

Once the demo set is seeded, try asking the Chat page things a single-document search can't answer well:

- *"What are BERT's two pretraining objectives?"* — single-hop, either system should get this.
- *"Name three specific changes RoBERTa makes to BERT's pretraining recipe."* — needs the graph edge connecting RoBERTa's paper to its own claims about BERT, not just semantic similarity to the word "BERT".
- *"BERT and T5 both use a masking/corruption-based pretraining signal, but T5 changes what the model has to predict. Contrast BERT's masked language modeling with T5's span-corruption objective."* — multi-hop: requires pulling claims from two different papers and relating them, which is exactly where GraphRAG's graph traversal is supposed to outperform vanilla RAG's flat vector search.

The Compare page runs a question through both systems side-by-side so the difference is visible directly, not just in an aggregate score.

## Evaluation

`tests/eval/run_eval.py` runs a 27-question benchmark (single-hop / multi-hop / comparison questions, gold answers in `tests/eval/eval_dataset.json`) through both GraphRAG and vanilla RAG, scores each answer with an LLM judge, and reports accuracy + source-paper recall per system and per category.

Latest published run (pre-dates this session's entity/relation-extraction quality fixes — see `tests/eval/eval_results/` for the full report and raw JSON):

| System | Accuracy | Source-paper recall |
|---|---|---|
| GraphRAG | 0.444 | 0.954 |
| Vanilla RAG | 0.370 | 0.917 |

| Category | GraphRAG accuracy | Vanilla accuracy |
|---|---|---|
| single-hop | 0.667 | 0.500 |
| multi-hop | 0.250 | 0.333 |
| comparison | 0.500 | 0.250 |

GraphRAG already wins overall and on single-hop/comparison questions, largely on citing the right source paper more reliably. It was *behind* vanilla RAG on multi-hop questions in this run — the actual hard case GraphRAG's graph traversal is supposed to be built for. That gap traced back to graph data-quality bugs (LLM extraction occasionally attaching a relationship to the wrong entity, or double-counting a dataset as both training and evaluation data) rather than a retrieval-design problem — several rounds of fixes for exactly this are in this repo's recent history. Re-run `run_eval.py` after seeding to get current numbers; this table will go stale as extraction quality keeps improving.

## Architecture

```
                              FRONTEND (React + TypeScript)
        Chat  ·  Graph Explorer (Cytoscape.js)  ·  Papers  ·  Compare
                                    │ REST API
                                    ▼
                          BACKEND (FastAPI, async)
   /ingest   /query   /graph   /papers   /collections
        │
        ▼
   Service layer
   ┌─────────────────┬──────────────────┬────────────────────┐
   │ Ingestion        │ Retrieval        │ Generation          │
   │ PDF parse        │ Vector search    │ Context builder     │
   │ Chunk + embed    │ Graph traversal  │ LLM call            │
   │ Entity extract   │ Hybrid scoring   │ Citation formatting │
   │ Entity resolve   │                  │                     │
   │ Graph write      │                  │                     │
   └─────────────────┴──────────────────┴────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
   PostgreSQL          Neo4j AuraDB         Qdrant Cloud
   (Supabase Cloud)    (knowledge graph:    (vector embeddings:
   (paper metadata,     Method/Dataset/      paper chunks +
    job status)          Claim/Author nodes)  resolved entities)

   Celery + Redis (Upstash Cloud) run ingestion as a background job — an
   LLM-heavy paper extraction can take minutes; the upload request returns
   immediately with a job id, polled via GET /ingest/status/{job_id}.
```

All four data stores above are managed cloud services, not containers — `docker compose up` brings up only `backend` and `celery_worker`; both read their connection strings from `.env`.

Full detail: [Technical Architecture doc](docs/02_TECHNICAL_ARCHITECTURE.md).

### Ingestion pipeline

1. **Parse** — PyMuPDF extracts text, sections, tables, title/authors from the PDF.
2. **Chunk + embed** — split into overlapping chunks, embed locally (`all-MiniLM-L6-v2`, no API call), store in Qdrant Cloud.
3. **Extract** — per section, an LLM pulls out methods, datasets, metrics, and claims, then relationships between them (two passes: relationships within this paper, then relationships to entities already known from *other* papers).
4. **Resolve** — a cascading strategy (exact match → fuzzy name match → embedding similarity → LLM verification as the final tiebreak) decides whether a newly-extracted entity is the same real-world thing as one already in the graph, so "BERT" mentioned in five different papers becomes one node, not five.
5. **Write** — entities and relationships land in Neo4j AuraDB; a paper's claims and its chunk embeddings both get a Qdrant entry so retrieval can hit either.

### Retrieval

A question is answered by **both** a vector search over chunk/entity embeddings and a graph traversal from any entities named in the question, then a hybrid scorer merges the two into one ranked context before the generation LLM call. Vanilla RAG (the comparison baseline) only does the vector-search half.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (async Python) | Auto-generated OpenAPI docs, Pydantic validation, async I/O for concurrent LLM calls |
| Metadata DB | PostgreSQL (Supabase Cloud) | Paper records, extraction job status, collections — managed, no local container to keep alive |
| Knowledge graph | Neo4j (AuraDB Cloud, free tier) | Purpose-built for relationship traversal (Cypher); managed instance instead of a local Neo4j container |
| Vector store | Qdrant Cloud | Paper chunks + resolved entities. Migrated from an embedded ChromaDB container — `src/vectorstore/store.py`'s `QdrantCollectionAdapter` keeps the same collection interface the rest of the pipeline already used, so nothing above the vectorstore layer had to change |
| LLM | Provider-agnostic client (`src/utils/llm_client.py`) — Gemini/Groq/OpenAI/Anthropic/OpenRouter/local Ollama, one interface | Free-tier daily caps on any single provider are tight enough (as low as ~20 req/day, measured live) that a single-provider design isn't viable for a portfolio-scale demo — the client transparently fails over across providers mid-run rather than losing an in-progress paper's extraction |
| Embeddings | `all-MiniLM-L6-v2` (local, sentence-transformers) | Zero cost, zero rate limit; swappable for an API embedding model later via config |
| PDF parsing | PyMuPDF | Fast, no extra infra; heuristic section/author/reference extraction tuned against real papers (see `src/services/ingestion/pdf_parser.py`'s own comments for the specific live-PDF edge cases it handles) |
| Frontend | React + TypeScript + Tailwind | Standard, type-safe, fast to iterate |
| Graph UI | Cytoscape.js | Purpose-built graph/network visualization with layout algorithms |
| Task queue | Celery + Redis (Upstash Cloud) | Ingestion is LLM-bound and slow; runs as a background job, not inline with the upload request. Managed Redis instead of a local container — same reasoning as the other three data stores |
| Containerization | Docker Compose | Brings up `backend` + `celery_worker`; the four data stores above are managed cloud services, not containers, so there's nothing else in the compose file |

## Key Decisions and Tradeoffs

- **Provider-agnostic LLM client with automatic failover, not a single hardcoded provider.** Every major free-tier provider's daily quota turned out to be small enough, live, that a real multi-section paper extraction can exhaust it mid-paper. `llm_client.py`'s key/provider ring walks forward through providers on a quota or server error (never backward — a quota reset doesn't happen mid-process anyway) instead of failing the whole job. Local Ollama sits last in the chain as a genuinely unlimited (if slower) fallback once every cloud option is exhausted.
- **Entity resolution is a cascade, not one similarity check.** Exact name match alone misses "BERT" vs "BERT-base"; a raw string-edit-distance ratio alone misses "BERT" vs its own full expansion ("Bidirectional Encoder Representations from Transformers"); embedding similarity alone can't distinguish "BERT" the model from a person named "BERT" if their descriptions happen to read similarly. Each signal covers the others' blind spot; an LLM call is the final tiebreaker only for the ambiguous cases the cheaper signals flag, not every entity.
- **Structural backstops over prompt-only fixes where the mistake has a generic shape.** Prompt wording alone doesn't reliably stop an LLM from e.g. attaching a relationship to an entity that's never actually named in its own cited evidence sentence — even a strongly-worded instruction can lose out to a plausible-looking pattern match. Where a bad extraction has a checkable structural signature (the target name doesn't appear in the evidence text; the same dataset gets contradictory relationship types in one run), the pipeline verifies and drops it in code, generically — never via a hardcoded list of specific paper/method/dataset names.
- **Managed cloud services over local Docker containers for every data store.** Postgres, Neo4j, and the vector store started as local containers (ChromaDB's zero-config embedded mode, specifically, for build-phase iteration speed) but migrated to Supabase/AuraDB/Qdrant Cloud/Upstash once the project moved past single-machine iteration — one `.env` swap instead of four local services to keep alive, back up, and share across machines. `src/vectorstore/store.py`'s `QdrantCollectionAdapter` deliberately mirrors ChromaDB's old collection interface (`.get()`/`.add()`/`.delete()`/`.query()`) so the migration stayed contained to that one file — nothing in the ingestion or retrieval layers above it changed. The migration scripts (`scripts/migrate_*.py`) and a local dump of the pre-migration data (`data_backups/`, gitignored) are kept around as the rollback path; the local containers themselves stay up for a couple of weeks post-migration as a live safety net before being torn down.
- **Collections are organizational, not a retrieval boundary, by default.** An entity like "BERT" resolved from papers in two different collections shows up in both collections' results rather than being resolved separately per collection — simpler, and avoids doubling the graph's node count for shared entities. See `POLISH-005b` for where per-collection retrieval scoping was added on top once actually needed. This is a soft boundary, not hard data isolation: only `Paper` nodes carry a `collection_id` (Method/Dataset/Author/Claim never do, by design), so a shared entity with even one genuine edge into a collection survives that collection's filter — and can pull its *source paper's* own citation/content along with it. Confirmed live: a bad cross-paper extraction (fixed in `EVAL-002` follow-up — see `pipeline.py`'s `_drop_non_content_sections`/`_exclude_own_name_candidates`) had bridged two otherwise-unrelated collections through exactly one spurious edge. If your collections need to stay topically hard-isolated, keep that in mind — a genuinely-discussed cross-paper relationship between two collections' papers will surface the same way, by design, not just a bug.

## Roadmap

Shipped: core ingestion pipeline (parse → chunk → extract → resolve → graph), hybrid retrieval, Chat/Graph/Papers/Compare pages, collection management, automated evaluation harness, demo seed script, request-ID error handling + duplicate-upload guard, rate limiting (slowapi), one-click ArXiv import, dark mode, a self-audit faithfulness check on GraphRAG answers, graph data export (JSON), migration off local Docker DB containers onto managed cloud services (Supabase/AuraDB/Qdrant Cloud/Upstash).

Every ticket in [`docs/05_FEATURE_TICKETS.md`](docs/05_FEATURE_TICKETS.md)'s Epic 8 (Polish) is now shipped — see that doc for what's scoped as future/production-only work beyond MVP (auth, GraphML/CSV export formats beyond JSON, etc).

## Docs

Full specs live in [`docs/`](docs/): [PRD](docs/01_PRD.md), [Technical Architecture](docs/02_TECHNICAL_ARCHITECTURE.md), [Security & Access](docs/03_SECURITY_ACCESS.md), [Frontend Spec](docs/04_FRONTEND_SPECIFICATION.md), [Feature Tickets](docs/05_FEATURE_TICKETS.md).

## License

MIT — see [LICENSE](LICENSE).

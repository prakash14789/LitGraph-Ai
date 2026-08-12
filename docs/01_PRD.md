# LitGraph — Product Requirements Document (PRD)

> **Version:** 1.0  
> **Last Updated:** August 11, 2026  
> **Author:** Prakash  
> **Status:** Draft  

---

## 1. Executive Summary

**LitGraph** is a GraphRAG-powered research intelligence platform that transforms academic papers from flat, disconnected PDFs into a traversable knowledge graph — enabling researchers, students, and R&D teams to ask multi-hop questions that traditional vector-based RAG systems fundamentally cannot answer.

Unlike existing tools (Semantic Scholar, Connected Papers, Elicit, ChatGPT with PDFs), LitGraph doesn't just retrieve relevant chunks of text. It **extracts entities** (papers, authors, methods, datasets, metrics, findings), **maps relationships** between them (extends, contradicts, outperforms, uses), and performs **hybrid retrieval** combining graph traversal with vector similarity — so it can answer questions like:

- *"What's the full lineage of attention mechanisms from 2017 to 2025?"*
- *"Which papers contradict each other on the effectiveness of dropout in transformers?"*
- *"Show me every method that was evaluated on SQuAD and how their F1 scores compare across papers."*

These are **graph-shaped questions** — they require understanding connections between entities across multiple documents. Vector RAG retrieves isolated chunks; LitGraph retrieves structured subgraphs.

---

## 2. Problem Statement

### 2.1 The Core Problem

Academic researchers spend **30-50% of their literature review time** not reading papers, but manually tracing connections: who cited whom, which method extended which, what datasets were used across related work, and where findings conflict. This is graph traversal done by hand — slow, error-prone, and impossible to scale beyond ~50 papers.

### 2.2 Why Existing Tools Fail

| Tool | What It Does | Where It Breaks |
|------|-------------|-----------------|
| **Semantic Scholar** | Citation graph + semantic search | No content-level entity extraction — you see citation links but can't query "which papers used BERT on medical data" |
| **Connected Papers** | Visual citation similarity graph | Similarity-based, not relationship-based — can't distinguish "extends" from "contradicts" |
| **Elicit** | LLM-powered paper search + extraction | Flat extraction — pulls fields per-paper but doesn't build cross-paper relationships |
| **ChatGPT / Perplexity** | Chat over papers | Pure vector RAG — retrieves similar chunks, fails on multi-hop ("what method did Paper A use, and which later paper improved it?") |
| **ResearchRabbit** | Citation-based discovery | No content understanding — operates purely on citation metadata |

### 2.3 The Gap

No existing tool combines:
1. **Content-level entity extraction** (methods, datasets, metrics, claims — not just title/author/abstract)
2. **Typed relationship mapping** across papers (EXTENDS, CONTRADICTS, OUTPERFORMS, USES_METHOD, EVALUATES_ON)
3. **Hybrid retrieval** that combines graph structure with semantic similarity
4. **Natural language querying** over the resulting knowledge graph

LitGraph fills this gap.

---

## 3. Target Users

### 3.1 Primary Users

| User Persona | Pain Point | How LitGraph Helps |
|-------------|-----------|-------------------|
| **Graduate Students (MS/PhD)** doing literature reviews | Manually reading 50-200 papers, building mental models of "who did what, building on whom" — this takes weeks | Upload papers → instant knowledge graph → ask multi-hop questions → get cited, structured answers in minutes |
| **Research Engineers (Industry R&D)** evaluating methods for production | Need to quickly compare approaches: which method works best on which data, with what tradeoffs — buried across 20+ papers | Query "compare all methods evaluated on [dataset] by [metric]" → structured comparison grounded in extracted data |
| **Academic Advisors / PIs** staying current in fast-moving fields | Can't read every new paper — need "what changed in [subfield] in the last 6 months" type summaries | Upload recent papers → graph auto-links to existing knowledge → surface new methods, contradictions, trends |

### 3.2 Secondary Users

- **Science journalists** who need to trace the evolution of an idea (e.g., "how did mRNA vaccine research evolve from 2010 to 2020?")
- **Patent analysts** checking prior art across research publications
- **Systematic review authors** who need exhaustive method/result tracking across a corpus

### 3.3 User Stories

**US-1:** As a PhD student, I want to upload 30 papers from my reading list and ask "which papers in this set used transformer-based methods, and how did their approaches differ?" — so I can write my related work section in hours instead of days.

**US-2:** As a research engineer, I want to ask "show me the lineage of object detection methods from R-CNN to YOLOv8, including what each version changed" — so I can understand the design decisions behind the current state-of-the-art.

**US-3:** As a PhD student, I want to ask "which papers in my collection contradict each other on [specific claim]?" — so I can identify open research questions and position my contribution.

**US-4:** As a PI, I want to upload 10 new papers and see how they connect to my existing knowledge graph — so I can quickly spot which new work is relevant to my lab's research directions.

**US-5:** As a researcher, I want to visually explore the knowledge graph — click on a method node, see all papers that use it, click on a paper, see what it extends — so I can discover connections I didn't know existed.

**US-6:** As a user, I want to compare my GraphRAG answers against a baseline vanilla RAG — so I can see the quality difference and trust the system.

---

## 4. Product Features

### 4.1 Feature Map (Priority Tiers)

#### P0 — Must Have (MVP)

| Feature | Description |
|---------|-------------|
| **F1: Paper Ingestion Pipeline** | Upload PDFs or paste ArXiv URLs → parse full text (sections, references, tables) → store raw content. Support batch upload (up to 50 papers at once). Handle common PDF formats (two-column, single-column, LaTeX-generated). |
| **F2: Entity Extraction** | LLM-based extraction of entities from each paper: Paper metadata (title, authors, year, venue), Methods/Models mentioned, Datasets used, Metrics reported (with values), Key Claims/Findings. Output as structured JSON per paper. |
| **F3: Relationship Extraction** | LLM-based extraction of typed relationships between entities: CITES, EXTENDS (method A builds on method B), CONTRADICTS (finding A opposes finding B), USES_METHOD, EVALUATES_ON (paper evaluated on dataset X), OUTPERFORMS (method A beats method B on metric M), AUTHORED_BY, INTRODUCES (paper first proposes method/dataset). |
| **F4: Entity Resolution** | Deduplicate entities across papers — "BERT," "BERT-base," "Bidirectional Encoder Representations" → single canonical entity. Use embedding similarity + fuzzy string matching + LLM verification for ambiguous cases. |
| **F5: Knowledge Graph Construction** | Store entities as nodes, relationships as typed edges in Neo4j. Each node carries: metadata, source paper reference, text chunk embedding. Each edge carries: type, confidence score, source evidence (the text span that supports this relationship). |
| **F6: Hybrid Retrieval Engine** | Given a natural language query: (a) vector search to find seed entities/papers, (b) graph traversal N hops from seeds, (c) combined scoring (graph distance + semantic similarity), (d) return ranked subgraph as structured context. |
| **F7: Answer Generation** | LLM generates answer from structured graph context. Answer must: cite source papers, reference specific relationships, handle "I don't know" when graph doesn't contain the answer. |
| **F8: Chat Interface** | Clean chat UI where user types questions and gets answers with citations. Show which papers/entities were used in the answer. |

#### P1 — Should Have (Post-MVP)

| Feature | Description |
|---------|-------------|
| **F9: Graph Visualization** | Interactive visual graph explorer (D3.js / Cytoscape.js). Click nodes to see details, hover edges to see relationship evidence. Filter by entity type, relationship type, date range. For each query answer, show the retrieved subgraph visually. |
| **F10: Baseline Comparison Mode** | Side-by-side: same question answered by vanilla vector RAG vs. GraphRAG. Shows retrieved chunks (vector) vs. retrieved subgraph (graph). Lets user see where GraphRAG wins. |
| **F11: ArXiv Auto-Import** | Paste an ArXiv URL or paper ID → auto-download PDF + metadata → run through ingestion pipeline. Also: given a paper, auto-fetch its references from ArXiv/Semantic Scholar API and offer to ingest them. |
| **F12: Collection Management** | Organize papers into named collections/projects. Each collection has its own knowledge graph. User can merge collections or compare graphs across collections. |

#### P2 — Nice to Have (Future)

| Feature | Description |
|---------|-------------|
| **F13: Incremental Graph Updates** | When new papers are added, update the graph incrementally (don't rebuild from scratch). Detect how new papers connect to existing entities. Surface "new connections" to the user. |
| **F14: Contradiction Detection** | Automated scan: find entity pairs where one paper claims X and another claims NOT-X (or significantly different results). Surface these as "open questions" or "debates in the literature." |
| **F15: Export** | Export knowledge graph as JSON-LD, RDF, or CSV. Export answers as formatted markdown/PDF reports with citations. |
| **F16: Collaborative Collections** | Multiple users contribute papers to a shared collection. Shared knowledge graph with access controls. |
| **F17: Citation-Aware Writing Assistant** | "Help me write the related work section" → uses graph to generate a structured narrative of how methods evolved, with proper citations. |

---

## 5. Entity & Relationship Schema

### 5.1 Entity Types

```
PAPER
  - title: string
  - authors: string[]
  - year: integer
  - venue: string (conference/journal name)
  - arxiv_id: string (optional)
  - doi: string (optional)
  - abstract: string
  - source_pdf_path: string

METHOD
  - canonical_name: string (e.g., "BERT")
  - aliases: string[] (e.g., ["BERT-base", "Bidirectional Encoder Representations"])
  - category: string (e.g., "language model", "object detection", "optimization")
  - description: string (extracted from first-introducing paper)

DATASET
  - canonical_name: string (e.g., "SQuAD 2.0")
  - aliases: string[]
  - domain: string (e.g., "NLP", "computer vision", "medical")
  - description: string

METRIC
  - name: string (e.g., "F1 Score", "BLEU", "mAP")
  - higher_is_better: boolean

CLAIM
  - text: string (the actual claim, extracted verbatim or paraphrased)
  - claim_type: enum [RESULT, HYPOTHESIS, LIMITATION, FUTURE_WORK]
  - source_paper_id: string

AUTHOR
  - name: string
  - aliases: string[]
  - affiliations: string[]
```

### 5.2 Relationship Types

```
CITES              (PAPER) -[:CITES]-> (PAPER)
EXTENDS            (PAPER|METHOD) -[:EXTENDS]-> (METHOD)
CONTRADICTS        (CLAIM) -[:CONTRADICTS]-> (CLAIM)
USES_METHOD        (PAPER) -[:USES_METHOD]-> (METHOD)
EVALUATES_ON       (PAPER) -[:EVALUATES_ON {metric: string, value: float}]-> (DATASET)
OUTPERFORMS        (METHOD) -[:OUTPERFORMS {metric: string, dataset: string, margin: float}]-> (METHOD)
INTRODUCES         (PAPER) -[:INTRODUCES]-> (METHOD|DATASET)
AUTHORED_BY        (PAPER) -[:AUTHORED_BY]-> (AUTHOR)
REPORTS_RESULT     (PAPER) -[:REPORTS_RESULT]-> (CLAIM)
```

Each relationship edge carries:
- `confidence`: float (0-1) — extraction confidence
- `evidence_text`: string — the source text span that supports this relationship
- `source_paper_id`: string — which paper this was extracted from

---

## 6. Success Metrics

### 6.1 Technical Metrics (You Measure These)

| Metric | Target | How to Measure |
|--------|--------|---------------|
| **Multi-hop Answer Accuracy** | GraphRAG answers ≥70% of multi-hop questions correctly vs. ≤30% for vanilla RAG | Build eval set of 50 multi-hop questions with gold answers. Score both systems. |
| **Entity Extraction Precision** | ≥85% of extracted entities are real entities mentioned in the paper | Manual review of extraction output on 20 papers |
| **Entity Resolution Accuracy** | ≥80% of duplicate entities correctly merged | Create test set with known duplicates, measure merge accuracy |
| **Relationship Extraction Precision** | ≥75% of extracted relationships are factually correct | Manual review of relationship output on 20 papers |
| **Retrieval Relevance (Subgraph)** | ≥80% of nodes in retrieved subgraph are relevant to the query | Manual relevance judgment on 30 queries |
| **Answer Faithfulness** | ≥90% of generated answer claims are grounded in retrieved subgraph | Manual faithfulness check on 30 answers |
| **Ingestion Latency** | ≤60 seconds per paper (parse + extract + graph insert) | Time the pipeline end-to-end |
| **Query Latency** | ≤10 seconds from query to answer (including graph traversal + LLM call) | Time the retrieval + generation pipeline |

### 6.2 Product Metrics (If Deployed)

| Metric | Target | How to Measure |
|--------|--------|---------------|
| **User Retention** | 40% of users return within 7 days | Analytics |
| **Papers Ingested Per User** | Average ≥15 papers per active user | Usage tracking |
| **Queries Per Session** | Average ≥5 queries per session (indicates trust + value) | Usage tracking |
| **Graph Exploration Engagement** | ≥30% of users interact with graph visualization | Click tracking |
| **Baseline Comparison Usage** | ≥20% of users try the GraphRAG vs. vanilla RAG comparison | Feature usage tracking |

### 6.3 Portfolio/Recruiter Success Metrics

| Metric | What It Proves |
|--------|---------------|
| **Working demo with 30+ papers ingested** | You built something real, not a toy |
| **Side-by-side comparison showing GraphRAG winning on multi-hop** | You understand evaluation + can articulate why your approach is better |
| **Graph visualization showing extracted entities/relationships** | Instant visual "wow factor" — 10-second recruiter hook |
| **Clean GitHub repo with architecture docs** | Professional engineering habits |
| **Blog post / README explaining the architecture and tradeoffs** | Communication skills + technical depth |

---

## 7. What LitGraph is NOT

- **Not a paper search engine.** It doesn't crawl the internet for papers. You bring the papers — it builds the graph.
- **Not a citation manager.** It's not competing with Zotero/Mendeley. It doesn't manage your bibliography formatting.
- **Not a paper summarizer.** ChatGPT already summarizes papers fine. LitGraph's value is in *cross-paper* relationships, not single-paper summaries.
- **Not a writing tool.** It helps you understand the literature, not write your paper (though F17 could add this later).

---

## 8. Competitive Landscape & Differentiation

```
                    Content Understanding
                          HIGH
                           |
                  LitGraph ★
                           |
         Elicit ●          |
                           |
    LOW ───────────────────┼─────────────────── HIGH
     (No cross-paper       |         (Cross-paper
      relationships)       |          relationships)
                           |
         ChatGPT ●         |        Connected Papers ●
                           |        Semantic Scholar ●
                           |
                          LOW
                    Content Understanding
```

**LitGraph's unique position:** HIGH content understanding (entity/relationship extraction from full text) + HIGH cross-paper relationship modeling (typed edges in a knowledge graph, not just citation links).

---

## 9. Assumptions & Risks

### Assumptions
1. LLM-based entity/relationship extraction is accurate enough (≥75% precision) to build a useful graph without massive manual correction.
2. Users have PDFs or ArXiv links for papers they want to analyze (we don't need to solve paper discovery).
3. A corpus of 20-100 papers is the sweet spot — small enough to ingest affordably, large enough to show graph value.
4. Researchers find multi-hop questions genuinely useful (not just a technical flex).

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Entity extraction too noisy → garbage graph | HIGH — core value proposition breaks | Confidence thresholds + human-in-loop review UI for low-confidence extractions |
| Entity resolution fails → duplicate nodes everywhere | HIGH — graph becomes misleading | Multiple resolution strategies (embedding + fuzzy + LLM) + merge review UI |
| LLM API costs too high for large corpora | MEDIUM — limits scale | Batch processing, caching, smaller models for extraction (not generation) |
| Graph traversal too slow for large graphs | MEDIUM — bad UX | Neo4j indexing, limit traversal depth, cache frequent subgraph patterns |
| Users don't ask multi-hop questions naturally | MEDIUM — they might not know what to ask | Suggested questions, example queries, guided exploration via graph viz |

---

## 10. Release Plan

| Phase | Scope | Timeline Target |
|-------|-------|----------------|
| **Phase 1: Baseline** | Vanilla vector RAG over papers (comparison baseline) | Week 1-2 |
| **Phase 2: Extraction** | Entity + relationship extraction pipeline | Week 3-4 |
| **Phase 3: Resolution** | Entity resolution + deduplication | Week 5 |
| **Phase 4: Graph** | Neo4j graph construction + hybrid retrieval | Week 6-7 |
| **Phase 5: Generation** | Answer generation with graph context + chat UI | Week 8 |
| **Phase 6: Visualization** | Interactive graph explorer + baseline comparison | Week 9-10 |
| **Phase 7: Evaluation** | Build eval set, run comparisons, write up results | Week 11-12 |

---

## 11. Open Questions

1. **What LLM to use for extraction?** GPT-4o/Claude for quality, or a smaller fine-tuned model for cost? Start with API (GPT-4o-mini or Claude Haiku for extraction, full model for generation), consider fine-tuning later.
2. **How to handle papers without clear methodology sections?** Survey papers, position papers — extraction pipeline needs graceful degradation.
3. **How many hops in graph traversal?** 2-hop covers most multi-hop questions. 3+ gets noisy. Make it configurable and evaluate.
4. **Should users be able to manually correct extractions?** Adds complexity but dramatically improves graph quality. Start without it, add if extraction quality is too low.

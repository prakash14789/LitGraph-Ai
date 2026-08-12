# LitGraph

LitGraph is a GraphRAG system for academic literature: it ingests research papers, extracts entities and relationships with an LLM, builds a knowledge graph in Neo4j, and answers multi-hop questions (e.g. "what methods improved on BERT and by how much?") that plain vector-search RAG can't — with an evaluation suite that measures the difference against a vanilla RAG baseline.

Setup coming soon.

## Docs

Full specs live in [`docs/`](docs/): [PRD](docs/01_PRD.md), [Technical Architecture](docs/02_TECHNICAL_ARCHITECTURE.md), [Security & Access](docs/03_SECURITY_ACCESS.md), [Frontend Spec](docs/04_FRONTEND_SPECIFICATION.md), [Feature Tickets](docs/05_FEATURE_TICKETS.md).

## License

MIT — see [LICENSE](LICENSE).

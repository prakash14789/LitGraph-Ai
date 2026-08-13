// Mirrors src/api/schemas/query.py and src/models/paper.py — kept minimal
// to what api.ts actually needs today (FE-001's own scope is the API
// client shell, not full page implementations); extend per-field as
// FE-002/003/GRAPH pages start consuming more of each response.

export interface Citation {
  paper_id: string;
  title: string | null;
  year: number | null;
}

export interface SubgraphNode {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
  score: number;
  vector_similarity: number;
  graph_distance: number | null;
  avg_edge_confidence: number;
}

export interface SubgraphEdge {
  source: string;
  target: string;
  rel_type: string;
  properties: Record<string, unknown>;
}

export interface RetrievedSubgraph {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
}

export interface RetrievalStats {
  entity_seeds: number;
  chunk_seeds: number;
  graph_nodes: number;
  ranked_nodes: number;
  context_tokens: number;
  context_truncated: boolean;
  latency_ms: number;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  retrieved_subgraph: RetrievedSubgraph;
  retrieval_stats: RetrievalStats;
}

export interface SourceChunk {
  paper_id: string;
  paper_title: string | null;
  section_name: string;
  page_number: number | null;
  score: number;
  text: string;
}

export interface VanillaQueryResponse {
  answer: string;
  sources: SourceChunk[];
  latency_ms: number;
}

export interface CompareQueryResponse {
  graphrag: QueryResponse;
  vanilla: VanillaQueryResponse;
  total_latency_ms: number;
}

export type IngestionStatus = "pending" | "processing" | "completed" | "failed";

// Mirrors src/api/schemas/papers.py's PaperListItem exactly.
export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  ingestion_status: IngestionStatus;
  collection_id: string | null;
  created_at: string;
}

import axios from "axios";

import type {
  Collection,
  CompareQueryResponse,
  CompareVerdict,
  EntityDetailResponse,
  GraphOverview,
  GraphSubgraphResponse,
  Paper,
  PaperDetail,
  QueryResponse,
  SearchResponse,
  VanillaQueryResponse,
} from "@/types";

// No auth interceptors — MVP has no authentication (Security §2.1), no
// /auth/* API exists to call. Add JWT/cookie handling here only once one
// does; see 04_FRONTEND_SPECIFICATION.md §7.1 for the specific pitfall to
// avoid (refresh must go through this same client, HttpOnly cookies not
// localStorage).
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
  timeout: 60000, // 60s — queries can be slow (RETRIEVAL-005's own <15s target, plus margin)
});

export interface UploadResult {
  filename: string;
  status: string;
  paper_id: string | null;
  job_id: string | null;
  error: string | null;
}

export interface JobStatus {
  job_id: string;
  paper_id: string;
  status: string;
  entities_found: number;
  relations_found: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export const litgraphApi = {
  // Query — collectionId (POLISH-005b) scopes both GraphRAG's retrieval and
  // vanilla RAG's chunk search to one collection; omit/undefined for the
  // original global-corpus behavior. compareQuery doesn't take one yet —
  // ComparePage.tsx wasn't in this pass's scope, left global on purpose.
  query: (query: string, collectionId?: string | null) =>
    api.post<QueryResponse>("/query", { query, collection_id: collectionId || undefined }),
  queryVanilla: (query: string, collectionId?: string | null) =>
    api.post<VanillaQueryResponse>("/query/vanilla", {
      query,
      collection_id: collectionId || undefined,
    }),
  compareQuery: (query: string) =>
    api.post<CompareQueryResponse>("/query/compare", { query }),
  voteCompare: (queryLogId: string, verdict: CompareVerdict) =>
    api.post(`/query/compare/${queryLogId}/vote`, { verdict }),

  // Ingest
  uploadPapers: (files: File[], collectionId?: string | null) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (collectionId) form.append("collection_id", collectionId);
    return api.post<UploadResult[]>("/ingest/upload", form);
  },
  // POLISH-004 — `identifier` accepts a bare arXiv id or a full abs/pdf URL,
  // resolved server-side (see _parse_arxiv_id in src/api/routes/ingest.py).
  importArxiv: (identifier: string, collectionId?: string | null) =>
    api.post<UploadResult>("/ingest/arxiv", {
      identifier,
      collection_id: collectionId || undefined,
    }),
  getIngestionStatus: (jobId: string) => api.get<JobStatus>(`/ingest/status/${jobId}`),

  // Papers
  getPapers: (collectionId?: string | null) =>
    api.get<Paper[]>("/papers", { params: collectionId ? { collection_id: collectionId } : {} }),
  getPaper: (id: string) => api.get<PaperDetail>(`/papers/${id}`),
  deletePaper: (id: string) => api.delete(`/papers/${id}`),
  assignPaperCollection: (id: string, collectionId: string | null) =>
    api.patch<Paper>(`/papers/${id}`, { collection_id: collectionId }),

  // Collections (POLISH-005 — organizational CRUD; POLISH-005b then added
  // the collectionId params above/below that actually scope retrieval).
  getCollections: () => api.get<Collection[]>("/collections"),
  createCollection: (name: string, description?: string) =>
    api.post<Collection>("/collections", { name, description }),
  renameCollection: (id: string, name: string) =>
    api.patch<Collection>(`/collections/${id}`, { name }),
  deleteCollection: (id: string) => api.delete(`/collections/${id}`),

  // Graph
  getGraphOverview: (collectionId?: string | null) =>
    api.get<GraphOverview>("/graph/overview", {
      params: collectionId ? { collection_id: collectionId } : {},
    }),
  // entityId omitted -> backend returns a capped whole-graph snapshot
  // (GRAPH-003's "full graph loads on page visit"); collectionId (POLISH-
  // 005b) scopes that snapshot to one collection either way.
  getSubgraph: (entityId?: string, hops = 2, collectionId?: string | null) =>
    api.get<GraphSubgraphResponse>("/graph/subgraph", {
      params: { entity_id: entityId, hops, collection_id: collectionId || undefined },
    }),
  getEntity: (id: string) => api.get<EntityDetailResponse>(`/graph/entity/${id}`),
  searchEntities: (q: string, type?: string) =>
    api.get<SearchResponse>("/graph/search", { params: { q, type } }),
};

export default api;

import axios from "axios";

import type {
  CompareQueryResponse,
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

// Only wraps endpoints that exist today (RETRIEVAL-005/006, INGEST-004/007,
// GRAPH-001's subgraph/search — overview/entity added once GRAPH-003 needs
// them). Collections CRUD (POLISH-005) isn't built yet — added once that
// ticket lands, not stubbed against routes that would just 404.
export const litgraphApi = {
  // Query — no collection_id param. Per RETRIEVAL-001's MVP scoping
  // decision, retrieval is global across all ingested papers, not filtered
  // by collection. Don't add a collectionId argument here until
  // POLISH-005b actually implements collection-filtered retrieval on the
  // backend.
  query: (query: string) => api.post<QueryResponse>("/query", { query }),
  queryVanilla: (query: string) =>
    api.post<VanillaQueryResponse>("/query/vanilla", { query }),
  compareQuery: (query: string) =>
    api.post<CompareQueryResponse>("/query/compare", { query }),

  // Ingest
  uploadPapers: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return api.post<UploadResult[]>("/ingest/upload", form);
  },
  getIngestionStatus: (jobId: string) => api.get<JobStatus>(`/ingest/status/${jobId}`),

  // Papers
  getPapers: () => api.get<Paper[]>("/papers"),
  getPaper: (id: string) => api.get<PaperDetail>(`/papers/${id}`),
  deletePaper: (id: string) => api.delete(`/papers/${id}`),

  // Graph
  getSubgraph: (entityId: string, hops = 2) =>
    api.get<GraphSubgraphResponse>("/graph/subgraph", { params: { entity_id: entityId, hops } }),
  searchEntities: (q: string, type?: string) =>
    api.get<SearchResponse>("/graph/search", { params: { q, type } }),
};

export default api;

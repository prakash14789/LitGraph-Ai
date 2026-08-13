import { create } from "zustand";

import { litgraphApi } from "@/services/api";
import type { Citation, RetrievalStats, RetrievedSubgraph } from "@/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  retrievalStats?: RetrievalStats;
  retrievedSubgraph?: RetrievedSubgraph; // FE-004/FE-005: context panel + entity modal
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  lastQuery: string | null;
  send: (query: string) => void;
  retry: () => void;
}

let idCounter = 0;
const nextId = () => `msg-${Date.now()}-${++idCounter}`;

// Session-only store (FE-003 AC: "Chat history preserved during session") —
// no persist middleware, a refresh clearing history is the intended MVP
// behavior, not a bug.
export const useChatStore = create<ChatState>((set, get) => {
  const runQuery = async (query: string, pushUserBubble: boolean) => {
    set((s) => ({
      messages: pushUserBubble
        ? [...s.messages, { id: nextId(), role: "user", content: query }]
        : s.messages,
      isLoading: true,
      error: null,
      lastQuery: query,
    }));

    try {
      const { data } = await litgraphApi.query(query);
      set((s) => ({
        messages: [
          ...s.messages,
          {
            id: nextId(),
            role: "assistant",
            content: data.answer,
            citations: data.citations,
            retrievalStats: data.retrieval_stats,
            retrievedSubgraph: data.retrieved_subgraph,
          },
        ],
        isLoading: false,
      }));
    } catch {
      set({ isLoading: false, error: "Something went wrong answering that question." });
    }
  };

  return {
    messages: [],
    isLoading: false,
    error: null,
    lastQuery: null,

    send: (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || get().isLoading) return;
      void runQuery(trimmed, true);
    },

    retry: () => {
      const q = get().lastQuery;
      if (q && !get().isLoading) void runQuery(q, false);
    },
  };
});
